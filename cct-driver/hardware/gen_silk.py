#!/usr/bin/env python3
"""丝印整理:
1. 位号统一字号(常规 0.7,密集区 0.55),避障重摆(候选环搜索)
2. 功能标注:通道号/引脚名/24V 输入/保险丝规格/接口名/板名版本/测试点网络名
运行后需重新 DRC 检查丝印计数。
"""
import gc, math
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

board = pcbnew.LoadBoard("cct-main.kicad_pcb")
mm = pcbnew.ToMM
F = pcbnew.F_Cu
FSILK = pcbnew.F_SilkS

BOARD_W, BOARD_H = 110.0, 145.0
EDGE = 0.45

# ---------- 障碍收集 ----------
pad_boxes = []      # (x1,y1,x2,y2)  顶层焊盘
silk_boxes = []     # 每条丝印图元的 bbox(线段级)
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or p.IsOnLayer(F):
            bb = p.GetBoundingBox()
            pad_boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    for g in fp.GraphicalItems():
        if g.GetLayer() == FSILK and g.GetClass() == "PCB_SHAPE":
            bb = g.GetBoundingBox()
            silk_boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
# 过孔(未盖油时丝印压环会告警;保守作为小障碍)
via_pts = []
for t in board.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition()
        via_pts.append((mm(p.x), mm(p.y)))

placed_texts = []   # 已放置文本 bbox

def text_box(x, y, w_chars, size):
    w = 0.92 * size * w_chars + 0.3
    h = size + 0.25
    return (x - w/2, y - h/2, x + w/2, y + h/2)

def box_clash(a, b, margin=0.12):
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or
                a[3] + margin < b[1] or b[3] + margin < a[1])

def spot_ok(bx, own_pads=None):
    if bx[0] < EDGE or bx[1] < EDGE or bx[2] > BOARD_W - EDGE or bx[3] > BOARD_H - EDGE:
        return False
    for pb in pad_boxes:
        if own_pads and pb in own_pads:
            pass
        if box_clash(bx, pb, 0.1):
            return False
    for sb in silk_boxes:
        if box_clash(bx, sb, 0.08):
            return False
    for tb in placed_texts:
        if box_clash(bx, tb, 0.15):
            return False
    for (vx, vy) in via_pts:
        if bx[0] - 0.3 < vx < bx[2] + 0.3 and bx[1] - 0.3 < vy < bx[3] + 0.3:
            return False
    return True

# ---------- 2. 功能标注 ----------
def label(x, y, s, size=0.9, angle=0, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.18 if bold else 0.13))
    t.SetLayer(FSILK)
    t.SetTextAngleDegrees(angle)
    board.Add(t)
    if angle % 180 == 90:
        w = 0.92 * size * len(s) + 0.3
        h = size + 0.25
        placed_texts.append((x - h/2, y - w/2, x + h/2, y + w/2))
    else:
        placed_texts.append(text_box(x, y, len(s), size))

def pad_pos(ref, num):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            for p in fp.Pads():
                if p.GetNumber() == str(num):
                    pp = p.GetPosition()
                    return mm(pp.x), mm(pp.y)
    return None

# 通道端子:CHn 与引脚名
for i, J in enumerate(["J3","J4","J5","J6","J7","J8"]):
    col = 30.0 + 14.0*i
    label(col, 1.7, f"CH{i+1}", 1.0, bold=True)
    label(col - 3.81, 13.9, "WW", 0.6)
    label(col, 13.9, "CW", 0.6)
    label(col + 3.81, 13.9, "V+", 0.6)
