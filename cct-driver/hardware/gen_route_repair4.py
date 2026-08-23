#!/usr/bin/env python3
"""第四轮总修:
A 栅极线(CH2-6 CW_GR)跨 WW 对角线的 F 段 → 过孔对 + B 层绕行
B CH3/CH6 C17 馈线改 B 层支线(原 p1 与栅极线交叉)
C USB_VBUS 改 y131.15 高走廊 + J2 下方 y140.85 绕行;SW_IN3 冗余 B 支删除改 F 直连
D CC2 起步段避开 R10.2;E LED6_K 改 B 跳;F V24_LOGIC 路径微调
G U2 pad9 撤过孔改 pad7 短接;H 开尔文 V24_BUS 重加;CH6 WW 车道左移 0.2
"""
from pathlib import Path
import gc, math
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = Path(__file__).parent
board = pcbnew.LoadBoard(str(HERE / "cct-main.kicad_pcb"))
mm = pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu

def net(n):
    x = board.FindNet(n); assert x, n; return x

def is_via(t):
    return t.Type() == pcbnew.PCB_VIA_T

def ends(t):
    return mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)

def tw(t):
    try:
        return mm(t.GetWidth(F)) if is_via(t) else mm(t.GetWidth())
    except TypeError:
        return mm(t.GetWidth())

