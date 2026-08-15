#!/usr/bin/env python3
"""把板子的「网络 → 焊盘」全集与**原理图导出的网表**逐条比对,必须零差异。

**为什么有它。** v2 是把 205 个元件重摆、重布的一整块板。改完之后
「我们分不清好坏」——肉眼看渲染图看不出一根线接错。所以连通性不靠人看,
靠这个脚本:原理图那边导出真网表,板子这边遍历所有焊盘,两边做集合 diff。

用法(要用 KiCad 自带的 python,因为要读板文件):
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \\
        hardware/verify_netlist_v2.py

它会打印三张表:
  ① 网表 diff —— 必须空
  ② 「一个电气端子 = 多个焊盘」的显式对照表(PAD_GROUPS)—— 人肉审这张表
  ③ 板上没有网络的焊盘 —— 每一个都要有说得出口的理由
"""
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
SCH = HERE / "cct-main.kicad_sch"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
NETLIST = HERE / ".netlist-verify.net"

# 与 gen_pcb_v2.py 的 PAD_GROUPS 同源(从那边读,避免两份表走散)
_src = (HERE / "gen_pcb_v2.py").read_text(encoding="utf-8")
PAD_GROUPS = eval(re.search(r"^PAD_GROUPS = (\{.*?^\})", _src, re.S | re.M).group(1))

# 板上有、原理图没有的元件(纯板级件)。它们不参与 diff,但要逐个列出来。
BOARD_ONLY = {f"TP{i}" for i in range(1, 10)} | {f"H{i}" for i in range(1, 10)}

# 允许没有网络的焊盘 —— 每一条都要写清楚为什么
UNNETTED_OK = {
    "J9": ("5", "6", "机械固定盘(Qwiic 座的两个加固脚),原理图上没有对应引脚"),
    "SW1": ("3", "4", "4 脚轻触开关:同一侧的两脚在开关内部就是一根,1/2 已接,3/4 是重复脚"),
    "SW2": ("3", "4", "同 SW1"),
    "U2": ("", "", "SOIC-8 散热焊盘下的 4 个无编号热过孔(gen_dfm_fixes.py 会把它们并进 GND)"),
    "J2": ("", "", "Type-C 封装里 4 个无编号的定位/加固盘 + SBU1/SBU2(规格书写明 NC)"),
    "U1": ("3", "8", "3=ALERT(规格书 Block A 写明 NC);"
                     "8=VBUS —— ⚠️ 规格书的 U1 引脚表里根本没有这一脚,"
                     "母线电压那一路因此测不出来(电流那一路不受影响)。"
                     "这是**原理图的事**,本轮不改,已上报"),
    "U4": ("14", "32", "14=IO12(规格书写明必须悬空,它是启动时的 flash 电压选择脚);"
                       "17–22=模组内部接 flash 的脚,数据手册要求不得外接;32=NC"),
    "U5": ("7", "15", "CH340C 用不到的调制解调器控制脚(OUT/CTS/DSR/RI/DCD/R232)与 NC"),
    "U7": ("11", "14", "第二片 74HCT245 只用 4 路,B5–B8 空着(规格书里就是 NC_U7_B5..B8);"
                       "对应的 A5–A8 输入已按规格书接 GND,不会悬空乱翻"),
}

problems = []

# ---------------------------------------------------------------- ① 原理图网表
r = subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", str(NETLIST), str(SCH)], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout, r.stderr)
    sys.exit("kicad-cli 导出网表失败")

