#!/usr/bin/env python3
"""审计全板「一个电气端子对应多个焊盘」及未联网机械/重复焊盘。

同时导出原理图网表,把 F1 的符号引脚网络映射到库封装的重复焊盘编号；这项检查
保证以后从原理图更新 PCB 时,进线和出线仍会落在两个不同的保险丝夹子上。

用法:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
      hardware/check-multipad-mapping.py
"""
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import pcbnew


HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
SCH = HERE / "cct-main.kicad_sch"
PRETTY = HERE / "kicad-lib" / "cct.pretty"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"


# 每一个自动发现的候选位号必须在这里有人工复核结论；出现新候选时脚本会失败。
CLASSIFICATION = {
    "F1": ("已修正", "3557-2 左夹两盘=端子1,右夹两盘=端子2;重复焊盘编号固化映射"),
    "J2": ("有意", "Type-C 的 VBUS/GND/D+/D−各有重复触点;外壳固定脚接地,SBU/定位孔 NC"),
    "J9": ("有意", "5/6 是 Qwiic 座机械加固脚,无电气端子"),
    "SW1": ("有意", "轻触开关 1/3、2/4 分别内部相连;1/2 已取两侧,3/4 仅作重复焊脚"),
    "SW2": ("有意", "轻触开关 1/3、2/4 分别内部相连;1/2 已取两侧,3/4 仅作重复焊脚"),
    "U1": ("有意/待同步", "A0/A1/GND 分别接地;ALERT 有意 NC;VBUS 已在原理图修正,等 PCB 更新"),
    "U2": ("有意", "裸露焊盘与散热过孔接 GND;无编号孔是同一散热结构"),
    "U3": ("有意", "稳压器 VOUT 引脚与散热片都是 V3P3"),
    "U4": ("有意", "ESP32 多个 GND 与 9 个同号裸露焊盘;保留脚/NC 按手册悬空"),
    "U5": ("有意", "CH340C 的 VCC/V3 同接 V3P3;未使用调制解调器脚与 NC 悬空"),
    "U6": ("有意", "VCC 与 DIR 是不同端子但按设计同接 V5_SYS"),
    "U7": ("有意", "VCC/DIR 同接 V5_SYS;未用 A5–A8 接地,B5–B8 NC"),
    **{f"H{i}": ("有意", "安装孔是纯机械焊盘") for i in range(1, 10)},
}


def pad_numbers(path):
    """读取库封装里的焊盘号；兼容旧式未加引号与新式加引号写法。"""
    txt = path.read_text(encoding="utf-8")
    return [a or b for a, b in re.findall(
        r'\(pad\s+(?:"([^"]*)"|([^\s()]+))\s+', txt)]


def export_pin_nets():
    with tempfile.TemporaryDirectory(prefix="cct-multipad-") as tmp:
        netfile = Path(tmp) / "cct.net"
        run = subprocess.run(
            [CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
             "-o", str(netfile), str(SCH)], capture_output=True, text=True)
        if run.returncode:
            sys.exit(f"kicad-cli 导出网表失败:\n{run.stdout}\n{run.stderr}")
        txt = netfile.read_text(encoding="utf-8")
    result = {}
    for name, body in re.findall(
            r'\(net\s*\(code "\d+"\)\s*\(name "([^"]*)"\)(.*?)'
            r'(?=\n\t\t\(net\n|\n\t\)\n)', txt, re.S):
        for ref, pin in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', body):
            result[(ref, pin)] = name
    return result


board = pcbnew.LoadBoard(str(BOARD))
candidates = set()
board_padnets = {}
used_footprints = {}
for fp in board.GetFootprints():
    ref = fp.GetReference()
    used_footprints[ref] = fp.GetFPID().GetLibItemName()
    by_net = defaultdict(list)
    pads = []
    for pad in fp.Pads():
        number, net = pad.GetNumber(), pad.GetNetname()
        pads.append((number, net))
        by_net[net].append(number)
    board_padnets[ref] = pads
    if any(len(numbers) > 1 for numbers in by_net.values()) or "" in by_net:
        candidates.add(ref)

for ref, footprint in used_footprints.items():
    path = PRETTY / f"{footprint}.kicad_mod"
    if not path.exists():
        continue  # KiCad 标准库里的安装孔仍会由板上无网络焊盘发现
    counts = Counter(n for n in pad_numbers(path) if n)
    if any(count > 1 for count in counts.values()):
        candidates.add(ref)

unknown = sorted(candidates - CLASSIFICATION.keys())
stale = sorted(set(CLASSIFICATION) - candidates)

print("| 分类 | 位号 | 复核结论 |")
print("|---|---|---|")
groups = [
    ("已修正", "F1", CLASSIFICATION["F1"][1]),
    ("有意", "J2", CLASSIFICATION["J2"][1]),
    ("有意", "J9", CLASSIFICATION["J9"][1]),
    ("有意", "SW1/SW2", CLASSIFICATION["SW1"][1]),
    ("有意/待同步", "U1", CLASSIFICATION["U1"][1]),
    ("有意", "U2", CLASSIFICATION["U2"][1]),
    ("有意", "U3", CLASSIFICATION["U3"][1]),
    ("有意", "U4", CLASSIFICATION["U4"][1]),
    ("有意", "U5", CLASSIFICATION["U5"][1]),
    ("有意", "U6/U7", "供电、方向与未用通道是不同引脚按设计并网,不是封装内部短接"),
    ("有意", "H1–H9", "安装孔是纯机械焊盘"),
]
for status, refs, reason in groups:
    print(f"| {status} | {refs} | {reason} |")

problems = []
if unknown:
    problems.append(f"未分类的新候选: {unknown}")
if stale:
    problems.append(f"分类表中已不再被扫描到的位号: {stale}")

# F1 验收:导出的两脚网表 + 库封装重复编号,共同决定未来 PCB 的四个焊盘网络。
pin_nets = export_pin_nets()
f1_nums = Counter(n for n in pad_numbers(
    PRETTY / "FUSE-TH_4P-L19.8-W6.7_3557-2.kicad_mod") if n)
expected_nets = {("F1", "1"): "V24_IN", ("F1", "2"): "V24_FUSED"}
if {key: pin_nets.get(key) for key in expected_nets} != expected_nets:
    problems.append(f"F1 导出网表错误: {[(key, pin_nets.get(key)) for key in expected_nets]}")
if f1_nums != Counter({"1": 2, "2": 2}):
    problems.append(f"F1 库封装焊盘编号错误: {dict(f1_nums)}")

current_f1 = defaultdict(list)
for pad, net in board_padnets["F1"]:
    current_f1[net].append(pad)
if set(current_f1["V24_IN"]) != {"1", "2"} or set(current_f1["V24_FUSED"]) != {"3", "4"}:
    problems.append(f"当前板 F1 手工映射不符合已确认状态: {dict(current_f1)}")

print()
print("F1 导出网表/库封装映射:")
print(f"  符号 1 = {pin_nets.get(('F1', '1'))} → 左夹 pad 1 × {f1_nums['1']}")
print(f"  符号 2 = {pin_nets.get(('F1', '2'))} → 右夹 pad 2 × {f1_nums['2']}")
print("  当前板只读复核:pad 1+2=V24_IN,pad 3+4=V24_FUSED")
print(f"  自动候选 {len(candidates)} 个位号;实际映射缺陷 1 处(F1),已修正;其他未分类错误 {len(unknown)} 处")

if problems:
    print("❌ 多焊盘映射审计失败:")
    for problem in problems:
        print(f"  · {problem}")
    sys.exit(1)
print("✅ 多焊盘映射审计通过")
