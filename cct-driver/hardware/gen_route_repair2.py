#!/usr/bin/env python3
"""修复第二轮:撤销第一轮错误配方,按实测焊盘几何重画。KiCad python 运行。

要点:
- 六通道三线新配方:VOUT 右侧斜线接 D6.1;CW 中缝下行左绕 D6.1 入 Q_cw 大焊盘;
  WW 走 col-6.2 左车道入 Q_ww 大焊盘,D6.2 右侧竖线并入;TVS 支路(D7 走 B.Cu / D8 绕右)。
- V24_BUS 立管移到 x18.8-24(B)+ x19.5-24(F),给 CH1 WW 车道让路。
- 左列:V24_FUSED 母排 y23.6;PMOS_GATE 走双管散热片中缝 x11;GND 汇流 y41.23 → x17 过孔。
- USB_VBUS / CC2 / BOOT / V24_LOGIC 末段 / LED6_K / TP 迁址。
"""
from pathlib import Path
import gc, math, os
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = Path(__file__).parent
board = pcbnew.LoadBoard(str(HERE / "cct-main.kicad_pcb"))
mm = pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu

def net(n):
    x = board.FindNet(n); assert x, n; return x

def pad_of(ref, num):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            for p in fp.Pads():
                if p.GetNumber() == str(num):
                    return p
    raise SystemExit(f"no {ref}.{num}")

def ppos(ref, num):
    p = pad_of(ref, num).GetPosition()
    return mm(p.x), mm(p.y)

NEW_SEGS = []   # (x1,y1,x2,y2,halfw,layer) 用于后续 GND 过孔避让
def trk(pts, netname, w, layer=F):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        board.Add(t)
        NEW_SEGS.append((x1, y1, x2, y2, w / 2, layer))

def via(x, y, netname, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(net(netname)); v.SetLayerPair(F, B)
    board.Add(v)

def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

# ============ 0. 撤销与清理 ============
removed = {"trk": 0, "via": 0, "zone": 0}
SNAP = list(board.GetTracks())
DELETED = set()
def is_via(t): return t.Type() == pcbnew.PCB_VIA_T

def del_item(t):
    if id(t) in DELETED:
        return
    DELETED.add(id(t))
    board.Remove(t)
    if is_via(t): removed["via"] += 1
    else: removed["trk"] += 1

def live():
    return [t for t in SNAP if id(t) not in DELETED]

# 0a. 全删网络:六通道三线(仅功率网,信号网 CHn_CW/_G/_GR 不受影响)+ 左列局部网
FULL_DEL = set()
for i in range(1, 7):
    FULL_DEL |= {f"CH{i}_VOUT", f"CH{i}_CW_D", f"CH{i}_WW_D"}
FULL_DEL |= {"V24_FUSED", "PMOS_GATE"}
for t in live():
    if t.GetNetname() in FULL_DEL:
        del_item(t)

def ends(t):
    return mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)

def match_seg(t, x1, y1, x2, y2, tol=0.08):
    a = ends(t)
    return ((abs(a[0]-x1) < tol and abs(a[1]-y1) < tol and abs(a[2]-x2) < tol and abs(a[3]-y2) < tol) or
            (abs(a[0]-x2) < tol and abs(a[1]-y2) < tol and abs(a[2]-x1) < tol and abs(a[3]-y1) < tol))

# 0b. 精确删除第一轮/收尾脚本的具体走线与过孔
EXACT = [
    ("V3P3",       [(10.0, 49.5, 10.0, 48.2), (10.0, 48.2, 16.5, 48.2),
                    (16.5, 48.2, 16.5, 50.0), (16.5, 50.0, 15.0, 50.0)]),
    ("V24_BUS",    [(8.5, 49.5, 8.5, 47.6), (8.5, 47.6, 14.27, 47.6),
                    (14.27, 47.6, 14.27, 46.31),
                    (14.07, 46.31, 26.0, 46.31)]),          # 旧 RS1 粗短线
    ("V24_LOGIC",  [(38.0, 105.0, 35.5, 105.0), (35.5, 105.0, 35.5, 109.26),
                    (35.5, 109.26, 31.37, 109.26)]),
    ("MASTER_OFF_B", [(13.75, 43.12, 13.75, 39.34)]),        # 与 GND 汇流冲突的竖段
    ("CH1_CW_GR",  [(23.95, 75.66, 26.55, 73.06)]),          # TP5 旧短线
    ("GND",        [(72.8, 138.53, 72.8, 136.33), (79.2, 138.53, 79.2, 136.33)]),  # J2 屏蔽
]
for netname, segs in EXACT:
    for t in live():
        if is_via(t) or t.GetNetname() != netname:
            continue
        for s in segs:
            if match_seg(t, *s):
                del_item(t); break

