#!/usr/bin/env python3
"""丝印整理:
1. 位号统一字号(常规 0.7,密集区 0.55),避障重摆(候选环搜索)
2. 功能标注:通道号/引脚名/24V 输入/保险丝规格/接口名/板名版本/测试点网络名
运行后需重新 DRC 检查丝印计数。

⚠️ 坐标系:板文件的方向**就是上墙安装的方向**——接线端子(J1/J3–J8)在下方
y≈137,传感器接口(J2/J9/J10/J11)在上方 y≈4。见 gen_rotate180.py。
所以本脚本里所有文字一律用自然角度(横排 0°、左缘竖排 90°),
**不要**再写 `angle=180` 之类的"预转补偿"——那是 2026-08-13 之前的老做法,
而且对位号根本无效(KiCad 的 keep-upright 会把封装自带文字扶正)。

用法:
    python3 gen_silk.py                  整套丝印(位号重摆 + 全部功能标注),只能在干净板上跑一次
    python3 gen_silk.py --boardname-only 只重做板名那两行(幂等:先删旧的再放,重跑结果一样)
"""
import gc, math, sys
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

BOARDNAME_ONLY = "--boardname-only" in sys.argv

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
# 板级丝印图形(目前只有订单二维码的 8×8 白油块,gen_whiteblock.py 放的)
for g in board.GetDrawings():
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
def label(x, y, s, size=0.9, angle=0, bold=False, left=False):
    """left=True 时 x 是左端而不是中心(多行左对齐用,由 KiCad 自己对齐,
    不依赖这里那套估算宽度)。"""
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.18 if bold else 0.13))
    t.SetLayer(FSILK)
    t.SetTextAngleDegrees(angle)
    if left:
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    board.Add(t)
    if angle % 180 == 90:
        w = 0.92 * size * len(s) + 0.3
        h = size + 0.25
        placed_texts.append((x - h/2, y - w/2, x + h/2, y + w/2))
    elif left:
        placed_texts.append(text_box(x + (0.92*size*len(s) + 0.3)/2, y, len(s), size))
    else:
        placed_texts.append(text_box(x, y, len(s), size))

# ---------- 板名(白油块右侧两行) ----------
# 白油块 4.2–12.2 / 49.2–57.2(gen_whiteblock.py),中心 y = 53.2。
# 两行左端都从 NAME_X 起,由 KiCad 做左对齐;上下对称落在白块中心两侧。
NAME_LINES = ("PendingHome", "CCT LED Driver 1")
NAME_X     = 13.2      # 左端,离白油块右沿 1.0mm
NAME_CY    = 53.2      # 与白油块垂直居中
NAME_SIZE  = 0.9
NAME_PITCH = 1.5       # 行距(字高 0.9,字间净空 0.6mm)

def board_name():
    others = list(placed_texts)      # 冻结:板名自己那两行之间的行距不算"障碍"
    ys = [NAME_CY + (i - (len(NAME_LINES) - 1) / 2) * NAME_PITCH
          for i in range(len(NAME_LINES))]
    for s, y in zip(NAME_LINES, ys):
        w = 0.92 * NAME_SIZE * len(s) + 0.3
        bx = (NAME_X, y - (NAME_SIZE + 0.25) / 2, NAME_X + w, y + (NAME_SIZE + 0.25) / 2)
        gap, who = nearest_gap(bx, others)
        print(f"  板名 {s!r:<20} {bx[0]:.2f},{bx[1]:.2f} – {bx[2]:.2f},{bx[3]:.2f}"
              f"  最近障碍 {who} 距 {gap:.2f}mm")
        assert gap >= 0.3, f"板名「{s}」净空只有 {gap:.2f}mm({who}),往右挪或缩字号"
        label(NAME_X, y, s, NAME_SIZE, bold=True, left=True)