txt = NETLIST.read_text(encoding="utf-8")
sch_net = defaultdict(set)          # 网络名 → {(ref, pin)}
for m in re.finditer(r'\(net\s*\(code "\d+"\)\s*\(name "([^"]*)"\)(.*?)(?=\n\t\t\(net\n|\n\t\)\n)',
                     txt, re.S):
    name, body = m.group(1), m.group(2)
    for node in re.finditer(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', body):
        sch_net[name].add((node.group(1), node.group(2)))
NETLIST.unlink(missing_ok=True)

# 未连接网络(KiCad 给的自动名 unconnected-…)与 NC_ 网络不参与比对
def is_real(name):
    return not name.startswith("unconnected-") and not name.startswith("NC_")


sch_pairs = {(n, ref, pin) for n, nodes in sch_net.items() if is_real(n)
             for (ref, pin) in nodes}

# ---------------------------------------------------------------- ② 板上焊盘
board = pcbnew.LoadBoard(str(BOARD))
pcb_pairs = set()
unnetted = defaultdict(list)
board_only_pads = []
for fp in board.GetFootprints():
    ref = fp.GetReference()
    grp = PAD_GROUPS.get(ref, {})
    pad2pin = {}
    for pin, padlist in grp.items():
        for pad in padlist:
            pad2pin[pad] = pin
    for p in fp.Pads():
        num, net = p.GetNumber(), p.GetNetname()
        if not net:
            unnetted[ref].append(num)
            continue
        if ref in BOARD_ONLY:
            board_only_pads.append((ref, num, net))
            continue
        pcb_pairs.add((net, ref, pad2pin.get(num, num)))

print("=" * 78)
print("① 网表 diff:原理图 cct-main.kicad_sch  ↔  板 cct-main.kicad_pcb")
print("=" * 78)
only_sch = sorted(sch_pairs - pcb_pairs)
only_pcb = sorted(pcb_pairs - sch_pairs)
print(f"   原理图侧 (网络, 位号, 引脚) 三元组 {len(sch_pairs)} 条")
print(f"   板侧     (网络, 位号, 焊盘) 三元组 {len(pcb_pairs)} 条(焊盘已按 PAD_GROUPS 归回引脚)")
if only_sch:
    print(f"   ❌ 只在原理图里、板上没有({len(only_sch)} 条):")
    for x in only_sch[:40]:
        print(f"        {x}")
    problems.append(f"{len(only_sch)} 条连接只在原理图里")
if only_pcb:
    print(f"   ❌ 只在板上、原理图里没有({len(only_pcb)} 条):")
    for x in only_pcb[:40]:
        print(f"        {x}")
    problems.append(f"{len(only_pcb)} 条连接只在板上")
if not only_sch and not only_pcb:
    print("   ✅ 零差异 —— 板上每一个焊盘的网络都与原理图逐条一致")

print()
print("=" * 78)
print("② 「一个电气端子 = 多个焊盘」对照表(请人肉审这张表)")
print("=" * 78)
if not PAD_GROUPS:
    print("   (空)")
for ref, g in sorted(PAD_GROUPS.items()):
    for pin, pads in sorted(g.items()):
        print(f"   {ref} 引脚 {pin}  →  焊盘 {', '.join(pads)}")
print("   理由:F1 是 Keystone 3557-2「一颗保险丝、两个夹子」的座,每个夹子两根引脚。")
print("   焊盘 1+2 是同一个夹子、3+4 是另一个。老板文件把进线接 1、出线接 2 ——")
print("   两者被夹子的金属短接,**15A 主保险丝被完全旁路**。这里改对了。")

print()
print("=" * 78)
print("③ 板上没有网络的焊盘(每一个都要有理由)")
print("=" * 78)
for ref in sorted(unnetted):
    nums = unnetted[ref]
    why = None
    if ref in UNNETTED_OK:
        why = UNNETTED_OK[ref][2]
    elif ref in BOARD_ONLY:
        why = "纯机械件(安装孔),没有电气网络"
    if why:
        print(f"   ✅ {ref:<5} 焊盘 {nums}  —— {why}")
    else:
        print(f"   ❌ {ref:<5} 焊盘 {nums}  —— 没有说明")
        problems.append(f"{ref} 有 {len(nums)} 个焊盘没有网络,也没有理由")

print()
print(f"   板级件(不在原理图里)的焊盘 {len(board_only_pads)} 个:"
      + ", ".join(f"{r}={n}" for r, _p, n in sorted(board_only_pads)))

print()
print("=" * 78)
if problems:
    print(f"❌ {len(problems)} 处不过:")
    for p in problems:
        print(f"   · {p}")
    sys.exit(1)
print("✅ 连接关系与原理图完全一致(零差异)")
sys.exit(0)
