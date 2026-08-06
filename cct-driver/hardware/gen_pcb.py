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

BOARD_H = 150

# ---- 六列功率级 ----
COL_X = [14, 28.5, 43, 57.5, 72, 86]
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
    at(J, x, 8, 180)
    y = place_row(14.5, [(F, x, 0)])
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

# ---- 驱动区 ----
DRV_Y = col_end + 0.6
drv_end = place_row(DRV_Y, [("C14", 27, 90), ("U6", 35, 0), ("U7", 55, 0), ("C15", 63, 90),
                            ("R13", 70, 0), ("Q6", 74.5, 0), ("R14", 79, 0), ("R15", 83, 0)])
# 12 组通道指示灯(电气上属驱动区:接 HCT245 输出)
LEDS = [("LED2","R20"),("LED3","R21"),("LED4","R26"),("LED5","R27"),("LED6","R32"),("LED7","R33"),
        ("LED8","R38"),("LED9","R39"),("LED10","R44"),("LED11","R45"),("LED12","R50"),("LED13","R51")]
_slots = [8+3*i for i in range(6)] + [41+3*i for i in range(3)] + [88+3*i for i in range(3)]
for (led, res), lx in zip(LEDS, _slots):
    at(led, lx, DRV_Y + 2.4, 0)
    at(res, lx, DRV_Y + 5.4, 0)

# ---- 功率脊椎(x 位置经包络审计)----
SP_Y = drv_end + 0.6
ends = []
ends.append(place_row(SP_Y + 2, [("J1", 5, 90)]))
ends.append(place_row(SP_Y + 1.5, [("F1", 26.5, 0)]))
y = place_row(SP_Y, [("Q1", 43, 0)]); ends.append(place_row(y, [("Q2", 43, 0)]))
y = place_row(SP_Y, [("DZ1", 50.8, 0)])
y = place_row(y, [("R1", 50.8, 0)])
ends.append(place_row(y, [("Q3", 50.8, 0)]))
y = place_row(SP_Y, [("R2", 54.5, 0)]); ends.append(place_row(y, [("R3", 54.5, 0)]))
row1 = place_row(SP_Y, [("C1", 62, 0), ("C2", 74.4, 0), ("C3", 86.8, 0)])
row2 = place_row(SP_Y + 13.4, [("RS1", 41, 0), ("C6", 50, 0), ("U1", 56, 0), ("C4", 66, 0), ("C5", 78.4, 0), ("D1", 89, 0)])
sp_end = max(ends + [row1, row2])

# ---- 控制区 ----
CT_Y = sp_end + 0.6
y1 = place_row(CT_Y, [("PTC1", 14, 0), ("R52", 19, 0), ("R53", 22.5, 0), ("C32", 27, 0),
                      ("C34", 31.5, 90), ("R62", 36, 0), ("R65", 40, 0), ("SW2", 45, 0),
                      ("SW1", 54, 0), ("LED1", 59, 0), ("R8", 63, 0), ("R4", 67, 0),
                      ("C12", 71, 0), ("R5", 75, 0), ("C10", 79, 0), ("C11", 83, 0)])
y2 = place_row(y1, [("L1", 20, 0), ("C33", 29, 0), ("U2", 36, 0),
                    ("R66", 42, 0), ("C39", 46, 0), ("C35", 64, 0)])
y2b = place_row(y1 + 7.5, [("R67", 42, 0), ("C40", 46, 0), ("C38", 50, 0)])
y3 = place_row(max(y2, y2b), [("D2", 27, 0), ("R63", 33, 0), ("C36", 37.5, 0),
                     ("D3", 42.5, 0), ("U3", 52, 0), ("C13", 58, 0), ("U5", 65, 0),
                     ("Q4", 72.5, 0), ("R11", 76.5, 0)])
y3b = place_row(y3, [("R64", 33, 0), ("C37", 37.5, 0), ("D4", 42.5, 0), ("C41", 49.5, 0),
                     ("Q5", 72.5, 0), ("R12", 76.5, 0)])
y_ctl_end = y3b
at("C42", 44, BOARD_H - 12.5, 0); at("C43", 44, BOARD_H - 10, 0)
at("R9", 47, BOARD_H - 12.5, 0); at("R10", 47, BOARD_H - 10, 0)
print(f"[zones] 列尾 {col_end:.1f} | 驱动 {drv_end:.1f} | 脊椎 {sp_end:.1f} | 控制 {y_ctl_end:.1f}(板高 {BOARD_H})")

# ---- 底边固定带(与 RC 阵列 x 错开共存)----
for i, r in enumerate(["C28", "C29", "C30", "C31"]):
    at(r, 51 + i * 4, BOARD_H - 12.5, 0)
for i, r in enumerate(["R58", "R59", "R60", "R61"]):
    at(r, 51 + i * 4, BOARD_H - 10, 0)
for i, r in enumerate(["R54", "R55", "R56", "R57"]):
    at(r, 51 + i * 4, BOARD_H - 7.5, 0)
at("J9", 10, BOARD_H - 4, 180)
at("J10", 22, BOARD_H - 4, 180)
at("J11", 36, BOARD_H - 3, 180)
at("J2", 70, BOARD_H - 4, 0)
at("U4", 88, BOARD_H - 12, 180)   # 天线悬出下板边

def auto_nudge(max_iter=25):
    # 测试点作为固定障碍参与避让
    fixed = {"J1","F1","J2","J9","J10","J11","U4","U6","U7"} | set(f"J{i}" for i in range(3,9))
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
                envs.pop(mover, None)
                x, y, rot = POS[mover]
                e = envelope(fp_of(ref_padnets[mover][0]), rot)
                envs[mover] = (x + e[0], y + e[1], x + e[2], y + e[3])
                moved += 1
        if moved == 0:
            print(f"[nudge] 第 {it+1} 轮收敛")
            return True
    print(f"[nudge] {max_iter} 轮未完全收敛")
    return False
TPS = [("TP1", "V24_BUS", 46, 74), ("TP2", "GND", 96, 68),
       ("TP3", "V5_SYS", 40, 101), ("TP4", "V3P3", 53, 99),
       ("TP5", "CH1_CW_GR", 3, 60.5), ("TP6", "CH1_CW_D", 3, 31)]
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
for i, (x, y) in enumerate([(4, 4), (96, 4), (4, BOARD_H - 16), (96, BOARD_H - 30)]):
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
edge(0, 0, 100, 0); edge(100, 0, 100, BOARD_H); edge(100, BOARD_H, 0, BOARD_H); edge(0, BOARD_H, 0, 0)


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
