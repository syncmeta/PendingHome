#!/usr/bin/env python3
"""生成初始 PCB(cct-main.kicad_pcb):板框、M3 孔、分区摆放、焊盘赋网络。

必须用 KiCad 自带 python 运行(需要 pcbnew 模块):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_pcb.py

布线不在本脚本范围 —— 输出的是"元件就位 + 网络就绪 + 飞线可见"的起点板。
分区坐标依据 layout-guide.md。
"""
import re, sys, importlib.util
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = Path(__file__).parent
PRETTY = str(HERE / "kicad-lib" / "cct.pretty")

# ---- 载入网表数据(gen_sch.py 的 P 表与引脚解析) ----
spec = importlib.util.spec_from_file_location("g", HERE / "gen_sch.py")
g = importlib.util.module_from_spec(spec)
_argv = sys.argv; sys.argv = ["gen_sch.py", "--noop"]
try:
    spec.loader.exec_module(g)
except SystemExit:
    pass
sys.argv = _argv

syms = g.parse_lib()
cmap = g.build_cid_map(syms)
libtxt = open(HERE / "kicad-lib" / "cct.kicad_sym", encoding="utf-8").read()

def fp_of(cid):
    sn = cmap[cid]
    m = re.search(r'\(symbol "' + re.escape(sn) + r'".*?"Footprint"\s+"(?:cct:)?([^"]*)"',
                  libtxt, re.S)
    return m.group(1)

# ref → {pad号: 网络}
ref_padnets = {}
for ref, cid, pins in g.P:
    sn = cmap[cid]
    d = {}
    for pname, net in pins.items():
        for hit in g.resolve_pin(sn, syms, pname, cid):
            d[hit[0]] = net
    ref_padnets[ref] = (cid, d)


# ---- 封装包络测量(焊盘 ∪ courtyard,相对原点,含旋转)----
_env_cache = {}
def envelope(fpname, rot):
    key = (fpname, rot % 360)
    if key in _env_cache:
        return _env_cache[key]
    fp = pcbnew.FootprintLoad(PRETTY, fpname)
    fp.SetOrientationDegrees(rot)
    xs, ys = [], []
    for pad in fp.Pads():
        bb = pad.GetBoundingBox()
        xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
        ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    bb = fp.GetBoundingBox(False)  # 含 courtyard/丝印外的图形,不含文本
    xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
    ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    env = (min(xs), min(ys), max(xs), max(ys))
    _env_cache[key] = env
    return env

def env_of_ref(ref):
    cid = ref_padnets[ref][0]
    rot = POS[ref][2] if ref in POS else 0
    return envelope(fp_of(cid), rot)

def stack_column(x, items, y_start, margin=0.4):
    """items: [(ref, xoff, rot)];按各自真实包络自动向下堆叠,返回末端 y。"""
    y = y_start
    for ref, xoff, rot in items:
        cid = ref_padnets[ref][0]
        e = envelope(fp_of(cid), rot)
        top = -e[1]          # 原点上方的伸出量
        POS[ref] = (x + xoff, y + top, rot)
        y = y + top + e[3] + margin
    return y

# ============================================================================
# 摆放计划(全自动纵向分区:每区从上一区实测末端开始)
# ============================================================================
POS = {}

def at(ref, x, y, rot=0):
    POS[ref] = (x, y, rot)

# ---- 封装包络测量(焊盘 ∪ courtyard,相对原点,含旋转)----
_env_cache = {}
def envelope(fpname, rot):
    key = (fpname, rot % 360)
    if key in _env_cache:
        return _env_cache[key]
    fp = pcbnew.FootprintLoad(PRETTY, fpname)
    fp.SetOrientationDegrees(rot)
    xs, ys = [], []
    for pad in fp.Pads():
        bb = pad.GetBoundingBox()
        xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
        ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    bb = fp.GetBoundingBox(False)
    xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
    ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    env = (min(xs), min(ys), max(xs), max(ys))
    _env_cache[key] = env
    return env

def env_ref(ref):
    return envelope(fp_of(ref_padnets[ref][0]), 0)

def place_row(y, items, margin=0.5):
    """items: [(ref, x, rot)];全部顶边贴 y 放置,返回行底边。"""
    bot = y
    for ref, x, rot in items:
        e = envelope(fp_of(ref_padnets[ref][0]), rot)
        POS[ref] = (x, y - e[1], rot)
        bot = max(bot, y - e[1] + e[3])
    return bot + margin

BOARD_W = 110
BOARD_H = 145   # v15 实测分区后收敛值

