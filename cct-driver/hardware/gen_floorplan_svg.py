#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v2 楼层规划分区示意图(1:1 mm SVG)+ 元件归区清点。

用法:
    python3 gen_floorplan_svg.py            # 写 floorplan-v2.svg,打印清点表
    python3 gen_floorplan_svg.py --census   # 只打印清点表(markdown)

坐标系与 KiCad 文件一致:原点左上角,x 向右,y 向下,单位 mm。
文件方向 = 上墙安装方向(接线端子在下边)。

数据来源:
  - 封装外形尺寸(courtyard)取自 cct-main.kicad_pcb,见 FP 字典的注释
  - 位号全集读自 cpl-jlc.csv(195 个贴装件)+ 本文件里的 10 个非贴装件
    (H1–H4 安装孔、TP1–TP6 测试焊盘),合计 205
本脚本只读不写 PCB 文件。
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CPL = os.path.join(HERE, "cpl-jlc.csv")
OUT_SVG = os.path.join(HERE, "floorplan-v2.svg")

# ---------------------------------------------------------------- 板框
BW, BH = 130.0, 145.0          # v2 推荐板框
V1_BW, V1_BH = 110.0, 145.0    # 现版板框(画参考虚线用)

# ------------------------------------------------ 封装 courtyard 实测值(mm)
# 全部来自 cct-main.kicad_pcb 的 F.CrtYd,pcbnew.GetCourtyard().BBox()
FP = {
    "R0603":      (1.69, 0.89),
    "C0603":      (1.69, 0.89),
    "C0805":      (2.09, 1.33),
    "C1210":      (3.29, 2.59),
    "LED0805":    (2.09, 1.34),
    "ELEC8":      (8.40, 8.39),   # CAP-SMD_BD8.0 100µF/50V 铝电解
    "SMB":        (4.69, 3.69),   # SS36B / SMBJ26A
    "TO252":      (6.69, 6.14),   # UMW 20N06
    "TO252P":     (6.69, 6.19),   # SQD50P06 (P-MOS)
    "TSSOP20":    (6.59, 4.49),   # 74HCT245PW
    "NANO2":      (9.82, 5.12),   # 支路保险丝座
    "ATO2":       (19.90, 6.81),  # F1 Keystone 3557-2 双联 ATO
    "KF7622P":    (16.53, 12.09), # J1 24V 输入端子
    "KF2EDGV3P":  (12.31, 7.09),  # J3–J8 灯带输出端子
    "R2512":      (6.39, 3.29),   # RS1
    "VSSOP10":    (3.09, 3.09),   # U1 INA237
    "WROOM":      (25.59, 18.09), # U4 ESP32-WROOM-32E
    "SOIC8EP":    (4.99, 3.99),   # U2 TPS54360B
    "IND12":      (12.39, 12.39), # L1 33µH
    "SOP16":      (9.99, 3.99),   # U5 CH340C
    "SOT223":     (3.59, 6.59),   # U3 AMS1117
    "TYPEC":      (9.03, 7.44),   # J2
    "XH4":        (12.59, 5.89),  # J10
    "KF1285P":    (13.45, 6.65),  # J11
    "QWIIC":      (6.09, 3.89),   # J9
    "SW":         (5.19, 5.19),   # SW1/SW2
    "F1812":      (4.65, 3.33),   # PTC1
    "MH":         (6.99, 6.99),   # M3 安装孔 courtyard
    "TP":         (2.59, 2.59),
}

# ---------------------------------------------------------------- 通道几何
CH_PITCH = 16.0
CH_X = {1: 92.0, 2: 76.0, 3: 60.0, 4: 44.0, 5: 28.0, 6: 12.0}   # 列心 x
CH_HALF = CH_PITCH / 2.0

