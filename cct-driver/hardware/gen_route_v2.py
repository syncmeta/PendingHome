#!/usr/bin/env python3
"""v2 布线 + 覆铜:按 `floorplan-v2.md` 的车道 / 分区规划走线。

必须用 KiCad 自带 python 运行:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_route_v2.py

**跑法(顺序不能乱)**:
    KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
    $KP gen_pcb_v2.py            # 摆位(从空板重建)
    $KP gen_silk_refdes_fix.py   # 位号避障(只动丝印)
    $KP gen_route_v2.py          # 本脚本:布线 + 覆铜

**幂等**:每次先把板上所有走线 / 过孔 / 覆铜(以及本脚本自己下的规则区)删干净,
再从头按规划重铺。整条流水线跑两遍,板文件的**内容完全一致** —— 实测:
把 uuid 与覆铜填充多边形(那是 kicad-cli 现算的)归一化之后,两次的行集合逐条相同,
差别只在文件里的**排列顺序**(pcbnew 内部 Add/Remove 之后的存储次序),不影响板子。

⛔ 不用自动布线器,也不再有 `gen_route_repair*.py` 那种「一轮轮打补丁」。
   布不通就报出来,不靠补丁堆。

──────────────────────────────────────────────────────────────────────────────
层分配 —— 这是整份规划的骨架,读代码前先读这段
──────────────────────────────────────────────────────────────────────────────
                      F.Cu(顶层)                     B.Cu(底层)
逻辑区 y 0–63.5       信号 + GND 覆铜                  信号 + GND 覆铜
脊椎带 y 65–77        V24_BUS 覆铜(**不断**)          V24_BUS 覆铜,每列让出 6mm 信号车道
通道列 y 78–129       器件之间的短连线 + MOS 漏极铜面    竖向干线:CHn_VOUT / 两条漏极 / 两条栅极
                                                       + GND 覆铜填满其余
底部带 y 129.8–147    GND(在列与列之间的空当里)        GND 覆铜 + 每列三条竖线下到端子
入电区 D0 x 101–130   V24_PROT / V24_FUSED / V24_IN     GND 覆铜

一列之内的底层车道(相对列心 cx 的 x 偏移),六列一模一样:
    栅极 CW  cx−7.4  │  CHn_VOUT cx−5.2(3.5mm)│ 漏极 CW cx−1.5 │
    漏极 WW  cx+1.5  │  栅极 WW  cx+7.4        │  其余是 GND 覆铜
"""
import gc
gc.disable()          # pcbnew 的 SWIG 对象所有权:不关 GC 会在 SaveBoard 时崩
import subprocess
import sys
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"

board = pcbnew.LoadBoard(str(BOARD))
_pro_backup = (HERE / "cct-main.kicad_pro").read_bytes()
NET = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
F, B = pcbnew.F_Cu, pcbnew.B_Cu

COL_X = {1: 92.0, 2: 76.0, 3: 60.0, 4: 44.0, 5: 28.0, 6: 12.0}

# 行 y(与 gen_pcb_v2.py 的 ROW 表一致)
FUSE_Y, CEL_Y, LED_Y = 81.67, 97.13, 104.78
TVS_Y, FW_Y, R5_Y, MOS_Y, TERM_Y = 110.10, 116.24, 120.84, 128.26, 141.20
RAIL_Y = 102.40                    # 电解与指示灯之间那条 2.2mm 空带里的 V+ 横向分配轨
SPINE_Y0, SPINE_Y1 = 65.0, 77.0
SPINE_X0, SPINE_X1 = 6.0, 108.0

# 列内底层车道(相对列心)
LANE_GATE_CW, LANE_VOUT, LANE_DCW, LANE_DWW, LANE_GATE_WW = -7.20, -5.40, -2.00, 2.00, 7.20
LANE_SPINE_CW, LANE_SPINE_WW = -1.50, 1.50   # 穿脊椎那 6mm 车道里的两条
FANOUT_Y = 92.0                               # 出脊椎之后向列两侧张开的高度
                                              #(放在换保险丝的净空那一段,底层是空的)

# 线宽(§A5.3)
W_BUS = 4.0
W_VOUT = 2.6      # 底层竖带。列内五条车道排完之后能给到的最大宽度
W_VOUT_F = 2.5
W_DRAIN = 1.2
W_PROT = 3.0
W_PWR1 = 1.0
W_SIG = 0.25
W_KELVIN = 0.3
VIA_D, VIA_DRILL = 0.6, 0.3
STITCH_D, STITCH_DRILL = 0.5, 0.3


# ============================================================================
# 基础工具
# ============================================================================
PLACED = []          # 本脚本已经放下的铜:(x0, y0, x1, y1, layer, netname)
                     # seg()/via() 自己往里记,避障小路由据此判间距


def net(name):
    if name not in NET:
        raise SystemExit(f"网络不存在:{name}")
    return NET[name]


# 焊盘坐标**在动手删东西之前**就抄成普通浮点数存下来。
# 原因还是那个 SWIG 坑:`board.Remove()` 调用过之后,先前拿到的 PAD 代理对象会失效
#(连 `GetPosition().x` 都取不到),而 clear_copper() 是本脚本第一件事。
PADXY = {}
PADHALF = {}         # (ref, net) → 焊盘半宽半高,给「先垂直逃出焊盘排」用
PADBOX = []          # 焊盘外框,给避障小路由用
for fp in board.GetFootprints():
    _ref = fp.GetReference()
    for p in fp.Pads():
        q = p.GetPosition()
        PADXY.setdefault((_ref, p.GetNetname()), (ToMM(q.x), ToMM(q.y)))
        bb = p.GetBoundingBox()
        PADHALF.setdefault((_ref, p.GetNetname()),
                           (ToMM(bb.GetRight() - bb.GetLeft()) / 2,
                            ToMM(bb.GetBottom() - bb.GetTop()) / 2))
        PADBOX.append((ToMM(bb.GetLeft()), ToMM(bb.GetTop()),
                       ToMM(bb.GetRight()), ToMM(bb.GetBottom()),
                       p.GetNetname(), p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD,
                       p.IsOnLayer(F), p.IsOnLayer(B)))


def P(ref, netname):
    """位号 + 网络名 → 焊盘中心 (x, y)。"""
    if (ref, netname) not in PADXY:
        raise SystemExit(f"找不到焊盘:{ref} 上没有网络 {netname}")
    return PADXY[(ref, netname)]


def clear_copper():
    """删掉所有走线 / 过孔 / 覆铜(规则区留着)。

    ⚠️ 必须**先把要删的都收集完**再动手:`board.Remove()` 一旦调用过,同一进程里
    其它 SWIG 代理对象就会集体失效(`'SwigPyObject' object has no attribute ...`)。
    """
    PLACED.clear()
    items = list(board.GetTracks())
    # 覆铜全删;规则区只删本脚本自己下的那些(名字带「车道」),
    # gen_pcb_v2.py 下的天线禁区留着 —— 否则跑几次就叠出一堆重复的规则区。
    items += [board.GetArea(i) for i in range(board.GetAreaCount())
              if not board.GetArea(i).GetIsRuleArea()
              or "车道" in board.GetArea(i).GetZoneName()]
    for it in items:
        board.Remove(it)
    return len(items)


def seg(x1, y1, x2, y2, layer, width, netname):
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        return
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    t.SetLayer(layer)
    t.SetWidth(FromMM(width))
    t.SetNet(net(netname))
    board.Add(t)
    _o = (min(x1, x2) - width / 2, min(y1, y2) - width / 2,
          max(x1, x2) + width / 2, max(y1, y2) + width / 2, layer, netname)
    PLACED.append(_o)
    _index(_o)


