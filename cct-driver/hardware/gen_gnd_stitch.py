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

    added, stranded = 0, []
    _keep = []
    for lay, idx, o, area in isl:
        if o is main[lay]:
            continue
        has = any(o[0].Contains(VECTOR2I(FromMM(vx), FromMM(vy)), o[1])
                  for vx, vy in vias)
        if has:
            continue
        if area < MIN_AREA:
            stranded.append((board.GetLayerName(lay), idx, area, "面积过小"))
            continue
        others = [m for l2, ms in planes.items() if l2 != lay for m in ms]
        p = spot(o, others, MARGIN) or spot(o, others, MARGIN_TIGHT)
        if p is None:
            stranded.append((board.GetLayerName(lay), idx, area, "岛内放不下过孔"))
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

print(f"\n[地岛缝合] 共补 {total} 颗过孔")
if stranded:
    print(f"缝不上的 {len(stranded)} 块碎铜(逐块列名,不糊):")
    for lay, idx, area, why in stranded:
        print(f"  · {lay} 第 {idx} 块 {area:.2f}mm² —— {why}")
sys.exit(0)
