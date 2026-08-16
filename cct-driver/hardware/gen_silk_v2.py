#!/usr/bin/env python3
"""v2 丝印功能标注:通道号、端子引脚名、极性、接口电压、板名、操作警示。

必须用 KiCad 自带 python 运行:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_silk_v2.py

**只写板级丝印文字(gr_text),一个铜箔、一个位号都不碰。** 位号归位是
`gen_silk_refdes_fix.py` 的活,两者互不干涉。

**幂等**:每次先把本脚本上次写的板级 F.SilkS 文字全删掉再重写
(靠一个不可见的标记行认领,见 TAG)。

老的 `gen_silk.py` 坐标是 110×145 那块板的,整份对不上 v2,所以另起一份。
文字都用**英文与符号**:出货 Gerber 走 KiCad 的笔画字体,中文在上面既不保证
渲染、也不保证厂家的丝印工艺认得。

跑法(**要排在位号归位之前**,好让位号躲开这些功能标注):
    gen_pcb_v2.py → **gen_silk_v2.py** → gen_silk_refdes_fix.py → gen_route_v2.py
"""
import gc
gc.disable()          # pcbnew 的 SWIG 所有权:不关 GC 会在 SaveBoard 时崩

import sys
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
FSILK = pcbnew.F_SilkS

board = pcbnew.LoadBoard(str(BOARD))
_pro_backup = (HERE / "cct-main.kicad_pro").read_bytes()
_KEEP = []

COL_X = {1: 92.0, 2: 76.0, 3: 60.0, 4: 44.0, 5: 28.0, 6: 12.0}
TERM_Y = 141.20
FUSE_Y = 81.67
LED_Y = 104.78

# 本脚本写的每一条文字都记在这张表里;重跑时按内容清场,所以必须是「本脚本独有」的串。
TEXTS = []


def T(txt, x, y, size=0.8, angle=0.0, mirror=False, bold=False):
    TEXTS.append((txt, x, y, size, angle, bold))


# ---------------------------------------------------------------- 六路输出端子
# 读起来就是「灯 → CW/WW → 端子的 V+ CW WW → CH1..CH6」一路从上往下对得上。
for n, cx in COL_X.items():
    # 端子那两行要落在 MOS 下沿(134.80)与端子体上沿(138.16)之间那 3.36mm 里,
    # 再往下就被插座本体挡住看不见了(渲染图上验过)。
    T(f"CH{n}", cx, 135.4, 1.1, bold=True)
    T("V+", cx - 3.81, 137.5, 0.65)
    T("CW", cx, 137.5, 0.65)
    T("WW", cx + 3.81, 137.5, 0.65)
    # 指示灯:左半边是 CW、右半边是 WW(一列之内左右镜像,见 gen_pcb_v2.py)
    T("CW", cx - 5.52, LED_Y - 1.9, 0.6)
    T("WW", cx + 5.52, LED_Y - 1.9, 0.6)
    # 支路保险丝的规格不逐颗写 —— 逐颗写会跟位号 F2–F7 挤在同一小块地方
    # (渲染图上就是「4A7T」这种糊在一起的样子)。改成在脊椎带里写一行总的。

# ---------------------------------------------------------------- 24V 进线
T("24V IN", 116.0, 132.6, 1.1, bold=True)
T("+", 112.19, 137.6, 0.9)
T("-", 119.81, 137.6, 0.9)
T("F1  ATO 15A", 116.0, 123.2, 0.7)
T("F2-F7  4A T 32V", 26.0, 74.0, 0.9)   # 写在脊椎带里 —— 保险丝座正下方那一条会被座体挡住

# ⚠️ 人类 2026-08-15 确认的操作规矩:带电插拔那颗 24V 端子会拉火花烧触点。
# 写在 J1 正下方的支撑带里 —— 那一片是空板,插拔的时候眼睛正好看得到。
# 长度按板宽收过:原来那句伸出板框外面去了(渲染图上验过)。
T("24V MAX 12A  -  POWER OFF BEFORE UNPLUG J1", 106.0, 152.6, 0.85, bold=True)
T("POWER OFF BEFORE UNPLUG", 45.0, 152.6, 0.9, bold=True)

# ---------------------------------------------------------------- 上板边接口
T("USB-C  PROG", 48.0, 11.0, 0.7)
T("SW1-4 + GND", 76.0, 10.0, 0.7)
T("UART 5V", 94.0, 9.2, 0.7)
T("I2C 3.3V", 112.0, 9.2, 0.7)

# ---------------------------------------------------------------- 测试焊盘
for ref, label in (("TP1", "V24"), ("TP2", "GND"), ("TP3", "5V"), ("TP4", "3V3"),
                   ("TP5", "G1W"), ("TP6", "D1W"), ("TP7", "OFF"), ("TP8", "PG"),
                   ("TP9", "GND")):
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        continue
    p = fp.GetPosition()
    T(label, ToMM(p.x), ToMM(p.y) + 2.1, 0.6)

# ---------------------------------------------------------------- 板名
T("cct-driver  v2", 60.0, 68.0, 1.6, bold=True)
T("6CH CCT LED DRIVER  24V 12A", 60.0, 71.0, 0.9)

# ============================================================================
# 落笔
# ============================================================================
TAG_TEXTS = {t[0] for t in TEXTS}

removed = 0
_old = [d for d in board.GetDrawings()
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == FSILK]
for d in _old:
    if d.GetText() in TAG_TEXTS:
        board.Remove(d)
        removed += 1

for txt, x, y, size, angle, bold in TEXTS:
    t = pcbnew.PCB_TEXT(board)
    _KEEP.append(t)
    t.SetText(txt)
    t.SetLayer(FSILK)
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(size * (0.20 if bold else 0.16)))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    if angle:
        t.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
    board.Add(t)

pcbnew.SaveBoard(str(BOARD), board)
(HERE / "cct-main.kicad_pro").write_bytes(_pro_backup)

print(f"[丝印] 清掉上次的 {removed} 条,写入 {len(TEXTS)} 条板级功能标注")
print("   六路端子:CHn / V+ CW WW / 指示灯 CW·WW")
print("   进线:24V IN MAX 12A / + - / F1 ATO 15A;支路保险丝规格写在脊椎带一行")
print("   ⚠️ 操作警示:「POWER OFF BEFORE UNPLUG J1」写在 J1 正下方的支撑带里,下板边另有一句")
print("   接口:USB-C PROG / SW1-4 + GND / UART 5V / I2C 3.3V;9 个测试焊盘各自标网络")
print("   板名:cct-driver v2 + 一行说明")
sys.exit(0)