def path(pts, layer, width, netname):
    for a, b in zip(pts, pts[1:]):
        seg(a[0], a[1], b[0], b[1], layer, width, netname)


def via(x, y, netname, d=VIA_D, drill=VIA_DRILL):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetWidth(FromMM(d))
    v.SetDrill(FromMM(drill))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(F, B)
    v.SetNet(net(netname))
    board.Add(v)
    _o = (x - d / 2, y - d / 2, x + d / 2, y + d / 2, None, netname)
    PLACED.append(_o)
    _index(_o)


def drop(x, y, netname, w=W_SIG, frm=None):
    """在 (x,y) 打一个换层过孔;frm 给了就先从 frm 用顶层短线接过来。"""
    if frm is not None:
        path([frm, (x, y)], F, w, netname)
    via(x, y, netname)


# ⚠️ SWIG 所有权坑:`ZONE::SetOutline()` 接管的是指针,但 Python 这边一旦把
# 局部变量重新绑定,引用计数归零就把它释放了 —— 存盘时 double free,进程**无声退出**
# (连回溯都没有,只看到脚本跑到一半没了)。所以每一个 SHAPE_POLY_SET / LSET
# 都存进 _KEEP 里,活到进程结束。gc.disable() 挡不住这个,因为它是引用计数不是 GC。
_KEEP = []


def poly(pts):
    ps = pcbnew.SHAPE_POLY_SET()
    _KEEP.append(ps)
    ps.NewOutline()
    for (x, y) in pts:
        ps.Append(FromMM(x), FromMM(y))
    return ps


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def zone(netname, layers, pts, priority=0, name="", clr=0.25):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    _KEEP.append(ls)
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetNet(net(netname))
    z.SetOutline(poly(pts))
    z.SetAssignedPriority(priority)
    z.SetZoneName(name or netname)
    z.SetLocalClearance(FromMM(clr))
    z.SetMinThickness(FromMM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)   # 大电流:焊盘全连,不用热焊盘
    z.SetIsFilled(False)
    board.Add(z)
    return z


def keepout_fill(layers, pts, name):
    """只禁覆铜填充的规则区 —— 走线与过孔照走。"""
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    _KEEP.append(ls)
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetOutline(poly(pts))
    z.SetZoneName(name)
    board.Add(z)


print(f"[清场] 删掉 {clear_copper()} 个旧走线/过孔/覆铜(幂等的前提)")

# ============================================================================
# 一个**会避障的小路由**(只走直角,只给短距离信号线用)
# ============================================================================
# 为什么要有它:逻辑区那些两端元件,**另一只脚常常正好落在 L 形的拐角上**,
# 靠人一条条挑拐点又慢又容易漏。这里把「候选拐法 → 逐段查间距 → 第一个干净的就用」
# 写成代码:候选是有限且**按固定顺序**枚举的,所以结果可复现,不是随机试出来的。
#
# 它**只解决短距离两点连线**,不是自动布线器:不会自己找绕远的路、布不通就明说
# 布不通(记进 UNROUTED,末尾统一列出来),绝不硬塞。

def _box(x1, y1, x2, y2, w):
    return (min(x1, x2) - w / 2, min(y1, y2) - w / 2,
            max(x1, x2) + w / 2, max(y1, y2) + w / 2)


def _hit(b1, b2, clr):
    return not (b1[2] + clr <= b2[0] or b2[2] + clr <= b1[0]
                or b1[3] + clr <= b2[1] or b2[3] + clr <= b1[1])


BLOCKERS_SEEN = []       # 布不通时用来说清「是谁挡的」
GRID = 6.0
_gidx = {}           # (gx, gy) → [障碍物]