def nearest_gap(bx, texts=None):
    """矩形 bx 到最近障碍(顶层焊盘/丝印图元/已放文字/过孔)的间距与它是谁。"""
    texts = placed_texts if texts is None else texts
    def gap(b):
        dx = max(b[0] - bx[2], bx[0] - b[2])
        dy = max(b[1] - bx[3], bx[1] - b[3])
        return (dx*dx + dy*dy) ** 0.5 if dx >= 0 and dy >= 0 else max(dx, dy)
    cands = [(gap(b), "焊盘") for b in pad_boxes]
    cands += [(gap(b), "丝印图元") for b in silk_boxes]
    cands += [(gap(b), "已放文字") for b in texts]
    cands += [(gap((vx-0.3, vy-0.3, vx+0.3, vy+0.3)), "过孔") for (vx, vy) in via_pts]
    return min(cands)

def pad_pos(ref, num):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            for p in fp.Pads():
                if p.GetNumber() == str(num):
                    pp = p.GetPosition()
                    return mm(pp.x), mm(pp.y)
    return None

# ---------- 只重做板名(幂等) ----------
if BOARDNAME_ONLY:
    OLD_NAMES = {"PendingHome CCT LED Driver 1", "CCT-DRIVER v1.0 2026-08"} | set(NAME_LINES)
    removed = 0
    for d in list(board.GetDrawings()):
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == FSILK and d.GetText() in OLD_NAMES:
            board.Remove(d)
            removed += 1
    print(f"清除旧板名文字 {removed} 条")
    # 板上现存的所有丝印文字(位号 + 其余板级标注)都算障碍
    for fp in board.GetFootprints():
        r = fp.Reference()
        if r.IsVisible() and r.GetLayer() == FSILK:
            bb = r.GetBoundingBox()
            placed_texts.append((mm(bb.GetLeft()), mm(bb.GetTop()),
                                 mm(bb.GetRight()), mm(bb.GetBottom())))
    for d in board.GetDrawings():
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == FSILK:
            bb = d.GetBoundingBox()
            placed_texts.append((mm(bb.GetLeft()), mm(bb.GetTop()),
                                 mm(bb.GetRight()), mm(bb.GetBottom())))
    board_name()
    pcbnew.SaveBoard("cct-main.kicad_pcb", board)
    print("✅ 板名已重排(白油块右侧两行)")
    raise SystemExit

# 通道端子(板子下缘):CHn 与引脚名。CH1 在右、CH6 在左
for i, J in enumerate(["J3","J4","J5","J6","J7","J8"]):
    col = 80.0 - 14.0*i
    label(col, 143.3, f"CH{i+1}", 1.0, bold=True)
    label(col + 3.81, 131.1, "WW", 0.6)
    label(col, 131.1, "CW", 0.6)
    label(col - 3.81, 131.1, "V+", 0.6)
# 24V 输入(下缘最右)
label(99.0, 130.5, "DC 24V IN  MAX 12A", 0.65, bold=True)
# 极性号对准 J1 的两个脚(间距 7.62,中心 99.0),与板上一致
label(95.19, 133.7, "+", 1.1, bold=True)
label(102.81, 133.7, "-", 1.1, bold=True)
# 保险丝(左缘竖排)
label(2.4, 115.0, "FUSE 4A-T x6 / MAIN 15A", 0.8, angle=90)
# 板名:白油块右侧两行,左端对齐,与白块垂直居中(白块 4.2–12.2 / 49.2–57.2,中心 y 53.2)
board_name()
# 上缘接口:标注放在封装下方(朝板内)
for (ref_, txt) in [("J9","I2C 3.3V"), ("J10","UART 5V"), ("J11","SW1-4 DRY")]:
    pos = None
    for fp in board.GetFootprints():
        if fp.GetReference() == ref_:
            bb = fp.GetBoundingBox(False)
            pos = ((mm(bb.GetLeft())+mm(bb.GetRight()))/2, mm(bb.GetBottom()) + 0.9)
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
