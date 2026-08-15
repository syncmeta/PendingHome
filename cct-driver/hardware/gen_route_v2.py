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
def net(name):
    if name not in NET:
        raise SystemExit(f"网络不存在:{name}")
    return NET[name]


# 焊盘坐标**在动手删东西之前**就抄成普通浮点数存下来。
# 原因还是那个 SWIG 坑:`board.Remove()` 调用过之后,先前拿到的 PAD 代理对象会失效
#(连 `GetPosition().x` 都取不到),而 clear_copper() 是本脚本第一件事。
PADXY = {}
for fp in board.GetFootprints():
    _ref = fp.GetReference()
    for p in fp.Pads():
        q = p.GetPosition()
        PADXY.setdefault((_ref, p.GetNetname()), (ToMM(q.x), ToMM(q.y)))


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
vl = P("PTC1", "V24_LOGIC")
c35 = P("C35", "V24_LOGIC")
path([vl, (128.6, vl[1]), (128.6, 24.0), (c35[0], 24.0), (c35[0], c35[1])],
     B, W_PWR1, "V24_LOGIC")
for r in ("C32", "C33", "C34", "R66"):
    p2 = P(r, "V24_LOGIC")
    path([(p2[0], 24.0), (p2[0], p2[1] - 2.0), p2], B, W_PWR1 if r != "R66" else W_SIG,
         "V24_LOGIC")
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