def spd(px, py, x1, y1, x2, y2):
    dx, dy = x2-x1, y2-y1
    L2 = dx*dx+dy*dy
    if L2 == 0:
        return math.hypot(px-x1, py-y1)
    t = max(0.0, min(1.0, ((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx), py-(y1+t*dy))

def ssd(a, b):
    (ax1, ay1, ax2, ay2) = a
    (bx1, by1, bx2, by2) = b
    d1 = (ax2-ax1)*(by1-ay1)-(ay2-ay1)*(bx1-ax1)
    d2 = (ax2-ax1)*(by2-ay1)-(ay2-ay1)*(bx2-ax1)
    d3 = (bx2-bx1)*(ay1-by1)-(by2-by1)*(ax1-bx1)
    d4 = (bx2-bx1)*(ay2-by1)-(by2-by1)*(ax2-bx1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(spd(bx1, by1, *a), spd(bx2, by2, *a), spd(ax1, ay1, *b), spd(ax2, ay2, *b))

DELETED = set()
SNAP = list(board.GetTracks())
def live():
    return [t for t in SNAP if id(t) not in DELETED]

def kill(t):
    if id(t) not in DELETED:
        DELETED.add(id(t)); board.Remove(t)

def trk(pts, netname, w, layer=F):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        board.Add(t)

def via(x, y, netname, dia=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(net(netname)); v.SetLayerPair(F, B)
    board.Add(v)

def match_seg(t, x1, y1, x2, y2, tol=0.12):
    a = ends(t)
    return ((abs(a[0]-x1)<tol and abs(a[1]-y1)<tol and abs(a[2]-x2)<tol and abs(a[3]-y2)<tol) or
            (abs(a[0]-x2)<tol and abs(a[1]-y2)<tol and abs(a[2]-x1)<tol and abs(a[3]-y1)<tol))

def del_exact(netname, segs):
    n = 0
    for t in live():
        if is_via(t) or t.GetNetname() != netname:
            continue
        for s in segs:
            if match_seg(t, *s):
                kill(t); n += 1
                break
    return n

def del_via_at(pts, tol=0.15):
    for t in live():
        if not is_via(t):
            continue
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        for (vx, vy) in pts:
            if abs(x-vx) < tol and abs(y-vy) < tol:
                kill(t); break

def check(pts, hw, layer, netname, margin=0.24, verbose=None, del_gnd=True):
    to_del = set()
    for a, b in zip(pts, pts[1:]):
        seg = (a[0], a[1], b[0], b[1])
        for t in live():
            if t.GetNetname() == netname:
                continue
            if is_via(t):
                vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
                if spd(vx, vy, *seg) < hw + tw(t)/2 + margin:
                    if verbose:
                        print(f"  ✗ {verbose} seg{seg}: via[{t.GetNetname()}]({vx:.1f},{vy:.1f})")
                    return False
            else:
                if t.GetLayer() != layer:
                    continue
                if ssd(seg, ends(t)) < hw + tw(t)/2 + margin:
                    if t.GetNetname() == "GND" and del_gnd:
                        to_del.add(id(t))
                    else:
                        if verbose:
                            e = ends(t)
                            print(f"  ✗ {verbose} seg{seg}: trk[{t.GetNetname()}]({e[0]:.1f},{e[1]:.1f})->({e[2]:.1f},{e[3]:.1f})")
                        return False
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == netname:
                    continue
                if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH and not p.IsOnLayer(layer):
                    continue
                bb = p.GetBoundingBox()
                px1, px2 = mm(bb.GetLeft()), mm(bb.GetRight())
                py1, py2 = mm(bb.GetTop()), mm(bb.GetBottom())
                if spd((px1+px2)/2, (py1+py2)/2, *seg) < hw + math.hypot(px2-px1, py2-py1)/2 + margin:
                    for e in [(px1,py1,px2,py1),(px2,py1,px2,py2),(px2,py2,px1,py2),(px1,py2,px1,py1)]:
                        if ssd(seg, e) < hw + margin:
                            if verbose:
                                print(f"  ✗ {verbose} seg{seg}: pad {fp.GetReference()}.{p.GetNumber()}")
                            return False
    for gid in to_del:
        for t in SNAP:
            if id(t) == gid:
                kill(t)
    return True

def chkvia(x, y, netname, r=0.3, margin=0.24, verbose=None):
    for t in live():
        if t.GetNetname() == netname:
            continue
        if is_via(t):
            vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
            if math.hypot(vx-x, vy-y) < r + tw(t)/2 + margin:
                if verbose:
                    print(f"  ✗ {verbose} via({x:.1f},{y:.1f}): via[{t.GetNetname()}]({vx:.1f},{vy:.1f})")
                return False
        else:
            if t.GetNetname() == "GND":
                continue
            if ssd((x, y, x, y), ends(t)) < r + tw(t)/2 + margin:
                if verbose:
                    e = ends(t)
                    print(f"  ✗ {verbose} via({x:.1f},{y:.1f}): trk[{t.GetNetname()}]L{t.GetLayer()}({e[0]:.1f},{e[1]:.1f})->({e[2]:.1f},{e[3]:.1f})")
                return False
    return True

WARN = []

# ============ CH6 WW 车道左移(F7 保险丝焊盘 0.1mm 间隙) ============
del_exact("CH6_WW_D", [(96.19,8.0,96.19,11.5),(96.19,11.5,93.1,14.5),
                       (93.1,14.5,93.1,42.6),(93.1,42.6,98.0,45.6)])
trk([(96.19,8.0),(96.19,11.5),(92.9,14.6),(92.9,42.6),(98.0,45.6)], "CH6_WW_D", 1.2)

# ============ A. 栅极线跨 WW 对角线 → B 层跳线 ============
WW_DIAG = {2:(37.1,42.6,42.0,45.6), 3:(51.1,42.6,56.0,45.6), 4:(65.1,42.6,70.0,45.6),
           5:(79.1,42.6,84.0,45.6), 6:(93.1,42.6,98.0,45.6)}
for i, diag in WW_DIAG.items():
    gnet = f"CH{i}_CW_GR"
    crossers = []
    for t in live():
        if is_via(t) or t.GetNetname() != gnet or t.GetLayer() != F:
            continue
        if ssd(diag, ends(t)) < 0.6 + tw(t)/2 + 0.24:
            crossers.append(t)
    for t in crossers:
        x1, y1, x2, y2 = ends(t)
        P = (x1, y1) if y1 < y2 else (x2, y2)
        Q = (x2, y2) if y1 < y2 else (x1, y1)
        kill(t)
        cands = [
            [P, Q],
            [P, (P[0], Q[1]), Q],
            [P, (P[0]-1.2, P[1]+2.0), (P[0]-1.2, Q[1]-1.5), Q],
            [P, (P[0]+1.2, P[1]+2.0), (P[0]+1.2, Q[1]-1.5), Q],
            [P, (P[0], 58.0), (Q[0]-2.0, 66.0), Q],
        ]
        done = False
        for pth in cands:
            if chkvia(*P, gnet) and chkvia(*Q, gnet) and check(pth, 0.15, B, gnet):
                via(*P, gnet); via(*Q, gnet)
                trk(pth, gnet, 0.3, layer=B)
                done = True
                break
        if not done:
            check([P, Q], 0.15, B, gnet, verbose=f"CH{i}gate", del_gnd=False)
            WARN.append(f"CH{i} CW_GR 跳线")
            # 恢复原线避免断网
            trk([(x1, y1), (x2, y2)], gnet, tw(t) if tw(t) > 0 else 0.25)

# ============ B. CH3/CH6 C17 馈线改 B 支线 ============
for i, (c16x, c16y, c17x, c17y) in {3:(53.3,67.5,56.3,73.15), 6:(95.3,67.5,98.3,73.15)}.items():
    vn = f"CH{i}_VOUT"
    del_exact(vn, [(c16x,c16y,c16x+1.7,70.5),(c16x+1.7,70.5,c17x,71.8),(c17x,71.8,c17x,c17y)])
    p_b = [(c16x, 65.6), (c17x-0.7, 66.8), (c17x-0.7, 72.3)]
    p_f = [(c17x-0.7, 72.4), (c17x-0.3, 73.0), (c17x, c17y)]
    if check(p_b, 0.3, B, vn, verbose=f"CH{i}C17-B") and \
       chkvia(c17x-0.7, 72.4, vn, verbose=f"CH{i}C17") and \
       check(p_f, 0.15, F, vn, verbose=f"CH{i}C17-F"):
        trk(p_b, vn, 0.6, layer=B)
        via(c17x-0.7, 72.4, vn)
        trk(p_f, vn, 0.3)
    else:
        WARN.append(f"CH{i} C17")

# ============ C. USB_VBUS 重走 + SW_IN3 冗余支清理 ============
# 删旧 VBUS
del_exact("USB_VBUS", [(44.36,127.1,58.6,132.0),(58.6,132.0,60.3,133.3),
                       (60.3,133.3,60.3,136.6),(60.3,136.6,78.4,136.6),
                       (73.6,136.6,73.6,138.53),(78.4,136.6,78.4,138.53)])
del_via_at([(73.6,136.6),(78.4,136.6)])
# SW_IN3:删 (63,138.3) 冗余 B 支,补 F 直连
del_exact("SW_IN3", [(63.8,137.5,63.0,137.5),(63.0,137.5,63.0,138.3),
                     (63.0,138.3,64.7,136.6),(64.7,136.6,64.7,135.2)])
del_via_at([(63.0,138.3)])
trk([(63.8,137.5),(63.8,135.0)], "SW_IN3", 0.25)
# 新 VBUS
p1 = [(44.36,127.1),(60.0,131.15),(73.6,131.15)]
p2 = [(73.6,131.15),(73.6,138.53),(73.6,140.85)]
p3 = [(73.6,140.85),(78.4,140.85)]
p4 = [(78.4,140.85),(78.4,138.53)]
okv = check(p1, 0.25, B, "USB_VBUS", verbose="VBUS-1") and \
      chkvia(73.6,131.15,"USB_VBUS",verbose="VBUS") and \
      check(p2, 0.15, F, "USB_VBUS", verbose="VBUS-2") and \
      chkvia(73.6,140.85,"USB_VBUS",verbose="VBUS") and \
      check(p3, 0.15, B, "USB_VBUS", verbose="VBUS-3") and \
      chkvia(78.4,140.85,"USB_VBUS",verbose="VBUS") and \
      check(p4, 0.15, F, "USB_VBUS", verbose="VBUS-4")
if okv:
    trk(p1, "USB_VBUS", 0.5, layer=B)
    via(73.6,131.15,"USB_VBUS")
    trk(p2, "USB_VBUS", 0.3)
    via(73.6,140.85,"USB_VBUS")
    trk(p3, "USB_VBUS", 0.3, layer=B)
    via(78.4,140.85,"USB_VBUS")
    trk(p4, "USB_VBUS", 0.3)
else:
    WARN.append("USB_VBUS")

# ============ D. CC2 起步段避开 R10.2;末段沿 B5 自身 x 进入 ============
del_exact("CC2", [(68.85,136.6,69.5,136.2),(69.5,136.2,70.5,135.9),
                  (76.9,135.9,77.4,136.3),(77.4,136.3,77.4,137.9),
                  (77.4,137.9,77.75,138.3),(77.75,138.3,77.75,138.53)])
del_via_at([(70.5,135.9)])
# R10 口袋里的 GND 斜线(67.8,133.4)->(71.7,137.3) 让位
for t in live():
    if not is_via(t) and t.GetNetname() == "GND" and match_seg(t, 67.8,133.4,71.7,137.3, tol=0.3):
        kill(t)
p_s = [(68.85,136.6),(68.85,136.0),(69.45,135.65)]
p_e = [(76.9,135.9),(77.75,136.7),(77.75,138.4)]
if check(p_s, 0.125, F, "CC2", verbose="CC2-s") and chkvia(69.75,135.75,"CC2",verbose="CC2") and \
   check([(69.75,135.75),(70.5,135.9)], 0.125, B, "CC2", verbose="CC2-b") and \
   check(p_e, 0.125, F, "CC2", verbose="CC2-e", margin=0.18):
    trk(p_s + [(69.75,135.75)], "CC2", 0.25)
    via(69.75,135.75,"CC2")
    trk([(69.75,135.75),(70.5,135.9)], "CC2", 0.25, layer=B)
    trk(p_e, "CC2", 0.25)
else:
    WARN.append("CC2")

# ============ E. LED6_K 改 B 跳 ============
del_exact("LED6_K", [(16.05,83.56,16.05,83.0),(16.05,83.0,17.31,81.26),(17.31,81.26,17.31,80.56)])
if chkvia(16.05,82.7,"LED6_K",verbose="LED6K") and chkvia(17.31,81.9,"LED6_K",verbose="LED6K") and \
   check([(16.05,82.7),(17.31,81.9)], 0.15, B, "LED6_K", verbose="LED6K-B") and \
   check([(17.31,81.9),(17.31,81.0)], 0.15, F, "LED6_K", verbose="LED6K-F"):
    trk([(16.05,83.56),(16.05,83.1)], "LED6_K", 0.3)
    via(16.05,82.7,"LED6_K")
    trk([(16.05,82.7),(17.31,81.9)], "LED6_K", 0.3, layer=B)
    via(17.31,81.9,"LED6_K")
    trk([(17.31,81.9),(17.31,81.0)], "LED6_K", 0.3)
else:
    WARN.append("LED6_K")

# ============ F. V24_LOGIC B 路径微调(FB_5V 过孔 0.1mm) ============
del_exact("V24_LOGIC", [(31.37,109.8,33.3,107.6),(33.3,107.6,34.6,107.0),
                        (34.6,107.0,39.5,105.3),(39.5,105.3,39.5,105.2)])
trk([(31.37,109.8),(33.3,107.3),(34.6,106.75),(39.5,105.3),(39.5,105.2)], "V24_LOGIC", 0.4, layer=B)

# ============ G. U2 pad9:撤中心过孔,pad7 短接 ============
del_via_at([(32.0,106.49)])
trk([(31.37,104.5),(31.9,105.7)], "GND", 0.25)

# ============ H. 开尔文 V24_BUS 重加 + U1.7 GND 链改道(避 I2C_SDA) ============
trk([(8.5,49.5),(8.5,48.45),(13.5,48.45),(14.07,47.9),(14.07,46.31)], "V24_BUS", 0.25)
del_exact("GND", [(9.5,52.0,11.2,53.0),(11.2,53.0,11.2,55.5),(11.2,55.5,13.36,57.31)])
trk([(9.5,52.0),(10.6,52.3),(12.7,52.3),(12.7,56.2),(13.36,57.31)], "GND", 0.3)

if WARN:
    print("⚠️ 未完成:", "; ".join(WARN))
else:
    print("✅ 第四轮全部完成")
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones():
    zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