def _gkeys(b):
    for gx in range(int(b[0] // GRID), int(b[2] // GRID) + 1):
        for gy in range(int(b[1] // GRID), int(b[3] // GRID) + 1):
            yield (gx, gy)


def _index(obst):
    for k in _gkeys(obst):
        _gidx.setdefault(k, []).append(obst)


def _near(b):
    seen = set()
    for k in _gkeys((b[0] - 1, b[1] - 1, b[2] + 1, b[3] + 1)):
        for o in _gidx.get(k, ()):
            if id(o) not in seen:
                seen.add(id(o))
                yield o


# 对所有网络一视同仁的禁区:天线净空 A0,以及板边留白。
# 避障小路由本来看不见它们 —— 不加进来,它会大大方方从天线底下和板边外面绕过去。
FORBIDDEN = [(0.0, 0.0, 8.0, 25.0)]      # A0 天线净空(双面)
EDGE_KEEP = 0.6                          # 走线中心到板边至少留这么多


def _clean(pts, layer, width, netname, clr):
    """这条折线在这一层上,离所有**别的网络**的焊盘与已铺铜是否都够远;
    并且不进天线净空、不贴板边。"""
    for a, b in zip(pts, pts[1:]) if len(pts) > 1 else [(pts[0], pts[0])]:
        bb = _box(a[0], a[1], b[0], b[1], width)
        if (bb[0] < EDGE_KEEP or bb[1] < EDGE_KEEP
                or bb[2] > 130.0 - EDGE_KEEP or bb[3] > 164.0 - EDGE_KEEP):
            return False
        if any(_hit(bb, fb, 0.3) for fb in FORBIDDEN):
            return False
        for o in _near(bb):
            if len(o) == 8:                       # 焊盘
                px0, py0, px1, py1, pnet, thru, onf, onb = o
                if pnet == netname:
                    continue
                if not (thru or (onf and layer in (F, None))
                        or (onb and layer in (B, None))):
                    continue
                if _hit(bb, (px0, py0, px1, py1), clr):
                    BLOCKERS_SEEN.append(f"焊盘[{pnet or '无网络'}]")
                    return False
            else:                                 # 已铺的铜
                qx0, qy0, qx1, qy1, qlayer, qnet = o
                if qnet == netname:
                    continue
                if qlayer is not None and layer is not None and qlayer != layer:
                    continue
                if _hit(bb, (qx0, qy0, qx1, qy1), clr):
                    BLOCKERS_SEEN.append(f"走线[{qnet}]")
                    return False
    return True


def _emit(pts, layer, width, netname):
    for a, b in zip(pts, pts[1:]):
        if a == b:
            continue
        seg(a[0], a[1], b[0], b[1], layer, width, netname)   # seg 自己会记进 PLACED


def _escapes(ref, netname, toward):
    """从焊盘先**垂直逃出它那一排**再拐 —— 密集排里这是唯一能出去的方向。

    返回若干候选逃逸点(含「原地不动」),按「朝着目标那一侧」优先排序。
    """
    x, y = PADXY[(ref, netname)]
    hw, hh = PADHALF.get((ref, netname), (0.4, 0.4))
    out = [(x, y)]
    for d in (hh + 0.65, hh + 1.3, hh + 2.4, hh + 4.0, hh + 6.0):
        out += [(x, y - d), (x, y + d)]
    for d in (hw + 0.65, hw + 1.3, hw + 2.4, hw + 4.0, hw + 6.0):
        out += [(x - d, y), (x + d, y)]
    out.sort(key=lambda p2: (p2[0] - toward[0]) ** 2 + (p2[1] - toward[1]) ** 2)
    return out[:14]


def _cands(a, b, step=0.25, span=12.0):
    """候选拐法:先横后竖、先竖后横,再加两族 Z 形(拐点按固定步长枚举)。"""
    out = [[a, (b[0], a[1]), b], [a, (a[0], b[1]), b]]
    lo, hi = min(a[1], b[1]) - span, max(a[1], b[1]) + span
    ys = sorted((lo + k * step for k in range(int((hi - lo) / step) + 1)),
                key=lambda y: abs(y - (a[1] + b[1]) / 2))
    out += [[a, (a[0], y), (b[0], y), b] for y in ys]
    lo, hi = min(a[0], b[0]) - span, max(a[0], b[0]) + span
    xs = sorted((lo + k * step for k in range(int((hi - lo) / step) + 1)),
                key=lambda x: abs(x - (a[0] + b[0]) / 2))
    out += [[a, (x, a[1]), (x, b[1]), b] for x in xs]
    # 再加一族「竖 → 横 → 竖 → 横」的五点路径:两个自由参数,步长放粗一点,
    # 用来绕开中间那些排得很密的小件(逻辑区那些长距离连线全靠它)。
    cy = sorted((min(a[1], b[1]) - span + k for k in range(int(2 * span + abs(a[1] - b[1])) + 1)),
                key=lambda y: abs(y - (a[1] + b[1]) / 2))[:22]
    cx = sorted((min(a[0], b[0]) - span + k for k in range(int(2 * span + abs(a[0] - b[0])) + 1)),
                key=lambda x: abs(x - (a[0] + b[0]) / 2))[:22]
    out += [[a, (a[0], y), (x, y), (x, b[1]), b] for y in cy for x in cx]
    return out


for _o in PADBOX:            # 焊盘一次性进网格索引(它们不会变)
    _index(_o)

UNROUTED = []
DIRTY = []


def _who(n=3):
    """挡路的都是谁 —— 出现次数最多的那几个,报告里直接说出名字。"""
    from collections import Counter
    c = Counter(BLOCKERS_SEEN)
    BLOCKERS_SEEN.clear()
    return "、".join(f"{k}×{v}" for k, v in c.most_common(n)) or "(无)"


def hpath(pts, layer, width, netname, tag):
    """手写的走线也要**先查干净再落笔**;不干净就记账,不硬塞。"""
    if _clean(pts, layer, width, netname, 0.21):
        _emit(pts, layer, width, netname)
        return True
    DIRTY.append((netname, tag))
    return False


def corridor(netname, a, b, ys=None, xs=None, width=W_SIG, ea=2.2, eb=2.2, clr=0.21):
    """a ─竖出来─▶ **底层**走廊 ─竖回去─▶ b。走廊位置从 ys(或 xs)里依次试。

    手写的干线也要**先查干净再落笔** —— 一条都不干净就记进 DIRTY,末尾统一报,
    绝不硬塞。这是本文件里所有「跨区干线」的统一写法。
    """
    # 逃逸点也依次试:上下、左右、远近 —— 两头都被密集焊盘夹着的时候就差这一下
    def _outs(pt, d):
        return [(pt[0], pt[1] + d * f) for f in (1.0, -1.0, 1.7, -1.7, 2.6, -2.6)] + \
               [(pt[0] + d * f, pt[1]) for f in (1.0, -1.0, 1.7, -1.7, 2.6, -2.6)]
    for pa in _outs(a, ea):
      for pb in _outs(b, eb):
       for c in [v + d for v in (ys or xs) for d in (0.0, 0.6, -0.6, 1.2, -1.2)]:
        mid = ([pa, (pa[0], c), (pb[0], c), pb] if ys
               else [pa, (c, pa[1]), (c, pb[1]), pb])
        if (_clean([a, pa], F, width, netname, clr)
                and _clean([b, pb], F, width, netname, clr)
                and _clean([pa], None, VIA_D, netname, clr)
                and _clean([pb], None, VIA_D, netname, clr)
                and _clean(mid, B, width, netname, clr)):
            _emit([a, pa], F, width, netname)
            _emit([b, pb], F, width, netname)
            via(pa[0], pa[1], netname)
            via(pb[0], pb[1], netname)
            _emit(mid, B, width, netname)
            return True
    DIRTY.append((netname, f"{a}→{b}", _who()))
    return False


def auto(netname, ra, rb, width=W_SIG, clr=0.21, layers=(F,), esc=1.4):
    """把 ra、rb 两个位号上的同名网络连起来。布不通就记账,返回 False。

    layers 里给 B 时会在两端各打一个换层过孔(离焊盘 esc 毫米,不打在焊盘上)。
    """
    a, b = P(ra, netname), P(rb, netname)
    ea, eb = _escapes(ra, netname, b), _escapes(rb, netname, a)
    for layer in layers:
        if layer == F:
            for pa in ea:
                if not _clean([a, pa], F, width, netname, clr):
                    continue
                for pb in eb:
                    if not _clean([b, pb], F, width, netname, clr):
                        continue
                    for pts in _cands(pa, pb):
                        if _clean(pts, F, width, netname, clr):
                            _emit([a, pa], F, width, netname)
                            _emit([b, pb], F, width, netname)
                            _emit(pts, F, width, netname)
                            return True
        else:
            for va in ea[1:]:
                if not (_clean([a, va], F, width, netname, clr)
                        and _clean([va], None, VIA_D, netname, clr)):
                    continue
                for vb in eb[1:]:
                    if not (_clean([b, vb], F, width, netname, clr)
                            and _clean([vb], None, VIA_D, netname, clr)):
                        continue
                    for pts in _cands(va, vb):
                        if _clean(pts, B, width, netname, clr):
                            _emit([a, va], F, width, netname)
                            _emit([b, vb], F, width, netname)
                            via(va[0], va[1], netname)
                            via(vb[0], vb[1], netname)
                            _emit(pts, B, width, netname)
                            return True
    UNROUTED.append((netname, ra, rb, _who()))
    return False


# ============================================================================
# ① B0 24V 分配脊椎 —— 双面 12mm + 每 3mm 一颗 0.5mm 缝合过孔
# ============================================================================
zone("V24_BUS", [F], rect(SPINE_X0, SPINE_Y0, SPINE_X1, SPINE_Y1), 30, "B0 脊椎 顶层(不断)")
zone("V24_BUS", [B], rect(SPINE_X0, SPINE_Y0, SPINE_X1, SPINE_Y1), 30, "B0 脊椎 底层")
for n, cx in COL_X.items():
    keepout_fill([B], rect(cx - 3.0, SPINE_Y0 - 3.0, cx + 3.0, SPINE_Y1 + 3.0),
                 f"CH{n} 栅极信号车道(底层脊椎让位 6mm)")

stitch = 0
lanes = [(cx - 3.6, cx + 3.6) for cx in COL_X.values()]
x = SPINE_X0 + 2.5
while x < SPINE_X1 - 2.0:
    if not any(a <= x <= b for a, b in lanes):
        for yy in (SPINE_Y0 + 2.5, (SPINE_Y0 + SPINE_Y1) / 2, SPINE_Y1 - 2.5):
            via(x, yy, "V24_BUS", STITCH_D, STITCH_DRILL)
            stitch += 1
    x += 3.0
print(f"[脊椎] 双面 12mm(x {SPINE_X0}–{SPINE_X1} / y {SPINE_Y0}–{SPINE_Y1});"
      f"缝合过孔 {stitch} 颗;6 条 6mm 底层信号车道处顶层不断、底层让位")

# ============================================================================
# ② 六列功率级(六列完全相同)
# ============================================================================
CH = {n: dict(F=f"F{n+1}", J=f"J{n+2}") for n in range(1, 7)}
CH_PARTS = [
    (1, "F2", "J3", "Q7", "Q8", "R16", "R17", "R18", "R19", "D5", "D6", "D7", "D8",
     "C16", "C17", "LED2", "LED3", "R20", "R21"),
    (2, "F3", "J4", "Q9", "Q10", "R22", "R23", "R24", "R25", "D9", "D10", "D11", "D12",
     "C18", "C19", "LED4", "LED5", "R26", "R27"),
    (3, "F4", "J5", "Q11", "Q12", "R28", "R29", "R30", "R31", "D13", "D14", "D15", "D16",
     "C20", "C21", "LED6", "LED7", "R32", "R33"),
    (4, "F5", "J6", "Q13", "Q14", "R34", "R35", "R36", "R37", "D17", "D18", "D19", "D20",
     "C22", "C23", "LED8", "LED9", "R38", "R39"),
    (5, "F6", "J7", "Q15", "Q16", "R40", "R41", "R42", "R43", "D21", "D22", "D23", "D24",
     "C24", "C25", "LED10", "LED11", "R44", "R45"),
    (6, "F7", "J8", "Q17", "Q18", "R46", "R47", "R48", "R49", "D25", "D26", "D27", "D28",
     "C26", "C27", "LED12", "LED13", "R50", "R51"),
]

for (n, Fz, Jz, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw, Dtc, Dtw,
     Ce, Cm, Lc, Lw, Rlc, Rlw) in CH_PARTS:
    cx = COL_X[n]
    V = f"CH{n}_VOUT"

    # ---- ② a 脊椎 → 支路保险丝 ----
    fin = P(Fz, "V24_BUS")
    seg(fin[0], SPINE_Y1 - 1.0, fin[0], fin[1], F, W_BUS, "V24_BUS")

    # ---- ② b CHn_VOUT:保险丝 → 电解 + → 横向分配轨 → 底层竖带 → 端子 V+ ----
    fout = P(Fz, V)
    cel = P(Ce, V)
    path([fout, (cel[0], fout[1] + 3.0), cel], F, W_VOUT, V)
    # 电解正极 → 横向分配轨(顶层,走电解与指示灯之间那条 2.2mm 空带)
    la, lb = P(Lc, V), P(Lw, V)
    path([(cel[0], cel[1]), (cel[0], RAIL_Y), (la[0], RAIL_Y), (la[0], la[1])],
         F, 1.2, V)
    path([(cel[0], RAIL_Y), (lb[0], RAIL_Y), (lb[0], lb[1])], F, 1.2, V)
    # 换到底层竖带下去端子
    vx = cx + LANE_VOUT
    drop(vx, RAIL_Y, V, 1.2, frm=(cel[0], RAIL_Y))
    term_v = P(Jz, V)
    path([(vx, RAIL_Y), (vx, 137.0), (term_v[0], term_v[1])], B, W_VOUT, V)

    # 续流阴极与 100nF 的 V+ 都挂在**续流与栅阻之间那条 2.2mm 空带**上的一条顶层横轨:
    # 它左右对称地横穿一列,两端各上一小截到续流阴极,中间下一小截到 100nF。
    # 续流阴极的正上方是 TVS 的地脚、正下方是栅阻,只有这条横带过得去。
    TAP_Y = 119.30
    via(vx, TAP_Y, V)
    kc, kw = P(Dfc, V), P(Dfw, V)
    path([(kc[0], TAP_Y), (kw[0], TAP_Y)], F, 0.6, V)
    path([(kc[0], TAP_Y), (kc[0], kc[1])], F, 0.6, V)
    path([(kw[0], TAP_Y), (kw[0], kw[1])], F, 0.6, V)
    cmv = P(Cm, V)
    path([(cmv[0], TAP_Y), cmv], F, 0.4, V)

    # ---- ② c 两个半边(CW / WW)----
    for side, sgn, Q, Rg, Rpd, Dfw_, Dtvs, Rl, L in (
            ("CW", -1, Qc, Rgc, Rpc, Dfc, Dtc, Rlc, Lc),
            ("WW", +1, Qw, Rgw, Rpw, Dfw, Dtw, Rlw, Lw)):
        D = f"CH{n}_{side}_D"
        G = f"CH{n}_{side}_G"
        GR = f"CH{n}_{side}_GR"
        LK = f"{L}_K"
        dx = cx + (LANE_DCW if sgn < 0 else LANE_DWW)

        # 指示灯 → 限流电阻(顶层,两脚就在隔壁)
        path([P(L, LK), P(Rl, LK)], F, 0.4, LK)

        # 漏极:限流电阻 → TVS → 续流 → 底层 → MOS 散热片 → 端子
        # ⚠️ 从限流电阻那一脚出发**不能横着走** —— 它旁边就是同一颗电阻的另一脚
        #(指示灯阴极),横过去直接压上。先竖下来出了指示灯那一排再拐。
        r_d, t_d, f_d = P(Rl, D), P(Dtvs, D), P(Dfw_, D)
        path([r_d, (r_d[0], LED_Y + 2.2), (dx, LED_Y + 3.2), (dx, t_d[1]), t_d],
             F, 0.8, D)
        path([t_d, (dx, t_d[1]), (dx, f_d[1]), f_d], F, W_DRAIN, D)
        drop(dx, f_d[1] + 1.8, D, W_DRAIN, frm=(dx, f_d[1]))
        tab = P(Q, D)
        term_d = P(Jz, D)
        path([(dx, f_d[1] + 1.8), (dx, tab[1] + 4.0), (term_d[0], 137.5), term_d],
             B, W_DRAIN, D)
        # 散热片本体接到底层这条干线上:3 颗过孔**沿着干线**打(不是横着排),
        # 横着排会把过孔打到隔壁 CHn_VOUT 的底层竖带上去。
        for k in (-1.8, 0.6, 2.6):
            via(dx, tab[1] + k, D)

        # 栅极信号:驱动器 → 脊椎底层车道 → 栅阻(顶层脚就在车道正下方)
        gx = cx + (LANE_GATE_CW if sgn < 0 else LANE_GATE_WW)
        sx = cx + (LANE_SPINE_CW if sgn < 0 else LANE_SPINE_WW)
        g_pad = P(Rg, G)
        path([(sx, SPINE_Y0 - 1.5), (sx, FANOUT_Y), (gx, FANOUT_Y + 1.5),
              (gx, R5_Y - 2.0), (g_pad[0], R5_Y - 2.0)], B, W_SIG, G)
        drop(g_pad[0], R5_Y - 2.0, G)
        seg(g_pad[0], R5_Y - 2.0, g_pad[0], g_pad[1], F, W_SIG, G)

        # 栅阻下游 → 下拉 → MOS 栅极(顶层一条线,不折返)
        gr_r, gr_pd, gr_q = P(Rg, GR), P(Rpd, GR), P(Q, GR)
        path([gr_r, gr_pd], F, 0.4, GR)
        # 下拉电阻的另一脚是地,横着过去会压上它 —— 先竖下来出了这一排再拐
        path([gr_pd, (gr_pd[0], R5_Y + 2.0), (gr_q[0], R5_Y + 2.0), gr_q], F, 0.4, GR)

print("[通道列] 六列的 V+ / 漏极 / 栅极干线已铺")

# ============================================================================
# ③ D0 入电保护区:J1 → F1 → Q1/Q2 → 体电容 → RS1 → 脊椎
# ============================================================================
j1 = P("J1", "V24_IN")
f1a = P("F1", "V24_IN")
# 走**底层**:J1 与 F1 都是插件件,两层都通,底层这一段正好从进线阻尼 RC 那一排下面
# 穿过去,不用在顶层跟 C44 / R68 抢位置。
path([j1, (j1[0], 138.0), (f1a[0], 133.5), (f1a[0], 129.01), (f1a[0], 125.61)],
     B, W_PROT, "V24_IN")

# V24_FUSED:F1 右夹子 → Q1/Q2 散热片 → 进线阻尼 C44
zone("V24_FUSED", [F], rect(101.5, 112.0, 129.0, 124.3), 25, "V24_FUSED(Q1/Q2 散热片)")
c44 = P("C44", "V24_FUSED")
f1b = P("F1", "V24_FUSED")
# F1 的出线夹子(3/4 脚)→ 上行进 V24_FUSED 那片铜;再横过去喂进线阻尼 C44
path([(f1b[0], 129.01), (f1b[0], 125.61), (f1b[0], 123.0)], F, W_PROT, "V24_FUSED")
path([(f1b[0], 130.5), (f1b[0], 132.8), (c44[0], 132.8), c44], F, W_PWR1, "V24_FUSED")
# 阻尼 RC 的中点与地
snub = P("R68", "SNUB_MID")
path([P("C44", "SNUB_MID"), snub], F, W_PWR1, "SNUB_MID")

# V24_PROT:Q1/Q2 源极 → 体电容 → D1 → RS1 → PTC1
zone("V24_PROT", [F], rect(101.5, 74.0, 129.5, 111.0), 25, "V24_PROT(源极 → 体电容 → RS1)")
for q in ("Q1", "Q2"):
    s = P(q, "V24_PROT")
    seg(s[0], s[1], s[0], 110.6, F, 2.0, "V24_PROT")
rs_hi = P("RS1", "V24_PROT")
seg(rs_hi[0], 74.5, rs_hi[0], rs_hi[1], F, 2.5, "V24_PROT")
ptc = P("PTC1", "V24_PROT")
path([(ptc[0], 74.5), (129.2, 72.0), (129.2, ptc[1]), ptc], F, W_PWR1, "V24_PROT")

# PMOS_GATE:两个栅极 → DZ1 / R1 / TP8
gq1, gq2 = P("Q1", "PMOS_GATE"), P("Q2", "PMOS_GATE")
gdz = P("DZ1", "PMOS_GATE")
path([gq1, (gq1[0], 107.0), (gq2[0], 107.0), (gdz[0], 107.0), gdz], F, 0.4, "PMOS_GATE")
path([gdz, P("R1", "PMOS_GATE")], F, 0.4, "PMOS_GATE")
path([P("R1", "PMOS_GATE"), P("TP8", "PMOS_GATE")], F, 0.4, "PMOS_GATE")

# V24_BUS:RS1 下游 → 脊椎(脊椎覆铜自己会长过来,这里补一条粗线保证一定连上)
# RS1 的下游脚就落在脊椎那片铜里(脊椎 x 到 108,RS1 下游脚在 106.93),
# 不再补一段粗线 —— 4mm 宽的短线会蹭到旁边 C46 的地脚。

# V24_LOGIC:PTC1 → 沿右板边细线上行 → buck 的输入电容
# V24_LOGIC 从 PTC1 沿右板边上行去 buck。**不能横穿右板边那两条 I2C 竖道**,
# 所以先在 y≈57(I2C 拐弯处以下)横过来,再上到体电容 C35。
vl = P("PTC1", "V24_LOGIC")
c35 = P("C35", "V24_LOGIC")
# 横过来的那一段走 y=52 —— y=40 那条走廊要留给 buck 的 FB / COMP / EN 分压回 U2
path([vl, (vl[0], 57.5), (90.0, 57.5), (90.0, 52.0), (c35[0], 52.0), (c35[0], c35[1])],
     B, W_PWR1, "V24_LOGIC")
u2vin = P("U2", "V24_LOGIC")
drop(u2vin[0], u2vin[1] - 2.0, "V24_LOGIC", W_PWR1, frm=u2vin)

# 开尔文采样:RS1 两脚 → U1 的 IN+ / IN−(两根 0.3mm 并行等长)
for netname in ("V24_PROT", "V24_BUS"):
    a = P("RS1", netname)
    b = P("U1", netname)
    path([a, (a[0], 69.0), (b[0], 69.0), b], F, W_KELVIN, netname)

print("[入电区] J1 → F1 → Q1/Q2 → 体电容 → RS1 → 脊椎 一条直线,无折返")

# ============================================================================
# ④ GND —— 拆成「逻辑地」和「功率地」两片,只在 RS1 附近汇合
# ============================================================================
zone("GND", [F, B], rect(0.5, 0.5, 129.5, 63.5), 5, "GND 逻辑地(y ≤ 63.5)")
zone("GND", [B], rect(0.5, 78.0, 129.5, 163.5), 5, "GND 功率地(底层,y ≥ 78)")
zone("GND", [B], rect(100.5, 55.0, 129.5, 80.0), 5, "GND 汇合颈(RS1 旁,唯一的连接点)")
zone("GND", [F], rect(0.5, 78.0, 100.5, 146.5), 4, "GND 功率地(顶层,通道列 + 底部带)")
zone("GND", [F], rect(100.5, 74.0, 129.5, 146.5), 3, "GND 入电区顶层(优先级低于 V24_PROT)")

# MOS 源极不单独打过孔:顶层在通道列里本来就是一片功率地,源极焊盘直接落在铜面上,
# 一路向下汇到底部带、横着回 J1 的负极。(原来在源极旁边打过孔,反而会打到
# 隔壁 CHn_VOUT 的底层竖带和漏极车道上去。)

# 列内其它 GND 脚(电解负极 / 100nF / TVS 阳极 / 栅极下拉)不再逐脚打过孔 ——
# 顶层在通道列里本来就铺了一片功率地,它们直接落在铜面上。这里只在每一列打一组
# 缝合过孔,把顶层这片和底层那片订在一起。
for (n, *_r) in CH_PARTS:
    cx = COL_X[n]
    # 打在「漏极 WW 车道」与「栅极 WW 车道」之间那条确实空着的带上(cx+5.0)。
    # 打在列边界上不行:相邻列的栅极车道就在 0.4mm 外。
    for yy in (94.0, 100.0, 113.2, 122.4, 127.0, 136.0, 143.0):
        via(cx + 5.0, yy, "GND", STITCH_D, STITCH_DRILL)

print("[地] 逻辑地 / 功率地两片,只在 RS1 旁边那一段颈上汇合")

# ============================================================================
# ⑤ 栅极驱动区 A5 与总断路
# ============================================================================
DRV_Y = 54.5
# 12 根栅极信号的扇出。两件事同时满足:
#   ① 同层的走线**不交叉** —— 引脚顺序与目标顺序单调对应,拉直线即可;
#   ② 换层过孔彼此离得开 —— 目标 x 天然隔 3mm 以上,但一根线不能压到别人的过孔上,
#      所以按「跑得远的排在离引脚近的车道」分四条车道,同车道那两根的 x 区间不重叠。
GATE_LANES = (59.0, 59.8, 60.6, 61.4)
for (u, chans) in (("U6", [(1, "CW"), (1, "WW"), (2, "CW"), (2, "WW"),
                           (3, "CW"), (3, "WW"), (4, "CW"), (4, "WW")]),
                   ("U7", [(5, "CW"), (5, "WW"), (6, "CW"), (6, "WW")])):
    items = []
    for (n, side) in chans:
        G = f"CH{n}_{side}_G"
        a = P(u, G)
        sx = COL_X[n] + (LANE_SPINE_CW if side == "CW" else LANE_SPINE_WW)
        items.append((abs(sx - a[0]), a, sx, G))
    # 左右分组各自排队:**引脚越靠外,车道越靠上**。
    # 这样每根线的竖直段都停在自己车道上方,底下那些横向车道从它旁边过去时不会撞上;
    # 而横向线经过别人的过孔时,那个过孔一定在更上面的车道,竖直距离就是车道间距。
    left = sorted((it for it in items if it[2] < it[1][0]), key=lambda it: it[1][0])
    right = sorted((it for it in items if it[2] >= it[1][0]), key=lambda it: -it[1][0])
    plan = [(it, GATE_LANES[k]) for k, it in enumerate(left)] + \
           [(it, GATE_LANES[k]) for k, it in enumerate(right)]
    if max(len(left), len(right)) > len(GATE_LANES):
        raise SystemExit("扇出车道不够,要加车道或把驱动器再往上挪")
    for ((_d, a, sx, G), ly) in plan:
        path([a, (a[0], ly), (sx, ly)], F, W_SIG, G)
        via(sx, ly, G, 0.5, 0.3)
        seg(sx, ly, sx, SPINE_Y0 - 1.5, B, W_SIG, G)

# /OE 是一条横穿整个驱动带的干线。它的两端是 U6/U7 的 19 脚,而 19 脚旁边就是
# 通道输入脚 —— 顶层横过去必压。改走**底层**,从两片 TSSOP 的身子底下穿过去。
OE_Y = 56.0
oe_taps = [P("R13", "OE_N"), P("Q6", "OE_N"), P("U6", "OE_N"), P("U7", "OE_N")]
xs = sorted(x for x, _y in oe_taps)
seg(xs[0], OE_Y, xs[-1], OE_Y, B, W_SIG, "OE_N")
for (px, py) in oe_taps:
    drop(px, OE_Y, "OE_N", W_SIG, frm=(px, py))
path([P("Q6", "OE_B"), (P("Q6", "OE_B")[0], DRV_Y + 3.2),
      (P("R14", "OE_B")[0], DRV_Y + 3.2), P("R14", "OE_B")], F, W_SIG, "OE_B")
path([P("R14", "OE_B"), P("R15", "OE_B")], F, W_SIG, "OE_B")
path([P("R15", "OE_B"), (P("R15", "OE_B")[0], DRV_Y + 2.8),
      (P("Q3", "OE_B")[0], DRV_Y + 2.8), P("Q3", "OE_B")], F, W_SIG, "OE_B")
path([P("Q3", "MASTER_OFF_B"), P("R3", "MASTER_OFF_B")], F, W_SIG, "MASTER_OFF_B")
path([P("R3", "MASTER_OFF_B"), (P("R3", "MASTER_OFF_B")[0], DRV_Y - 3.0),
      (P("R2", "MASTER_OFF_B")[0], DRV_Y - 3.0), P("R2", "MASTER_OFF_B")],
     F, W_SIG, "MASTER_OFF_B")
path([P("R2", "MASTER_OFF_TP"), P("TP7", "MASTER_OFF_TP")], F, W_SIG, "MASTER_OFF_TP")

print("[驱动区] 12 根栅极信号从驱动器垂直下到本列的脊椎车道,不跨列", flush=True)

# ============================================================================
# ⑥a A3 三个接口 → U4:8 根信号横穿整块板
# ============================================================================
# 这是「MCU 在左上、对外接口在右上」这个楼层规划的必然代价:干接点四路、I2C 两路、
# UART2 两路,都要从 x≈70–112 回到 U4 下排 x≈11–22。8 根线成束走,规矩和 PWM 那束一样:
#
#   源头焊盘 ─(顶层短脚)─▶ 过孔 ─(**底层**竖下来)─▶ 过孔
#           ─(**顶层**横向车道,每根一条自己的 y)─▶ 竖上去插进 U4 的脚
#
# 车道 y **按目标 x 从右到左依次下移**:每根线最后那一竖只会经过比自己更靠右的
# 车道所在的 x,而那些车道早就拐走了。源头那一竖放底层,与顶层车道天然不打架。
# 为了腾出 y 22.4–28 这条带,A1 那排小件整体下移了 3.5mm、C35 下移 1.5mm(见 gen_pcb_v2.py)。
A3_BUS = [                      # (网络, 源位号) —— 顺序即车道自上而下
    ("UART2_RX", "J10"), ("UART2_TX", "J10"),
    ("I2C_SCL", "R53"), ("I2C_SDA", "R52"),
    ("SW_IN2", "C29"), ("SW_IN1", "C28"), ("SW_IN4", "C31"), ("SW_IN3", "C30"),
]
A3_BUS.sort(key=lambda it: -P("U4", it[0])[0])
for k_, (netname, src_ref) in enumerate(A3_BUS):
    lane = 23.2 + 0.65 * k_    # 起点要在 U4 下排焊盘的下沿(22.65)之外
    s, d = P(src_ref, netname), P("U4", netname)
    esc = (s[0], s[1] + 2.2)
    path([s, esc], F, W_SIG, netname)
    via(esc[0], esc[1], netname)
    path([esc, (esc[0], lane)], B, W_SIG, netname)
    via(esc[0], lane, netname)
    path([(esc[0], lane), (d[0], lane), (d[0], d[1])], F, W_SIG, netname)

# I2C 还要沿右板边下行到 D0 的 U1(全板唯一一条从逻辑区伸进功率区的信号)
# 沿右板边下行的两条 I2C:**外面那条要拐得更靠下**,否则它的竖直段会横穿里面那条的横道。
for netname, rpull, ex, ey, turn in (("I2C_SCL", "R53", 126.4, 19.4, 60.5),
                                     ("I2C_SDA", "R52", 127.2, 20.4, 62.0)):
    a, b = P(rpull, netname), P("U1", netname)
    esc = (a[0], a[1] - 2.2)
    path([a, esc], F, W_SIG, netname)
    via(esc[0], esc[1], netname)
    path([esc, (esc[0], ey), (ex, ey), (ex, turn), (b[0], turn)], B, W_SIG, netname)
    via(b[0], turn, netname)
    seg(b[0], turn, b[0], b[1], F, W_SIG, netname)

print("[接口总线] 干接点 / I2C / UART2 共 8 根横向车道布完", flush=True)

# ============================================================================
# ⑥ 12 路 PWM:U4 → 驱动器的 A 侧输入(全板最长的一批信号)
# ============================================================================
# 难在两头都挤:U4 的 PWM 脚大半在模组**上排** y=3.6,而驱动器的输入脚只隔 0.65mm。
# 结构是「**底层竖下来 → 顶层横过去 → 顶层竖下去**」:
#
#   U4 焊盘 ─(顶层短脚)─▶ 过孔 ─(底层竖直,x = 焊盘自己的 x)─▶ 过孔
#           ─(顶层横向车道,每根一条自己的 y)─▶ 竖下去插进驱动器的输入脚
#
# 车道的 y **按目标 x 从右到左依次下移**。这样每根线最后那一竖,
# 只会经过比自己**更靠右**的车道所在的 x —— 而那些车道早就在它上方拐走了,
# 所以一根都不交叉。源头那一竖放在底层,与顶层车道天然不打架。
#
# 它比通用小路由靠谱,是因为这十二根是**一束**,要一起规划;
# 一根根去找缝一定会互相堵死(试过,只布通 3 根)。
PWM_LANES_U6 = (37.0, 37.8, 38.6, 39.4, 40.2, 41.0, 41.8, 42.6)
PWM_LANES_U7 = (43.4, 44.2, 45.0, 45.8)

# U4 上下两排会出现**同一个 x** 的两只脚(上排 y=3.6、下排 y=21.6),
# 底层那一竖如果都放在焊盘正下方就会叠在一起。所以先给每根线分一条**互不重叠的竖道**。
_used_x = []          # [(x, 归谁)] —— 同一根线自己的逃逸孔不算冲突


def _lane_x(px, owner, step=0.63, tries=10):
    cands = [px] + [px + s * step * k for k in range(1, tries) for s in (1, -1)]
    for cand in cands:
        if all(abs(cand - u) > 0.6 or o == owner for u, o in _used_x):
            _used_x.append((cand, owner))
            return cand
    raise SystemExit(f"{owner}:底层竖道排不下,要重新分配")


for drv, lanes in (("U6", PWM_LANES_U6), ("U7", PWM_LANES_U7)):
    chans = [(n, s) for n in (range(1, 5) if drv == "U6" else range(5, 7))
             for s in ("CW", "WW")]
    order = sorted(chans, key=lambda ns: -P(drv, f"CH{ns[0]}_{ns[1]}")[0])
    for lane, (n, s) in zip(lanes, order):
        G = f"CH{n}_{s}"
        src, tgt = P("U4", G), P(drv, G)
        if src[0] > 25.0:                      # 模组右侧那一脚:先往左出模组
            ex, ey = _lane_x(src[0] - 2.2, G), src[1]
        elif src[1] < 12.0:                    # 上排:往模组里(下)走
            ex, ey = _lane_x(src[0], G), src[1] + 2.6
        else:                                  # 下排:往**模组里面**(上)走再换层。
            # 往下不行:紧挨着的两只脚只隔 1.27mm,过孔一定压上;
            # 再往下 y23.2 起是接口总线带,顶层横穿它也撞。模组两排焊盘之间是空的。
            ex, ey = _lane_x(src[0], G), 19.0
        esc = (ex, ey)
        vx = ex
        path([src, esc], F, W_SIG, G)
        via(esc[0], esc[1], G)
        path([esc, (vx, lane)], B, W_SIG, G)
        via(vx, lane, G)
        path([(vx, lane), (tgt[0], lane), (tgt[0], tgt[1])], F, W_SIG, G)

# IO0 也在 U4 的**上排**,处境跟 12 路 PWM 一模一样:必须从模组底下走底层下来。
# 顺手在同一套竖道分配里给它留一条,免得跟 PWM 抢同一个 x。
_io0_u4 = P("U4", "IO0")
_io0_esc = (_lane_x(_io0_u4[0], "IO0"), _io0_u4[1] + 2.6)
path([_io0_u4, _io0_esc], F, W_SIG, "IO0")
via(_io0_esc[0], _io0_esc[1], "IO0")
_io0_sw = P("SW1", "IO0")
path([_io0_esc, (_io0_esc[0], 34.5), (_io0_sw[0], 34.5)], B, W_SIG, "IO0")
via(_io0_sw[0], 34.5, "IO0")
path([(_io0_sw[0], 34.5), _io0_sw], F, W_SIG, "IO0")

print("[PWM] 12 路 PWM + IO0 按「底层竖 → 顶层车道 → 顶层竖」布完", flush=True)

# ============================================================================
# ⑥ 逻辑区 A1–A4
# ============================================================================
# 全部交给上面那个会避障的小路由。每一条都写成「从哪到哪」,顺序 = 信号流向,
# 读起来就是一张接线表。布不通的不硬塞,末尾统一列出来。
FB = (F, B)          # 先试顶层,顶层挤不下再换底层(两端各打一个换层过孔)

# ---- 跨区干线先走 ----
# 这些干线两头都被密集焊盘夹住、中间还要横穿半块板,**能走的走廊只有那么一两条**。
# 所以必须排在前面挑路;放到后面,那几条走廊早被就近的小连线占掉了(实测就是这么栽的)。
corridor("FB_5V", P("R64", "FB_5V"), P("U2", "FB_5V"),
         ys=[40.6, 41.2, 40.0, 39.4, 41.8], ea=-1.8, eb=1.8)
corridor("COMP", P("U2", "COMP"), P("R65", "COMP"),
         ys=[47.5, 48.1, 46.9, 51.0, 51.6], ea=1.8, eb=1.8)
corridor("EN_BUCK", P("R67", "EN_BUCK"), P("U2", "EN_BUCK"),
         xs=[91.5, 92.5, 93.5, 94.5, 96.5, 98.5, 80.5, 79.5, 78.5, 82.5], ea=1.8, eb=-1.8)
corridor("USB_VBUS", P("J2", "USB_VBUS"), P("D4", "USB_VBUS"), width=0.6,
         ys=[33.0, 34.0, 35.0, 32.0, 31.0, 36.5, 38.0, 39.5, 41.0, 43.0, 44.5], ea=2.6, eb=-2.6)
corridor("USB_DM", P("J2", "USB_DM"), P("U5", "USB_DM"),
         xs=[49.9, 51.2, 52.4, 45.0], ea=3.5, eb=1.6)
corridor("USB_DP", P("J2", "USB_DP"), P("U5", "USB_DP"),
         xs=[46.6, 45.4, 44.2, 52.8, 54.0], ea=3.5, eb=1.6)
# OE_CTRL:MCU 右侧脚 → 驱动区的 /OE 电平转换。它要绕过 U4 底下那 12 根 PWM 的底层竖道
# (x 8.9–25.6),所以先往右出到 x≈30 再下来。这条是失效安全链的输入,不能不通。
corridor("OE_CTRL", P("U4", "OE_CTRL"), P("R14", "OE_CTRL"),
         xs=[30.0, 31.0, 32.0, 33.0, 29.0, 34.5, 36.0], ea=3.0, eb=2.4)
corridor("V3P3", P("C43", "V3P3"), P("U1", "V3P3"), width=0.5,
         xs=[123.3, 122.3, 121.3, 124.3, 119.5, 118.5, 125.3, 117.5], ea=2.5, eb=-1.8)
corridor("V5_SYS", P("C41", "V5_SYS"), P("J10", "V5_SYS"), width=0.5,
         ys=[9.5, 10.5, 8.6, 11.5, 12.5, 13.5, 14.5, 7.5, 15.5], ea=-2.6, eb=4.5)

# ---- 低压电源干线(链式串起来,不是星形)----
for w, chain in ((W_PWR1, ["PTC1", "C35", "C32", "C33", "C34", "U2", "R66"]),):
    for a, b in zip(chain, chain[1:]):
        auto("V24_LOGIC", a, b, width=w, layers=FB)
for a, b in zip(["L1", "C36", "C37", "R63", "D3"], ["C36", "C37", "R63", "D3", "D3"]):
    if a != b:
        auto("V5_BUCK", a, b, width=W_PWR1, layers=FB)
for a, b in zip(["D3", "D4", "C41", "TP3", "U3"], ["D4", "C41", "TP3", "U3", "U3"]):
    if a != b:
        auto("V5_SYS", a, b, width=0.8, layers=FB)

# V5_SYS 要喂两片驱动器和 R13,它们分散在 x 20–71。拉**一条顶层横轨走 y=50**:
# 上面是 PWM 的横向车道(37–46)与自动下载那一行(46.5),下面是两片驱动器的身子(50.76 起),
# 中间这条正好空着,而且驱动器的 VCC 脚(1 脚)就在上排 y=51.63,直接往下扎进去。
V5_RAIL_Y = 50.0
_u3 = P("U3", "V5_SYS")
# U3 的三只脚是竖着排的,不能顺着 x 往下走 —— 先往右让开,再下来
# 横轨本身走**底层** —— 顶层这一条被 12 根 PWM 最后那一竖横着穿过去(x 65.7–70.3),
# 放顶层必撞。底层那一带是空的,只在三个抽头处上一个过孔。
path([_u3, (117.8, _u3[1])], F, 0.8, "V5_SYS")
via(117.8, _u3[1], "V5_SYS")
path([(117.8, _u3[1]), (117.8, V5_RAIL_Y), (22.93, V5_RAIL_Y)], B, 0.8, "V5_SYS")
for _ref in ("U6", "U7", "R13"):
    _p = P(_ref, "V5_SYS")
    via(_p[0], V5_RAIL_Y, "V5_SYS")
    path([(_p[0], V5_RAIL_Y), (_p[0], _p[1])], F, 0.5, "V5_SYS")
for _x in (70.93, 22.93):        # 驱动器的两只 VCC 脚在 IC 两排之间对接
    path([(_x, 51.63), (_x, 57.37)], F, 0.5, "V5_SYS")
# 走底层:顶层 y≈9.5 那一带要留给 J9 的 I2C 竖下来
for a, b in zip(["U3", "C42", "C43", "TP4", "R53", "R52", "J9"],
                ["C42", "C43", "TP4", "R53", "R52", "J9", "J9"]):
    if a != b:
        auto("V3P3", a, b, width=0.8, layers=FB)
# U1(INA237)的 V3P3 就近从 A4 的 C43 取,不要绕右上角那一大圈
# U1 的 V3P3 就近从 A4 的 C43 沿右板边内侧下来(x=123.3 那条竖道)
corridor("V3P3", P("U1", "V3P3"), P("C6", "V3P3"), width=0.5,
         ys=[68.0, 69.5, 71.0, 59.5, 58.5], ea=1.8, eb=1.8)
for a, b in zip(["U4", "C10", "C11", "R4", "R5", "U5", "C13"],
                ["C10", "C11", "R4", "R5", "U5", "C13", "C13"]):
    if a != b:
        auto("V3P3", a, b, width=0.8, layers=FB)

# ---- buck 自己那一圈 ----
auto("BOOT", "U2", "C38", layers=FB)
auto("RT_CLK", "U2", "R62", layers=FB)
auto("SW_NODE", "U2", "D2", width=W_PWR1, layers=FB)
auto("SW_NODE", "U2", "L1", width=W_PWR1, layers=FB)
auto("SW_NODE", "C38", "L1", layers=FB)
auto("FB_5V", "R63", "R64", layers=FB)
# FB / COMP / EN 分压回 U2:U2 两排脚只隔 1.27mm,顶层横过去必压隔壁脚,
# 所以都从脚正下方/正上方竖出来一小截换到底层,横过去再竖回去。
auto("COMP", "R65", "C40", layers=FB)
auto("COMP_Z", "R65", "C39", layers=FB)
auto("EN_BUCK", "R66", "R67", layers=FB)

# ---- A3 干接点:端子 → 串阻(端子侧)→ 上拉 + 消抖(MCU 侧)→ U4 ----
for i in range(1, 5):
    auto(f"SW_T{i}", "J11", f"R{53+i}", layers=FB)
    auto(f"SW_IN{i}", f"R{53+i}", f"R{57+i}", layers=FB)
    auto(f"SW_IN{i}", f"R{57+i}", f"C{27+i}", layers=FB)
    # (已由 ⑥a 的横向车道接管)

# ---- A3 I2C:接口 → 上拉 → MCU;并沿右板边下行到 D0 的 U1 ----
for netname, rpull in (("I2C_SDA", "R52"), ("I2C_SCL", "R53")):
    auto(netname, "J9", rpull, layers=FB)
    # (已由 ⑥a 的横向车道接管)
    # (已由 ⑥a 的横向车道接管)
# (已由 ⑥a 的横向车道接管)
# (已由 ⑥a 的横向车道接管)

# ---- A2 USB 与自动下载(交叉接法:DTR→R11→RTS_B→Q4→EN,RTS→R12→DTR_B→Q5→IO0)----
auto("CC1", "J2", "R9", layers=FB)
_cc, _r10 = P("J2", "CC2"), P("R10", "CC2")
path([_cc, (_cc[0], 10.5), (_r10[0], 10.5), _r10], F, W_SIG, "CC2")
# (已由前面的 corridor 接管)
auto("U0TXD", "U5", "U4", layers=FB)
auto("U0RXD", "U5", "U4", layers=FB)
auto("DTR", "U5", "R11", layers=FB)
auto("RTS", "U5", "R12", layers=FB)
auto("RTS_B", "R11", "Q4", layers=FB)
auto("DTR_B", "R12", "Q5", layers=FB)
auto("EN", "Q4", "R4", layers=FB)
auto("EN", "R4", "C12", layers=FB)
auto("EN", "C12", "SW2", layers=FB)
auto("EN", "SW2", "U4", layers=FB)
auto("IO0", "Q5", "R5", layers=FB)
auto("IO0", "R5", "SW1", layers=FB)
# (已由 ⑥ 的上排竖道接管)

# ---- A1 状态灯 / 总断路控制 ----
auto("LED_STATUS", "U4", "LED1", layers=FB)
auto("LED1_K", "LED1", "R8", layers=FB)
# (已由前面的 corridor 接管)

print(f"[逻辑区] 近距离连线布完;没布通的 {len(UNROUTED)} 条", flush=True)
if DIRTY:
    print(f"[干线] 手写干线里有 {len(DIRTY)} 条找不到干净走廊:", flush=True)
    for _n, _w, _b in DIRTY:
        print(f"    ✗ {_n:<12} {_w}\n         挡路的:{_b}", flush=True)
for _n, _a, _b, _w in UNROUTED:
    print(f"    ✗ {_n:<12} {_a} → {_b}   挡路的:{_w}", flush=True)


# ============================================================================
# 收尾:填充覆铜、报告
# ============================================================================
# 覆铜填充不在本进程里做 —— pcbnew 的 ZONE_FILLER 在无头环境里跑多块覆铜会直接崩掉
# (进程无声退出,连回溯都没有)。改用命令行的 `kicad-cli pcb drc --refill-zones
# --save-board`,它在自己的进程里填、填完存盘,顺带把 DRC 也跑了。
pcbnew.SaveBoard(str(BOARD), board)
(HERE / "cct-main.kicad_pro").write_bytes(_pro_backup)

CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
rpt = HERE / ".drc-v2.rpt"
r = subprocess.run([CLI, "pcb", "drc", "--refill-zones", "--save-board",
                    "--severity-error", "--severity-warning",
                    "-o", str(rpt), str(BOARD)], capture_output=True, text=True)
(HERE / "cct-main.kicad_pro").write_bytes(_pro_backup)

# 统计另起一个进程做 —— 本进程里已经 Remove/Add 过大量对象,再 LoadBoard 会踩 SWIG 坑。
count_src = """
import gc; gc.disable()
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1])
c = b.GetConnectivity(); c.RecalculateRatsnest()
tr = sum(1 for t in b.GetTracks() if t.GetClass() == 'PCB_TRACK')
vi = sum(1 for t in b.GetTracks() if t.GetClass() == 'PCB_VIA')
print(tr, vi, b.GetAreaCount(), c.GetUnconnectedCount(True))
"""
out = subprocess.run([sys.executable, "-c", count_src, str(BOARD)],
                     capture_output=True, text=True)
ntr, nvia, nzone, unrouted = out.stdout.strip().split()

txt = rpt.read_text(encoding="utf-8") if rpt.exists() else ""
import re as _re
cat = {}
for m in _re.finditer(r"^\[([a-z_]+)\]", txt, _re.M):
    cat[m.group(1)] = cat.get(m.group(1), 0) + 1
print()
print("=" * 78)
print(f"走线 {ntr} 段 · 过孔 {nvia} 颗 · 覆铜 {nzone} 块")
print(f"未连接(ratsnest)条数:{unrouted}")
print(f"DRC 违规 {sum(cat.values())} 条:")
for k, v in sorted(cat.items(), key=lambda kv: -kv[1]):
    print(f"    {k:<22} {v}")
print("=" * 78)
