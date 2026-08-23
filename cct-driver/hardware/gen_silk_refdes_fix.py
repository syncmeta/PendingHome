#!/usr/bin/env python3
"""把「认不出是哪个元件」的丝印位号重新摆位(幂等)。

**问题。** 用户原话:「丝印标号和元器件也经常对不上,一个元器件旁边有好几个标号,
都不知道哪个是哪个」。这不是主观感觉,是可以量出来的:

    歧义判据 —— 设 ds = 文字到**自己元件外框**的距离、do = 到**最近的其它元件外框**
    的距离。要求 `do ≥ ds + max(0.20mm, 0.5×ds)`,不满足就算认不出来。

「就近认人」只看 `do > ds` 是不够的:F2–F5 那四个位号 **ds = do = 0.92mm**,正正
卡在两颗保险丝中间,谁都说不清它标的是哪一颗 —— 光比大小,浮点上还可能侥幸过关。
所以要求「离自己近出一截」:近端至少 0.20mm 的绝对差,远处按比例放宽到一半。

按这个判据,改之前 181 个可见位号里有 56 个中招(最狠的 C3:离自己 3.89mm,
却贴在 R62 身上 0.00mm)。

**怎么修。** 只动位号文字的坐标(必要时连同角度),元件本体、焊盘、铜箔、覆铜、
板框、开孔**一个都不碰**。对每个中招的位号,在它自己元件的四边外侧生成候选位
(4 边 × 5 个对齐点 × 5 个间隙 × 0/90 度),逐个验:

  1. 落在板内(离板边 ≥ 0.30mm,不新增 silk_edge_clearance)
  2. 不压任何焊盘(含自己的)—— 这是 `silk_over_copper` 唯一会报的东西
  3. 不压任何元件外框(含自己的)—— 顺带保证不压自己的丝印图形与极性标记
  4. 不压任何别的丝印文字:别的位号、以及 `CH1 / V+ / CW / WW / DC 24V IN` 那类
     功能丝印和板名 —— 不新增 `silk_overlap`
  5. 满足上面那条歧义判据,并且再多留一段富余(富余从 0.8mm 起,摆不下就依次
     降到 0.4 / 0.15 / 0mm —— 降到 0 就是刚好达标)

取「贴自己最紧、同时离别人最远」的那个。**四轮余量全试完还摆不下的,把该位号
隐藏,并在报告里逐个列名 + 写清为什么** —— 不静默隐藏。

**F7 那 0.9mm 没有挪,而且不该挪** —— 见文件末尾 `try_align_f7()` 的说明与实测。

幂等:摆好之后位号已经不满足歧义判据,再跑一次待办集合是空的,不写盘。用法:
    python3 hardware/gen_silk_refdes_fix.py
    python3 hardware/gen_silk_refdes_fix.py --check   只报告,不写盘
"""
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
CHECK_ONLY = "--check" in sys.argv

IU = 1e6                     # nm → mm
EDGE_KEEPOUT = 0.30          # 文字外框离板边最少留这么多
PAD_CLR = 0.15               # 文字外框离焊盘最少留这么多
BODY_CLR = 0.05              # 文字外框离别的元件外框最少留这么多
SILK_CLR = 0.10              # 文字外框离别的丝印最少留这么多(板规 min_silk_clearance=0)
EXTRAS = (0.8, 0.4, 0.15, 0.0)    # 在「刚好达标」之上再要的富余,从宽到紧
GAPS = (0.20, 0.35, 0.55, 0.80, 1.20)
ALIGNS = (0.0, -0.5, 0.5, -1.0, 1.0)   # 沿边对齐点,按 body 半宽/半高的倍数
NEAR = 25.0                  # 只跟这个半径内的东西比,纯提速

# 板框尺寸从 Edge.Cuts 现取 —— v2 改成 130×164 之后写死的 110×145 会让
# 「离板边 ≥0.30mm」这一条按错误的边界判,右下角一大片位号会被误判成出界。
BOARD_W, BOARD_H = None, None   # 见下方 LoadBoard 之后的赋值


# ---------------------------------------------------------------- 几何小工具
def box(b):
    """BOX2I → (left, top, right, bottom),单位 mm。"""
    return (b.GetLeft() / IU, b.GetTop() / IU, b.GetRight() / IU, b.GetBottom() / IU)