# 功率通道列的行结构:(行名, 中心 y, 该行最高元件的 courtyard 高度)
CH_ROWS = [
    ("支路保险丝  Fn",              89.60, FP["NANO2"][1]),
    ("输出电解 + 指示灯 ×2",         104.36, FP["ELEC8"][1]),
    ("输出 TVS  SMBJ26A ×2",       112.60, FP["SMB"][1]),
    ("续流二极管  SS36B ×2",        118.50, FP["SMB"][1]),
    ("栅阻/下拉 ×4 + 100nF",        122.99, FP["R0603"][1]),
    ("功率 MOS  20N06 ×2",          128.70, FP["TO252"][1]),
    ("输出端子  Jn",                137.50, FP["KF2EDGV3P"][1]),
]

# 入电保护区的行结构(电流自下而上)
IN_ROWS = [
    ("RS1 + U1 + C6 →分配点",       82.00, FP["R2512"][1]),
    ("C4 C5 电解 + D1 TVS",         90.50, FP["ELEC8"][1]),
    ("C1 C2 C3 电解(体电容)",       100.00, FP["ELEC8"][1]),
    ("Q1‖Q2 P-MOS + DZ1 R1 Q3",     111.50, FP["TO252P"][1]),
    ("F1 主保险丝座 15A",           122.00, FP["ATO2"][1]),
    ("J1  24V 输入端子",            137.00, FP["KF7622P"][1]),
]

SPINE = dict(x0=8.5, x1=100.0, y0=73.0, y1=85.0)     # 24V 分配脊椎带
IN_BLOCK = dict(x0=101.0, y0=62.0, x1=130.0, y1=145.0)
ANT_KEEPOUT = dict(x0=0.0, y0=0.0, x1=8.0, y1=25.0)

HOLES = [("H4", 4.0, 30.0), ("H3", 126.0, 30.0),
         ("H2", 4.0, 79.0), ("H1", 126.0, 79.0)]
HOLE5 = ("H5", 103.0, 137.0)   # 建议新增

# ---------------------------------------------------------------- 分区定义
# (id, 名称, x0, y0, x1, y1, 填充色, 说明)
ZONES = [
    ("A1", "主控区", 0.0, 0.0, 40.0, 62.0, "#dbeafe",
     "U4 ESP32 天线朝左板边;复位/BOOT 键、状态灯"),
    ("A2", "USB / 串口区", 40.0, 0.0, 66.0, 62.0, "#e0e7ff",
     "J2 Type-C 在上板边;CH340C + 自动下载"),
    ("A3", "传感器 / 干接点接口区", 66.0, 0.0, 101.0, 26.0, "#e0f2fe",
     "J11 / J10 / J9 全部在上板边,插拔方向朝外"),
    ("A4", "低压电源区 (buck + OR + LDO)", 66.0, 26.0, 130.0, 62.0, "#fef3c7",
     "U2/L1/D2 开关环路 <2cm²;SW 铜面积最小"),
    ("A5", "栅极驱动区", 4.0, 62.0, 101.0, 71.0, "#ddd6fe",
     "U6 压在 CH1–CH4 质心、U7 压在 CH5–CH6 质心"),
    ("B0", "24V 分配脊椎 (纯铜箔)", SPINE["x0"], SPINE["y0"], SPINE["x1"], SPINE["y1"],
     "#fecaca", "双面 12mm 铜 + 每 3mm 一颗 0.5mm 缝合过孔;底层每列让出 6mm 信号车道"),
    ("D0", "入电保护区 (电流自下而上)", IN_BLOCK["x0"], IN_BLOCK["y0"],
     IN_BLOCK["x1"], IN_BLOCK["y1"], "#fed7aa",
     "J1→F1→Q1/Q2→体电容→RS1,一条直线不折返"),
    ("A0", "天线净空区", 0.0, 0.0, 8.0, 25.0, "#ffffff",
     "双面禁铜 / 无元件 / 无过孔 / 无螺丝"),
]

