#!/usr/bin/env python3
"""3d:补齐剩余 5 条支路;扩充候选;失败打印阻挡物。"""
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

SNAP = list(board.GetTracks())
DELETED = set()

def is_via(t):
    return t.Type() == pcbnew.PCB_VIA_T

def live():
    return [t for t in SNAP if id(t) not in DELETED]

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

NEW_SEGS = []; NEW_VIAS = []
def trk(pts, netname, w, layer=F):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        board.Add(t)
        NEW_SEGS.append((x1, y1, x2, y2, w/2, layer, netname))

def via(x, y, netname, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(net(netname)); v.SetLayerPair(F, B)
    board.Add(v)
    NEW_VIAS.append((x, y, dia/2, netname))

def seg_blockers(x1, y1, x2, y2, hw, layer, netname, margin=0.28):
    """返回 (非GND阻挡列表, 可删的GND明线集合)"""
    seg = (x1, y1, x2, y2)
    hard = []; gnd = set()
    for t in live():
        if t.GetNetname() == netname:
            continue
        if is_via(t):
            vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
            if spd(vx, vy, *seg) < hw + tw(t)/2 + margin:
                hard.append(t)
        else:
            if t.GetLayer() != layer:
                continue
            if ssd(seg, ends(t)) < hw + tw(t)/2 + margin:
                if t.GetNetname() == "GND":
                    gnd.add(id(t)); gnd_map[id(t)] = t
                else:
                    hard.append(t)
    for (sx1, sy1, sx2, sy2, shw, sl, sn) in NEW_SEGS:
        if sn == netname or sl != layer:
            continue
        if ssd(seg, (sx1, sy1, sx2, sy2)) < hw + shw + margin:
            hard.append("newseg")
    for (vx, vy, vr, vn) in NEW_VIAS:
        if vn == netname:
            continue
        if spd(vx, vy, *seg) < hw + vr + margin:
            hard.append("newvia")
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
                        hard.append(f"pad{fp.GetReference()}.{p.GetNumber()}")
                        break
    return hard, gnd

gnd_map = {}

LAST_FAIL = []
def try_path(pts, hw, layer, netname):
    """若路径只被 GND 明线挡:删之并返回 True"""
    all_gnd = set(); ok = True
    for a, b in zip(pts, pts[1:]):
        hard, gnd = seg_blockers(a[0], a[1], b[0], b[1], hw, layer, netname)
        if hard:
            def fmt(h):
                if isinstance(h, str): return h
                if is_via(h):
                    return f"via[{h.GetNetname()}]({mm(h.GetPosition().x):.1f},{mm(h.GetPosition().y):.1f})"
                e = ends(h)
                return f"trk[{h.GetNetname()}]({e[0]:.1f},{e[1]:.1f})->({e[2]:.1f},{e[3]:.1f})"
            LAST_FAIL.append(f"  seg({a[0]:.1f},{a[1]:.1f})->({b[0]:.1f},{b[1]:.1f}): " + "; ".join(fmt(h) for h in hard[:3]))
            ok = False
            break
        all_gnd |= gnd
    if not ok:
        return False
    for gid in all_gnd:
        t = gnd_map[gid]
        if id(t) not in DELETED:
            DELETED.add(id(t)); board.Remove(t)
    return True

gnd_removed_before = len(DELETED)
WARN = []
CH = {1:("D7","D8","Q7","Q8","C16","C17","D6"), 2:("D11","D12","Q9","Q10","C18","C19","D10"),
      3:("D15","D16","Q11","Q12","C20","C21","D14"), 4:("D19","D20","Q13","Q14","C22","C23","D18"),
      5:("D23","D24","Q15","Q16","C24","C25","D22"), 6:("D27","D28","Q17","Q18","C26","C27","D26")}
COLS = {1:30.0, 2:44.0, 3:58.0, 4:72.0, 5:86.0, 6:100.0}

FAILED_C16 = [2]
FAILED_C17 = [5]
FAILED_CWTVS = [1, 4]
FAILED_WWTVS = [2]

for i in sorted(set(FAILED_C16+FAILED_C17+FAILED_CWTVS+FAILED_WWTVS)):
    Dtvc, Dtvw, Qc, Qw, Cel, Cml, Dfw = CH[i]
    col = COLS[i]
    ch = f"CH{i}"
    tc_x, tc_y = ppos(Dtvc, 1)
    tw_x, tw_y = ppos(Dtvw, 1)
    c16x, c16y = ppos(Cel, 1)
    c17x, c17y = ppos(Cml, 1)
    d1x, d1y = ppos(Dfw, 1)
    # --- C16 ---
    if i in FAILED_C16:
        done = False
        for x_e in (col+4.9, col+5.5, col+4.35):
            for yh in (64.9, 65.7, 63.9):
                pth = [(d1x, 27.0), (x_e, 29.5), (x_e, yh), (c16x, yh), (c16x, 65.6)]
                stub = [(c16x, 65.8), (c16x, c16y)]
                if try_path(pth, 0.4, B, f"{ch}_VOUT") and try_path(stub, 0.4, F, f"{ch}_VOUT"):
                    trk(pth, f"{ch}_VOUT", 0.8, layer=B)
                    via(c16x, 65.8, f"{ch}_VOUT", 0.8, 0.4)
                    trk(stub, f"{ch}_VOUT", 0.8)
                    done = True
                    break
            if done: break
        if not done: WARN.append(f"{ch} C16")
    # --- C17 ---
    if i in FAILED_C17:
        cands = [
            [(c16x, c16y), (c16x+1.7, 70.5), (c17x, 71.8), (c17x, c17y)],
            [(c16x, c16y), (c17x, 70.0), (c17x, c17y)],
            [(c16x, c16y), (c16x+1.2, 69.5), (c17x+0.7, 70.8), (c17x, 72.5), (c17x, c17y)],
            [(c16x, c16y), (c16x-0.7, 70.5), (c16x-0.7, 72.6), (c16x-0.4, 74.2), (c17x-0.4, 74.2), (c17x, 73.4), (c17x, c17y)],
        ]
        done = False
        for pth in cands:
            if try_path(pth[1:], 0.3, F, f"{ch}_VOUT"):
                trk(pth, f"{ch}_VOUT", 0.6)
                done = True
                break
        if not done: WARN.append(f"{ch} C17")
    # --- CW-TVS ---
    if i in FAILED_CWTVS:
        done = False
        for x_c in (tc_x, col-3.5, col-2.6, col-7.2, col-6.85, col-8.6, col-0.5):
            p_b = [(col-1.5, 36.2), (x_c, 39.5), (x_c, 54.2)]
            p_f = [(x_c, 54.5), (tc_x, 55.6), (tc_x, tc_y)]
            if try_path(p_b, 0.5, B, f"{ch}_CW_D") and try_path(p_f, 0.5, F, f"{ch}_CW_D"):
                via(col-1.5, 36.2, f"{ch}_CW_D", 0.8, 0.4)
                trk(p_b, f"{ch}_CW_D", 1.0, layer=B)
                via(x_c, 54.35, f"{ch}_CW_D", 0.8, 0.4)
                trk(p_f, f"{ch}_CW_D", 1.0)
                done = True
                break
        if not done: WARN.append(f"{ch} CW-TVS")
    # --- WW-TVS ---
    if i in FAILED_WWTVS:
        e1 = [(col+2.5, 48.5), (col+4.2, 50.5), (col+4.2, 58.0), (tw_x, 60.5)]
        e3 = [(col+2.5, 48.5), (col+4.2, 50.5), (col+4.2, 63.2), (tw_x, 63.2), (tw_x, 61.5)]
        e5 = [(col+2.5, 48.5), (col+4.2, 50.5), (col+4.2, 57.6), (col+2.5, 57.9), (tw_x, 58.9), (tw_x, 60.5)]
        done = False
        for pth in (e1, e3, e5):
            if try_path(pth[1:], 0.5, F, f"{ch}_WW_D"):
                trk(pth, f"{ch}_WW_D", 1.0)
                done = True
                break
        if not done: WARN.append(f"{ch} WW-TVS")

print(f"删除 GND 明线 {len(DELETED)} 条")
if WARN:
    print("⚠️ 仍未布:", "; ".join(WARN))
    print("阻挡明细(末尾20条):")
    for l in LAST_FAIL[-20:]:
        print(l)
else:
    print("✅ 13 条支路全部补齐")
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones():
    zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
