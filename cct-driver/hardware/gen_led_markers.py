#!/usr/bin/env python3
"""给 12 颗通道指示灯逐个补上 CW / WW 丝印标注(幂等)。

`gen_led_silk.py` 那一遍的避障搜索太保守,12 个只放下 7 个。这里把候选位放宽
(上下各三档、左右各让 0.6/1.2mm),并且**逐个检查哪盏灯还缺**,只补缺的 ——
所以可以反复跑,不会重复堆字。

标注放在灯的正下方(灯与端子之间那 2.7mm 里),读起来就是:
    灯 → CW/WW → 端子的 V+ / CW / WW → CH1–CH6
一路从上往下对得上。

用法:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_led_markers.py
    ... --check   只报告还缺几个,不写盘
"""
import gc
import sys

gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM

BOARD = "cct-main.kicad_pcb"
CHECK_ONLY = "--check" in sys.argv
board = pcbnew.LoadBoard(BOARD)
mm = pcbnew.ToMM
FSILK = pcbnew.F_SilkS

CH = {1: ("LED2", "LED3"), 2: ("LED4", "LED5"), 3: ("LED6", "LED7"),
      4: ("LED8", "LED9"), 5: ("LED10", "LED11"), 6: ("LED12", "LED13")}
SIZE, THICK = 0.5, 0.12

fps = {f.GetReference(): f for f in board.GetFootprints()}

# ---- 障碍:焊盘 + 所有 F.SilkS 图元与位号 + 过孔 ----
obst, vias = [], []
for fp in board.GetFootprints():
    for p in fp.Pads():
        bb = p.GetBoundingBox()
        obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    for g in fp.GraphicalItems():
        if g.GetLayer() == FSILK:
            bb = g.GetBoundingBox()
            obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    r = fp.Reference()
    if r.IsVisible() and r.GetLayer() == FSILK:
        bb = r.GetBoundingBox()
        obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
for t in board.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        q = t.GetPosition()
        vias.append((mm(q.x), mm(q.y), mm(t.GetWidth()) / 2))

existing = []
for d in board.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetLayer() == FSILK:
        bb = d.GetBoundingBox()
        obst.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
        if d.GetText() in ("CW", "WW"):
            q = d.GetPosition()
            existing.append((d.GetText(), mm(q.x), mm(q.y)))


def free(bx):
    for o in obst:
        if not (o[2] + 0.12 < bx[0] or bx[2] + 0.12 < o[0] or o[3] + 0.12 < bx[1] or bx[3] + 0.12 < o[1]):
            return False
    for (vx, vy, vr) in vias:
        if bx[0] - vr - 0.15 < vx < bx[2] + vr + 0.15 and bx[1] - vr - 0.15 < vy < bx[3] + vr + 0.15:
            return False
    return True


missing, done = [], 0
for ch, (led_cw, led_ww) in CH.items():
    for ref, txt in ((led_cw, "CW"), (led_ww, "WW")):
        lx = mm(fps[ref].GetPosition().x)
        ly = mm(fps[ref].GetPosition().y)
        if any(t == txt and abs(x - lx) < 1.5 and abs(y - ly) < 4.0 for t, x, y in existing):
            continue
        w, h = 0.92 * SIZE * len(txt) + 0.3, SIZE + 0.25
        spot = None
        for dy in (1.85, 2.15, 2.45, 2.75, -1.85, -2.15):
            for dx in (0.0, 0.6, -0.6, 1.2, -1.2, 1.8, -1.8, 2.4):
                bx = (lx + dx - w / 2, ly + dy - h / 2, lx + dx + w / 2, ly + dy + h / 2)
                if free(bx):
                    spot = (lx + dx, ly + dy, bx)
                    break
            if spot:
                break
        if not spot:
            missing.append((ch, txt, ref))
            continue
        if not CHECK_ONLY:
            t = pcbnew.PCB_TEXT(board)
            t.SetText(txt)
            t.SetPosition(VECTOR2I(FromMM(spot[0]), FromMM(spot[1])))
            t.SetTextSize(VECTOR2I(FromMM(SIZE), FromMM(SIZE)))
            t.SetTextThickness(FromMM(THICK))
            t.SetLayer(FSILK)
            t.thisown = 0
            board.Add(t)
        obst.append(spot[2])
        done += 1
        print(f"  CH{ch} {txt}({ref}) → 补在 ({spot[0]:.2f}, {spot[1]:.2f})")

print(f"本次补 {done} 个;仍放不下 {len(missing)} 个" + (f" → {missing}" if missing else ""))
if CHECK_ONLY:
    print("(--check:没有写盘)")
    raise SystemExit(1 if (done or missing) else 0)
if done:
    pcbnew.SaveBoard(BOARD, board)
    print("✅ 已保存")
else:
    print("✅ 12 个标注都在,无需补")
