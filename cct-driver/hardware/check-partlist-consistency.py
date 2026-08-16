#!/usr/bin/env python3
"""元件清单四处一致性检查:原理图源 / 原理图文件 / 规格书 / BOM。

**为什么有这个检查。** 元件的增减必须同时落到四个地方:
`gen_sch.py` 的 P 表、`cct-main.kicad_sch`、`netlist-spec.md` 的网表表格、
`bom.csv` / `bom-jlc.csv`。少落一处不会报错,只会在下单时贴错料或漏贴。
2026-08-15 加输入级 RC 与母线陶瓷时,`gen_bom.py` 的位号全集还是"PCB 里的
footprint",新增件被静默漏掉 —— 就是这类错。

它还会顺带比一次 `bom-jlc.csv` 与 `cpl-jlc.csv`:两者位号对不上,说明
**BOM 已经是新版、而 Gerber/CPL 还停在旧版**,这一包不能拿去下单。

用法:
    python3 check-partlist-consistency.py           打印报表
    python3 check-partlist-consistency.py --quiet   只给退出码
"""
import csv, re, sys
from pathlib import Path

HERE = Path(__file__).parent
QUIET = "--quiet" in sys.argv
problems = []
notes = []


def say(*a):
    if not QUIET:
        print(*a)


# ---- 1. gen_sch.py 的 P 表(执行它的头部,不用正则去猜) ----
src = (HERE / "gen_sch.py").read_text().split("def gen()")[0]
ns = {"__file__": str(HERE / "gen_sch.py")}
exec(compile(src, "gen_sch.py", "exec"), ns)
P = ns["P"]
sch_refs = {ref for ref, _cid, _pins in P}
sch_cid = {ref: cid for ref, cid, _pins in P}
if len(sch_refs) != len(P):
    problems.append(f"gen_sch.py 的 P 表里位号有重复({len(P)} 条 / {len(sch_refs)} 个位号)")

# 不采购件(测试点、安装孔)—— 与 gen_bom.py 的 SUPP 保持一致
# 安装孔 v2 是 9 个(H1–H9),不是 4 个 —— 按受力点重排,见 floorplan-v2.md §A4c
NON_PURCHASED = {f"TP{i}" for i in range(1, 10)} | {f"H{i}" for i in range(1, 10)}

# ---- 2. cct-main.kicad_sch 里的符号 ----
sch_txt = (HERE / "cct-main.kicad_sch").read_text()
file_refs = set(re.findall(r'\(property "Reference" "([^"]+)"', sch_txt))

# ---- 3. netlist-spec.md 的网表表格 ----
# 合法位号前缀(见 §约定)。用它把引脚表里的 IO4 / CH1 / UART2 / A1 挡在外面。
PREFIX = ("J", "F", "Q", "D", "C", "R", "L", "U", "RS", "DZ", "SW", "LED", "PTC", "TP", "H")


def ok(pref, num):
    # C 编号(C25804 之类)也长得像位号 —— 本板位号编号都是 1–3 位,C 编号是 4 位以上
    return pref in PREFIX and len(num) <= 3


def expand(tok):
    """'C1–C5' / 'R16,R17' / 'R54-R57' / 'C32' → 位号列表"""
    out = []
    for t in re.split(r"[,,]", tok):
        t = t.strip().replace("**", "").replace("`", "")
        m = re.fullmatch(r"([A-Z]+)(\d+)\s*[-–—~]\s*([A-Z]*)(\d+)", t)
        if m:
            pref, a, _p2, b = m.groups()
            if ok(pref, b):
                out += [f"{pref}{i}" for i in range(int(a), int(b) + 1)]
            continue
        m = re.fullmatch(r"([A-Z]+)(\d+)", t)
        if m and ok(*m.groups()):
            out.append(t)
    return out