# ============================================================================
# 布局架构(v15):所有对外接线集中在上板边
#   上边:24V 输入 J1(最左)+ CH1..CH6 灯带端子
#   左列:输入保护与计量链(F1→Q1/Q2→RS1→INA237),紧邻 J1,避免 15A 主干折返
#   右侧六列:每路 保险丝→MOS→续流→TVS→本地去耦
#   下方:驱动区 → 大电解排 → 控制区(buck/USB/ESP32,接口在下板边)
# ============================================================================

TOP_Y = 8.0          # 上边所有端子的中心 y
ZONE_Y = 16.0        # 端子下方各列的起始 y
LCOL_X = 11.0        # 左侧保护列中心
COL_X = [28, 42, 56, 70, 84, 98]

# ---- 上板边:24V 输入 + 6 路灯带端子 ----
at("J1", LCOL_X, TOP_Y, 180)

# ---- 左列:输入保护与计量(与 J1 同侧,主干不折返)----
ly = place_row(ZONE_Y, [("F1", LCOL_X, 0)])
ly = place_row(ly, [("Q1", LCOL_X, 0)])
ly = place_row(ly, [("Q2", LCOL_X, 0)])
ly = place_row(ly, [("DZ1", LCOL_X - 4, 0), ("R2", LCOL_X + 3.5, 0)])
ly = place_row(ly, [("R1", LCOL_X - 4, 0), ("R3", LCOL_X + 3.5, 0)])
ly = place_row(ly, [("Q3", LCOL_X - 4, 0)])
ly = place_row(ly, [("RS1", LCOL_X, 0)])
ly = place_row(ly, [("U1", LCOL_X - 2, 0), ("C6", LCOL_X + 5, 0)])
ly = place_row(ly, [("D1", LCOL_X, 0)])
left_end = ly

# ---- 六列功率级 ----
CH = [
    (1, "F2", "J3", "Q7", "Q8", "R16", "R17", "R18", "R19", "D5", "D6", "D7", "D8", "C16", "C17", "LED2", "LED3", "R20", "R21"),
    (2, "F3", "J4", "Q9", "Q10", "R22", "R23", "R24", "R25", "D9", "D10", "D11", "D12", "C18", "C19", "LED4", "LED5", "R26", "R27"),
    (3, "F4", "J5", "Q11", "Q12", "R28", "R29", "R30", "R31", "D13", "D14", "D15", "D16", "C20", "C21", "LED6", "LED7", "R32", "R33"),
    (4, "F5", "J6", "Q13", "Q14", "R34", "R35", "R36", "R37", "D17", "D18", "D19", "D20", "C22", "C23", "LED8", "LED9", "R38", "R39"),
    (5, "F6", "J7", "Q15", "Q16", "R40", "R41", "R42", "R43", "D21", "D22", "D23", "D24", "C24", "C25", "LED10", "LED11", "R44", "R45"),
    (6, "F7", "J8", "Q17", "Q18", "R46", "R47", "R48", "R49", "D25", "D26", "D27", "D28", "C26", "C27", "LED12", "LED13", "R50", "R51"),
]
col_end = 0
for i, (n, F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw) in enumerate(CH):
    x = COL_X[i]
    at(J, x, TOP_Y, 180)
    y = place_row(ZONE_Y, [(F, x, 0)])
    y = place_row(y, [(Dfc, x - 2.6, 0)])
    y = place_row(y, [(Dfw_, x + 2.6, 0)])
    y = place_row(y, [(Qc, x, 0)])
    y = place_row(y, [(Qw, x, 0)])
    y = place_row(y, [(Dtc, x - 2.6, 0)])
    y = place_row(y, [(Dtw, x + 2.6, 0)])
    y = place_row(y, [(Ce, x - 1, 0)])
    y = place_row(y, [(Rgc, x - 4.2, 0), (Cm, x - 1, 0), (Rgw, x + 4.2, 0)])
    y = place_row(y + 0.9, [(Rpc, x - 4.2, 0), (Rpw, x + 4.2, 0)])
    col_end = max(col_end, y)

# ---- 驱动区(HCT245 + 12 组通道指示灯)----
DRV_Y = max(col_end, left_end) + 0.8
drv_end = place_row(DRV_Y, [("C14", 26, 90), ("U6", 34, 0), ("U7", 56, 0), ("C15", 64, 90),
                            ("R13", 72, 0), ("Q6", 77, 0), ("R14", 82, 0), ("R15", 86, 0)])
LEDS = [("LED2","R20"),("LED3","R21"),("LED4","R26"),("LED5","R27"),("LED6","R32"),("LED7","R33"),
        ("LED8","R38"),("LED9","R39"),("LED10","R44"),("LED11","R45"),("LED12","R50"),("LED13","R51")]
_slots = [4+3.2*i for i in range(6)] + [40+3.2*i for i in range(3)] + [92+3.2*i for i in range(3)]
for (led, res), lx in zip(LEDS, _slots):
    at(led, lx, DRV_Y + 2.4, 0)
    at(res, lx, DRV_Y + 5.4, 0)

