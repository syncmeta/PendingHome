#!/usr/bin/env python3
"""布线修补:补齐 freerouting 未完成的连接,清理覆铜/过孔冲突。KiCad python 运行。"""
from pathlib import Path
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

def trk(pts, netname, w, layer=F):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        board.Add(t)

def via(x, y, netname, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(net(netname)); v.SetLayerPair(F, B)
    board.Add(v)

# ---- 0. 清理:砸中别网走线的 GND 缝合过孔、贴边 GND 走线、间距过近的 BUS 过孔 ----
removed = 0
gnd_code = net("GND").GetNetCode()
tracks = [t for t in board.GetTracks() if not t.Type() == pcbnew.PCB_VIA_T]
vias = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
def near(ax, ay, bx, by, d): return (ax-bx)**2 + (ay-by)**2 < d*d
for v in list(vias):
    if v.GetNetCode() != gnd_code: continue
    vx, vy = mm(v.GetPosition().x), mm(v.GetPosition().y)
    hit = False
    for t in tracks:
        if t.GetNetCode() == gnd_code: continue
        for pt in (t.GetStart(), t.GetEnd()):
            if near(vx, vy, mm(pt.x), mm(pt.y), 1.6): hit = True; break
        # 线段中段粗判
        sx, sy, ex, ey = mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)
        if min(sx,ex)-1 < vx < max(sx,ex)+1 and min(sy,ey)-1 < vy < max(sy,ey)+1:
            # 距线段距离
            import math
            dx, dy = ex-sx, ey-sy
            L2 = dx*dx+dy*dy
            if L2 > 0:
                tt = max(0, min(1, ((vx-sx)*dx+(vy-sy)*dy)/L2))
                px, py = sx+tt*dx, sy+tt*dy
                if near(vx, vy, px, py, 1.1): hit = True
        if hit: break
    # 悬空(30,142)与 J11 冲突的那颗也会被下面的孔距判定清掉
    if hit or near(vx, vy, 30, 142, 1.5):
        board.Remove(v); removed += 1
for t in list(tracks):
    if t.GetNetCode() != gnd_code: continue
    if max(mm(t.GetStart().x), mm(t.GetEnd().x)) > 109.3:
        board.Remove(t); removed += 1
# BUS 过孔太挤的一对:删 (25,16) 附近多余那颗
for v in list(vias):
    if v.GetNetname() == "V24_BUS" and near(mm(v.GetPosition().x), mm(v.GetPosition().y), 25.0, 16.0, 0.6):
        board.Remove(v); removed += 1; break
print(f"清理 {removed} 项")

# ---- 1. 左列小网络(被禁布区困住的)----
# V24_FUSED: F1.p2 → Q1.p3 → Q2.p3;DZ1.K
f1x, f1y = ppos("F1", 2)
q1fx, q1fy = ppos("Q1", 3); q2fx, q2fy = ppos("Q2", 3)
dzkx, dzky = ppos("DZ1", 1)
trk([(f1x, f1y), (q1fx, q1fy)], "V24_FUSED", 1.5)
trk([(q1fx, q1fy), (q2fx, q2fy)], "V24_FUSED", 1.5)
trk([(q1fx, q1fy), (2.0, q1fy), (2.0, dzky), (dzkx, dzky)], "V24_FUSED", 0.6)
# PMOS_GATE: Q1.G, Q2.G, DZ1.A, R1.1, Q3.C
q1gx, q1gy = ppos("Q1", 1); q2gx, q2gy = ppos("Q2", 1)
dzax, dzay = ppos("DZ1", 2)
r1ax, r1ay = ppos("R1", 1)
q3cx, q3cy = ppos("Q3", 3)
LANE = (q1gx + q2gx) / 2 + 0.35   # 两管散热片之间的窄缝
trk([(q1gx, q1gy), (LANE, q1gy + 1.2), (LANE, 38.3), (r1ax, r1ay)], "PMOS_GATE", 0.25)
trk([(q2gx, q2gy), (q2gx + 1.6, q2gy + 1.2), (q2gx + 1.6, 38.3), (LANE, 38.3)], "PMOS_GATE", 0.25)
trk([(dzax, dzay), (r1ax, r1ay)], "PMOS_GATE", 0.25)
trk([(r1ax, r1ay), (q3cx, q3cy)], "PMOS_GATE", 0.25)
# MASTER_OFF_B: Q3.B → R3.1 → R2.1
q3bx, q3by = ppos("Q3", 1)
r3ax, r3ay = ppos("R3", 1); r2ax, r2ay = ppos("R2", 1)
trk([(q3bx, q3by), (r3ax, q3by), (r3ax, r3ay), (r2ax, r2ay)], "MASTER_OFF_B", 0.25)
# 左列 GND:短线引到 x19.5 走 B.Cu 地平面
for (ref, num) in [("R1","2"),("Q3","2"),("R2","2"),("R3","2")]:
    x, y = ppos(ref, num)
    trk([(x, y), (19.0, y)], "GND", 0.4)
    via(19.6, y, "GND")
