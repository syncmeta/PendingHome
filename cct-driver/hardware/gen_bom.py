#!/usr/bin/env python3
"""生成 BOM:
- bom.csv         内部核对用(位号/描述/LCSC/数量/来源块)
- bom-jlc.csv     嘉立创 SMT 格式(Comment,Designator,Footprint,LCSC Part #)
数据源:gen_sch.py 的 P 表(C 号)+ netlist-spec.md(描述)+ cct-main.kicad_pcb(封装名)。
"""
import csv, re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

# 1. gen_sch.py 里的 (ref, cid)
parts = {}   # ref -> cid
src = (HERE / "gen_sch.py").read_text()
for m in re.finditer(r'part\(\s*(f?)"([^"]+)"\s*,\s*"(C\d+)"', src):
    fstr, ref, cid = m.groups()
    if not fstr:
        parts[ref] = cid
# f-string 形式:part(f"C{i}", "C2836439", ...) 之类 —— 处理已知循环
loops = re.findall(r'for (\w+) in range\((\d+),\s*(\d+)\):\s*\n\s*part\(f"([A-Za-z]+)\{\w+\}"\s*,\s*"(C\d+)"', src)
for var, a, b, prefix, cid in loops:
    for i in range(int(a), int(b)):
        parts[f"{prefix}{i}"] = cid
# for r in ("Q1","Q2") 形式
for m in re.finditer(r'for \w+ in \(([^)]+)\):\s*\n\s*part\(\w+,\s*"(C\d+)"', src):
    refs, cid = m.groups()
    for r in re.findall(r'"([^"]+)"', refs):
        parts[r] = cid

# 2. netlist-spec.md 描述
desc = {}
for line in (HERE / "netlist-spec.md").read_text().splitlines():
    m = re.match(r'\|\s*([A-Z]+[0-9]+(?:\s*[,,]\s*[A-Z]*[0-9]+[^|]*)?)\s*\|\s*([^|]+)\|', line)
    if not m:
        continue
    refs_raw, d = m.group(1), m.group(2).strip()
    d = re.sub(r'\*\*', '', d)
    for token in re.split(r'[,,]', refs_raw):
        token = token.strip()
        mm2 = re.match(r'^([A-Z]+)?([0-9]+)(?:[--~]([A-Z]*)([0-9]+))?$', token)
        if not mm2:
            continue
        p1, n1, p2, n2 = mm2.groups()
        if n2:   # 范围 R16-R27
            pref = p1 or p2
            for i in range(int(n1), int(n2) + 1):
                desc.setdefault(f"{pref}{i}", d)
        elif p1:
            desc.setdefault(f"{p1}{n1}", d)

# 3. PCB 封装名
import gc
gc.disable()
import pcbnew
board = pcbnew.LoadBoard(str(HERE / "cct-main.kicad_pcb"))
fp_name = {}
for fp in board.GetFootprints():
    fp_name[fp.GetReference()] = str(fp.GetFPID().GetLibItemName())

# 3b. 通道循环 / Block F 循环 / 非采购件 显式补充
SUPP = {}
CH_ROWS = [
    ("F2","J3","Q7","Q8","R16","R17","R18","R19","D5","D6","D7","D8","C16","C17","LED2","LED3","R20","R21"),
    ("F3","J4","Q9","Q10","R22","R23","R24","R25","D9","D10","D11","D12","C18","C19","LED4","LED5","R26","R27"),
    ("F4","J5","Q11","Q12","R28","R29","R30","R31","D13","D14","D15","D16","C20","C21","LED6","LED7","R32","R33"),
    ("F5","J6","Q13","Q14","R34","R35","R36","R37","D17","D18","D19","D20","C22","C23","LED8","LED9","R38","R39"),
    ("F6","J7","Q15","Q16","R40","R41","R42","R43","D21","D22","D23","D24","C24","C25","LED10","LED11","R44","R45"),
    ("F7","J8","Q17","Q18","R46","R47","R48","R49","D25","D26","D27","D28","C26","C27","LED12","LED13","R50","R51"),
]
CH_CIDS = ["C108518","C441333","C2890395","C2890395","C22775","C22775","C25804","C25804",
           "C35490","C35490","C19077580","C19077580","C2836439","C14663","C2297","C2297","C23162","C23162"]
for row in CH_ROWS:
    for ref, cid in zip(row, CH_CIDS):
        SUPP[ref] = cid
for i in range(1, 5):
    SUPP[f"R{53+i}"] = "C21190"
    SUPP[f"R{57+i}"] = "C25804"
    SUPP[f"C{27+i}"] = "C14663"
for r in ("TP1","TP2","TP3","TP4","TP5","TP6","H1","H2","H3","H4"):
    SUPP[r] = "无需采购"
parts.update({k: v for k, v in SUPP.items() if k not in parts})

# 4. 汇总
missing_c = []
groups = defaultdict(list)   # cid -> [refs]
for ref in sorted(fp_name, key=lambda r: (re.sub(r'\d+', '', r), int(re.sub(r'\D', '', r) or 0))):
    cid = parts.get(ref)
    if cid is None:
        missing_c.append(ref)
        cid = "待核实"
    groups[(cid, fp_name[ref])].append(ref)

with open(HERE / "bom.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["LCSC", "数量", "位号", "描述", "封装"])
    for (cid, fpn), refs in sorted(groups.items()):
        d = desc.get(refs[0], "")
        w.writerow([cid, len(refs), " ".join(refs), d, fpn])

with open(HERE / "bom-jlc.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for (cid, fpn), refs in sorted(groups.items()):
        d = desc.get(refs[0], "")[:40]
        w.writerow([d or cid, ",".join(refs), fpn, cid if cid.startswith("C") else ""])

print(f"元件 {len(fp_name)},分组 {len(groups)}")
print("缺 C 号:", missing_c if missing_c else "无")
with open(HERE / "bom.csv") as f:
    n_pending = sum(1 for line in f if "待核实" in line)
print(f"待核实行:{n_pending}")
