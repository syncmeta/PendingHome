#!/usr/bin/env python3
"""4b:VBUS(y130.6 走廊)、CC2、LED6_K、CH4 栅极定制绕行。"""
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
def match_seg(t, x1, y1, x2, y2, tol=0.15):
    a = ends(t)
    return ((abs(a[0]-x1)<tol and abs(a[1]-y1)<tol and abs(a[2]-x2)<tol and abs(a[3]-y2)<tol) or
            (abs(a[0]-x2)<tol and abs(a[1]-y2)<tol and abs(a[2]-x1)<tol and abs(a[3]-y1)<tol))
def del_exact(netname, segs):
    for t in live():
        if is_via(t) or t.GetNetname() != netname:
            continue
        for s in segs:
            if match_seg(t, *s):
                kill(t); break
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


# ---- USB_VBUS 最终:A 侧 F 绕定位销,B 侧 B4A9 盘中孔 + B 层绕 ----
p1 = [(44.36,127.1),(52.0,130.6),(73.3,130.6)]
p2a = [(73.3,130.6),(73.6,131.5),(73.6,138.6)]
p2b = [(73.6,138.6),(73.75,139.0),(73.75,140.3),(73.6,140.9)]
p3 = [(73.6,140.9),(77.9,140.9),(78.0,139.5),(78.4,138.6)]
okv = check(p1, 0.25, B, "USB_VBUS", verbose="VBUS-1") and \
      chkvia(73.3,130.6,"USB_VBUS",verbose="VBUSv1",margin=0.2) and \
      check(p2a, 0.15, F, "USB_VBUS", verbose="VBUS-2a", margin=0.13) and \
      check(p2b, 0.125, F, "USB_VBUS", verbose="VBUS-2b", margin=0.09) and \
      chkvia(73.6,140.9,"USB_VBUS",verbose="VBUSv2",margin=0.15) and \
      check(p3, 0.125, B, "USB_VBUS", verbose="VBUS-3", margin=0.12) and \
      chkvia(78.4,138.6,"USB_VBUS",verbose="VBUSv3",margin=0.15)
if okv:
    trk(p1, "USB_VBUS", 0.5, layer=B)
    via(73.3,130.6,"USB_VBUS")
    trk(p2a, "USB_VBUS", 0.3)
    trk(p2b, "USB_VBUS", 0.25)
    via(73.6,140.9,"USB_VBUS")
    trk(p3, "USB_VBUS", 0.25, layer=B)
    via(78.4,138.6,"USB_VBUS")
    print("✓ USB_VBUS")
else:
    WARN.append("USB_VBUS")

if WARN:
    print("⚠️ 未完成:", "; ".join(WARN))
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones():
    zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
