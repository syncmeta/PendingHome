#!/usr/bin/env python3
"""嘉立创订单追溯二维码的白油块(8×8mm 实心白丝印)+ 域名文字标注。

背景:首板改用哑黑阻焊,嘉立创的订单二维码在黑底上扫不出来,要求文件里
预留一块白油方块,它再往白底上喷深色二维码(下单页选「8*8mm」+
「指定位置添加(文件已有位置)」)。

本脚本取代 gen_qr.py:
  1. 清除原自制二维码(反色,174 个 F.SilkS 实心矩形)所在窗口的全部
     板级丝印矩形——包括本脚本上次生成的白油块,故可重复运行;
  2. 在原二维码油墨区中心放一个 8×8mm 的 F.SilkS 实心矩形;
  3. 二维码内容(http://cct-driver.local)改用普通丝印文字保留,放在
     白油块下方(整板旋转 180° 安装后位于块的上方),字号与板上其他
     功能标注一致(0.7mm),朝向同为 180°。

嘉立创对白油块的要求:加在大铜面或基材区域,避开走线/钻孔/阻焊开窗/
字符。该区域是 GND 大铜面,无顶层走线、无过孔、无焊盘、无其他丝印;
脚本内置校验,净空或边距不足会直接 assert 失败。
"""
import gc
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

BLOCK = 8.0                 # 白油块边长 mm(下单页选的 8*8mm)
CX, CY = 101.8, 91.8        # 块中心 = 原二维码油墨区(96.8~106.8 / 86.8~96.8)中心
CLEAR = 0.5                 # 白油块四周要求的最小净空 mm
EDGE_MIN = 3.0              # 白油块离板边最小距离 mm
TEXT = "cct-driver.local"   # 原二维码内容(http://cct-driver.local)
TSIZE, TTHICK = 0.8, 0.13   # 同板上功能标注(如保险丝规格那条),且 ≥DRC 最小字高 0.8
TANGLE = 180                # 全板丝印统一 180°(端子朝下,倒装上墙后正读)
TY = 97.4                   # 文字中心 y(块下沿 95.8 之下,留 >0.5mm)
CLEAN = (95.0, 85.0, 108.0, 99.0)   # 清理窗口 x1,y1,x2,y2(覆盖旧 QR 含静区)

board = pcbnew.LoadBoard("cct-main.kicad_pcb")
mm = pcbnew.ToMM
FSILK = pcbnew.F_SilkS

BX1, BY1 = CX - BLOCK / 2, CY - BLOCK / 2
BX2, BY2 = CX + BLOCK / 2, CY + BLOCK / 2

# 文字对象先建好并量出实际包围盒——GetBoundingBox() 要在动板(增删图元)之前
# 调用,之后 swig 返回的 BOX2I 包装会失效。
text = pcbnew.PCB_TEXT(board)
text.SetText(TEXT)
text.SetPosition(VECTOR2I(FromMM(CX), FromMM(TY)))
text.SetTextSize(VECTOR2I(FromMM(TSIZE), FromMM(TSIZE)))
text.SetTextThickness(FromMM(TTHICK))
text.SetLayer(FSILK)
text.SetTextAngleDegrees(TANGLE)
_tb = text.GetBoundingBox()
TX1, TY1 = mm(_tb.GetLeft()), mm(_tb.GetTop())
TX2, TY2 = mm(_tb.GetRight()), mm(_tb.GetBottom())

def in_clean(x1, y1, x2, y2):
    return CLEAN[0] <= x1 and CLEAN[1] <= y1 and x2 <= CLEAN[2] and y2 <= CLEAN[3]

# ---------- 1. 障碍收集(先于删除;清理窗口内的旧图元不算障碍) ----------
# 只看顶面:焊盘、顶层走线/过孔、顶层丝印。底层铜与白油块无关。
boxes = []   # (x1,y1,x2,y2,标签)      —— 用包围盒判定
segs = []    # (x1,y1,x2,y2,半宽,标签) —— 走线按线段判定(斜线包围盒会误判)
for fp in board.GetFootprints():
    for p in fp.Pads():
        bb = p.GetBoundingBox()
        boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()),
                      f"{fp.GetReference()} pad{p.GetNumber()}"))
    for g in list(fp.GraphicalItems()) + [fp.Reference(), fp.Value()]:
        if g.GetLayer() != FSILK or not getattr(g, "IsVisible", lambda: True)():
            continue
        bb = g.GetBoundingBox()
        boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()),
                      f"{fp.GetReference()} silk"))
for t in board.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition()
        r = mm(t.GetWidth(pcbnew.F_Cu)) / 2      # 过孔取顶层焊环直径
        segs.append((mm(p.x), mm(p.y), mm(p.x), mm(p.y), r, "via"))
    elif t.IsOnLayer(pcbnew.F_Cu):
        if t.Type() == pcbnew.PCB_ARC_T:
            bb = t.GetBoundingBox()
            boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()),
                          "顶层圆弧走线"))
        else:
            s, e = t.GetStart(), t.GetEnd()
            segs.append((mm(s.x), mm(s.y), mm(e.x), mm(e.y), mm(t.GetWidth()) / 2, "顶层走线"))
