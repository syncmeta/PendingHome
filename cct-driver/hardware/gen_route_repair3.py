#!/usr/bin/env python3
"""修复第三轮(干净版)。PHASE=del 撤销保存;PHASE=add [SKIP_TAILS=1] 新增。"""
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

NEW_SEGS = []; NEW_VIAS = []
def trk(pts, netname, w, layer=F):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        board.Add(t)
        NEW_SEGS.append((x1, y1, x2, y2, w / 2, layer, netname))

def via(x, y, netname, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(net(netname)); v.SetLayerPair(F, B)
    board.Add(v)
    NEW_VIAS.append((x, y, dia / 2, netname))

def seg_pt_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

def seg_seg_dist(a, b):
    (ax1, ay1, ax2, ay2) = a
    (bx1, by1, bx2, by2) = b
    d1 = (ax2-ax1)*(by1-ay1)-(ay2-ay1)*(bx1-ax1)
    d2 = (ax2-ax1)*(by2-ay1)-(ay2-ay1)*(bx2-ax1)
    d3 = (bx2-bx1)*(ay1-by1)-(by2-by1)*(ax1-bx1)
    d4 = (bx2-bx1)*(ay2-by1)-(by2-by1)*(ax2-bx1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(seg_pt_dist(bx1, by1, *a), seg_pt_dist(bx2, by2, *a),
               seg_pt_dist(ax1, ay1, *b), seg_pt_dist(ax2, ay2, *b))

# ============ 0. 撤销 ============
removed = {"trk": 0, "via": 0}
SNAP = list(board.GetTracks())
DELETED = set()

def is_via(t):
    return t.Type() == pcbnew.PCB_VIA_T

def del_item(t):
    if id(t) in DELETED:
        return
    DELETED.add(id(t)); board.Remove(t)
    if is_via(t):
        removed["via"] += 1
    else:
        removed["trk"] += 1

def live():
    return [t for t in SNAP if id(t) not in DELETED]

def ends(t):
    return mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)

def track_w(t):
    try:
        return mm(t.GetWidth(F)) if is_via(t) else mm(t.GetWidth())
    except TypeError:
        return mm(t.GetWidth())

def match_seg(t, x1, y1, x2, y2, tol=0.1):
    a = ends(t)
    return ((abs(a[0]-x1)<tol and abs(a[1]-y1)<tol and abs(a[2]-x2)<tol and abs(a[3]-y2)<tol) or
            (abs(a[0]-x2)<tol and abs(a[1]-y2)<tol and abs(a[2]-x1)<tol and abs(a[3]-y1)<tol))

FULL_DEL = set()
for i in range(1, 7):
    FULL_DEL |= {f"CH{i}_VOUT", f"CH{i}_CW_D", f"CH{i}_WW_D"}
FULL_DEL |= {"V24_FUSED", "PMOS_GATE"}
for t in live():
    if t.GetNetname() in FULL_DEL:
        del_item(t)

EXACT = [
    ("V24_BUS", [(8.5,49.5,8.5,48.55),(8.5,48.55,13.5,48.55),
                 (13.5,48.55,14.07,47.9),(14.07,47.9,14.07,46.31)]),
    ("GND",     [(8.0,54.2,6.8,54.2)]),
]
for netname, segs in EXACT:
    for t in live():
        if is_via(t) or t.GetNetname() != netname:
            continue
        for s in segs:
            if match_seg(t, *s):
                del_item(t); break

VIA_DEL = [(72.8,136.33),(79.2,136.33),(11.0,31.9),(2.0,31.9)]
for t in live():
    if not is_via(t):
        continue
    x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
    for (vx, vy) in VIA_DEL:
        if abs(x-vx) < 0.15 and abs(y-vy) < 0.15:
            del_item(t); break

for t in live():
    if is_via(t) or t.GetNetname() != "V24_BUS":
        continue
    x1, y1, x2, y2 = ends(t)
    w = mm(t.GetWidth())
    if abs(x1-x2) < 0.01 and abs(w-2.0) < 0.05:
        continue
    if min(y1, y2) < 19.5 and max(y1, y2) < 22:
        del_item(t)

print("撤销:", removed)
if os.environ.get("PHASE") == "del":
    pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
    print("✅ 撤销阶段已保存")
    raise SystemExit(0)

# ============ 净空检查器 ============
def clear_seg(x1, y1, x2, y2, hw, layer, netname, margin=0.28):
    seg = (x1, y1, x2, y2)
    for t in live():
        if t.GetNetname() == netname:
            continue
        if is_via(t):
            vx, vy = mm(t.GetPosition().x), mm(t.GetPosition().y)
            if seg_pt_dist(vx, vy, *seg) < hw + track_w(t)/2 + margin:
                return False
        else:
            if t.GetLayer() != layer:
                continue
            if seg_seg_dist(seg, ends(t)) < hw + track_w(t)/2 + margin:
                return False
    for (sx1, sy1, sx2, sy2, shw, sl, sn) in NEW_SEGS:
        if sn == netname or sl != layer:
            continue
        if seg_seg_dist(seg, (sx1, sy1, sx2, sy2)) < hw + shw + margin:
            return False
    for (vx, vy, vr, vn) in NEW_VIAS:
        if vn == netname:
            continue
        if seg_pt_dist(vx, vy, *seg) < hw + vr + margin:
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
            cx, cy = (px1+px2)/2, (py1+py2)/2
            if seg_pt_dist(cx, cy, *seg) < hw + math.hypot(px2-px1, py2-py1)/2 + margin:
                for e in [(px1,py1,px2,py1),(px2,py1,px2,py2),(px2,py2,px1,py2),(px1,py2,px1,py1)]:
                    if seg_seg_dist(seg, e) < hw + margin:
                        return False
                if px1 < (x1+x2)/2 < px2 and py1 < (y1+y2)/2 < py2:
                    return False
    return True

def clear_path(pts, hw, layer, netname, margin=0.28):
    return all(clear_seg(a[0], a[1], b[0], b[1], hw, layer, netname, margin)
               for a, b in zip(pts, pts[1:]))

WARN = []
SKIP = bool(os.environ.get("SKIP_TAILS"))

# ============ 1. 左列重画 ============
f2x, f2y = ppos("F1", 2)
trk([(f2x, f2y), (f2x, 22.2)], "V24_FUSED", 3.0)
trk([(f2x, 22.2), (12.11, 22.2)], "V24_FUSED", 3.6)
trk([(5.31, 22.2), (5.31, 25.89)], "V24_FUSED", 0.9)
trk([(12.11, 22.2), (12.11, 25.89)], "V24_FUSED", 0.9)
trk([(5.31, 25.89), (4.2, 26.6), (3.4, 27.4), (3.4, 36.5), (4.6, 37.09), (5.36, 37.09)], "V24_FUSED", 0.5)
trk([(9.9, 26.5), (11.0, 26.5), (11.0, 36.0), (8.64, 37.09)], "PMOS_GATE", 0.4)
trk([(11.0, 27.75), (16.69, 27.75), (16.69, 26.6)], "PMOS_GATE", 0.4)
trk([(8.64, 37.09), (8.64, 38.5), (6.25, 38.5), (6.25, 39.34)], "PMOS_GATE", 0.4)
trk([(6.25, 39.34), (6.25, 41.3), (6.0, 42.17)], "PMOS_GATE", 0.4)
rs2x, rs2y = ppos("RS1", 2)
if not SKIP:
    trk([(8.5, 49.5), (8.5, 48.45), (13.5, 48.45), (14.07, 47.9), (14.07, rs2y)], "V24_BUS", 0.25)
    trk([(8.0, 49.5), (8.0, 48.6), (7.93, 47.8), (7.93, 46.31)], "V24_PROT", 0.25)
    trk([(8.0, 54.2), (8.0, 53.5), (10.01, 52.30)], "GND", 0.25)

# ============ 2. 六通道重画 ============
CH = [("J3","F2","D5","D6","D7","D8","Q7","Q8","C16","C17"),
      ("J4","F3","D9","D10","D11","D12","Q9","Q10","C18","C19"),
      ("J5","F4","D13","D14","D15","D16","Q11","Q12","C20","C21"),
      ("J6","F5","D17","D18","D19","D20","Q13","Q14","C22","C23"),
      ("J7","F6","D21","D22","D23","D24","Q15","Q16","C24","C25"),
      ("J8","F7","D25","D26","D27","D28","Q17","Q18","C26","C27")]
for i, (J, Fu, Dcw, Dfw, Dtvc, Dtvw, Qc, Qw, Cel, Cml) in enumerate(CH):
    ch = f"CH{i+1}"
    p1x, p1y = ppos(J, 1); p2x, p2y = ppos(J, 2); p3x, p3y = ppos(J, 3)
    f1x_, f1y_ = ppos(Fu, 1); fux, fuy = ppos(Fu, 2)
    d5ax, d5ay = ppos(Dcw, 1)
    d1x, d1y = ppos(Dfw, 1)
    d2x, d2y = ppos(Dfw, 2)
    tc_x, tc_y = ppos(Dtvc, 1)
    tw_x, tw_y = ppos(Dtvw, 1)
    c16x, c16y = ppos(Cel, 1)
    c17x, c17y = ppos(Cml, 1)
    col = p2x
    gx = (f1x_ + fux) / 2
    # VOUT 主线
    trk([(p1x, p1y), (p1x, 15.0), (fux, 16.6), (fux, fuy), (fux, 20.0)], f"{ch}_VOUT", 2.0)
    trk([(fux, 20.0), (col + 1.75, 25.1), (d1x, 27.0)], f"{ch}_VOUT", 1.2)
    trk([(d1x, 27.0), (d1x, d1y)], f"{ch}_VOUT", 1.2)
    # D5.1 馈线
    via(d1x, 27.0, f"{ch}_VOUT", 0.8, 0.4)
    trk([(d1x, 27.0), (d5ax, 27.0), (d5ax, 25.8)], f"{ch}_VOUT", 0.8, layer=B)
    via(d5ax, 25.8, f"{ch}_VOUT", 0.8, 0.4)
    trk([(d5ax, 25.8), (d5ax, 24.0)], f"{ch}_VOUT", 0.8)
    # C16/C17 馈线
    done = False
    for x_e in (col + 4.9, col + 5.5, col + 4.35):
        for yh in (64.9, 65.7, 63.9):
            pth = [(d1x, 27.0), (x_e, 29.5), (x_e, yh), (c16x, yh)]
            if clear_path(pth, 0.4, B, f"{ch}_VOUT") and \
               clear_seg(c16x, yh, c16x, 65.6, 0.3, B, f"{ch}_VOUT") and \
               clear_path([(c16x, 65.8), (c16x, c16y)], 0.4, F, f"{ch}_VOUT"):
                trk(pth, f"{ch}_VOUT", 0.8, layer=B)
                trk([(c16x, yh), (c16x, 65.6)], f"{ch}_VOUT", 0.8, layer=B)
                via(c16x, 65.8, f"{ch}_VOUT", 0.8, 0.4)
                trk([(c16x, 65.8), (c16x, c16y)], f"{ch}_VOUT", 0.8)
                done = True
                break
        if done:
            break
    if not done:
        WARN.append(f"{ch} C16")
    p_c17 = [(c16x, c16y), (c16x + 1.7, 70.5), (c17x, 71.8), (c17x, c17y)]
    if clear_path(p_c17[1:], 0.3, F, f"{ch}_VOUT"):
        trk(p_c17, f"{ch}_VOUT", 0.6)
    else:
        WARN.append(f"{ch} C17")
    # CW
    trk([(p2x, p2y), (col, 11.0), (gx, 12.6), (gx, 23.2), (col - 1.8, 24.8), (col - 1.8, 31.5)], f"{ch}_CW_D", 1.2)
    done = False
    for x_c in (tc_x, col - 3.5, col - 2.6, col - 5.7):
        p_b = [(col - 1.5, 36.2), (x_c, 39.5), (x_c, 54.4)]
        p_f = [(x_c, 54.6), (tc_x, 55.6), (tc_x, tc_y)]
        if clear_path(p_b, 0.5, B, f"{ch}_CW_D") and clear_path(p_f, 0.5, F, f"{ch}_CW_D"):
            via(col - 1.5, 36.2, f"{ch}_CW_D", 0.8, 0.4)
            trk(p_b, f"{ch}_CW_D", 1.0, layer=B)
            via(x_c, 54.6, f"{ch}_CW_D", 0.8, 0.4)
            trk(p_f, f"{ch}_CW_D", 1.0)
            done = True
            break
    if not done:
        WARN.append(f"{ch} CW-TVS")
    # WW
    lane = col - 6.9
    trk([(p3x, p3y), (p3x, 11.5), (lane, 14.5), (lane, 42.6), (col - 2.0, 45.6)], f"{ch}_WW_D", 1.2)
    trk([(d2x, d2y), (d2x, 42.6), (col + 2.4, 45.4)], f"{ch}_WW_D", 1.2)
    e1 = [(col + 2.5, 48.5), (col + 4.2, 50.5), (col + 4.2, 58.0), (tw_x, 60.5)]
    e3 = [(col + 2.5, 48.5), (col + 4.2, 50.5), (col + 4.2, 63.2), (tw_x, 63.2), (tw_x, 61.5)]
    if clear_path(e1[1:], 0.5, F, f"{ch}_WW_D"):
        trk(e1, f"{ch}_WW_D", 1.0)
    elif clear_path(e3[1:], 0.5, F, f"{ch}_WW_D"):
        trk(e3, f"{ch}_WW_D", 1.0)
    else:
        WARN.append(f"{ch} WW-TVS")

# 立管过孔 x21.9 → x21.7
for t in live():
    if is_via(t) and t.GetNetname() == "V24_BUS":
        x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
        if abs(x - 21.9) < 0.05 and y < 48:
            t.SetPosition(VECTOR2I(FromMM(21.7), FromMM(y)))

# ============ 3. 与新走线冲突的 GND 明线清理 ============
gnd_del = 0
for t in live():
    if is_via(t) or t.GetNetname() != "GND":
        continue
    e = ends(t); ly = t.GetLayer(); hw = mm(t.GetWidth())/2
    for (x1, y1, x2, y2, shw, sl, sn) in NEW_SEGS:
        if sl != ly:
            continue
        if seg_seg_dist((x1, y1, x2, y2), e) < hw + shw + 0.25:
            del_item(t); gnd_del += 1
            break
print(f"清除与新走线冲突的 GND 明线 {gnd_del} 条")

# ============ 4. 收尾网络(SKIP_TAILS=1 跳过) ============
if not SKIP:
    trk([(31.37, 109.8), (33.3, 107.6), (34.6, 107.0), (39.5, 105.3), (39.5, 105.2)], "V24_LOGIC", 0.4, layer=B)
    trk([(44.8, 114.9), (45.8, 112.9), (45.8, 111.6)], "BOOT", 0.3, layer=B)
    via(45.8, 111.6, "BOOT", 0.6, 0.3)
    trk([(45.8, 111.6), (46.3, 111.2), (46.3, 111.04)], "BOOT", 0.3)
    via(32.0, 106.49, "GND", 0.6, 0.3)
    for fp in board.GetFootprints():
        if fp.GetReference() == "R10":
            fp.SetPosition(VECTOR2I(FromMM(69.6), FromMM(136.6)))
            fp.SetOrientationDegrees(0)
    r101x, r101y = ppos("R10", 1)
    trk([(r101x, r101y), (69.5, 136.2), (70.5, 135.9)], "CC2", 0.25)
    via(70.5, 135.9, "CC2", 0.6, 0.3)
    trk([(70.5, 135.9), (76.9, 135.9)], "CC2", 0.25, layer=B)
    via(76.9, 135.9, "CC2", 0.6, 0.3)
    trk([(76.9, 135.9), (77.4, 136.3), (77.4, 137.9), (77.75, 138.3), (77.75, 138.53)], "CC2", 0.25)
    a49x, _a = ppos("J2", "A4B9"); b49x, _b = ppos("J2", "B4A9")
    trk([(44.36, 127.1), (58.6, 132.0), (60.3, 133.3), (60.3, 136.6), (b49x, 136.6)], "USB_VBUS", 0.25, layer=B)
    via(a49x, 136.6, "USB_VBUS", 0.6, 0.3)
    trk([(a49x, 136.6), (a49x, 138.53)], "USB_VBUS", 0.25)
    via(b49x, 136.6, "USB_VBUS", 0.6, 0.3)
    trk([(b49x, 136.6), (b49x, 138.53)], "USB_VBUS", 0.25)

# ============ 5. 重填、保存 ============
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