# 只吃 Block A–F 的网表表格,不吃 §A2 里的设计说明表
spec_txt = (HERE / "netlist-spec.md").read_text()
spec_body = spec_txt.split("## Block A2")[0] + spec_txt.split("## Block B:低压电源链")[1]
spec_refs = set()
for line in spec_body.splitlines():
    if not line.startswith("|"):
        continue
    for cell in line.strip("|").split("|"):
        spec_refs.update(expand(cell))

# ---- 4. bom.csv / bom-jlc.csv ----
bom_refs, bom_cid = set(), {}
for row in csv.DictReader(open(HERE / "bom.csv")):
    for r in row["位号"].split():
        bom_refs.add(r)
        bom_cid[r] = row["LCSC"]
jlc_refs = set()
for row in csv.DictReader(open(HERE / "bom-jlc.csv")):
    jlc_refs.update(x.strip() for x in row["Designator"].split(","))

# ---- 5. cpl-jlc.csv(旧版布局产物,只做提示) ----
cpl_refs = {row[0] for row in list(csv.reader(open(HERE / "cpl-jlc.csv")))[1:] if row}

# ============================ 比对 ============================
expected_board = sch_refs | NON_PURCHASED

say(f"原理图源 gen_sch.py       {len(sch_refs):>4} 个采购件")
say(f"原理图 cct-main.kicad_sch {len(file_refs):>4} 个符号")
say(f"规格书 netlist-spec.md    {len(spec_refs):>4} 个位号(含测试点/安装孔)")
say(f"bom.csv                   {len(bom_refs):>4} 个位号")
say(f"bom-jlc.csv               {len(jlc_refs):>4} 个位号")
say(f"不采购件(TP/H)          {len(NON_PURCHASED):>4} 个")
say(f"→ 板上应有元件总数         {len(expected_board):>4} 个")
say("")


def cmp(name_a, a, name_b, b, hard=True):
    only_a, only_b = sorted(a - b), sorted(b - a)
    if not only_a and not only_b:
        say(f"✅ {name_a} == {name_b}")
        return
    msg = f"{name_a} 与 {name_b} 不一致:只在前者 {only_a or '无'};只在后者 {only_b or '无'}"
    (problems if hard else notes).append(msg)
    say(("❌ " if hard else "⚠️  ") + msg)


cmp("gen_sch.py", sch_refs, "cct-main.kicad_sch", file_refs)
cmp("bom.csv", bom_refs, "原理图+不采购件", expected_board)
cmp("bom-jlc.csv", jlc_refs, "bom.csv", bom_refs)
# 安装孔是纯机械件,规格书不列,所以从这一比里排掉
cmp("netlist-spec.md", spec_refs, "bom.csv(不含安装孔)",
    {r for r in bom_refs if not r.startswith("H")})

# C 编号一致性
mismatch = [(r, sch_cid[r], bom_cid.get(r)) for r in sorted(sch_refs)
            if bom_cid.get(r) != sch_cid[r]]
if mismatch:
    problems.append(f"{len(mismatch)} 个位号的 C 编号在 BOM 与原理图之间不一致:{mismatch[:6]}")
    say(f"❌ C 编号不一致 {len(mismatch)} 处:{mismatch[:6]}")
else:
    say("✅ 所有位号的 C 编号在 BOM 与原理图之间一致")

# 与 CPL(布局产物)的偏差 —— 只提示,不算硬错
cmp("bom-jlc.csv(采购件)", bom_refs - NON_PURCHASED, "cpl-jlc.csv", cpl_refs, hard=False)

say("")
if problems:
    say(f"❌ {len(problems)} 处硬性不一致")
    sys.exit(1)
if notes:
    say("⚠️  BOM 已是新版而 CPL/Gerber 还是旧版布局 —— **这一包不能下单**,")
    say("   等布局重做完、重跑 gen_cpl.py 与 Gerber 导出之后再核一次。")
    sys.exit(0)
say("✅ 四处元件清单完全一致")
sys.exit(0)
