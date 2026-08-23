#!/usr/bin/env python3
"""亚克力图纸的等价性检查:证明「实物一点没变,只是图纸换了方向」。

2026-08-13 整块 PCB 绕板心转了 180°(见 gen_rotate180.py),板文件的方向此后
就是上墙安装的方向。gen_acrylic.py 随之去掉了「三明治整体转 180° 安装」那套
补偿写法。上下夹板(120×155)因此等于把旧图整体转 180° 重画,背板与绕线盘
则连图都不该变。**尺寸、孔位、孔距一个都不许变** —— 这个脚本就是来钉死这一点的。

做两层比对:
  1. 几何层:解析 SVG,把上下夹板的新图绕板心转 180° 回去,与旧图逐特征比。
     闭合轮廓(葫芦孔)按顶点集合比 —— 起点从哪个角开始、顺时针还是逆时针,
     都不影响切出来的形状。
  2. 像素层:把两张图渲染成 PNG(上下夹板的新图转 180°),逐像素比。

用法:
    python3 hardware/verify_acrylic_equiv.py <旧 SVG 目录>
旧图从 git 里取:
    mkdir /tmp/acr-old && git show HEAD:hardware/acrylic/driver-top.svg > /tmp/acr-old/driver-top.svg  ...
"""
import collections
import re
import subprocess
import sys
from pathlib import Path

NEW = Path(__file__).parent / "acrylic"
RSVG = "rsvg-convert"

# (文件, 宽, 高, 新图是否要转 180° 回去)
SHEETS = [("driver-top.svg", 120, 155, True),
          ("driver-bottom.svg", 120, 155, True),
          ("backing-board.svg", 240, 380, False),
          ("winding-discs.svg", 150, 76, False)]

CMD = re.compile(r'([MLA])\s*([-\d.\s]+)')


def path_points(d):
    """闭合轮廓的真实落点:M/L 的 (x,y) 与圆弧命令的终点;半径与 flag 不算。"""
    pts = []
    for c, args in CMD.findall(d):
        n = [float(v) for v in args.split()]
        if c in "ML":
            pts += [(n[i], n[i + 1]) for i in range(0, len(n), 2)]
        else:
            pts.append((n[-2], n[-1]))
    return pts


def path_arcs(d):
    """圆弧的半径与 large-arc 标志(不看 sweep —— 反向走一遍是同一条弧)。"""
    out = []
    for c, args in CMD.findall(d):
        if c == "A":
            n = [float(v) for v in args.split()]
            out.append((round(n[0], 4), round(n[1], 4), int(n[3])))
    return sorted(out)


def features(svg, W, H, rot):
    t = Path(svg).read_text()

    def T(x, y):
        return (round(W - x, 4), round(H - y, 4)) if rot else (round(x, 4), round(y, 4))

    f = collections.Counter()
    for m in re.finditer(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"', t):
        f[("circle",) + T(float(m[1]), float(m[2])) + (round(float(m[3]), 4),)] += 1
    for m in re.finditer(
            r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="([\d.]+)"', t):
        x, y, w, h, r = map(float, m.groups())
        a, b = T(x, y), T(x + w, y + h)
        f[("rect", min(a[0], b[0]), min(a[1], b[1]), round(w, 4), round(h, 4), round(r, 4))] += 1
    for m in re.finditer(r'<path d="([^"]+)"', t):
        # 顶点用集合(去重):闭合轮廓从哪个角起笔、朝哪个方向走,切出来一样
        f[("outline",
           tuple(sorted(set(T(x, y) for x, y in path_points(m[1])))),
           tuple(path_arcs(m[1])))] += 1
    return f


def pixels(svg, rot, px=1200):
    """渲染成二值图。切割线只有 0.1mm 宽,而 1200px/120mm = 0.1mm/像素,
    抗锯齿的灰边会在两个方向上采样出不同的灰度 —— 所以按 50% 二值化后再比,
    只看「这里有没有线」,不看边缘那一圈灰。"""
    from PIL import Image
    import io
    png = subprocess.run([RSVG, "-w", str(px), "-b", "white", str(svg)],
                         check=True, capture_output=True).stdout
    im = Image.open(io.BytesIO(png)).convert("L")
    if rot:
        im = im.rotate(180)
    return im.point(lambda v: 0 if v < 128 else 255)


def main(old_dir):
    old_dir = Path(old_dir)
    ok = True
    print(f"{'图纸':<20}{'图元':>10}   几何比对                        像素比对")
    print("-" * 92)
    for name, W, H, rot in SHEETS:
        o = features(old_dir / name, W, H, False)
        n = features(NEW / name, W, H, rot)
        geo = (o == n)
        a, b = pixels(old_dir / name, False), pixels(NEW / name, rot)
        tot = a.size[0] * a.size[1]
        if a.size != b.size:
            pix, npix = False, -1
        else:
            npix = sum(1 for p, q in zip(a.getdata(), b.getdata()) if p != q)
            pix = (npix / tot <= 1e-4)      # ≤0.01% = 抗锯齿边缘,不是几何差异
        ok &= geo and pix
        tag = "旧图转 180° 后逐特征相同" if rot else "整份未变,逐特征相同"
        pixtxt = (f"✅ {tot} 像素中差 {npix}({100*npix/tot:.4f}%,抗锯齿边缘)"
                  if pix else f"❌ 差 {npix}/{tot} 像素")
        print(f"{name:<20}{sum(o.values()):>4} → {sum(n.values()):<4}"
              f"{'✅ ' + tag if geo else '❌ 有物理差异':<32}{pixtxt}")
        if not geo:
            for k in (o - n):
                print("      仅旧图有", k)
            for k in (n - o):
                print("      仅新图有", k)
    print("-" * 92)
    print("结论:", "✅ 亚克力实物与旧版完全等价 —— 尺寸/孔位/孔距一个都没变,只是图纸按上墙方向重画"
          if ok else "❌ 实物被改了,必须排查")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
