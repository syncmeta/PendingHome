#!/usr/bin/env python3
"""亚克力图纸生成(激光切割 SVG,1:1 mm)。

板框 110×145,安装孔(PCB 坐标):(4,66),(106,80),(4,133),(106,115),M3。
夹板 = 板框四周 +5mm → 120×155,孔位 = PCB 坐标 +(5,5)。

输出:
  acrylic/driver-top.svg      顶板:4×M3 + 顶部接线窗(端子插头与出线穿过)
  acrylic/driver-bottom.svg   底板:4×M3 + 20mm 网格 φ5.5 挂孔 + 2 葫芦孔
  acrylic/backing-board.svg   共用背板 240×380:驱动板区 + 电源腰形槽 + 绕线桩孔 + 挂孔/葫芦孔
  acrylic/winding-discs.svg   绕线桩顶盘 φ30 ×6
切割线统一红色 0.1mm 描边(激光厂商通用约定)。
"""
from pathlib import Path

OUT = Path(__file__).parent / "acrylic"
OUT.mkdir(exist_ok=True)

PCB_HOLES = [(4, 66), (106, 80), (4, 133), (106, 115)]
M3 = 3.2 / 2          # M3 通孔半径
PEG = 5.5 / 2         # 挂钩孔半径(宜家 SKÅDIS 钩 ~φ4.8 / 通用洞洞板钩)

def svg(name, w, h, body):
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" '
            f'viewBox="0 0 {w} {h}">\n'
            f'<g fill="none" stroke="#FF0000" stroke-width="0.1">\n')
    (OUT / name).write_text(head + body + "</g>\n</svg>\n")
    print(f"  {name}  {w}×{h}")

def rect(x, y, w, h, r=0):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}"/>\n'

def circle(cx, cy, r):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"/>\n'

def keyhole(cx, cy, flip=False):
    """葫芦孔:大孔 φ9 圆心在 (cx,cy),槽宽 4.5 延伸 8mm(默认向 -y;flip 向 +y)。
    挂 M4/M5 螺丝头(头径 ≤8.5 可穿大孔,杆 ≤4.2 滑入槽)。单一闭合轮廓。
    倒装(端子朝下)的板:板整体转 180° 安装,槽在板文件坐标里要向 +y(flip=True)。"""
    R, rr = 4.5, 2.25
    import math
    dy = math.sqrt(R*R - rr*rr)
    s = 1 if flip else -1
    y0 = cy + s*dy
    y1 = y0 + s*8
    sweep_slot = 0 if flip else 1
    sweep_big = 0 if flip else 1
    return (f'<path d="M {cx-rr} {y0} L {cx-rr} {y1} '
            f'A {rr} {rr} 0 0 {sweep_slot} {cx+rr} {y1} L {cx+rr} {y0} '
            f'A {R} {R} 0 1 {sweep_big} {cx-rr} {y0} Z"/>\n')

def slot(cx, cy, length, width, vertical=False):
    if vertical:
        return rect(cx - width/2, cy - length/2, width, length, r=width/2)
    return rect(cx - length/2, cy - width/2, length, width, r=width/2)

# ============ 1. 顶板 120×155 ============
b = rect(0.01, 0.01, 119.98, 154.98, r=3)
for (hx, hy) in PCB_HOLES:
    b += circle(hx + 5, hy + 5, M3)
# 顶部接线窗:PCB y2~15 → 板 y7~20;x 覆盖 J1+J3-J8(PCB x3~109 → 板 8~114)
b += rect(8, 7, 106, 13, r=2)
svg("driver-top.svg", 120, 155, b)

# ============ 2. 底板 120×155 ============
b = rect(0.01, 0.01, 119.98, 154.98, r=3)
occupied = []
for (hx, hy) in PCB_HOLES:
    b += circle(hx + 5, hy + 5, M3)
    occupied.append((hx + 5, hy + 5, 6))
# 葫芦孔 ×2:倒装(端子朝下)后位于墙面上部;板坐标 y=137,槽向 +y
for kx in (35, 85):
    b += keyhole(kx, 137, flip=True)
    occupied.append((kx, 141, 9))
# 20mm 网格挂孔(兼容 SKÅDIS 40mm 钩距与通用单点挂钩),边距 ≥10
for gy in range(20, 150, 20):
    for gx in range(20, 110, 20):
        if any((gx-ox)**2 + (gy-oy)**2 < (orad+PEG+2)**2 for (ox, oy, orad) in occupied):
            continue
        b += circle(gx, gy, PEG)
svg("driver-bottom.svg", 120, 155, b)

# ============ 3. 共用背板 240×380(端子朝下版) ============
# 布局自上而下:葫芦孔 → 电源 LRS-350-24 → 驱动板三明治(倒装,端子朝下)→ 绕线区
# 所有线(电源出线、灯带线、下行的传感器线)从底部离开背板。
W, H = 240, 380
b = rect(0.01, 0.01, W-0.02, H-0.02, r=5)
# 顶部葫芦孔 ×3(y=15,x=40/120/200)
for kx in (40, 120, 200):
    b += keyhole(kx, 15)
# 侧缘挂孔列(挂 SKÅDIS/洞洞板用),x=15/225,y 40~360 每 40
for gx in (15, 225):
    for gy in range(40, 370, 40):
        b += circle(gx, gy, PEG)
# —— 电源区(y 35~150):LRS-350-24 底面 215×115,腰形槽 ×4 适配未知孔位 ——
PX, PY = 12.5, 35
for (sx, sy) in [(45, 25), (170, 25), (45, 90), (170, 90)]:
    b += slot(PX + sx, PY + sy, 20, 4.5)
for (cx, cy) in [(PX, PY), (PX+215, PY), (PX, PY+115), (PX+215, PY+115)]:
    dx = 5 if cx == PX else -5
    dy = 5 if cy == PY else -5
    b += f'<path d="M {cx} {cy+dy} L {cx} {cy} L {cx+dx} {cy}"/>\n'
# —— 驱动板区(y 160~315):三明治整体转 180° 安装,孔位取旋转后坐标 ——
DX, DY = 60, 160
for (hx, hy) in PCB_HOLES:
    b += circle(DX + 5 + (110 - hx), DY + 5 + (145 - hy), M3)
# 扎带孔对(φ3.5 ×2):传感器线(接口现朝上)沿两侧下行
for ty in (180, 220, 260, 300):
    for tx in (51, 189):
        b += circle(tx, ty, 1.75) + circle(tx + 6 if tx < 120 else tx - 6, ty, 1.75)
# 驱动板轮廓角标
for (cx, cy) in [(DX, DY), (DX+120, DY), (DX, DY+155), (DX+120, DY+155)]:
    dx = 5 if cx == DX else -5
    dy = 5 if cy == DY else -5
    b += f'<path d="M {cx} {cy+dy} L {cx} {cy} L {cx+dx} {cy}"/>\n'
# —— 绕线区(y 325~372):M3 绕线桩孔 ×6,两排 ——
for (px, py) in [(70, 338), (120, 338), (170, 338), (70, 364), (120, 364), (170, 364)]:
    b += circle(px, py, M3)
svg("backing-board.svg", W, H, b)

# ============ 4. 绕线桩顶盘 φ30 ×6(+2 备用) ============
b = ""
for i in range(8):
    cx = 20 + (i % 4) * 36
    cy = 20 + (i // 4) * 36
    b += circle(cx, cy, 15) + circle(cx, cy, M3)
svg("winding-discs.svg", 150, 76, b)

print("✅ SVG 输出至 acrylic/")