# 0c. 第一轮左列 GND 短线(端点 x=19)与过孔(x=19.6)
for t in live():
    if t.GetNetname() != "GND":
        continue
    if is_via(t):
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        if abs(x - 19.6) < 0.05 and y < 60:
            del_item(t)
    else:
        x1, y1, x2, y2 = ends(t)
        if (abs(x1 - 19.0) < 0.05 and y1 < 60) or (abs(x2 - 19.0) < 0.05 and y2 < 60):
            del_item(t)
        elif match_seg(t, 9.5, 49.5, 9.5, 51.7):
            del_item(t)

# 0d. U2 散热盘上第一轮加的 4 颗过孔(封装自带阵列,冲突)
for t in live():
    if is_via(t) and t.GetNetname() == "GND":
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        if (abs(abs(x - 32.0) - 0.8) < 0.05) and (abs(abs(y - 106.49) - 0.8) < 0.05):
            del_item(t)

# 0e. 旧立管过孔(x=23/25)与游离 V24_BUS 走线
for t in live():
    if t.GetNetname() != "V24_BUS":
        continue
    if is_via(t):
        x = mm(t.GetPosition().x)
        if abs(x - 23.0) < 0.1 or abs(x - 25.0) < 0.1:
            del_item(t)
    else:
        x1, y1, x2, y2 = ends(t)
        w = mm(t.GetWidth())
        # 保险丝短线(竖直 w2.0)保留
        if abs(x1 - x2) < 0.01 and abs(w - 2.0) < 0.05:
            continue
        if y1 < 17.3 and y2 < 17.3 and abs(x1 - x2) > 1.0:
            del_item(t)                       # freerouting 在带顶乱窜的横线
        elif 19 < min(x1, x2) and max(x1, x2) < 27.5 and 17 < min(y1, y2) and max(y1, y2) < 45.5:
            del_item(t)                       # 旧立管走廊内碎线

# 0f. 悬空 V3P3 过孔 (55,142)
for t in live():
    if is_via(t) and t.GetNetname() == "V3P3":
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        if abs(x - 55) < 0.6 and abs(y - 142) < 0.6:
            del_item(t)

# 0g. 通道功率带内旧 MOS 源极 GND 过孔(将按新偏移重打)
for t in live():
    if is_via(t) and t.GetNetname() == "GND":
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        if x > 24 and 26 < y < 64:
            del_item(t)

# 0h. 旧 BUS/PROT_L 覆铜
for z in list(board.Zones()):
    if z.GetZoneName() in ("BUS_STRIP", "BUS_RISER", "BUS_RISER_F", "PROT_L"):
        board.Remove(z); removed["zone"] += 1
print("撤销:", removed)
if os.environ.get("PHASE") == "del":
    pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
    print("✅ 撤销阶段已保存")
    raise SystemExit(0)

