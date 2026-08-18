#!/usr/bin/env python3
"""按**实际填出来的铜**给地岛补缝合过孔。

必须用 KiCad 自带 python 运行:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_gnd_stitch.py

## 为什么要单独一步

`gen_route_v2.py` 里的缝合是**按 5mm 网格盲缝**的 —— 它不知道铜最后会填成什么样。
逻辑区那一片顶层地被横向车道带(接口 10 根 + PWM 12 根)切成一条条,车道之间
剩下的碎铜块正好落在网格的缝里,一颗过孔都没缝到,于是 DRC 报「地岛与地岛不连通」。

这一步在**填完铜之后**跑:读真实的填充多边形,逐块找出「一颗地过孔都没有」的孤岛,
在岛里找一个真放得下过孔的位置补一颗,然后重填、再看一遍。是**收敛式**的,不是打补丁 ——
判据(岛里有没有过孔)和落点(岛内能放下过孔的地方)都是从板子上量出来的,
换个摆位重跑一遍照样成立。

放不下过孔的碎铜(比车道间距还窄的那种)会逐块列出来:它们要么本来就该被
「移除孤岛」吃掉,要么说明那一块的车道排得太密,该回去改车道 —— 不在这里糊。

跑法(排在布线之后):
    gen_route_v2.py → **gen_gnd_stitch.py**
"""
import gc
gc.disable()

import subprocess
import sys
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

from pcb_connectivity import collect, components

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

STITCH_D, STITCH_DRILL = 0.5, 0.3
# 填出来的多边形**已经**按间距从异网铜那里缩过一圈了,所以过孔只要整个落在岛里就合法。
# 先按「半径 + 0.3 余量」找宽敞的落点,找不到再退到「够放下过孔本身」。
MARGIN = STITCH_D / 2 + 0.30
MARGIN_TIGHT = STITCH_D / 2 + 0.05
MIN_AREA = 1.0                    # 比这还小的碎铜不值得缝,单独列出来
STEP = 0.25                       # 岛内找落点的扫描步长
PASSES = 4


def fill_and_refresh():
    """用命令行填铜(pcbnew 的 ZONE_FILLER 在无头环境里会直接崩)。"""
    r = subprocess.run([CLI, "pcb", "drc", "--refill-zones", "--save-board",
                        "--severity-error", "-o", "/dev/null", str(BOARD)],
                       capture_output=True, text=True)
    if r.returncode not in (0, 5):
        sys.exit(f"填铜失败:\n{r.stdout}\n{r.stderr}")


def islands(board):
    """→ [(层, 序号, 多边形, 面积mm²)],按面积从大到小。"""
    out = []
    for z in board.Zones():
        if z.GetNetname() != "GND" or z.GetIsRuleArea():
            continue
        for lay in z.GetLayerSet().Seq():
            polys = z.GetFilledPolysList(lay)
            for i in range(polys.OutlineCount()):
                out.append((lay, i, (polys, i), ToMM(ToMM(polys.Outline(i).Area()))))
    out.sort(key=lambda t: -t[3])
    return out


def fits(island, x, y, margin):
    """(x,y) 为心、半径 margin 的圆是否整个落在这一块填充铜里(**算上挖空**)。"""
    polys, idx = island
    def inside(px, py):
        return polys.Contains(VECTOR2I(FromMM(px), FromMM(py)), idx)
    if not inside(x, y):
        return False
    for dx, dy in ((margin, 0), (-margin, 0), (0, margin), (0, -margin),
                   (margin * .71, margin * .71), (-margin * .71, margin * .71),
                   (margin * .71, -margin * .71), (-margin * .71, -margin * .71)):
        if not inside(x + dx, y + dy):
            return False
    return True


