#!/usr/bin/env python3
"""加宽阻焊桥:给指定焊盘设负的阻焊余量(缩小阻焊开窗)。

嘉立创 DFM 的阻焊桥判据(纯几何,与阻焊颜色无关):
    < 0.10mm  危险
    0.10~0.15mm 警告
    ≥ 0.15mm  良好

本板 DFM 结果:全板只有 J2(USB-C,TYPE-C-31-M-12)不合格,4 处——
  · 2 处 0.10mm(危险):J2 的 4 个大焊盘(0.7×1.4mm 圆角矩形,KiCad 导出
    成 %AMFreePoly 自由多边形)之间。板坐标 y=138.53,
    x=72.80/73.60 一对、x=78.40/79.20 一对;中心距 0.8mm、开窗宽 0.7mm。
  · 2 处 0.15mm(警告):上述大焊盘与相邻 0.3mm 信号焊盘(B5/B8)之间。
其余元件(U1 0.2mm、U6/U7 0.286mm、U4 0.32mm、U2 合并开窗)全在良好区,
不动。

做法:只给 J2 这 4 个大焊盘设负的 local solder mask margin,阻焊开窗每边
内缩,桥两侧各让出一半:
    大焊盘对大焊盘:0.10 + 2×内缩
    大焊盘对信号盘:0.15 + 1×内缩
    内缩 = (目标桥宽 - 0.10) / 2   →   两类同时到达目标桥宽
TARGET=0.20 时内缩 0.05mm/边,开窗 0.7×1.4 → 0.6×1.3,露铜面积少约 20%。
这 4 个是 USB-C 的供电与外壳固定大脚,面积充裕,可接受。

可行范围(同一算法往上推):
  TARGET 0.20 → 内缩 0.05mm/边,露铜 0.6×1.3,-20%   ← 本次采用
  TARGET 0.25 → 内缩 0.075mm/边,露铜 0.55×1.25,-30%
  TARGET 0.30 → 内缩 0.10mm/边,露铜 0.5×1.2,-39%,开始明显吃焊接面积
  TARGET ≥0.35 → 内缩 ≥0.125mm,不建议;应改合并开窗或换封装

一个 KiCad 的坑:负阻焊余量被夹在 -min(焊盘 size)/2。这 4 个是 custom 焊盘,
真实轮廓在 primitives 里,而锚点 size 只有 0.005mm,于是 -0.05 只生效
0.0025mm(实测开窗只缩了 0.0025mm/边)。所以要把锚点 size 一并放大到
4×内缩量——锚点是位于焊盘中心的小圆,完全落在 0.7×1.4 轮廓内部,铜层与钢网
的合并轮廓不变(已逐层比对 F_Cu / F_Paste 完全一致)。

注意:不少板厂 CAM 会对阻焊做统一放大(常见 0.05~0.1mm/边),我们缩多少
不一定等于最终桥宽多少,最终以厂方 DFM 报告为准。改完请重新导出 Gerber
并复量 F_Mask 层。
"""
import gc
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

TARGET = 0.20               # 目标最小阻焊桥宽度 mm
BASE = 0.10                 # J2 大焊盘之间的原始桥宽 mm
SHRINK = (TARGET - BASE) / 2    # 每边内缩 mm
PADS = {"J2": ["A1B12", "A4B9", "B1A12", "B4A9"]}   # 只动 USB-C 这 4 个大焊盘

assert SHRINK > 0, "目标桥宽必须大于原始桥宽"
assert SHRINK <= 0.125, f"内缩 {SHRINK:.3f}mm 过大,应改合并开窗或换封装"

board = pcbnew.LoadBoard("cct-main.kicad_pcb")
mm = pcbnew.ToMM

n = 0
for fp in board.GetFootprints():
    want = PADS.get(fp.GetReference())
    if not want:
        continue
    for p in fp.Pads():
        if p.GetNumber() not in want:
            continue
        sz = p.GetSize()
        w, h = mm(sz.x), mm(sz.y)
        if p.GetShape() == pcbnew.PAD_SHAPE_CUSTOM:      # 圆角焊盘:实际尺寸看 primitive
            bb = p.GetBoundingBox()
            w, h = mm(bb.GetRight() - bb.GetLeft()), mm(bb.GetBottom() - bb.GetTop())
            # 解除 -min(size)/2 的夹取:锚点放大到 4×内缩量,仍远在轮廓内部
            anchor = 4 * SHRINK
            assert anchor < min(w, h) - 2 * SHRINK, "锚点放大后会顶出焊盘轮廓"
            p.SetSize(VECTOR2I(FromMM(anchor), FromMM(anchor)))
        p.SetLocalSolderMaskMargin(FromMM(-SHRINK))
        n += 1
        keep = (w - 2 * SHRINK) * (h - 2 * SHRINK) / (w * h)
        print(f"  {fp.GetReference()}.{p.GetNumber()}  开窗 {w:.2f}×{h:.2f} → "
              f"{w - 2 * SHRINK:.2f}×{h - 2 * SHRINK:.2f}mm,露铜剩 {keep * 100:.0f}%")

assert n == sum(len(v) for v in PADS.values()), f"只改到 {n} 个焊盘,与预期不符"
print(f"目标桥宽 {TARGET}mm,每边内缩 {SHRINK}mm,共 {n} 个焊盘")

pcbnew.SaveBoard("cct-main.kicad_pcb", board)
print("✅ 已保存")
