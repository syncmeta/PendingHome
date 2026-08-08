#!/usr/bin/env python3
"""板上丝印二维码。
INVERT=False:亮模块=白丝印,暗模块=露绿阻焊(标准配色,通用可扫)
INVERT=True :暗模块=白丝印,亮模块=露绿阻焊(反色,静区留绿不印)
自动搜索净空区(无焊盘/无过孔/无元件本体/无既有丝印文本)。
重复运行会先清除 QR 区内既有丝印方块。"""
import gc
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

INVERT = True      # 反色
MOD = 0.4          # 模块尺寸 mm
QUIET = 2          # 静区模块数
board = pcbnew.LoadBoard("cct-main.kicad_pcb")
mm = pcbnew.ToMM
FSILK = pcbnew.F_SilkS

matrix = [[c == '1' for c in line] for line in open('/tmp/qr-matrix.txt').read().split()]
N = len(matrix)
SIZE = (N + 2 * QUIET) * MOD          # 总占位(含静区)
print(f"QR {N}x{N},占位 {SIZE:.1f}mm 见方")

# —— 障碍收集 ——
obs = []   # (x1,y1,x2,y2)
for fp in board.GetFootprints():
    bb = fp.GetBoundingBox(False)
    obs.append((mm(bb.GetLeft())-0.5, mm(bb.GetTop())-0.5, mm(bb.GetRight())+0.5, mm(bb.GetBottom())+0.5))
    r = fp.Reference()
    if r.IsVisible():
        tb = r.GetBoundingBox()
        obs.append((mm(tb.GetLeft())-0.2, mm(tb.GetTop())-0.2, mm(tb.GetRight())+0.2, mm(tb.GetBottom())+0.2))
for d in board.GetDrawings():
    bb = d.GetBoundingBox()
    obs.append((mm(bb.GetLeft())-0.2, mm(bb.GetTop())-0.2, mm(bb.GetRight())+0.2, mm(bb.GetBottom())+0.2))
for t in board.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition()
        x, y = mm(p.x), mm(p.y)
        obs.append((x-0.6, y-0.6, x+0.6, y+0.6))
# 天线区禁放
obs.append((74, 116, 110, 145))

def clear(x, y):
    x2, y2 = x + SIZE, y + SIZE
    if x < 2 or y < 2 or x2 > 108 or y2 > 143:
        return False
    for (a, b, c, d) in obs:
        if not (c < x or x2 < a or d < y or y2 < b):
            return False
    return True

# —— 搜索:按偏好锚点排序的网格 ——
cands = []
for gy in range(2, 132, 1):
    for gx in range(2, 97, 1):
        if clear(gx, gy):
            cands.append((gx, gy))
assert cands, "没有净空区!"
ax, ay = 96, 86   # 首版落点,保持不变
if (ax, ay) in cands or True:
    qx, qy = ax, ay
cands.sort(key=lambda p: (p[0]-ax)**2 + (p[1]-ay)**2)
print(f"放置于 ({qx},{qy}) - ({qx+SIZE:.1f},{qy+SIZE:.1f}),候选 {len(cands)} 处")

old = 0
for d in list(board.GetDrawings()):
    if d.GetClass()!="PCB_SHAPE" or d.GetLayer()!=FSILK: continue
    if d.GetShape()!=pcbnew.SHAPE_T_RECT: continue
    s,e = d.GetStart(), d.GetEnd()
    x1,y1 = mm(s.x), mm(s.y)
    if qx-0.1 <= x1 <= qx+SIZE+0.1 and qy-0.1 <= y1 <= qy+SIZE+0.1:
        board.Remove(d); old += 1
print(f"清除旧 QR 方块 {old} 个")

def frect(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_RECT)
    s.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    s.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    s.SetFilled(True)
    s.SetWidth(0)
    s.SetLayer(FSILK)
    board.Add(s)

ox, oy = qx + QUIET * MOD, qy + QUIET * MOD          # 矩阵原点
shapes = 0
if not INVERT:
    # 标准:静区与亮模块印白丝印
    frect(qx, qy, qx + SIZE, oy)
    frect(qx, oy + N * MOD, qx + SIZE, qy + SIZE)
    frect(qx, oy, ox, oy + N * MOD)
    frect(ox + N * MOD, oy, qx + SIZE, oy + N * MOD)
    shapes += 4
# 需要印丝印的模块:标准=亮模块(False),反色=暗模块(True)
want = INVERT
for r in range(N):
    c = 0
    while c < N:
        if matrix[r][c] == want:
            c0 = c
            while c < N and matrix[r][c] == want:
                c += 1
            frect(ox + c0 * MOD, oy + r * MOD, ox + c * MOD, oy + (r + 1) * MOD)
            shapes += 1
        else:
            c += 1
print(f"丝印图形 {shapes} 个")
pcbnew.SaveBoard("cct-main.kicad_pcb", board)
print("✅ 已保存")