def dist(a, c):
    """两个矩形之间的最短距离(相交返回 0)。"""
    dx = max(a[0] - c[2], c[0] - a[2], 0.0)
    dy = max(a[1] - c[3], c[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def hits(a, c, clr):
    """a 膨胀 clr 之后是否碰到 c。"""
    return dist(a, c) < clr


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def need(d_self):
    """「离自己」比「离最近的别人」至少要近这么多,才算认得出是谁的。"""
    return max(0.20, 0.5 * d_self)


# ---------------------------------------------------------------- 采集(改动前)
board = pcbnew.LoadBoard(str(BOARD))
_bb = board.GetBoardEdgesBoundingBox()
BOARD_W, BOARD_H = _bb.GetRight() / IU, _bb.GetBottom() / IU
fps = list(board.GetFootprints())

bodies = {}          # ref → 元件外框(不含文字)
pads = []            # 所有焊盘外框
static_silk = []     # 不会动的丝印:元件里的图形 + 板级文字/图形
for f in fps:
    ref = f.GetReference()
    bodies[ref] = box(f.GetBoundingBox(False, False))
    for p in f.Pads():
        pads.append(box(p.GetBoundingBox()))
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_SilkS:
            static_silk.append(box(g.GetBoundingBox()))
for d in board.GetDrawings():
    if d.GetLayer() == pcbnew.F_SilkS:
        static_silk.append(box(d.GetBoundingBox()))

body_list = sorted(bodies.items())
visible = sorted((f.GetReference(), f) for f in fps if f.Reference().IsVisible())
hidden_before = sorted(f.GetReference() for f in fps if not f.Reference().IsVisible())


def near_bodies(tb, skip):
    cx, cy = center(tb)
    return [(r, b) for r, b in body_list
            if r != skip and abs(center(b)[0] - cx) < NEAR and abs(center(b)[1] - cy) < NEAR]


def measure(ref, tb):
    """返回 (到自己外框的距离, 到最近的其它元件外框的距离, 那个元件是谁)。"""
    d_self = dist(tb, bodies[ref])
    best, who = 1e9, None
    for r, b in near_bodies(tb, ref):
        d = dist(tb, b)
        if d < best:
            best, who = d, r
    return d_self, best, who


# ---------------------------------------------------------------- 改动前的账
before = {}
for ref, f in visible:
    before[ref] = measure(ref, box(f.Reference().GetBoundingBox()))

bad = sorted(r for r, (ds, do, _) in before.items() if do < ds + need(ds))
print(f"元件 {len(fps)} 个,位号可见 {len(visible)} 个、隐藏 {len(hidden_before)} 个")
print(f"歧义判据(do < ds + max(0.20, 0.5×ds))命中 **{len(bad)}** 个:")
for r in sorted(bad, key=lambda r: before[r][0] - before[r][1], reverse=True):
    ds, do, who = before[r]
    print(f"    {r:<6} 离自己 {ds:5.2f}mm   离 {who:<5} 只有 {do:5.2f}mm")


# ---------------------------------------------------------------- 摆位
def candidates(f, ref):
    """生成 (角度, 文字中心 x, 文字中心 y, 间隙, |对齐|) —— 按 gap/align 稳定排序。

    ⚠️ pcbnew 的 `GetTextPos()` / `GetTextAngle()` 返回的是**内部对象的引用**,
    不是副本 —— 拿它当「原值」存起来再回填等于什么都没做,后面所有位置会串成
    最后一个候选位。这里一律立刻拆成 int / float 存,踩过一次,记在这儿当路标。
    """
    t = f.Reference()
    keep_pos = (t.GetTextPos().x, t.GetTextPos().y)
    keep_ang = t.GetTextAngle().AsDegrees()
    out = []
    for ang in (keep_ang, 90.0 if keep_ang % 180 == 0 else 0.0):
        t.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
        tb = box(t.GetBoundingBox())
        w, h = tb[2] - tb[0], tb[3] - tb[1]
        bl, bt, br, bb = bodies[ref]
        bw, bh = (br - bl) / 2, (bb - bt) / 2
        bcx, bcy = (bl + br) / 2, (bt + bb) / 2
        for g in GAPS:
            for k in ALIGNS:
                out.append((ang, bcx + k * bw, bt - g - h / 2, g, abs(k)))   # 上
                out.append((ang, bcx + k * bw, bb + g + h / 2, g, abs(k)))   # 下
                out.append((ang, bl - g - w / 2, bcy + k * bh, g, abs(k)))   # 左
                out.append((ang, br + g + w / 2, bcy + k * bh, g, abs(k)))   # 右
            for sx in (-1, 1):                                              # 四个斜角
                for sy in (-1, 1):
                    out.append((ang, bcx + sx * (bw + g + w / 2),
                                bcy + sy * (bh + g + h / 2), g, 1.5))
    t.SetTextAngle(pcbnew.EDA_ANGLE(keep_ang, pcbnew.DEGREES_T))
    t.SetTextPos(pcbnew.VECTOR2I(*keep_pos))
    return out


def place(f, ref, live_silk, count_only=False):
    """给 ref 找个位置。返回 (角度, x, y, 文字框, d_self, d_other, who) 或 None。

    `count_only=True` 时只数「不算别的位号、光看固定障碍能站几个位置」——
    用来给待办排序:**越挤的越先挑**。不这么排就会出现「宽松的那个先把窄缝占了、
    挤的那个反而没地方」(R17 抢掉 R22 唯一的缝就是这么来的)。
    """
    t = f.Reference()
    keep_pos = (t.GetTextPos().x, t.GetTextPos().y)
    keep_ang = t.GetTextAngle().AsDegrees()
    cands = candidates(f, ref)
    try:
        n_ok = 0
        for extra in ((EXTRAS[-1],) if count_only else EXTRAS):
            best = None
            for ang, cx, cy, g, ak in cands:
                ix, iy = int(round(cx * IU)), int(round(cy * IU))
                t.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
                t.SetTextPos(pcbnew.VECTOR2I(ix, iy))
                tb = box(t.GetBoundingBox())
                if (tb[0] < EDGE_KEEPOUT or tb[1] < EDGE_KEEPOUT
                        or tb[2] > BOARD_W - EDGE_KEEPOUT or tb[3] > BOARD_H - EDGE_KEEPOUT):
                    continue
                cxx, cyy = center(tb)
                if any(hits(tb, p, PAD_CLR) for p in pads
                       if abs(center(p)[0] - cxx) < NEAR and abs(center(p)[1] - cyy) < NEAR):
                    continue
                if any(hits(tb, b, BODY_CLR) for _, b in body_list
                       if abs(center(b)[0] - cxx) < NEAR and abs(center(b)[1] - cyy) < NEAR):
                    continue
                if any(hits(tb, s, SILK_CLR) for s in static_silk
                       if abs(center(s)[0] - cxx) < NEAR and abs(center(s)[1] - cyy) < NEAR):
                    continue
                if any(hits(tb, s, SILK_CLR) for r2, s in live_silk.items() if r2 != ref):
                    continue
                d_self, d_other, who = measure(ref, tb)
                if d_other < d_self + need(d_self) + extra:
                    continue
                n_ok += 1
                score = (round(d_self, 3), -round(d_other - d_self, 3), ak, g, ang != 0)
                if best is None or score < best[0]:
                    best = (score, ang, ix, iy, tb, d_self, d_other, who)
            if best is not None and not count_only:
                return best[1:]
        return n_ok if count_only else None
    finally:
        t.SetTextAngle(pcbnew.EDA_ANGLE(keep_ang, pcbnew.DEGREES_T))
        t.SetTextPos(pcbnew.VECTOR2I(*keep_pos))


# 动态障碍:不需要挪的位号用它们现在的框;需要挪的先不算(它们本来就要走),
# 排到谁谁就把自己的新框加进来。顺序按位号名排,保证可复现。
live = {r: box(f.Reference().GetBoundingBox()) for r, f in visible if r not in bad}
fp_by_ref = dict(visible)

# 越挤的越先挑位置(只看固定障碍能站几个位置);同分按位号名排,保证可复现
room = {ref: place(fp_by_ref[ref], ref, {}, count_only=True) for ref in bad}
order = sorted(bad, key=lambda r: (room[r], r))

moved, hidden_now = [], []
for ref in order:
    f = fp_by_ref[ref]
    res = place(f, ref, live)
    if res is None:
        hidden_now.append(ref)
        continue
    ang, ix, iy, tb, d_self, d_other, who = res
    moved.append((ref, ang, ix, iy, tb, before[ref], (d_self, d_other, who)))
    live[ref] = tb


# ---------------------------------------------------------------- F7 那 0.9mm
def try_align_f7():
    """支路保险丝 F2–F6 在 x = 80/66/52/38/24(14mm 等距),F7 却在 10.90 而不是 10.00。

    **看着像手滑,其实是躲 TP2。** 真把 F7 挪到 10.00,它的 2 脚(CH6_VOUT,
    3.80×3.00 焊盘)左边缘落到 x=4.70,而 TP2 的 GND 测试盘(φ1.5,中心 x=4.00)
    右边缘在 4.75 —— **两个不同网络的焊盘直接压上 0.05mm,是短路,不是间距不足**。
    实跑 kicad-cli DRC 复核,新增 9 条:

        shorting_items    F7 pad2 [CH6_VOUT] ↔ TP2 pad1 [GND]
        shorting_items    F7 pad1 [V24_BUS]  ↔ Track [CH6_CW_D]
        courtyards_overlap  F7 ↔ TP2
        solder_mask_bridge  ×2 / clearance ×2 / silk_over_copper ×2

    要挪就得先把 TP2 让开,那已经超出「只动丝印」的范围。**所以 F7 保持 10.90。**
    这个函数只做几何复核并报告,不写盘;哪天 TP2 挪走了,它会自己变成「可以挪」。
    """
    f7 = board.FindFootprintByReference("F7")
    x = f7.GetPosition().x / IU
    if abs(x - 10.90) > 0.001:
        print(f"\nF7:当前 x={x:.3f},不是预期的 10.900,先查清楚再说,本轮不动它")
        return
    dx = 10.00 - x
    clash = []
    for p in f7.Pads():
        pb = box(p.GetBoundingBox())
        pb = (pb[0] + dx, pb[1], pb[2] + dx, pb[3])
        for g in fps:
            if g.GetReference() == "F7":
                continue
            for q in g.Pads():
                if p.GetNetname() == q.GetNetname():
                    continue
                d = dist(pb, box(q.GetBoundingBox()))
                if d < 0.20:
                    clash.append((p.GetNumber(), p.GetNetname(),
                                  g.GetReference(), q.GetNumber(), q.GetNetname(), d))
    print("\nF7 对齐 CH6 列(x 10.900 → 10.000)的复核:")
    if clash:
        for n, net, gr, qn, qnet, d in clash:
            kind = "短路(直接压上)" if d <= 0 else f"间距只剩 {d:.2f}mm"
            print(f"    ✗ F7 pad{n} [{net}] ↔ {gr} pad{qn} [{qnet}] —— {kind}")
        print("    → **不挪**。挪它要先让开 TP2,那超出本轮「只动丝印」的范围;")
        print("      实测 DRC 会新增 9 条(含 2 条 shorting_items),见本函数 docstring。")
    else:
        print("    与其它焊盘无冲突 —— 但仍需 DRC 未连接检查确认铜箔连通后才可写盘")


try_align_f7()


# ---------------------------------------------------------------- 报告
print(f"\n重新摆位 {len(moved)} 个位号:")
for ref, ang, ix, iy, tb, (ds0, do0, who0), (ds1, do1, who1) in moved:
    print(f"    {ref:<6} ({ix/IU:7.3f},{iy/IU:7.3f}) {int(ang):>3}°  "
          f"自己 {ds0:5.2f}→{ds1:5.2f}   最近的别人 {do0:5.2f}({who0})→{do1:5.2f}({who1})")

if hidden_now:
    print(f"\n摆不下、只能隐藏的位号({len(hidden_now)} 个):")
    for ref in hidden_now:
        ds, do, who = before[ref]
        bl, bt, br, bb = bodies[ref]
        print(f"    {ref:<6} 元件外框 {br-bl:.2f}×{bb-bt:.2f}mm @({bl:.1f},{bt:.1f});"
              f" 原本离自己 {ds:.2f}mm、离 {who} {do:.2f}mm")
        print(f"           四边 + 四角 × 5 对齐 × 5 间隙 × 0/90° 全试过,没有一个位置能同时"
              f"「不压焊盘 / 不压别的外框 / 不压别的丝印 / 且满足歧义判据」")
else:
    print(f"\n没有需要隐藏的位号 —— {len(bad)} 个全部摆下了")

if not moved and not hidden_now:
    print("\n✅ 没有位号命中歧义判据,0 处需要处理(幂等)")
    raise SystemExit(0)

if CHECK_ONLY:
    print("\n(--check:只报告,没有写盘)")
    raise SystemExit(1)

for ref, ang, ix, iy, tb, _, _ in moved:
    t = fp_by_ref[ref].Reference()
    t.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
    t.SetTextPos(pcbnew.VECTOR2I(ix, iy))
for ref in hidden_now:
    fp_by_ref[ref].Reference().SetVisible(False)

board.Save(str(BOARD))
print(f"\n✅ 已写回板文件:{len(moved)} 个重摆、{len(hidden_now)} 个隐藏,铜箔一个字节没动")
