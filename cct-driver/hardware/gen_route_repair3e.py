#!/usr/bin/env python3
"""3e:最后 4 条支路的定制路径(带净空验证,失败打印阻挡)。"""
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

def check(pts, hw, layer, netname, margin=0.26, label=""):
    """返回 True 若可布;纯 GND 明线阻挡则删线。失败打印阻挡。"""
    to_del = set()
    for a, b in zip(pts, pts[1:]):
        seg = (a[0], a[1], b[0], b[1])
        for t in live():
            if t.GetNetname() == netname:
                continue
            if is_via(t):
                vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
                if spd(vx, vy, *seg) < hw + tw(t)/2 + margin:
                    print(f"  ✗ {label} seg{seg}: via[{t.GetNetname()}]({vx:.1f},{vy:.1f})")
                    return False
            else:
                if t.GetLayer() != layer:
                    continue
                if ssd(seg, ends(t)) < hw + tw(t)/2 + margin:
                    if t.GetNetname() == "GND":
                        to_del.add(id(t))
                    else:
                        e = ends(t)
                        print(f"  ✗ {label} seg{seg}: trk[{t.GetNetname()}]({e[0]:.1f},{e[1]:.1f})->({e[2]:.1f},{e[3]:.1f})")
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
                            print(f"  ✗ {label} seg{seg}: pad {fp.GetReference()}.{p.GetNumber()}[{p.GetNetname()}]")
                            return False
    for gid in to_del:
        for t in SNAP:
            if id(t) == gid and gid not in DELETED:
                DELETED.add(gid); board.Remove(t)
    return True

def chkvia(x, y, netname, r=0.4, margin=0.26, label=""):
    for t in live():
        if t.GetNetname() == netname:
            continue
        if is_via(t):
            vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
            if math.hypot(vx-x, vy-y) < r + tw(t)/2 + margin:
                print(f"  ✗ {label} via({x:.1f},{y:.1f}): via[{t.GetNetname()}]({vx:.1f},{vy:.1f})")
                return False
        else:
            if ssd((x, y, x, y), ends(t)) < r + tw(t)/2 + margin and t.GetNetname() != "GND":
                e = ends(t)
                print(f"  ✗ {label} via({x:.1f},{y:.1f}): trk[{t.GetNetname()}]({e[0]:.1f},{e[1]:.1f})->({e[2]:.1f},{e[3]:.1f}) L{t.GetLayer()}")
                return False
    return True

ok_all = True

# ---- CH2 C16:y55.65 走廊绕西,沿 x36.4 下行 ----
p_b = [(44.24, 27.0), (44.24, 29.0), (36.2, 32.8), (36.2, 67.5)]
p_f = [(36.2, 67.5), (37.5, 67.5)]
if check(p_b, 0.4, B, "CH2_VOUT", label="CH2C16-B") and \
   chkvia(36.2, 67.5, "CH2_VOUT", label="CH2C16") and \
   check(p_f, 0.3, F, "CH2_VOUT", label="CH2C16-F"):
    trk(p_b, "CH2_VOUT", 0.8, layer=B)
    via(36.2, 67.5, "CH2_VOUT", 0.8, 0.4)
    trk(p_f, "CH2_VOUT", 0.6)
    print("✓ CH2 C16")
else:
    ok_all = False

# ---- CH2 WW-TVS:已布通,跳过 ----
if False:
    p_b = [(44.24, 47.5), (44.24, 62.3)]


# ---- CH4 CW-TVS:已布通,跳过 ----

# ---- CH5 C17:已布通,跳过 ----
if False:
    p_b = [(81.3, 65.6), (83.6, 66.8), (83.6, 72.3)]


print(f"删除 GND 明线 {len(DELETED)} 条")
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones():
    zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