# ---------------------------------------------------------------- 元件归区
# 位号 → 区。每条规则是 (区 id, [位号...])
def ch_parts(n):
    """第 n 路(1..6)的 16 个元件位号,按 netlist-spec.md Block E 的复制规则。"""
    i = n - 1
    return [
        "F%d" % (2 + i),                       # 支路保险丝
        "J%d" % (3 + i),                       # 输出端子
        "Q%d" % (7 + 2 * i), "Q%d" % (8 + 2 * i),          # 2× MOS
        "R%d" % (16 + 6 * i), "R%d" % (17 + 6 * i),        # 2× 100Ω 栅阻
        "R%d" % (18 + 6 * i), "R%d" % (19 + 6 * i),        # 2× 栅源下拉 10k
        "D%d" % (5 + 4 * i), "D%d" % (6 + 4 * i),          # 2× 续流 SS36B
        "D%d" % (7 + 4 * i), "D%d" % (8 + 4 * i),          # 2× 输出 TVS
        "C%d" % (16 + 2 * i), "C%d" % (17 + 2 * i),        # 电解 + 去耦
        "LED%d" % (2 + 2 * i), "LED%d" % (3 + 2 * i),      # 2× 指示灯
        "R%d" % (20 + 6 * i), "R%d" % (21 + 6 * i),        # 2× 40.2k 限流
    ]


ASSIGN = [
    ("A1", ["U4", "C10", "C11", "R4", "C12", "R5", "SW1", "SW2", "LED1", "R8"]),
    ("A2", ["J2", "R9", "R10", "U5", "C13", "Q4", "Q5", "R11", "R12"]),
    ("A3", ["J9", "J10", "J11", "R52", "R53",
            "R54", "R55", "R56", "R57", "R58", "R59", "R60", "R61",
            "C28", "C29", "C30", "C31"]),
    ("A4", ["U2", "L1", "D2", "C32", "C33", "C34", "C35", "C38", "C39", "C40",
            "R62", "R63", "R64", "R65", "R66", "R67",
            "D3", "D4", "C41", "U3", "C42", "C43", "C36", "C37", "TP3", "TP4"]),
    ("A5", ["U6", "U7", "C14", "C15", "R13", "R14", "R15", "Q6", "TP5"]),
    ("B0", ["TP1"]),
    ("D0", ["J1", "F1", "Q1", "Q2", "R1", "DZ1", "Q3", "R2", "R3", "D1",
            "C1", "C2", "C3", "C4", "C5", "RS1", "U1", "C6", "PTC1", "TP2"]),
    ("MH", ["H1", "H2", "H3", "H4"]),
]
for _n in range(1, 7):
    ASSIGN.append(("C%d" % _n, ch_parts(_n)))
ASSIGN.append(("C1", ["TP6"]))   # TP6 = CH1_CW_D 波形点,只 CH1 有

ZONE_NAME = {z[0]: z[1] for z in ZONES}
ZONE_NAME["MH"] = "安装孔"
for _n in range(1, 7):
    ZONE_NAME["C%d" % _n] = "功率通道列 CH%d" % _n


