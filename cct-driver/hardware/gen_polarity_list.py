#!/usr/bin/env python3
"""生成《有极性件核对清单》→ `docs/polarity-check.md`。

**为什么要有它。** 下单页的贴片预览图写着「图片正在渲染中，订单支付后会有完整图片」
—— 也就是**付款前根本看不到**。原来计划的「在嘉立创预览里逐个核极性方向」这一步
落空了。所以改由我们自己出一份清单:数据全部从**板文件 + 出货用的 cpl-jlc.csv**
现取,人类拿着它对渲染图、或者收板后对实物,都不依赖对方那张图。

从板子重新生成:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_polarity_list.py
"""
import csv
import gc
import io
from pathlib import Path

gc.disable()
import pcbnew

HERE = Path(__file__).parent
OUT = HERE.parent / "docs" / "polarity-check.md"
board = pcbnew.LoadBoard(str(HERE / "cct-main.kicad_pcb"))
mm = pcbnew.ToMM

cpl = {r["Designator"]: (r["Mid X"], r["Mid Y"], r["Rotation"])
       for r in csv.DictReader(io.StringIO((HERE / "cpl-jlc.csv").read_text()))}
fps = {f.GetReference(): f for f in board.GetFootprints()}

GROUPS = [
    ("续流二极管 SS36B(阴极接本路 V+)", [f"D{i}" for i in (5, 6, 9, 10, 13, 14, 17, 18, 21, 22, 25, 26)],
     "装反的后果最重:正常工作时会直接把灯带短路。**这 12 颗务必逐个核。**"),
    ("TVS SMBJ26A(阴极接漏极、阳极接 GND)", [f"D{i}" for i in (7, 8, 11, 12, 15, 16, 19, 20, 23, 24, 27, 28)],
     "装反相当于把漏极对地接了个正向二极管,一通电就短。"),
    ("其余二极管与稳压管", ["D1", "D2", "D3", "D4", "DZ1"], "D2 是 buck 的续流管,装反 buck 不起振。"),
    ("铝电解 8mm(+ 接本路 V+)", ["C1", "C2", "C3", "C4", "C5", "C16", "C18", "C20", "C22", "C24", "C26", "C35"],
     "装反会鼓包甚至爆浆。板上外框有**缺角**、本体两侧印 `+` / `−`,肉眼可辨。"),
    ("通道指示灯(阳极接本路 V+)", [f"LED{i}" for i in range(2, 14)],
     "装反只是不亮,不影响别的。每颗灯下方印着 `CW` / `WW`。"),
    ("状态灯", ["LED1"], "ESP32 状态灯,装反只是不亮。"),
    ("IC 一脚", ["U1", "U2", "U3", "U4", "U5", "U6", "U7"], "U2(buck)装反=5V/3.3V 全没;U4 是 ESP32 模组。"),
    ("功率 MOS", ["Q1", "Q2"] + [f"Q{i}" for i in range(7, 19)], "TO-252,三个脚不对称,装反基本装不进去。"),
    ("小信号三极管 / USB 座", ["Q3", "Q4", "Q5", "Q6", "J2"], "J2 是 USB-C,有两个塑胶定位柱(已改 NPTH)定位。"),
]


def pin1(ref):
    fp = fps[ref]
    c = fp.GetPosition()
    for p in fp.Pads():
        if p.GetNumber() in ("1", "A", "K"):
            q = p.GetPosition()
            dx, dy = mm(q.x) - mm(c.x), mm(q.y) - mm(c.y)
            d = ("左" if dx < -0.05 else "右" if dx > 0.05 else "") + \
                ("上" if dy < -0.05 else "下" if dy > 0.05 else "")
            return p.GetNumber(), (d or "中心")
    return "—", "—"


L = ["# 有极性件核对清单",
     "",
     "> 本文由 `hardware/gen_polarity_list.py` 从**板文件 + 出货用的 `cpl-jlc.csv`** 直接生成,",
     "> 改板后重跑即可。**坐标系与实操单一致:元件面朝上、接线端子那条边朝下**",
     "> (也就是挂墙姿态),原点左上角。",
     "",
     "**为什么需要它**:嘉立创下单页那张贴片预览图**付款后才渲染得出来**,付款前看不到。",
     "所以极性不能指望在对方的预览里核 —— 用这份清单对 `hardware/render-top.png`,",
     "或者收板之后对实物,两种用法都行。",
     "",
     "**怎么用**:`CPL 角度`是贴片机实际会用的旋转角;`1 脚/阳极位置`是按这个角度摆好之后,",
     "该脚落在元件本体的哪一侧。两者对上,方向就是对的。",
     ""]

for title, refs, note in GROUPS:
    L += [f"## {title}", "", note, "",
          "| 位号 | CPL 坐标 (mm) | CPL 角度 | 1 脚/阳极位置 |", "|---|---|---|---|"]
    for r in refs:
        if r not in fps:
            continue
        n, d = pin1(r)
        x, y, a = cpl.get(r, ("—", "—", "—"))
        L.append(f"| {r} | {x}, {y} | {a}° | {n} 脚在**{d}** |")
    L.append("")

L += ["## 一眼可查的规律", "",
      "- **同一排的件方向必须一致** —— 12 颗续流管、12 颗 TVS、12 颗电解各自成排,",
      "  排里有一颗方向不一样,那颗几乎肯定是错的。这比逐个查坐标快得多。",
      "- 电解看**缺角**与本体两侧的 `+` / `−`;二极管看**色环/丝印端**;",
      "  IC 看**一脚圆点**;指示灯看外框那个小三角。",
      "- ⚠️ 上电前只做目视;真要通电验证,按 `docs/bring-up-checklist.md` 的顺序走。",
      ""]

OUT.write_text("\n".join(L), encoding="utf-8")
n = sum(1 for _, refs, _ in GROUPS for r in refs if r in fps)
print(f"✅ 已生成 {OUT.relative_to(HERE.parent)},共 {n} 个有极性件")