# ============ 1. 新覆铜(主干) ============
def add_zone(netname, layer, x1, y1, x2, y2, priority, name, min_w=0.3, clearance=0.3):
    z = pcbnew.ZONE(board)
    z.SetNet(net(netname)); z.SetLayer(layer)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(FromMM(clearance)); z.SetMinThickness(FromMM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    ol = z.Outline(); ol.NewOutline()
    for (x, y) in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        ol.Append(FromMM(x), FromMM(y))
    z.SetZoneName(name); board.Add(z)
    return z

add_zone("V24_BUS", B, 18.8, 13.16, 103.0, 16.86, 2, "BUS_STRIP")
add_zone("V24_BUS", B, 18.8, 13.16, 24.0, 48.3, 3, "BUS_RISER")
add_zone("V24_BUS", F, 19.5, 13.5, 24.0, 48.3, 3, "BUS_RISER_F")
add_zone("V24_PROT", F, 3.0, 29.1, 18.5, 48.3, 2, "PROT_L")

# 立管 F/B 缝合过孔(避开 F1 无网络焊盘 x16.5-19,避开 CH1 WW 车道 x23.2+)
for yy in [14.6, 18.0, 24.0, 30.0, 36.0, 42.0, 45.3, 47.3]:
    for xx in [20.4, 21.9]:
        via(xx, yy, "V24_BUS", 1.0, 0.5)
# RS1.2 → 立管粗短线
rs2x, rs2y = ppos("RS1", 2)
trk([(rs2x, rs2y), (21.5, rs2y)], "V24_BUS", 2.8)
# PROT_L → B.Cu 立管(PROT_RISER_B)补过孔(RS1.1 附近)
for (xx, yy) in [(3.6, 44.6), (5.2, 44.6), (3.6, 46.6), (5.2, 46.6)]:
    via(xx, yy, "V24_PROT", 1.0, 0.5)

# ============ 2. 左列走线 ============
# V24_FUSED:F1.2 → 母排 y23.6 → Q1.3 / Q2.3;左绕竖线 → DZ1.1
f2x, f2y = ppos("F1", 2)            # (4.26,21.2)
q13x, q13y = ppos("Q1", 3)          # (5.31,25.89)
q23x, q23y = ppos("Q2", 3)          # (12.11,25.89)
dz1x, dz1y = ppos("DZ1", 1)         # (5.36,37.09)
trk([(f2x, f2y), (f2x, 23.6)], "V24_FUSED", 3.0)
trk([(f2x, 23.6), (q23x, 23.6)], "V24_FUSED", 2.5)
trk([(q13x, 23.6), (q13x, q13y)], "V24_FUSED", 1.4)
trk([(q23x, 23.6), (q23x, q23y)], "V24_FUSED", 1.2)
trk([(4.6, 25.89), (3.4, 26.7), (3.4, 36.5), (4.6, 37.09), (dz1x, dz1y)], "V24_FUSED", 0.5)

# PMOS_GATE:中缝 x11 竖线 + 顶部横线到两栅极;下端接 DZ1.2/R1.1/Q3.3
q11x, q11y = ppos("Q1", 1)          # (9.89,25.89)
q21x, q21y = ppos("Q2", 1)          # (16.69,25.89)
dz2x, dz2y = ppos("DZ1", 2)         # (8.64,37.09)
r11x, r11y = ppos("R1", 1)          # (6.25,39.34)
q33x, q33y = ppos("Q3", 3)          # (6.00,42.17)
trk([(10.8, q11y), (11.0, 26.2), (11.0, 27.4)], "PMOS_GATE", 0.4)
trk([(11.0, 27.4), (q21x, 27.4), (q21x, 26.2)], "PMOS_GATE", 0.4)
trk([(11.0, 27.4), (11.0, 36.0), (dz2x, dz2y)], "PMOS_GATE", 0.4)
trk([(dz2x, dz2y), (dz2x, 38.5), (r11x, 38.5), (r11x, r11y)], "PMOS_GATE", 0.4)
trk([(r11x, r11y), (r11x, 41.3), (q33x, q33y)], "PMOS_GATE", 0.4)

# MASTER_OFF_B:竖段改 B.Cu 跳线(避让 GND 汇流横线)
via(13.75, 43.12, "MASTER_OFF_B", 0.6, 0.3)
trk([(13.75, 43.12), (13.75, 40.35)], "MASTER_OFF_B", 0.25, layer=B)
via(13.75, 40.35, "MASTER_OFF_B", 0.6, 0.3)
trk([(13.75, 40.35), (13.75, 39.34)], "MASTER_OFF_B", 0.25)

# 左列 GND:汇流 y41.23 → x17 过孔带(PROT_RISER_B 与 BUS_RISER 之间)
trk([(7.75, 39.34), (7.75, 40.5), (8.0, 41.23)], "GND", 0.4)     # R1.2 → Q3.2
trk([(8.0, 41.23), (16.5, 41.23)], "GND", 0.4)
via(17.0, 41.23, "GND")
trk([(16.5, 41.23), (17.0, 41.23)], "GND", 0.4)
trk([(15.25, 36.83), (16.6, 36.83)], "GND", 0.4); via(17.05, 36.83, "GND")
trk([(16.6, 36.83), (17.05, 36.83)], "GND", 0.4)
trk([(15.25, 39.34), (16.6, 39.34)], "GND", 0.4); via(17.05, 39.34, "GND")
trk([(16.6, 39.34), (17.05, 39.34)], "GND", 0.4)
# U1 GND:pad7 经芯片体下方接 D1.2;pad1-2 桥接并向左引出
trk([(9.5, 49.5), (9.5, 52.0), (11.2, 53.0), (11.2, 55.5), (13.36, 57.31)], "GND", 0.3)
trk([(8.0, 54.2), (8.5, 54.2)], "GND", 0.25)
trk([(8.0, 54.2), (6.8, 54.2)], "GND", 0.3)
# U1 细脚:V3P3(p6)→ C6.1;V24_BUS 开尔文(p9)→ RS1.2 下缘
trk([(10.0, 49.5), (10.6, 49.69), (15.1, 49.69)], "V3P3", 0.25)
trk([(8.5, 49.5), (8.5, 48.55), (13.5, 48.55), (14.07, 47.9), (14.07, rs2y)], "V24_BUS", 0.3)

# ============ 3. 六通道三线配方(实测几何版) ============
CH = [("J3", "F2", "D6", "D7", "D8", "Q7", "Q8"),
      ("J4", "F3", "D10", "D11", "D12", "Q9", "Q10"),
      ("J5", "F4", "D14", "D15", "D16", "Q11", "Q12"),
      ("J6", "F5", "D18", "D19", "D20", "Q13", "Q14"),
      ("J7", "F6", "D22", "D23", "D24", "Q15", "Q16"),
      ("J8", "F7", "D26", "D27", "D28", "Q17", "Q18")]
for i, (J, Fu, Dfw, Dtvc, Dtvw, Qc, Qw) in enumerate(CH):
    ch = f"CH{i+1}"
    p1x, p1y = ppos(J, 1)     # VOUT (col+3.81, 8)
    p2x, p2y = ppos(J, 2)     # CW_D (col, 8)
    p3x, p3y = ppos(J, 3)     # WW_D (col-3.81, 8)
    fux, fuy = ppos(Fu, 2)    # 保险丝出线 (col+3.4, 18.66)
    d1x, d1y = ppos(Dfw, 1)   # VOUT 侧 (col+0.24, 28.23)
    d2x, d2y = ppos(Dfw, 2)   # WW_D 侧 (col+4.96, 28.23)
    tc_x, tc_y = ppos(Dtvc, 1)  # CW TVS (col-4.96, 56.31)
    tw_x, tw_y = ppos(Dtvw, 1)  # WW TVS (col+0.24, 60.74)
    col = p2x
    # --- VOUT:J.1 → F.2 → 斜线 → D6.1 ---
    trk([(p1x, p1y), (p1x, 15.0), (fux, 16.6), (fux, fuy)], f"{ch}_VOUT", 2.0)
    trk([(fux, 20.0), (d1x, 26.9), (d1x, d1y)], f"{ch}_VOUT", 1.6)
    trk([(fux, fuy), (fux, 20.0)], f"{ch}_VOUT", 2.0)
    # --- CW:中缝直下,左绕 D6.1 入 Q_cw 大焊盘 ---
    trk([(p2x, p2y), (col, 23.2), (col - 1.8, 24.8), (col - 1.8, 31.5)], f"{ch}_CW_D", 1.2)
    # CW TVS 支路:大焊盘内过孔 → B.Cu 左下 → D7.1
    via(col - 1.5, 36.2, f"{ch}_CW_D", 0.8, 0.4)
    trk([(col - 1.5, 36.2), (tc_x, 39.5), (tc_x, 54.6)], f"{ch}_CW_D", 1.0, layer=B)
    via(tc_x, 54.6, f"{ch}_CW_D", 0.8, 0.4)
    trk([(tc_x, 54.6), (tc_x, tc_y)], f"{ch}_CW_D", 1.0)
    # --- WW:左车道 col-6.2 下行入 Q_ww 大焊盘;D6.2 右侧竖线并入;D8 绕右支路 ---
    lane = col - 6.2
    trk([(p3x, p3y), (p3x, 11.5), (lane, 14.5), (lane, 42.6), (col - 2.0, 45.6)], f"{ch}_WW_D", 1.2)
    trk([(d2x, d2y), (d2x, 42.6), (col + 2.4, 45.4)], f"{ch}_WW_D", 1.2)
    trk([(col + 2.5, 48.5), (col + 4.2, 50.5), (col + 4.2, 58.0), (tw_x, 60.5)], f"{ch}_WW_D", 1.0)
    # --- MOS 源极 GND 缝合过孔(避开新支路) ---
    via(col + 3.28, 41.82, "GND", 0.8, 0.4)   # CW 管源极旁
    via(col + 2.9, 54.4, "GND", 0.8, 0.4)     # WW 管源极旁

# ============ 4. 收尾网络 ============
# V24_LOGIC → U2.2:盘中孔 + B.Cu 绕行接宽走线馈电
u22x, u22y = ppos("U2", 2)          # (31.37,109.26)
via(u22x, 109.8, "V24_LOGIC", 0.6, 0.3)
trk([(u22x, 109.8), (33.5, 108.0), (39.5, 105.4), (39.5, 105.2)], "V24_LOGIC", 0.5, layer=B)
via(39.5, 105.2, "V24_LOGIC", 0.6, 0.3)
# BOOT:U2.1 盘中孔 → B.Cu 下绕 → C38.1
u21x, u21y = ppos("U2", 1)          # (30.10,109.26)
c381x, c381y = ppos("C38", 1)       # (46.30,111.04)
via(u21x, 109.8, "BOOT", 0.6, 0.3)
trk([(u21x, 109.8), (29.3, 111.0), (29.3, 113.9), (31.0, 114.9), (44.8, 114.9),
     (46.0, 113.7), (46.0, 112.2)], "BOOT", 0.3, layer=B)
via(46.0, 112.2, "BOOT", 0.6, 0.3)
trk([(46.0, 112.2), (c381x, 111.4), (c381x, c381y)], "BOOT", 0.3)
# USB_VBUS:D4.2 → B.Cu 斜线 → A4B9;A4B9 ↔ B4A9 经 B.Cu 桥
d42x, d42y = ppos("D4", 2)          # (44.36,125.80)
a49x, a49y = ppos("J2", "A4B9")     # (73.60,138.53)
b49x, b49y = ppos("J2", "B4A9")     # (78.40,138.53)
trk([(d42x, d42y), (d42x, 126.6)], "USB_VBUS", 0.8)
via(d42x, 127.1, "USB_VBUS", 0.6, 0.3)
trk([(d42x, 127.1), (a49x, 135.9), (a49x, 136.3)], "USB_VBUS", 0.5, layer=B)
via(a49x, 136.3, "USB_VBUS", 0.6, 0.3)
trk([(a49x, 136.3), (a49x, a49y)], "USB_VBUS", 0.3)
trk([(a49x, 136.3), (b49x, 136.3)], "USB_VBUS", 0.4, layer=B)
via(b49x, 136.3, "USB_VBUS", 0.6, 0.3)
trk([(b49x, 136.3), (b49x, b49y)], "USB_VBUS", 0.3)
# CC2:R10.1 → B.Cu → B5
r101x, r101y = ppos("R10", 1)       # (49.25,135)
b5x, b5y = ppos("J2", "B5")         # (77.75,138.53)
trk([(r101x, r101y), (r101x, 136.0)], "CC2", 0.25)
via(r101x, 136.4, "CC2", 0.6, 0.3)
trk([(r101x, 136.4), (b5x, 137.5)], "CC2", 0.25, layer=B)
via(b5x, 137.5, "CC2", 0.6, 0.3)
trk([(b5x, 137.5), (b5x, b5y)], "CC2", 0.25)
# LED6_K:R32.1 → LED6.2
trk([(16.05, 83.56), (16.05, 83.0), (17.31, 81.26), (17.31, 80.56)], "LED6_K", 0.3)

# ============ 5. TP5/TP6 迁址(放到本网走线上) ============
def move_tp(ref, x, y):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
            return
move_tp("TP6", 30.0, 12.5)          # CH1_CW_D 中缝直线上(J3 与 F2 之间)
# TP5:沿 CH1_CW_GR 既有走线找一个净空点
tp5_done = False
cands = []
for t in live():
    if is_via(t) or t.GetNetname() != "CH1_CW_GR":
        continue
    x1, y1, x2, y2 = ends(t)
    if t.GetLayer() != F or math.hypot(x2-x1, y2-y1) < 3.0:
        continue
    for frac in (0.5, 0.35, 0.65, 0.2, 0.8):
        cands.append((x1 + (x2-x1)*frac, y1 + (y2-y1)*frac))
def spot_clear(px, py):
    for fp in board.GetFootprints():
        if fp.GetReference() in ("TP5",):
            continue
        bb = fp.GetBoundingBox()
        if (mm(bb.GetLeft()) - 0.4 < px < mm(bb.GetRight()) + 0.4 and
                mm(bb.GetTop()) - 0.4 < py < mm(bb.GetBottom()) + 0.4):
            return False
    for t in live():
        if t.GetNetname() == "CH1_CW_GR":
            continue
        if is_via(t):
            if math.hypot(px - mm(t.GetPosition().x), py - mm(t.GetPosition().y)) < 1.4:
                return False
        else:
            x1, y1, x2, y2 = ends(t)
            if seg_dist(px, py, x1, y1, x2, y2) < mm(t.GetWidth())/2 + 1.05:
                return False
    for (x1, y1, x2, y2, hw, _ly) in NEW_SEGS:
        if seg_dist(px, py, x1, y1, x2, y2) < hw + 1.05:
            return False
    return True
for (px, py) in cands:
    if spot_clear(px, py):
        move_tp("TP5", px, py)
        tp5_done = True
        print(f"TP5 → ({px:.2f},{py:.2f})")
        break
if not tp5_done:
    print("⚠️ TP5 未找到净空点,留在原位需手查")

# ============ 6. 重填、保存 ============
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones():
    zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