# ---------------------------------------------------------------- 清点
def all_refs():
    """位号全集:cpl-jlc.csv 的 195 个贴装件 + 10 个非贴装件。"""
    refs = []
    with open(CPL, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            refs.append(row["Designator"].strip())
    refs += ["H1", "H2", "H3", "H4", "TP1", "TP2", "TP3", "TP4", "TP5", "TP6"]
    return refs


def census():
    refs = all_refs()
    ref_set = set(refs)
    assigned = {}
    dup = []
    for zid, lst in ASSIGN:
        for r in lst:
            if r in assigned:
                dup.append(r)
            assigned[r] = zid
    missing = sorted(ref_set - set(assigned))          # 有元件没归区
    ghost = sorted(set(assigned) - ref_set)            # 归了区但板上没有
    counts = {}
    for r, z in assigned.items():
        counts[z] = counts.get(z, 0) + 1
    return refs, assigned, counts, missing, ghost, dup


def print_census():
    refs, assigned, counts, missing, ghost, dup = census()
    order = ["A1", "A2", "A3", "A4", "A5", "B0",
             "C1", "C2", "C3", "C4", "C5", "C6", "D0", "MH"]
    print("| 区 | 名称 | 元件数 | 位号 |")
    print("|---|---|---:|---|")
    total = 0
    for z in order:
        lst = sorted([r for r, zz in assigned.items() if zz == z], key=sortkey)
        total += len(lst)
        print("| %s | %s | %d | %s |" % (z, ZONE_NAME[z], len(lst), " ".join(lst)))
    print("| **合计** | | **%d** | |" % total)
    print()
    print("板上位号总数 = %d;已归区 = %d;未归区 = %s;多余 = %s;重复 = %s"
          % (len(refs), total, missing or "无", ghost or "无", dup or "无"))
    return total, len(refs), missing, ghost, dup


def sortkey(r):
    i = 0
    while i < len(r) and not r[i].isdigit():
        i += 1
    return (r[:i], int(r[i:] or 0))


# ---------------------------------------------------------------- SVG
class Svg(object):
    def __init__(self):
        self.b = []

    def add(self, s):
        self.b.append(s)

    def rect(self, x, y, w, h, fill="none", stroke="none", sw=0.2, rx=0,
             dash=None, op=1.0):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<rect x="%.3f" y="%.3f" width="%.3f" height="%.3f" rx="%.2f" '
                 'fill="%s" fill-opacity="%.2f" stroke="%s" stroke-width="%.3f"%s/>'
                 % (x, y, w, h, rx, fill, op, stroke, sw, d))

    def line(self, x1, y1, x2, y2, stroke="#000", sw=0.2, dash=None, cap="round"):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<line x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f" stroke="%s" '
                 'stroke-width="%.3f" stroke-linecap="%s"%s/>'
                 % (x1, y1, x2, y2, stroke, sw, cap, d))

    def circle(self, cx, cy, r, fill="none", stroke="#000", sw=0.2):
        self.add('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="%s" stroke="%s" '
                 'stroke-width="%.3f"/>' % (cx, cy, r, fill, stroke, sw))

    def text(self, x, y, s, size=2.0, fill="#111", anchor="start",
             weight="normal", rot=None, family="PingFang SC, Hiragino Sans GB, "
             "Noto Sans CJK SC, Helvetica, sans-serif"):
        tr = ' transform="rotate(%.1f %.3f %.3f)"' % (rot, x, y) if rot else ""
        self.add('<text x="%.3f" y="%.3f" font-size="%.2f" fill="%s" '
                 'text-anchor="%s" font-weight="%s" font-family="%s"%s>%s</text>'
                 % (x, y, size, fill, anchor, weight, family, tr, esc(s)))

    def path(self, d, stroke="#000", sw=0.4, fill="none", marker=None, dash=None):
        m = ' marker-end="url(#%s)"' % marker if marker else ""
        da = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<path d="%s" fill="%s" stroke="%s" stroke-width="%.3f" '
                 'stroke-linecap="round" stroke-linejoin="round"%s%s/>'
                 % (d, fill, stroke, sw, m, da))


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


ARROW_PWR = "#dc2626"      # 24V 主干
ARROW_GND = "#334155"      # 地回流
ARROW_SIG = "#2563eb"      # 逻辑/信号