# ---- 大电解排(V24_PROT 节点,经左列宽铜连接)----
BULK_Y = drv_end + 0.8
bulk_end = place_row(BULK_Y, [("C1", 12, 0), ("C2", 26, 0), ("C3", 40, 0),
                              ("C4", 54, 0), ("C5", 68, 0)])

# ---- 控制区 ----
CT_Y = bulk_end + 0.8
y1 = place_row(CT_Y, [("PTC1", 6, 0), ("R52", 12, 0), ("R53", 16, 0), ("C32", 22, 0),
                      ("C34", 27, 90), ("R62", 32, 0), ("R65", 36, 0), ("SW2", 42, 0),
                      ("SW1", 51, 0), ("LED1", 57, 0), ("R8", 61, 0), ("R4", 65, 0),
                      ("C12", 69, 0), ("R5", 74, 0), ("C10", 78, 0), ("C11", 82, 0)])
y2 = place_row(y1, [("L1", 14, 0), ("C33", 24, 0), ("U2", 32, 0),
                    ("R66", 39, 0), ("C39", 43, 0), ("C35", 60, 0)])
y2b = place_row(y1 + 7.5, [("R67", 39, 0), ("C40", 43, 0), ("C38", 47, 0)])
y3 = place_row(max(y2, y2b), [("D2", 24, 0), ("R63", 31, 0), ("C36", 36, 0),
                     ("D3", 42, 0), ("U3", 50, 0), ("C13", 58, 0), ("U5", 66, 0),
                     ("Q4", 74, 0), ("R11", 78, 0)])
y3b = place_row(y3, [("R64", 31, 0), ("C37", 36, 0), ("D4", 42, 0), ("C41", 49, 0),
                     ("Q5", 74, 0), ("R12", 78, 0)])
y_ctl_end = y3b
print(f"[zones] 左列 {left_end:.1f} | 列尾 {col_end:.1f} | 驱动 {drv_end:.1f} | 电解 {bulk_end:.1f} | 控制 {y_ctl_end:.1f}")

# ---- 下板边:调试/传感器/开关接口 ----
for i, r in enumerate(["C28", "C29", "C30", "C31"]):
    at(r, 55 + i * 4, BOARD_H - 12.5, 0)
for i, r in enumerate(["R58", "R59", "R60", "R61"]):
    at(r, 55 + i * 4, BOARD_H - 10, 0)
for i, r in enumerate(["R54", "R55", "R56", "R57"]):
    at(r, 55 + i * 4, BOARD_H - 7.5, 0)
at("C42", 46, BOARD_H - 12.5, 0); at("C43", 46, BOARD_H - 10, 0)
at("R9", 50, BOARD_H - 12.5, 0); at("R10", 50, BOARD_H - 10, 0)
at("J9", 10, BOARD_H - 4, 180)
at("J10", 22, BOARD_H - 4, 180)
at("J11", 36, BOARD_H - 3, 180)
at("J2", 76, BOARD_H - 4, 0)
at("U4", 96, BOARD_H - 12, 180)


def auto_nudge(max_iter=25):
    # 固定件:全部端子、IC、模组、测试点;其余小件可被推开
    fixed = {"J1","F1","J2","J9","J10","J11","U4","U6","U7","U2","U5","L1"} | set(f"J{i}" for i in range(3,9))
    for it in range(max_iter):
        envs = {}
        for ref in ref_padnets:
            if ref not in POS: continue
            x, y, rot = POS[ref]
            e = envelope(fp_of(ref_padnets[ref][0]), rot)
            envs[ref] = (x + e[0], y + e[1], x + e[2], y + e[3])
        for tref, _n, tx, ty in TPS:
            envs[tref] = (tx - 1.3, ty - 1.3, tx + 1.3, ty + 1.3)
            fixed.add(tref)
        moved = 0
        refs = sorted(envs)
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                ra, rb = refs[i], refs[j]
                a, b = envs[ra], envs[rb]
                ox = min(a[2], b[2]) - max(a[0], b[0])
                oy = min(a[3], b[3]) - max(a[1], b[1])
                if ox <= 0.05 or oy <= 0.05: continue
                mover = rb if rb not in fixed else (ra if ra not in fixed else None)
                if mover is None: continue
                other = ra if mover == rb else rb
                mx, my, mr = POS[mover]
                oxc, oyc = ((envs[other][0]+envs[other][2])/2, (envs[other][1]+envs[other][3])/2)
                if ox <= oy:
                    mx += (ox + 0.3) * (1 if mx >= oxc else -1)
                else:
                    my += (oy + 0.3) * (1 if my >= oyc else -1)
                POS[mover] = (mx, my, mr)
                x, y, rot = POS[mover]
                e = envelope(fp_of(ref_padnets[mover][0]), rot)
                envs[mover] = (x + e[0], y + e[1], x + e[2], y + e[3])
                moved += 1
        if moved == 0:
            print(f"[nudge] 第 {it+1} 轮收敛")
            return True
    print(f"[nudge] {max_iter} 轮未完全收敛")
    return False

