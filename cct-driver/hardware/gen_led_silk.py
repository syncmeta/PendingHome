#!/usr/bin/env python3
"""指示灯改造的第二步:丝印 + 覆铜重填。

**为什么单独一个脚本。** pcbnew 的 Python 绑定有个坑:一旦脚本里做过大量
`board.Remove()`(gen_led_to_output.py 剪残枝时就会),同一个进程里后续的
`board.GetFootprints()` / `GraphicalItems()` 都会失效,报
`'SwigPyObject' object has no attribute ...`;**存盘再 LoadBoard 也救不回来**,
因为坏掉的是进程里的 SWIG 运行时。所以丝印这一步必须换个进程跑。

顺序:
    gen_led_to_output.py     铜:摆位 / 改网 / 布线 / 剪残枝
    gen_led_silk.py          丝印 + 覆铜重填   ← 本脚本
    gen_strip_res_silk.py    文本层去掉 12 个电阻的封装丝印外框
    gen_sync_values.py       板文件 Value 跟上 gen_sch.py

丝印怎么排:那条带只有 5mm 高,塞了 4 个件之后再摆 4 个位号是塞不下的。
而人真正要读的是"这颗灯是哪一路的冷白还是暖白",不是 LED12 这种位号 ——
通道号板子下缘本来就印着 CH1–CH6。所以这 24 个件的位号隐藏(装配用坐标文件,
不看丝印;位号在 cpl / BOM / 原理图里都在),改成在每颗灯旁边印 CW / WW。
"""
import gc

gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

BOARD = "cct-main.kicad_pcb"
board = pcbnew.LoadBoard(BOARD)
mm = pcbnew.ToMM

COL = {1: 80.0, 2: 66.0, 3: 52.0, 4: 38.0, 5: 24.0, 6: 10.0}
CH = {
    1: ("LED2", "R20", "LED3", "R21"), 2: ("LED4", "R26", "LED5", "R27"),
    3: ("LED6", "R32", "LED7", "R33"), 4: ("LED8", "R38", "LED9", "R39"),
    5: ("LED10", "R44", "LED11", "R45"), 6: ("LED12", "R50", "LED13", "R51"),
}
Y_ROW = 130.55
fps = {f.GetReference(): f for f in board.GetFootprints()}

# ---------- 5. 丝印:位号让位,改印通道冷暖 ----------
# 这条带只有 5mm 高,塞了 4 个件之后再摆 4 个位号是塞不下的(硬塞就是 DRC 里那
# 一百多条丝印压铜/重叠)。而且人真正要读的是"这颗灯是哪一路的冷白还是暖白",
# 不是 LED12 这种位号 —— 通道号板子下缘本来就印着 CH1–CH6。
# 所以:这 24 个件的位号隐藏(装配用的是坐标文件,不看丝印),改成在每颗灯旁边
# 印 CW / WW。位号信息不丢:cpl / BOM / 原理图里都在。
FSILK = pcbnew.F_SilkS
# 板子改了这么多之后,开头那份 fps 里的代理对象已经不可靠了,重新取一遍
fps = {f.GetReference(): f for f in board.GetFootprints()}
obst = []
for fp in board.GetFootprints():
    for q in fp.Pads():
        bb = q.GetBoundingBox()
        obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    for g in fp.GraphicalItems():
        if g.GetLayer() == FSILK:
            bb = g.GetBoundingBox()
            obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    r = fp.Reference()                      # 位号也算障碍,否则标注会压在 TP6 这类位号上
    if r.IsVisible() and r.GetLayer() == FSILK:
        bb = r.GetBoundingBox()
        obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))

hidden = 0
for ch in COL:
    for ref in CH[ch]:
        r = fps[ref].Reference()
        if r.IsVisible():
            r.SetVisible(False); hidden += 1
print(f"隐藏这 24 个件的位号 {hidden} 条(装配看坐标文件,不看丝印)")

def marker(x, y, txt, size=0.5):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(txt)
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.12))
    t.SetLayer(FSILK)
    t.SetTextAngleDegrees(0)
    t.thisown = 0
    board.Add(t)

placed = []
def free(bx):
    for o in obst + placed:
        if not (o[2] + 0.12 < bx[0] or bx[2] + 0.12 < o[0] or o[3] + 0.12 < bx[1] or bx[3] + 0.12 < o[1]):
            return False
    return True

n_mark = 0
for ch, cx in COL.items():
    for ref, txt in ((CH[ch][0], "CW"), (CH[ch][2], "WW")):
        lx = mm(fps[ref].GetPosition().x)
        w, h = 0.92 * 0.5 * len(txt) + 0.3, 0.5 + 0.25
        for dy in (1.85, 2.15, 2.45, -1.85, -2.15):
            bx = (lx - w / 2, Y_ROW + dy - h / 2, lx + w / 2, Y_ROW + dy + h / 2)
            if free(bx):
                marker(lx, Y_ROW + dy, txt); placed.append(bx); n_mark += 1
                break
print(f"每颗灯旁印上 CW / WW 共 {n_mark} 条")

# 12 个限流电阻的封装丝印外框也去掉:0603 挨着 0805 只隔 2.1mm,两圈外框必然压在一起
# (DRC 里那几十条 silk_overlap 就是它)。电阻没有极性,外框纯装饰;**灯的外框和极性
# 标记保留**,人工核对灯的方向还要靠它。

# 保险丝的位号原来印在 y129.2–130.5,正好被元件行占了 —— 挪到本路保险丝左侧的列间空隙
for ch, cx in COL.items():
    f = fps[{1: "F2", 2: "F3", 3: "F4", 4: "F5", 5: "F6", 6: "F7"}[ch]]
    f.Reference().SetPosition(VECTOR2I(FromMM(cx - 7.0), FromMM(126.33)))
print("F2–F7 的位号挪到各自保险丝左侧的列间空隙(y=126.33)")


# 端子引脚的 V+ / CW / WW 原来印在 y=131.1,正是现在元件行的位置 —— 挪到端子下方
moved = 0
for d in board.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetLayer() == FSILK and d.GetText() in ("V+", "CW", "WW"):
        q = d.GetPosition()
        if abs(mm(q.y) - 131.1) < 0.5:
            d.SetPosition(VECTOR2I(q.x, FromMM(141.85))); moved += 1
print(f"端子引脚标注 V+/CW/WW {moved} 条挪到端子下方 y=141.85(更贴近接线的那一头)")

# 端子位号原来就在 y≈142 那一带,会跟刚挪下去的 V+/CW/WW 撞;挪到各自端子右侧的列间空隙
for ch, cx in COL.items():
    j = fps[{1: "J3", 2: "J4", 3: "J5", 4: "J6", 5: "J7", 6: "J8"}[ch]]
    j.Reference().SetPosition(VECTOR2I(FromMM(cx + 7.0), FromMM(137.0)))
print("J3–J8 的位号挪到各自端子右侧的列间空隙(y=137.0)")


# 结构改过之后必须重建连通性,否则覆铜填充会踩到已删走线的悬空指针(直接段错误)
board.BuildConnectivity()
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("✅ 已保存")