for d in board.GetDrawings():
    if d.GetLayer() != FSILK:
        continue
    bb = d.GetBoundingBox()
    x1, y1, x2, y2 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
    if in_clean(x1, y1, x2, y2):
        continue
    boxes.append((x1, y1, x2, y2, "板级丝印"))

eb = board.GetBoardEdgesBoundingBox()
ex1, ey1 = mm(eb.GetLeft()), mm(eb.GetTop())
ex2, ey2 = mm(eb.GetRight()), mm(eb.GetBottom())

# ---------- 2. 清除旧二维码方块 / 上次生成的白油块与文字 ----------
old_rect = old_text = 0
for d in list(board.GetDrawings()):
    if d.GetLayer() != FSILK:
        continue
    bb = d.GetBoundingBox()
    if not in_clean(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())):
        continue
    if d.GetClass() == "PCB_SHAPE" and d.GetShape() == pcbnew.SHAPE_T_RECT:
        board.Remove(d); old_rect += 1
    elif d.GetClass() == "PCB_TEXT" and d.GetText() == TEXT:
        board.Remove(d); old_text += 1
print(f"清除旧丝印:矩形 {old_rect} 个,文字 {old_text} 条")

# ---------- 3. 净空校验 ----------
def box_gap(b, x1, y1, x2, y2):
    """两矩形的最小间距(相交为负)。"""
    dx = max(b[0] - x2, x1 - b[2])
    dy = max(b[1] - y2, y1 - b[3])
    if dx >= 0 and dy >= 0:
        return (dx * dx + dy * dy) ** 0.5
    return max(dx, dy)

def pt_seg(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L))
    dx, dy = px - (ax + u * vx), py - (ay + u * vy)
    return (dx * dx + dy * dy) ** 0.5

def seg_gap(s, x1, y1, x2, y2):
    """线段(含半宽)到矩形的最小间距。凸集:极值必在端点-矩形 或 角点-线段。"""
    ax, ay, bx, by, r, _ = s
    d = min(box_gap((ax, ay, ax, ay), x1, y1, x2, y2),
            box_gap((bx, by, bx, by), x1, y1, x2, y2))
    if d > 0:
        d = min(d, min(pt_seg(cx, cy, ax, ay, bx, by)
                       for cx in (x1, x2) for cy in (y1, y2)))
    return d - r

def nearest(x1, y1, x2, y2):
    """返回 (间距, 标签)。"""
    cands = [(box_gap(b, x1, y1, x2, y2), b[4]) for b in boxes]
    cands += [(seg_gap(s, x1, y1, x2, y2), s[5]) for s in segs]
    return min(cands)

wg, wlbl = nearest(BX1, BY1, BX2, BY2)
print(f"白油块 {BX1:.1f},{BY1:.1f} - {BX2:.1f},{BY2:.1f};最近障碍 {wlbl} 距 {wg:.2f}mm")
assert wg >= CLEAR, f"净空不足 {wg:.2f}mm < {CLEAR}mm({wlbl})"

edge = min(BX1 - ex1, BY1 - ey1, ex2 - BX2, ey2 - BY2)
print(f"离板边最近 {edge:.2f}mm")
assert edge >= EDGE_MIN, f"离板边不足 {edge:.2f}mm < {EDGE_MIN}mm"

# ---------- 4. 放白油块 ----------
s = pcbnew.PCB_SHAPE(board)
s.SetShape(pcbnew.SHAPE_T_RECT)
s.SetStart(VECTOR2I(FromMM(BX1), FromMM(BY1)))
s.SetEnd(VECTOR2I(FromMM(BX2), FromMM(BY2)))
s.SetFilled(True)
s.SetWidth(0)
s.SetLayer(FSILK)
board.Add(s)

# ---------- 5. 放域名文字 ----------
print(f"文字 {TEXT!r} {TX1:.2f},{TY1:.2f} - {TX2:.2f},{TY2:.2f}")
# 文字不得压进白油块及其 0.5mm 净空区
tg = box_gap((TX1, TY1, TX2, TY2), BX1 - CLEAR, BY1 - CLEAR, BX2 + CLEAR, BY2 + CLEAR)
assert tg >= 0, f"文字侵入白油块净空区 {tg:.2f}mm"
# 文字与其他障碍(白油块自身不在障碍表内)保持 0.15mm
twg, tlbl = nearest(TX1, TY1, TX2, TY2)
print(f"文字最近障碍 {tlbl} 距 {twg:.2f}mm;离板边 "
      f"{min(TX1 - ex1, TY1 - ey1, ex2 - TX2, ey2 - TY2):.2f}mm")
assert twg >= 0.15, f"文字净空不足 {twg:.2f}mm({tlbl})"
board.Add(text)

pcbnew.SaveBoard("cct-main.kicad_pcb", board)
print("✅ 已保存:白油块 1 个 + 文字 1 条")