def spot(island, targets, margin):
    """在这个岛里找一个既放得下过孔、对面层也接得住的落点。"""
    bb = island[0].Outline(island[1]).BBox()
    x0, y0 = ToMM(bb.GetLeft()), ToMM(bb.GetTop())
    x1, y1 = ToMM(bb.GetRight()), ToMM(bb.GetBottom())
    best = None
    y = y0 + STEP
    while y < y1:
        x = x0 + STEP
        while x < x1:
            if fits(island, x, y, margin) and any(fits(t, x, y, margin) for t in targets):
                # 越靠岛中间越稳妥 —— 用到 bbox 四边的最小距离当分数
                s = min(x - x0, x1 - x, y - y0, y1 - y)
                if best is None or s > best[0]:
                    best = (s, x, y)
            x += STEP
        y += STEP
    return best[1:] if best else None


total, stranded = 0, []
for _pass in range(PASSES):
    board = pcbnew.LoadBoard(str(BOARD))
    _pro = (HERE / "cct-main.kicad_pro").read_bytes()
    isl = islands(board)
    # 「主铜」= 每层最大的那一块,只用来判断谁不是孤岛。
    # ⚠️ 补过孔的落点**不能只认这一块**:本板的地是有意切成逻辑地 / 功率地两片的
    #(只在 RS1 旁边那一段颈上汇合),所以底层在逻辑区那一片是另一块独立多边形,
    # 面积第二大。只认最大那块的话,逻辑区的碎铜永远找不到落脚点。
    # 判据改成:落点要落进**对面层任意一块像样的铜**(≥50mm²)里。
    main, planes = {}, {}
    for lay, _i, o, a in isl:
        main.setdefault(lay, o)
        if a >= 50.0:
            planes.setdefault(lay, []).append(o)
    vias = [(ToMM(v.GetPosition().x), ToMM(v.GetPosition().y))
            for v in board.Tracks()
            if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"]

    # 先清掉**悬空的缝合过孔**:盲缝的网格不知道哪里最后会填出铜,
    # 落在 V24 那几片覆铜底下的过孔两层都够不着地,DRC 直接报悬空。
    # 判据是「两层的地铜都不含它」,从填充结果上量出来的,不是拍的。
    killed = 0
    for v in list(board.Tracks()):
        if v.Type() != pcbnew.PCB_VIA_T or v.GetNetname() != "GND":
            continue
        if ToMM(v.GetWidth()) > STITCH_D + 0.01:      # 只动缝合过孔,不动信号过孔
            continue
        pt = v.GetPosition()
        if not any(o[0].Contains(pt, o[1]) for _l, _i, o, _a in isl):
            board.Remove(v)
            killed += 1
    if killed:
        print(f"  − 清掉 {killed} 颗悬空的缝合过孔(两层地铜都够不着)")
        pcbnew.SaveBoard(str(BOARD), board)
        (HERE / "cct-main.kicad_pro").write_bytes(_pro)
        fill_and_refresh()
        (HERE / "cct-main.kicad_pro").write_bytes(_pro)
        board = pcbnew.LoadBoard(str(BOARD))
        isl = islands(board)
        main, planes = {}, {}
        for lay, _i, o, a in isl:
            main.setdefault(lay, o)
            if a >= 50.0:
                planes.setdefault(lay, []).append(o)
        vias = [(ToMM(v.GetPosition().x), ToMM(v.GetPosition().y))
                for v in board.Tracks()
                if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"]

    # 岛里有没有夹着焊盘 —— **夹着焊盘的岛不许按面积跳过**。
    # MIN_AREA 原来是无差别的:小于 1mm² 一律记一句「面积过小」了事。
    # 实测这条把两只真焊盘扔在外面(C11 的地脚 0.83mm²、SW2 的地脚 0.98mm²),
    # 而那两块其实**放得下一颗 0.5mm 的缝合过孔**,只是面积数字不好看。
    # 判据改成:**岛里夹着焊盘 → 无论多小都要试**,试不下再逐块列名;
    # 面积门槛只用来放过那些一只脚都不沾的纯碎铜(那种缝不缝无所谓)。
    gnd_pads = [(ToMM(p.GetPosition().x), ToMM(p.GetPosition().y))
                for fp in board.GetFootprints() for p in fp.Pads()
                if p.GetNetname() == "GND"]

    added, stranded = 0, []
    _keep = []
    for lay, idx, o, area in isl:
        if o is main[lay]:
            continue
        has = any(o[0].Contains(VECTOR2I(FromMM(vx), FromMM(vy)), o[1])
                  for vx, vy in vias)
        if has:
            continue
        holds_pad = any(o[0].Contains(VECTOR2I(FromMM(px), FromMM(py)), o[1])
                        for px, py in gnd_pads)
        if area < MIN_AREA and not holds_pad:
            stranded.append((board.GetLayerName(lay), idx, area, "面积过小,且没夹着焊盘"))
            continue
        others = [m for l2, ms in planes.items() if l2 != lay for m in ms]
        p = spot(o, others, MARGIN) or spot(o, others, MARGIN_TIGHT)
        if p is None:
            stranded.append((board.GetLayerName(lay), idx, area,
                             "岛内放不下过孔" + ("(⚠️ 里面夹着焊盘)" if holds_pad else "")))
            continue
        v = pcbnew.PCB_VIA(board)
        _keep.append(v)
        v.SetPosition(VECTOR2I(FromMM(p[0]), FromMM(p[1])))
        v.SetWidth(FromMM(STITCH_D))
        v.SetDrill(FromMM(STITCH_DRILL))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(board.GetNetsByName()["GND"].GetNetCode())
        board.Add(v)
        added += 1
        print(f"  + {board.GetLayerName(lay)} 第 {idx} 块({area:.1f}mm²)"
              f" 补一颗过孔 @({p[0]:.2f}, {p[1]:.2f})")

    print(f"[第 {_pass + 1} 轮] 地岛 {len(isl)} 块,补 {added} 颗,"
          f"缝不上 {len(stranded)} 块")
    total += added
    if not added:
        break
    pcbnew.SaveBoard(str(BOARD), board)
    (HERE / "cct-main.kicad_pro").write_bytes(_pro)
    fill_and_refresh()
    (HERE / "cct-main.kicad_pro").write_bytes(_pro)


# ============================================================================
# 第二趟:**按连通性并块**,不是按「这块岛上有没有过孔」
# ============================================================================
# 上面那一趟的判据是「岛里一颗地过孔都没有 → 补一颗」。它漏掉一整类:
# **岛上明明有过孔,过孔对面接住的却是另一块同样孤立的铜。** 本板实测栽在这儿 ——
# buck 那七颗去耦(C32–C37)加 R62 的地脚,连着 6 颗过孔和一块 212mm² 的底层铜,
# 自成一个封闭的小世界,和主地平面一点关系没有。R62 是振荡电阻,它的地一浮,
# buck 就没有基准 —— 和当初 EN 悬空一样是「整板起不来」级别,而第一趟一声不吭。
#
# 所以这一趟换判据:**先算出真实的连通块**(焊盘/走线/过孔/每一片填充岛,
# 见 pcb_connectivity.py),把最大的那块当主体,然后逐个孤立块去找一个落点 ——
# 落点要同时落在「这个孤立块某一层的铜」和「主体在另一层的铜」里,
# 一颗过孔就把两边并起来。找不到落点的**逐块列名并列出里面困着哪几只焊盘**,
# 不在这儿糊:那说明得回布线那一步给它拉一根线。
MERGE_PASSES = 4


def _fits_poly(sps, x, y, margin):
    """(x,y) 为心、半径 margin 的圆是否整个落在这块填充铜里(算上挖空)。

    ⚠️ x/y 是**内部单位(nm)**,margin 是毫米 —— 填充多边形的坐标是 nm,
    这里混过一次单位:传毫米进来的话 Contains() 全落在原点附近,一个落点都找不到,
    而报出来的是「和主体在两层上都没有重叠」,看着像几何结论,其实是单位错了。
    """
    for dx, dy in ((0, 0), (margin, 0), (-margin, 0), (0, margin), (0, -margin),
                   (margin * .71, margin * .71), (-margin * .71, margin * .71),
                   (margin * .71, -margin * .71), (-margin * .71, -margin * .71)):
        if not sps.Contains(VECTOR2I(int(x + dx * IU), int(y + dy * IU))):
            return False
    return True


IU = 1e6
merged, unmergeable = 0, []
for _pass in range(MERGE_PASSES):
    board = pcbnew.LoadBoard(str(BOARD))
    _pro = (HERE / "cct-main.kicad_pro").read_bytes()
    items = collect(board, "GND")["GND"]
    comps, _adj = components(items)
    comps.sort(key=len, reverse=True)
    if len(comps) == 1:
        print(f"[并块] 第 {_pass + 1} 轮:地已经是一整块,不用并")
        break
    main_zone = {}
    for i in comps[0]:
        if items[i].kind == "zone":
            lay = next(iter(items[i].layers))
            main_zone.setdefault(lay, []).append(items[i].shapes[lay])

    added, unmergeable = 0, []
    for c in comps[1:]:
        zs = [items[i] for i in c if items[i].kind == "zone"]
        pads = [items[i].label for i in c if items[i].kind == "pad"]
        hit = None
        for z in sorted(zs, key=lambda z: -z.shapes[next(iter(z.layers))].Area()):
            lay = next(iter(z.layers))
            targets = [t for l2, ts in main_zone.items() if l2 != lay for t in ts]
            if not targets:
                continue
            sps, bb = z.shapes[lay], z.bbox
            y = bb[1]
            while y <= bb[3] and hit is None:
                x = bb[0]
                while x <= bb[2]:
                    if (_fits_poly(sps, x, y, MARGIN)
                            and any(_fits_poly(t, x, y, MARGIN) for t in targets)):
                        hit = (x / IU, y / IU)
                        break
                    x += FromMM(STEP)
                y += FromMM(STEP)
            if hit:
                break
        if hit is None:
            unmergeable.append((len(c), pads,
                                [z.label for z in zs]))
            continue
        v = pcbnew.PCB_VIA(board)
        _keep.append(v)
        v.SetPosition(VECTOR2I(FromMM(hit[0]), FromMM(hit[1])))
        v.SetWidth(FromMM(STITCH_D))
        v.SetDrill(FromMM(STITCH_DRILL))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(board.GetNetsByName()["GND"].GetNetCode())
        board.Add(v)
        added += 1
        who = ("、".join(pads[:3]) + ("…" if len(pads) > 3 else "")) or "(无焊盘)"
        print(f"  + 孤立块({who})并入主体:过孔 @({hit[0]:.2f}, {hit[1]:.2f})")

    print(f"[并块] 第 {_pass + 1} 轮:地分成 {len(comps)} 块,"
          f"并掉 {added} 块,并不上 {len(unmergeable)} 块")
    if not added:
        break
    merged += added
    pcbnew.SaveBoard(str(BOARD), board)
    (HERE / "cct-main.kicad_pro").write_bytes(_pro)
    fill_and_refresh()
    (HERE / "cct-main.kicad_pro").write_bytes(_pro)

print(f"\n[地岛缝合] 第一趟补 {total} 颗过孔;第二趟按连通性并掉 {merged} 块孤立地")
if stranded:
    print(f"第一趟缝不上的 {len(stranded)} 块碎铜(逐块列名,不糊):")
    for lay, idx, area, why in stranded:
        print(f"  · {lay} 第 {idx} 块 {area:.2f}mm² —— {why}")
if unmergeable:
    print(f"⚠️ 第二趟并不上的 {len(unmergeable)} 块 —— 和主体在两层上都没有重叠,"
          f"一颗过孔解决不了,得回 gen_route_v2.py 给它拉一根线:")
    for _n, pads, zlabels in unmergeable:
        print(f"  · 困住 {len(pads)} 只焊盘:{'、'.join(pads) or '(无)'}")
        for zl in zlabels:
            print(f"      {zl}")
sys.exit(0)