# 24V 输入
label(11.0, 14.5, "DC 24V IN  MAX 12A", 0.65, bold=True)
label(19.2, 5.2, "+", 1.1, bold=True)
label(2.9, 5.2, "-", 1.1, bold=True)
# 保险丝(右缘竖排)
label(107.6, 30.0, "FUSE 4A-T x6 / MAIN 15A", 0.8, angle=90)
# 板名(白油块下方横排,180° 与全板一致;实测宽 21.87mm,最近障碍 TP4 位号 1.34mm)
label(96.8, 98.0, "PendingHome CCT LED Driver 1", 0.9, angle=180, bold=True)
# 底部接口
for (ref_, txt) in [("J9","I2C 3.3V"), ("J10","UART 5V"), ("J11","SW1-4 DRY")]:
    pos = None
    for fp in board.GetFootprints():
        if fp.GetReference() == ref_:
            bb = fp.GetBoundingBox(False)
            pos = ((mm(bb.GetLeft())+mm(bb.GetRight()))/2, mm(bb.GetTop()) - 0.9)
    if pos:
        label(pos[0], pos[1], txt, 0.7)
# 测试点网络名
for fp in board.GetFootprints():
    r = fp.GetReference()
    if not r.startswith("TP"):
        continue
    netname = ""
    for p in fp.Pads():
        netname = p.GetNetname()
    short = {"V24_BUS":"V24","V24_PROT":"V24P","V24_LOGIC":"V24L","V5_SYS":"5V",
             "V5_BUCK":"5V","V3P3":"3V3","GND":"GND"}.get(netname, netname[:6])
    pp = fp.GetPosition()
    x, y = mm(pp.x), mm(pp.y)
    for (tx, ty) in [(x, y-1.3), (x, y+1.3), (x-1.9, y), (x+1.9, y)]:
        bx = text_box(tx, ty, len(short), 0.6)
        if spot_ok(bx):
            label(tx, ty, short, 0.6)
            break

# ---------- 1. 位号重摆 ----------
moved = kept = failed = 0
fps = sorted(board.GetFootprints(), key=lambda f: (mm(f.GetPosition().y), mm(f.GetPosition().x)))
for fp in fps:
    ref = fp.Reference()
    r = fp.GetReference()
    fb = fp.GetBoundingBox(False)   # 不含文本
    x1, y1, x2, y2 = mm(fb.GetLeft()), mm(fb.GetTop()), mm(fb.GetRight()), mm(fb.GetBottom())
    cx, cy = (x1+x2)/2, (y1+y2)/2
    small = (x2-x1) < 2.6 and (y2-y1) < 2.6
    size = 0.65 if small else 0.75
    ref.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    ref.SetTextThickness(FromMM(0.12))
    ref.SetLayer(FSILK)
    ref.SetVisible(True)
    ref.SetTextAngleDegrees(0)
    n = len(r)
    h = size + 0.25
    cands = []
    for d in (0.35, 0.7, 1.1, 1.6, 2.2, 2.9, 3.6):
        cands += [(cx, y1 - d - h/2), (cx, y2 + d + h/2)]
        w = 0.92*size*n/2
        cands += [(x1 - d - w, cy), (x2 + d + w, cy)]
        cands += [(x1 - d - w, y1 - d - h/2), (x2 + d + w, y1 - d - h/2),
                  (x1 - d - w, y2 + d + h/2), (x2 + d + w, y2 + d + h/2)]
    done = False
    for (tx, ty) in cands:
        bx = text_box(tx, ty, n, size)
        if spot_ok(bx):
            ref.SetPosition(VECTOR2I(FromMM(tx), FromMM(ty)))
            placed_texts.append(bx)
            moved += 1
            done = True
            break
    if not done:
        # 缩小再试一轮
        size2 = 0.5
        ref.SetTextSize(VECTOR2I(FromMM(size2), FromMM(size2)))
        ref.SetTextThickness(FromMM(0.11))
        for (tx, ty) in cands:
            bx = text_box(tx, ty, n, size2)
            if spot_ok(bx):
                ref.SetPosition(VECTOR2I(FromMM(tx), FromMM(ty)))
                placed_texts.append(bx)
                moved += 1
                done = True
                break
    if not done:
        # 放弃避障:放在正上方并记录
        ref.SetPosition(VECTOR2I(FromMM(cx), FromMM(y1 - 0.7)))
        placed_texts.append(text_box(cx, y1 - 0.7, n, 0.55))
        failed += 1
print(f"位号:重摆 {moved},未净空 {failed}")

pcbnew.SaveBoard("cct-main.kicad_pcb", board)
print("✅ 丝印已保存")
