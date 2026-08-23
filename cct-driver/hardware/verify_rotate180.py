#!/usr/bin/env python3
"""整板转 180° 的安全网:证明除丝印外物理零改动。

用法:
    python3 hardware/verify_rotate180.py <旧 Gerber 目录> <新 Gerber 目录>

把新导出的每一层坐标**旋转回去**再与旧包比对。Gerber/钻孔的坐标系是 KiCad 坐标
的 Y 取负,所以整板绕 (55, 72.5) 转 180° 在出货文件里就是

    x → 110 - x        y → -145 - y

这是个对合变换(自己是自己的逆),对新文件施加一次就该还原成旧文件。
圆弧的 I/J 是相对偏移,180° 旋转下取负。

预期结果:F_Cu / B_Cu / F_Mask / B_Mask / F_Paste / B_Paste / B_Silkscreen /
Edge_Cuts 逐点(且同顺序)完全一致;PTH/NPTH 钻孔在 0.001mm 打印精度内一致 ——
少数落在半微米上的孔,正反两个方向四舍五入会差 1µm,那是打印格式的舍入,
不是几何改动(板级 nm 精度的比对见本文件末尾说明)。F_Silkscreen 不比,
它就是这次要改的东西。
"""
import re
import sys
import os
import collections

W_NM, H_NM = 110_000_000, 145_000_000   # Gerber 4.6 格式:1 单位 = 1e-6 mm
BOARD_W, BOARD_H = 110.0, 145.0

GERBER = ["F_Cu.gtl", "B_Cu.gbl", "F_Mask.gts", "B_Mask.gbs",
          "F_Paste.gtp", "B_Paste.gbp", "B_Silkscreen.gbo", "Edge_Cuts.gm1"]
DRILL = ["PTH.drl", "NPTH.drl"]

GBR_COORD = re.compile(rb'([XYIJ])(-?\d+)')
DRL_COORD = re.compile(rb'([XY])(-?\d+(?:\.\d+)?)')


def strip_stamp(data):
    keep = []
    for line in data.split(b"\n"):
        if (b"CreationDate" in line or b"Created by KiCad" in line
                or line.startswith(b"; DRILL file KiCad")):
            continue
        keep.append(line)
    return b"\n".join(keep)


def unrotate_gerber_text(data):
    """整份 Gerber 旋转回去(只动坐标指令行,不动 % 开头的格式/光圈定义)。"""
    out = []
    for line in data.split(b"\n"):
        if line.startswith(b"%") or line.startswith(b"G04"):
            out.append(line)
            continue

        def sub(m):
            ax, val = m.group(1), int(m.group(2))
            if ax == b'X':
                v = W_NM - val
            elif ax == b'Y':
                v = -H_NM - val
            else:                       # I / J 圆弧相对偏移
                v = -val
            return ax + str(v).encode()
        out.append(GBR_COORD.sub(sub, line))
    return b"\n".join(out)


def coords(data, drill):
    """按出现顺序取出绝对坐标点(展开模态省略)。"""
    pts, x, y = [], None, None
    rx = DRL_COORD if drill else GBR_COORD
    for line in data.split(b"\n"):
        if line[:1] in (b"%", b";") or line.startswith(b"G04"):
            continue
        hit = False
        for m in rx.finditer(line):
            ax = m.group(1)
            v = float(m.group(2)) if drill else int(m.group(2)) / 1e6
            if ax == b'X':
                x, hit = v, True
            elif ax == b'Y':
                y, hit = v, True
        if hit and x is not None and y is not None:
            pts.append((round(x, 6), round(y, 6)))
    return pts


def unrotate(pts):
    return [(round(BOARD_W - a, 6), round(-BOARD_H - b, 6)) for a, b in pts]


def main(old_dir, new_dir):
    ok = True
    print(f"{'层':<20}{'点数':>7}   点集(旋转回去 vs 旧包)")
    print("-" * 70)
    for name in GERBER:
        o = open(os.path.join(old_dir, "cct-main-" + name), "rb").read()
        n = open(os.path.join(new_dir, "cct-main-" + name), "rb").read()
        po, pb = coords(o, False), unrotate(coords(n, False))
        seq = po == pb
        st = collections.Counter(po) == collections.Counter(pb)
        byte_same = strip_stamp(unrotate_gerber_text(n)) == strip_stamp(o)
        if seq and byte_same:
            verdict = "✅ 逐点同序一致,且整份逐字节相同"
        elif st:
            verdict = "✅ 点集一致(顺序/写法有别)"
        else:
            verdict = "❌ 不一致"
            ok = False
        print(f"{name:<20}{len(po):>7}   {verdict}")

    for name in DRILL:
        o = open(os.path.join(old_dir, "cct-main-" + name), "rb").read()
        n = open(os.path.join(new_dir, "cct-main-" + name), "rb").read()
        po, pb = coords(o, True), unrotate(coords(n, True))
        so, sb = sorted(po), sorted(pb)
        exact = collections.Counter(po) & collections.Counter(pb)
        n_exact = sum(exact.values())
        if len(so) != len(sb):
            print(f"{name:<20}{len(po):>7}   ❌ 孔数不同({len(po)} vs {len(pb)})")
            ok = False
            continue
        worst = max((max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(so, sb)),
                    default=0.0)
        if worst <= 0.001 + 1e-9:
            print(f"{name:<20}{len(po):>7}   ✅ 逐孔一致(精确 {n_exact}/{len(po)},"
                  f"其余最大差 {worst*1000:.0f}µm = 钻孔文件 0.001mm 打印精度的舍入)")
        else:
            print(f"{name:<20}{len(po):>7}   ❌ 最大差 {worst:.4f}mm")
            ok = False

    print("-" * 70)
    print("结论:", "✅ 除 F_Silkscreen 外,出货文件物理零改动"
          if ok else "❌ 出现了非丝印改动,必须排查")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