u17x, u17y = ppos("U1", 7)
trk([(u17x, u17y), (u17x, u17y + 2.2), (19.0, u17y + 2.2)], "GND", 0.4)
via(19.6, u17y + 2.2, "GND")
# U1 细脚:V3P3(p6)、V24_BUS(p9)从各自焊盘正上方进
u16x, u16y = ppos("U1", 6)
u19x, u19y = ppos("U1", 9)
u1_top = min(u16y, u19y)
trk([(u16x, u16y), (u16x, u1_top - 1.3), (16.5, u1_top - 1.3)], "V3P3", 0.25)
# 接到 freerouting 留下的 V3P3 走线端(约 15,50 附近)——直接续到该点
trk([(16.5, u1_top - 1.3), (16.5, 50.0), (15.0, 50.0)], "V3P3", 0.25)
rs2x, rs2y = ppos("RS1", 2)
trk([(u19x, u19y), (u19x, u1_top - 1.9), (rs2x + 0.2, u1_top - 1.9), (rs2x + 0.2, rs2y)], "V24_BUS", 0.3)

# ---- 2. 六通道顶端三线配方 ----
for i, (J, Fk, Dfw, Qc) in enumerate([("J3","F2","D6","Q7"),("J4","F3","D10","Q9"),
                                       ("J5","F4","D14","Q11"),("J6","F5","D18","Q13"),
                                       ("J7","F6","D22","Q15"),("J8","F7","D26","Q17")]):
    p1x, p1y = ppos(J, 1)   # VOUT(外右)
    p2x, p2y = ppos(J, 2)   # CW_D(中)
    p3x, p3y = ppos(J, 3)   # WW_D(外左)
    f2x, f2y = ppos(Fk, 2)  # 保险丝输出侧
    dax, day = ppos(Dfw, 1) # WW 续流管阳极(WW_D 网)
    ch = f"CH{i+1}"
    # VOUT:F.p2 → 右外侧绕上 → p1(全程 1.6)
    trk([(f2x, f2y), (p1x + 1.5, f2y - 3.0), (p1x + 1.5, p1y + 1.5), (p1x, p1y)], f"{ch}_VOUT", 1.6)
    # CW_D:中缝直下(端子间隙内 1.0,出缝后 2.0 由既有走线接续)
    qtx, qty = ppos(Qc, 2)
    trk([(p2x, p2y), (p2x, 13.0)], f"{ch}_CW_D", 1.0)
    trk([(p2x, 13.0), (p2x, qty - 4.0)], f"{ch}_CW_D", 1.6)
    trk([(p2x, qty - 4.0), (qtx, qty)], f"{ch}_CW_D", 1.6)
    # WW_D:左外道下行(F.Cu),经 B.Cu 短横穿过中线,接 D6.A
    lane = p3x - 3.2
    trk([(p3x, p3y), (lane, p3y + 1.8), (lane, 29.2)], f"{ch}_WW_D", 1.0)
    via(lane, 30.0, f"{ch}_WW_D", 1.0, 0.5)
    trk([(lane, 30.0), (dax, 30.0)], f"{ch}_WW_D", 1.0, layer=B)
    via(dax, 30.0, f"{ch}_WW_D", 1.0, 0.5)
    trk([(dax, 30.0), (dax, day)], f"{ch}_WW_D", 1.0)

# ---- 3. 电解 GND 脚过孔、U2 散热盘、J2 屏蔽脚 ----
for c in ["C1", "C2", "C3", "C4", "C5"]:
    x, y = ppos(c, 2)
    trk([(x, y), (x + 2.0, y)], "GND", 1.0)
    via(x + 2.6, y, "GND", 1.0, 0.5)
u2p = pad_of("U2", "9")
ux, uy = mm(u2p.GetPosition().x), mm(u2p.GetPosition().y)
for dx, dy in [(-0.8, -0.8), (0.8, -0.8), (-0.8, 0.8), (0.8, 0.8)]:
    via(ux + dx, uy + dy, "GND", 0.6, 0.3)
for pad, xoff in [("A1B12", 0), ("B1A12", 0)]:
    p = pad_of("J2", pad)
    px, py = mm(p.GetPosition().x), mm(p.GetPosition().y)
    via(px, py - 2.2, "GND", 0.8, 0.4)
    trk([(px, py), (px, py - 2.2)], "GND", 0.6)

# ---- 4. V24_LOGIC 末段 + TP5/TP6 迁址 ----
u22x, u22y = ppos("U2", 2)
trk([(38.0, 105.0), (35.5, 105.0), (35.5, u22y), (u22x, u22y)], "V24_LOGIC", 1.0)
for tp, target in [("TP5", ("R16", 2)), ("TP6", ("Q7", 2))]:
    fp = None
    for f_ in board.GetFootprints():
        if f_.GetReference() == tp: fp = f_
    tx, ty = ppos(*target)
    if tp == "TP5":
        nx, ny = tx - 2.6, ty + 2.6
    else:
        nx, ny = tx - 5.2, ty + 0.5
    fp.SetPosition(VECTOR2I(FromMM(nx), FromMM(ny)))
    netname = fp.Pads()[0].GetNetname() if hasattr(fp.Pads(), '__getitem__') else None
    for p in fp.Pads():
        netname = p.GetNetname()
    trk([(nx, ny), (tx, ty)], netname, 0.3)
print("TP5/TP6 迁至目标焊盘旁")

# ---- 5. GND 覆铜改全连接 + 间隙加大(消 starved_thermal / hole_clearance)----
for z in board.Zones():
    if z.GetIsRuleArea(): continue
    if z.GetNetname() == "GND":
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetLocalClearance(FromMM(0.4))

# ---- 6. 重填、保存、统计 ----
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones(): zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