def build_svg():
    M_L, M_T, M_R, M_B = 48.0, 16.0, 46.0, 36.0
    vb = (-M_L, -M_T, BW + M_L + M_R, BH + M_T + M_B)
    s = Svg()
    s.add('<svg xmlns="http://www.w3.org/2000/svg" '
          'viewBox="%.2f %.2f %.2f %.2f" width="%.0f" height="%.0f">'
          % (vb[0], vb[1], vb[2], vb[3], vb[2] * 6.5, vb[3] * 6.5))
    s.add('<defs>')
    for name, col in (("apwr", ARROW_PWR), ("agnd", ARROW_GND), ("asig", ARROW_SIG)):
        s.add('<marker id="%s" viewBox="0 0 10 10" refX="8" refY="5" '
              'markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
              '<path d="M0,1 L9,5 L0,9 z" fill="%s"/></marker>' % (name, col))
    s.add('<pattern id="hatch" width="1.6" height="1.6" patternUnits="userSpaceOnUse" '
          'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="1.6" '
          'stroke="#94a3b8" stroke-width="0.35"/></pattern>')
    s.add('</defs>')
    s.add('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff"/>'
          % (vb[0], vb[1], vb[2], vb[3]))

    # ---- 标题
    s.text(-M_L + 2, -M_T + 6.0, "CCT LED 驱动板 · v2 楼层规划", size=5.0, weight="bold")
    s.text(-M_L + 2, -M_T + 11.2,
           "板框 130 × 145 mm(推荐)· 1:1 · 原点左上角 · 文件方向 = 上墙方向(端子在下)",
           size=2.6, fill="#475569")

    # ---- 现版板框参考
    s.rect(0, 0, V1_BW, V1_BH, stroke="#94a3b8", sw=0.35, dash="2 1.5")
    s.text(V1_BW - 1.0, -1.6, "现版板框 110×145", size=2.0, fill="#64748b", anchor="end")

    # ---- 新板框
    s.rect(0, 0, BW, BH, fill="#f8fafc", stroke="#0f172a", sw=0.7, rx=2.0)
    s.text(BW + 1.2, -1.6, "v2 板框 130×145", size=2.2, fill="#0f172a", anchor="end")

    # ---- 分区
    for zid, name, x0, y0, x1, y1, col, note in ZONES:
        w, h = x1 - x0, y1 - y0
        if zid == "A0":
            s.rect(x0, y0, w, h, fill="url(#hatch)", stroke="#64748b", sw=0.35,
                   dash="1.5 1")
        else:
            s.rect(x0, y0, w, h, fill=col, stroke="#475569", sw=0.3, op=0.85)

    # ---- 功率通道列(6 列 + 行带)
    cx_min = CH_X[6] - CH_HALF
    cx_max = CH_X[1] + CH_HALF
    s.rect(cx_min, 85.0, cx_max - cx_min, BH - 85.0, fill="#dcfce7",
           stroke="#475569", sw=0.3, op=0.85)
    for n in (1, 2, 3, 4, 5, 6):
        x = CH_X[n] - CH_HALF
        s.line(x, 85.0, x, BH - 1.0, stroke="#16a34a", sw=0.25, dash="1.2 1.2")
    s.line(cx_max, 85.0, cx_max, BH - 1.0, stroke="#16a34a", sw=0.25, dash="1.2 1.2")
    for label, cy, hgt in CH_ROWS:
        s.rect(cx_min + 0.4, cy - hgt / 2, (cx_max - cx_min) - 0.8, hgt,
               fill="#86efac", stroke="#15803d", sw=0.2, op=0.55)
        s.text(cx_min - 1.4, cy + 0.8, label, size=2.0, fill="#14532d", anchor="end")
    for n in (1, 2, 3, 4, 5, 6):
        s.text(CH_X[n], 90.6, "CH%d" % n, size=2.6, fill="#14532d",
               anchor="middle", weight="bold")

    # ---- 入电保护区行带
    ib = IN_BLOCK
    for label, cy, hgt in IN_ROWS:
        s.rect(ib["x0"] + 0.8, cy - hgt / 2, (ib["x1"] - ib["x0"]) - 1.6, hgt,
               fill="#fdba74", stroke="#c2410c", sw=0.2, op=0.6)
        s.text(ib["x1"] + 1.2, cy + 0.7, label, size=1.9, fill="#7c2d12")

    # ---- 区标题文字
    def ztitle(zid, tx, ty, name, note=None, size=2.4, anchor="start", col="#0f172a"):
        s.text(tx, ty, name, size=size, weight="bold", fill=col, anchor=anchor)
        if note:
            s.text(tx, ty + 2.7, note, size=1.85, fill="#475569", anchor=anchor)

    ztitle("A1", 8.0, 32.0, "A1 主控区", "U4 ESP32 · 复位/BOOT 键")
    s.text(8.0, 36.4, "x 0–40  y 0–62", size=1.8, fill="#64748b")
    ztitle("A2", 41.5, 46.0, "A2 USB / 串口", "J2 Type-C · CH340C · 自动下载")
    s.text(41.5, 50.4, "x 40–66  y 0–62", size=1.8, fill="#64748b")
    ztitle("A3", 67.5, 12.0, "A3 传感器 / 干接点接口", "J11 · J10 · J9 全在上板边")
    s.text(67.5, 16.4, "x 66–101  y 0–26", size=1.8, fill="#64748b")
    ztitle("A4", 67.5, 36.0, "A4 低压电源 buck + LDO",
           "U2 / L1 / D2 环路 <2cm² · U3 · OR 二极管")
    s.text(67.5, 40.4, "x 66–130  y 26–62", size=1.8, fill="#64748b")
    s.text(5.5, 65.6, "A5 栅极驱动区  x 4–101  y 62–71", size=2.0,
           weight="bold", fill="#4c1d95")
    s.text(5.5, 69.4, "U6 压 CH1–4 质心 x=68 · U7 压 CH5–6 质心 x=20 · "
                      "栅阻与下拉全部下放到 MOS 栅极旁", size=1.8, fill="#4c1d95")
    s.text(10.5, 75.9, "B0  24V 分配脊椎  x 8.5–100  y 73–85", size=2.0,
           weight="bold", fill="#991b1b")
    s.text(ib["x0"] + 1.4, 66.5, "D0 入电保护区", size=2.4, weight="bold", fill="#7c2d12")
    s.text(ib["x0"] + 1.4, 69.6, "x 101–130  y 62–145", size=1.8, fill="#7c2d12")
    s.text(ib["x0"] + 1.4, 72.6, "电流自下而上一条直线", size=1.8, fill="#7c2d12")
    s.text(4.0, 12.0, "A0 天线净空", size=2.0, weight="bold", fill="#334155",
           anchor="middle", rot=-90)

    # ---- 安装孔
    for name, hx, hy in HOLES:
        s.circle(hx, hy, 1.6, fill="#ffffff", stroke="#0f172a", sw=0.45)
        s.circle(hx, hy, 3.5, fill="none", stroke="#0f172a", sw=0.2)
        s.text(hx, hy - 4.6, name, size=2.0, anchor="middle", weight="bold")
    hn, hx, hy = HOLE5
    s.circle(hx, hy, 1.6, fill="#ffffff", stroke="#0f172a", sw=0.4)
    s.circle(hx, hy, 3.5, fill="none", stroke="#0f172a", sw=0.25)
    s.line(hx, hy + 4.0, hx, hy + 10.0, stroke="#0f172a", sw=0.25)
    s.text(hx, hy + 13.0, hn + " 建议新增(J3 与 J1 之间 9.6mm 空当)", size=2.0,
           anchor="middle", fill="#0f172a")

    # ================= 电流主干走向 =================
    # 1) 入电:J1 → 上行穿过保护链 → RS1
    s.path("M 116,130.5 L 116,85.0", stroke=ARROW_PWR, sw=1.6, marker="apwr")
    # 2) RS1 → 分配点 → 脊椎左行
    s.path("M 111,80.0 L 102.0,80.0 L 102.0,79.4 L 13,79.4",
           stroke=ARROW_PWR, sw=1.6, marker="apwr")
    # 3) 脊椎 → 每列下行(到保险丝)
    for n in (1, 2, 3, 4, 5, 6):
        s.path("M %.1f,79.4 L %.1f,86.4" % (CH_X[n], CH_X[n]),
               stroke=ARROW_PWR, sw=1.0, marker="apwr")
    # 4) 每列内部:保险丝 → … → 端子(向下)
    for n in (1, 2, 3, 4, 5, 6):
        x = CH_X[n] + 6.4
        s.path("M %.1f,92.5 L %.1f,133.2" % (x, x), stroke=ARROW_PWR, sw=0.65,
               marker="apwr", dash="2 1.4")
    # 5) 地回流:MOS 源极 → 沿底部带右行 → J1 负极
    s.path("M 8,143.4 L 110,143.4", stroke=ARROW_GND, sw=1.1, marker="agnd")

    # ================= 逻辑 / 信号走向 =================
    s.path("M 30,20 L 38.0,20 L 38.0,58.8 L 20,58.8 L 20,63.5",
           stroke=ARROW_SIG, sw=0.8, marker="asig")
    s.path("M 30,17 L 39.4,17 L 39.4,55.6 L 68,55.6 L 68,63.5",
           stroke=ARROW_SIG, sw=0.8, marker="asig")
    for n in (1, 2, 3, 4, 5, 6):
        x = CH_X[n] - 6.4
        s.path("M %.1f,70.5 L %.1f,121.8" % (x, x), stroke=ARROW_SIG, sw=0.55,
               marker="asig", dash="1.6 1.3")

    # ---- 电流标注
    s.text(121.5, 108, "24V 进线", size=2.2, fill=ARROW_PWR, weight="bold",
           rot=-90, anchor="middle")
    s.text(56, 77.8, "24V 分配 · 单向左行 · 全程不折返", size=2.1,
           fill=ARROW_PWR, weight="bold", anchor="middle")

    # ================= 图例 =================
    ly = BH + 6.0
    s.text(-M_L + 2, ly, "图例", size=2.6, weight="bold")
    items = [
        (ARROW_PWR, "24V 功率主干(粗)/ 每路 3A 支路(细虚线)—— 全程只向左、向下"),
        (ARROW_GND, "GND 功率回流:6 路 MOS 源极 → 底部带向右 → J1 负极,不进逻辑区"),
        (ARROW_SIG, "逻辑与栅极信号:ESP32 → U6/U7 → 12 根垂直下行,每列只走本列的网络"),
    ]
    for i, (col, txt) in enumerate(items):
        yy = ly + 4.6 + i * 4.4
        s.line(-M_L + 2, yy - 0.8, -M_L + 12, yy - 0.8, stroke=col, sw=1.2)
        s.text(-M_L + 14, yy, txt, size=2.2, fill="#0f172a")
    s.text(-M_L + 2, ly + 22.5,
           "尺寸全部为 courtyard 实测值(取自 cct-main.kicad_pcb);"
           "本图是楼层规划,不是最终摆位。生成脚本:hardware/gen_floorplan_svg.py",
           size=2.0, fill="#64748b")
    s.text(-M_L + 2, ly + 26.2,
           "通道列距 16mm(现版 14mm)· 行间距 ≥2.2mm 作丝印预算 · "
           "保险丝下方 8.0mm 镊子净空 · 205 个元件全部归区 · "
           "脊椎双面 12mm 铜 + 每 3mm 一颗缝合过孔,15A 压降 39mV / 0.59W(按铜箔电阻率估算)",
           size=2.0, fill="#64748b")

    s.add('</svg>')
    return "\n".join(s.b)


def main():
    if "--census" in sys.argv:
        print_census()
        return
    total, n, missing, ghost, dup = print_census()
    if missing or ghost or dup:
        print("!! 归区不完整,请修正 ASSIGN", file=sys.stderr)
        sys.exit(1)
    with open(OUT_SVG, "w", encoding="utf-8") as f:
        f.write(build_svg())
    print("\n写出 %s" % OUT_SVG)


if __name__ == "__main__":
    main()