TPS = [("TP1", "V24_BUS", 21, 30), ("TP2", "GND", 106, 20),
       ("TP3", "V5_SYS", 70, 128.5), ("TP4", "V3P3", 106, CT_Y + 6),
       ("TP5", "CH1_CW_GR", 106, 45), ("TP6", "CH1_CW_D", 106, 33)]
auto_nudge()

# ============================================================================
# 建板
# ============================================================================
board = pcbnew.CreateEmptyBoard()

# 网络
nets = {}
def net_of(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n
    return nets[name]

missing_pos, missing_pad = [], []
for ref, (cid, padnets) in ref_padnets.items():
    fpname = fp_of(cid)
    fp = pcbnew.FootprintLoad(PRETTY, fpname)
    if fp is None:
        raise SystemExit(f"footprint 载入失败: {fpname}")
    fp.SetReference(ref)
    fp.SetValue(cid)
    if ref not in POS:
        missing_pos.append(ref)
        fp.SetPosition(VECTOR2I(FromMM(120), FromMM(10 + 5 * len(missing_pos))))
    else:
        x, y, rot = POS[ref]
        fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
        fp.SetOrientationDegrees(rot)
    board.Add(fp)
    have = {p.GetNumber() for p in fp.Pads()}
    for padno, netname in padnets.items():
        if netname.startswith("NC_"):
            continue
        if padno not in have:
            missing_pad.append((ref, padno))
            continue
        for p in fp.Pads():
            if p.GetNumber() == padno:
                p.SetNet(net_of(netname))

# 测试焊盘(标准库 TestPoint)
KISYS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
for ref, netname, x, y in TPS:
    fp = pcbnew.FootprintLoad(KISYS + "/TestPoint.pretty", "TestPoint_Pad_D1.5mm")
    if fp is None:
        continue
    fp.SetReference(ref); fp.SetValue(netname)
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    board.Add(fp)
    for p in fp.Pads():
        p.SetNet(net_of(netname))

# M3 安装孔(右下角避开天线净空)
for i, (x, y) in enumerate([(4, 66), (BOARD_W - 4, 68), (4, 133), (BOARD_W - 4, 115)]):
    fp = pcbnew.FootprintLoad(KISYS + "/MountingHole.pretty", "MountingHole_3.2mm_M3")
    if fp is None:
        break
    fp.SetReference(f"H{i+1}"); fp.SetValue("M3")
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    board.Add(fp)

# 板框
def edge(x1, y1, x2, y2):
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    seg.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    seg.SetLayer(pcbnew.Edge_Cuts)
    seg.SetWidth(FromMM(0.1))
    board.Add(seg)
edge(0, 0, BOARD_W, 0); edge(BOARD_W, 0, BOARD_W, BOARD_H); edge(BOARD_W, BOARD_H, 0, BOARD_H); edge(0, BOARD_H, 0, 0)


# ---- 摆放重叠自检(包络级,与 DRC 独立)----
def overlap_report():
    envs = {}
    for tref, _n, tx, ty in TPS:
        envs[tref] = (tx - 1.3, ty - 1.3, tx + 1.3, ty + 1.3)
    for ref in list(ref_padnets) :
        if ref not in POS: continue
        x, y, rot = POS[ref]
        e = envelope(fp_of(ref_padnets[ref][0]), rot)
        envs[ref] = (x + e[0], y + e[1], x + e[2], y + e[3])
    refs = sorted(envs)
    bad = []
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            a, b = envs[refs[i]], envs[refs[j]]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > 0.05 and oy > 0.05:
                bad.append((refs[i], refs[j], round(ox, 2), round(oy, 2)))
    if bad:
        print(f"⚠️ 包络重叠 {len(bad)} 对:")
        for a, b, ox, oy in bad[:30]:
            print(f"   {a} × {b}  需挪 x:{ox} 或 y:{oy}")
    else:
        print("✅ 无包络重叠")
overlap_report()

out = str(HERE / "cct-main.kicad_pcb")
pcbnew.SaveBoard(out, board)
print(f"✅ 保存 {out}")
print(f"   元件 {len(ref_padnets)} + 测试点 {len(TPS)} + 安装孔 4;网络 {len(nets)}")
if missing_pos:
    print("⚠️ 未指定坐标(放板外待手摆):", missing_pos)
if missing_pad:
    print("⚠️ 焊盘号不匹配:", missing_pad[:20])
