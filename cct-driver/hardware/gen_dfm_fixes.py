#!/usr/bin/env python3
"""两处焊盘定义修正(2026-08-13,来自 Codex 对出货 Gerber 的审查)。

幂等:重复运行结果一致。运行:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_dfm_fixes.py

──────────────────────────────────────────────────────────────────────────
§1  U2(TPS54360B)散热焊盘下的 4 个热过孔
──────────────────────────────────────────────────────────────────────────
改之前:4 个**无编号、无网络**的 thru-hole 焊盘(0.61mm 盘 / 0.3mm 钻),
层写成 F.Cu + B.Cu + F.Mask + B.Mask + F.Paste + B.Paste。三个后果:

  1. **底面锡膏层里出现 4 个 0.61mm 开口** —— 而本板下单方式是「只贴顶层」,
     `B_Paste.gbp` 全层就只有这 4 个开口,自相矛盾,会被 PCBA 端误判成双面工艺。
  2. **无网络** → 上下两层的 GND 覆铜都会**避开**它们(覆铜只连同网络的东西)。
     顶面它们恰好落在 U2.9(EP,GND)那块 2.0×2.0 铜里,靠图形重叠算是连上了;
     **底面则是四个孤立铜岛,根本没接到底层 GND 大平面** —— 「热过孔」名不副实。
  3. 底面阻焊也开了窗 → 回流时顶面 EP 的锡可以顺着孔一路漏到底面。

改之后:编号并入 EP(pad 9)、接 GND、从 F.Paste/B.Paste/B.Mask 全部移除。
  · 接 GND:上下层覆铜都会连上,才真正成为热过孔兼 buck 回流的缝合孔
    (U2 的 EP 同时是芯片 GND,10mm 内原来只有 1 个 0.3mm GND 过孔在 1.74mm 外)。
  · 去掉 B.Mask = **底面盖油**。这也是抑制吃锡的主要机制:底面一封,孔就成了
    盲孔、里面的空气排不出去,锡只能进去一部分,不会像通孔那样被抽干。
  · 去掉两面锡膏:过孔上本来就不该印锡膏;顺带让 `B_Paste.gbp` 变成空层。

顶面 EP 锡膏收缩到 **64%** 覆盖率(2.0×2.0 → 1.6×1.6,solder paste margin −0.2mm):
TI PowerPAD 应用手册(SLMA002)对带过孔的散热焊盘给的区间是 50–80%;取 64% 兼顾
散热与「锡量别多到把芯片浮起来/挤出焊盘」。按嘉立创 0.12mm 钢网算,实心开窗的锡量
是 0.48mm³,4 个孔的孔腔合计 0.45mm³ —— 这就是为什么必须靠底面盖油把它变成盲孔,
单靠减锡膏压不住。

──────────────────────────────────────────────────────────────────────────
§2  J2(USB-C)那两个 0.6mm 外壳定位孔
──────────────────────────────────────────────────────────────────────────
改之前:PTH(金属化),盘径 = 钻径 = 0.6mm → **环宽 0**。DRC 报 2 条
`annular_width` error + 2 条 `padstack` warning。它们是 USB-C 座的塑胶定位柱,
无网络、不导电,镀铜只会让孔径变小、影响装配公差。
改之后:属性改成 NPTH(非金属化),盘径仍 = 钻径。改完那 4 条 DRC 应当消失,
且这两个孔从 `PTH.drl` 移到 `NPTH.drl`。
"""
import gc
gc.disable()
import pcbnew
from pcbnew import FromMM

BOARD = "cct-main.kicad_pcb"
board = pcbnew.LoadBoard(BOARD)
mm = pcbnew.ToMM

EP_PASTE_MARGIN_MM = -0.2      # 2.0×2.0 → 1.6×1.6,覆盖率 64%

gnd = board.FindNet("GND")
assert gnd, "板上找不到 GND 网络"

# ---------- §1 U2 热过孔 ----------
u2 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U2")
# EP 是那个 2.0×2.0 的贴片盘(无钻孔);热过孔重跑后也叫 9,所以要用"无钻孔"区分
ep = next(p for p in u2.Pads() if p.GetNumber() == "9" and p.GetDrillSizeX() == 0)
epb = ep.GetBoundingBox()

keep = pcbnew.LSET()
for lay in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_Mask):
    keep.addLayer(lay)

n_via = 0
for p in u2.Pads():
    # 认它们靠几何,不靠"有没有编号"——这样脚本重跑一次结果一样(幂等)
    if p.GetDrillSizeX() <= 0 or abs(mm(p.GetSize().x) - 0.61) > 1e-6:
        continue
    assert epb.Contains(p.GetPosition()), "钻孔盘不在 EP 范围内,先查清楚再改"
    p.SetNumber("9")                                # 并入 EP,网表上属于 U2 pin 9
    p.SetNet(gnd)
    p.SetLayerSet(keep)                             # 去掉 B.Mask / F.Paste / B.Paste
    n_via += 1
    print(f"  热过孔 ({mm(p.GetPosition().x):.3f},{mm(p.GetPosition().y):.3f}) "
          f"→ 编号 9 / 网络 GND / 层 F.Cu+B.Cu+F.Mask(底面盖油、两面无锡膏)")
assert n_via == 4, f"预期 4 个热过孔,实际找到 {n_via} 个"

ep.SetLocalSolderPasteMargin(FromMM(EP_PASTE_MARGIN_MM))
s = ep.GetSize()
print(f"  EP 锡膏 {mm(s.x):.1f}×{mm(s.y):.1f} → "
      f"{mm(s.x)+2*EP_PASTE_MARGIN_MM:.1f}×{mm(s.y)+2*EP_PASTE_MARGIN_MM:.1f}mm,"
      f"覆盖率 {((mm(s.x)+2*EP_PASTE_MARGIN_MM)*(mm(s.y)+2*EP_PASTE_MARGIN_MM))/(mm(s.x)*mm(s.y))*100:.0f}%")

# ---------- §2 J2 定位孔 ----------
j2 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "J2")
n_npth = 0
for p in j2.Pads():
    if p.GetNumber() or p.GetDrillSizeX() <= 0:
        continue
    assert abs(mm(p.GetSize().x) - mm(p.GetDrillSizeX())) < 1e-6, "盘径不等于钻径,先确认这是定位孔"
    p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    n_npth += 1
    print(f"  定位孔 ({mm(p.GetPosition().x):.3f},{mm(p.GetPosition().y):.3f}) "
          f"Ø{mm(p.GetDrillSizeX()):.1f}mm → NPTH(非金属化)")
assert n_npth == 2, f"预期 2 个定位孔,实际找到 {n_npth} 个"

# ---------- §3 重新填充覆铜 ----------
# 热过孔改接 GND 之后必须重填,否则上下两层的 GND 铜皮还在按"无网络"的老样子避开它们。
# 填充器是确定性的:拿改动前那版板子原地重填,全板铜面积 20612.310 → 20612.306 mm²
# (差 0.004mm²,-0.00002%),所以重填本身不会带来无关改动。
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
print("  覆铜已重新填充(热过孔现在被上下两层 GND 铜皮连上)")

pcbnew.SaveBoard(BOARD, board)
print(f"✅ 已保存:U2 热过孔 {n_via} 个修正 + EP 锡膏收缩,J2 定位孔 {n_npth} 个改 NPTH")
