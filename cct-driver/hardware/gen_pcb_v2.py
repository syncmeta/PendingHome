#!/usr/bin/env python3
"""v2 摆位:按 `floorplan-v2.md` 的分区表与行结构,从网表重建 cct-main.kicad_pcb。

必须用 KiCad 自带 python 运行(需要 pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_pcb_v2.py

**这一步只做摆位**:板框、安装孔、天线禁区、元件就位、焊盘赋网络。
布线与覆铜在 `gen_route_v2.py`(下一步)。脚本幂等 —— 每次都从空板重建,
输出只取决于 gen_sch.py 的 P 表 + 本文件的 POS 表。

它取代 `gen_pcb.py` + `gen_rotate180.py` + `gen_led_to_output.py` 的摆位部分。
老那条路(自动布线器 + 20 个 gen_route_repair*.py 打补丁)不再使用。

坐标系:原点左上角,x 向右,y 向下,mm。**文件方向 = 上墙安装方向**(接线端子在下边)。
"""
import re, sys, importlib.util
from pathlib import Path

import pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = Path(__file__).parent
PRETTY = str(HERE / "kicad-lib" / "cct.pretty")
KISYS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"

BOARD_W = 130.0
BOARD_H = 164.0

# ---- 载入网表(gen_sch.py 的 P 表就是唯一的网表源头)----
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
libtxt = (HERE / "kicad-lib" / "cct.kicad_sym").read_text(encoding="utf-8")

# 符号库里没有的新料号借用同型符号画原理图(gen_sch.CID_SYMBOL_ALIAS),
# 但**封装不能跟着借** —— R68 是 1206、C44/C45/C46 是 1210,借的符号是 0603。
FP_OVERRIDE = {"R68": "R1206"}


def fp_of(ref, cid):
    if ref in FP_OVERRIDE:
        return FP_OVERRIDE[ref]
    sn = cmap[g.CID_SYMBOL_ALIAS.get(cid, cid)]
    m = re.search(r'\(symbol "' + re.escape(sn) + r'".*?"Footprint"\s+"(?:cct:)?([^"]*)"',
                  libtxt, re.S)
    return m.group(1)


# ============================================================================
# 一个电气端子 = 多个焊盘 的显式对照表
# ============================================================================
# 为什么需要它:有些封装的一个电气端子在板上是**好几个焊盘**。原理图只有一个引脚号,
# 直接按引脚号赋网络就会只喂到其中一个焊盘,剩下的悬空 —— 或者更糟,把两个不同的网
# 喂到**同一块金属**上。
#
# ⚠️ F1 曾经就是后者,而且是实打实的短路:Keystone 3557-2 是「一颗保险丝、两个夹子」的座,
#    每个夹子两根引脚。老封装把四根脚编成 1/2/3/4,而 1、2 是**同一个夹子** ——
#    原理图的「1 进 2 出」照编号落下去,进线和出线就被夹子的金属短接,15A 主保险丝被完全旁路。
#
#    2026-08-16 已在**库封装那一层**根治:左夹两盘都编号 1、右夹两盘都编号 2
#    (提交 0de33f0)。KiCad 本来就是这么表达「一个端子多个焊盘」的,所以这里
#    **不再需要任何覆盖** —— 按编号赋网络自然就落到两个不同的夹子上。
#    `check-multipad-mapping.py` 会盯着这件事,退回旧接法它会报错。
#
# 这张表现在是空的。将来若再遇到「一个端子多个焊盘」而封装编号又改不了的情况,
# 才往这里加,并在 verify_netlist_v2.py 的报表里显式列出来给人审。
PAD_GROUPS = {}

# ref → (cid, {padno: net})
ref_padnets = {}
for ref, cid, pins in g.P:
    d = {}
    grp = PAD_GROUPS.get(ref, {})
    for pname, net in pins.items():
        for hit in g.resolve_pin(cmap[g.CID_SYMBOL_ALIAS.get(cid, cid)], syms, pname, cid):
            for padno in grp.get(hit[0], [hit[0]]):
                d[padno] = net
    ref_padnets[ref] = (cid, d)

# ---- 测试焊盘(不在 P 表里,是纯板级件)----
TPS = [
    ("TP1", "V24_BUS",       96.0,  71.0),    # B0 脊椎
    ("TP2", "GND",          126.5,  76.5),    # D0
    ("TP3", "V5_SYS",       127.0,  36.0),    # A4
    ("TP4", "V3P3",         127.0,  45.0),    # A4
    ("TP5", "CH1_WW_GR",    101.5, 120.84),   # C1 右肩:紧挨 Rg_ww / Q8 栅极
    ("TP6", "CH1_WW_D",     101.5, 116.24),   # C1 右肩:紧挨 D6 / Q8 漏极
    ("TP7", "MASTER_OFF_TP", 26.0,  54.5),    # A5:总断路控制焊盘
    ("TP8", "PMOS_GATE",    123.0, 116.5),    # D0:防反接 P-MOS 栅极
    ("TP9", "GND",          100.0,  47.0),   # A4:buck 就近地参考
]

# ---- 安装孔(§A4c,按受力点重排 4 → 9 个)----
HOLES = [
    ("H1",   4.0,  36.0), ("H2", 126.0,  12.0), ("H3",  58.0,   9.0),
    ("H4",   4.0,  71.0), ("H5", 126.0,  66.0),
    ("H6",  15.0, 158.0), ("H7",  50.0, 158.0), ("H8",  85.0, 158.0),
    ("H9", 117.0, 158.0),
]

# ============================================================================
# 摆位表 —— (x, y, 旋转)。y 全部是**封装原点**的 y,不是 courtyard 中心。
# ============================================================================
POS = {}


def at(ref, x, y, rot=0):
    POS[ref] = (float(x), float(y), float(rot))


# ---------------- A1 主控区 x 0–40 y 0–62 ----------------
at("U4",  16.6, 12.6, 0)        # 天线朝左出板边;courtyard x 0.03–25.62
at("LED1", 30.0,  8.0, 0)
at("R8",   34.5,  8.0, 0)
at("C10",  10.5, 29.5, 0)       # V3P3 去耦。这一排整体下移 3.5mm,
                                # 为的是在 U4 下方腾出 y 22.4–28 那条横向车道带 ——
                                # 右边三个接口(干接点/I2C/UART)的 8 根信号要横穿整块板回 MCU
at("C11",  15.0, 29.5, 0)
at("R4",   19.5, 29.5, 0)       # V3P3–EN
at("C12",  24.0, 29.5, 0)       # EN–GND
at("R5",   28.5, 29.5, 0)       # V3P3–IO0
at("SW2",  11.0, 34.0, 0)       # EN(复位);x 让开 H1(4,36) 的 courtyard
at("SW1",  22.0, 34.0, 0)       # IO0(BOOT)

# ---------------- A2 USB / 串口区 x 40–66 y 0–62 ----------------
at("J2",   48.0,  6.5, 180)     # Type-C 上板边,插拔朝外;右缘 52.51,给 H3 让开 2.0mm
at("R9",   44.0, 11.5, 0)       # CC1 下拉
at("R10",  48.0, 11.5, 0)       # CC2 下拉
at("C13",  41.0, 18.0, 0)
at("U5",   48.0, 18.0, 0)       # CH340C;上移 1mm,给下方那条横向车道带让路
at("Q4",   41.0, 46.5, 0)   # 自动下载那四件排成一行,压在 PWM 车道带以下、5V 横轨以上
                            #(y22–28 是接口总线、y37–46 是 PWM 车道,都不能占)
at("R11",  45.0, 46.5, 0)
at("Q5",   49.0, 46.5, 0)
at("R12",  53.0, 46.5, 0)

# ---------------- A3 传感器 / 干接点接口区 x 66–130 y 0–26 ----------------
at("J11",  76.0,  5.0, 0)       # 干接点 5P
at("J10",  94.0,  5.0, 0)       # UART 4P
at("J9",  112.0,  5.0, 0)       # I2C Qwiic
for i, x in enumerate((70.0, 74.5, 79.0, 83.5)):
    at(f"R{54+i}", x, 12.0, 0)  # 串阻(端子侧)
    at(f"R{58+i}", x, 15.5, 0)  # 上拉(MCU 侧)
    at(f"C{28+i}", x, 19.0, 0)  # 消抖
at("R52", 108.0, 12.0, 0)       # I2C 上拉
at("R53", 112.5, 12.0, 0)

# ---------------- A4 低压电源区 x 66–130 y 26–54 ----------------
# 左半 buck(C35 → VIN 陶瓷 → U2 → L1),右半 OR 二极管 + LDO;FB/COMP/EN 分压压在下沿。
at("C35",  73.0, 32.5, 0)       # V24_LOGIC 体电容(包络 12.04 × 8.60);
                                # 下移 1.5mm 给那条横向车道带让路
at("C32",  82.0, 30.0, 180)     # VIN 陶瓷,1 脚朝 U2;整排下移,让开 y23–28 的接口总线带
at("C33",  87.0, 30.0, 180)
at("C34",  91.0, 30.0, 180)
at("U2",   88.0, 36.0, 180)     # TPS54360:VIN/EN/RT/BOOT 在上排,SW/FB/COMP/GND 在下排
at("L1",  101.0, 36.0, 0)       # 紧接 SW(U2 8 脚到 L1 1 脚约 10mm)
at("D2",   86.0, 43.0, 0)       # 续流,贴 SW/GND;上移 2mm 把开关环路收进 2cm²
at("C38",  92.5, 34.5, 0)       # Cboot
at("R62",  82.0, 34.5, 0)       # RT/CLK,贴 U2 的 4 脚
at("R63",  73.0, 39.5, 0)       # FB 上
at("R64",  73.0, 42.5, 0)       # FB 下
at("R65",  73.0, 45.5, 0)       # COMP
at("C39",  73.0, 48.5, 0)
at("C40",  77.5, 39.5, 0)
at("R66",  77.5, 42.5, 0)       # EN 分压上
at("R67",  77.5, 45.5, 0)       # EN 分压下
at("C36", 112.0, 30.0, 0)       # V5_BUCK 输出
at("C37", 118.0, 30.0, 0)
at("D3",  112.0, 36.0, 0)       # V5_BUCK → V5_SYS
at("D4",  121.0, 36.0, 0)       # USB_VBUS → V5_SYS
at("C41", 127.0, 30.0, 0)
at("U3",  113.0, 46.0, 0)       # 3.3V LDO
at("C42", 120.0, 45.0, 0)
at("C43", 124.0, 45.0, 0)

# ---------------- A5 栅极驱动区 x 4–101 y 49–60 ----------------
# 往上挪了 4mm:驱动器下沿到脊椎上沿要留出 6.7mm,给 12 根栅极信号扇出用
#(它们的换层过孔必须彼此错开,挤在 0.65mm 的引脚间距上必然打架)。
at("U7",   20.0, 54.5, 180)     # 驱 CH5/CH6 —— 压在它们的 x 质心上
at("C15",  15.0, 54.5, 0)
at("U6",   68.0, 54.5, 180)     # 驱 CH1–CH4
at("C14",  63.0, 54.5, 0)
at("R2",   30.0, 54.5, 0)       # 总断路:TP7 → R2 → Q3 基极
at("Q3",   34.0, 54.5, 0)
at("R3",   38.0, 54.5, 0)
at("R13",  44.0, 54.5, 0)       # /OE 失效安全:R13 上拉
at("Q6",   48.0, 54.5, 0)
at("R14",  52.0, 54.5, 0)
at("R15",  56.0, 54.5, 0)

# ---------------- C1–C6 六列功率级(完全相同的行结构)----------------
COL_X = {1: 92.0, 2: 76.0, 3: 60.0, 4: 44.0, 5: 28.0, 6: 12.0}
CH_TABLE = g.CH_TABLE

# 行内 x 偏移(相对列心)与行 y —— 六列一模一样
ROW = dict(
    # ⚠️ 这些 y 不是 floorplan §A3.1 那张表的原值。原表按 **courtyard** 排的行,
    # 而好几个厂商封装的**焊盘伸到 courtyard 外面**(TO-252 的散热片焊盘 6.5mm 高、
    # courtyard 只有 6.14;8mm 电解的焊盘左右各伸出 6.02mm、courtyard 只有 4.2)。
    # 按真实包络(焊盘 ∪ 丝印)重排之后,一列要比原表多 7mm 左右 —— 见文件末尾的说明。
    # 补法:脊椎带 73–85 上移到 65–77、驱动带 62–71 上移到 54–63、
    #      换保险丝的镊子净空 10.0 → 8.5mm(硬要求是 ≥8mm,仍有 0.5mm 余量),
    #      **板框不变,仍是 130 × 164**。
    fuse_y=81.67,           # 行1 支路保险丝座,包络 79.00–84.33
    cel_y=97.13,            # 行2 100µF 电解(包络 12.04 × 8.60,几乎占满列宽)
    led_y=104.78,           # 行3 指示灯 + 限流电阻(左右镜像:灯 电阻 | 电阻 灯)
    led_cw=-5.52, rl_cw=-1.48, rl_ww=1.48, led_ww=5.52,
    tvs_y=110.10,           # 行4 输出 TVS(阴极朝列心)
    fw_y=116.24,            # 行5 续流(阴极朝列外侧,排在更靠近 MOS 的那一行)
    d_cw=-4.00, d_ww=4.00,
    r5_y=120.84,            # 行6 栅阻 / 下拉 / 100nF 去耦
    # 顺序按信号流向排,保证「栅极信号 → 栅阻 → 下拉 → MOS 栅极」一条线不折返:
    #   栅阻在外(迎脊椎下来的信号车道)、下拉在内(挨着 MOS 栅极)
    rg_cw=-6.60, rpd_cw=-3.30, cm=0.00, rpd_ww=3.30, rg_ww=6.60,
    mos_y=128.26, q_cw=-4.00, q_ww=4.00,   # 行7 MOS(rot180:漏极片朝下正对端子)
    term_y=141.20,          # 行8 输出端子
)


for (n, F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw) in CH_TABLE:
    cx = COL_X[n]
    at(F,  cx,                     ROW["fuse_y"], 180)  # 1 脚(V24_BUS)朝右迎脊椎
    at(Ce, cx,                     ROW["cel_y"], 0)
    # 一列之内左右镜像:CW 半边和 WW 半边的器件方向互为镜像,
    # 于是「阴极朝哪边」变成一条肉眼一扫就能查的规则(见 layout-guide.md)。
    at(Lc, cx + ROW["led_cw"],     ROW["led_y"], 180)  # 阳极朝列外
    at(Rlc, cx + ROW["rl_cw"],     ROW["led_y"], 0)
    at(Rlw, cx + ROW["rl_ww"],     ROW["led_y"], 180)
    at(Lw, cx + ROW["led_ww"],     ROW["led_y"], 0)
    at(Dtc, cx + ROW["d_cw"],      ROW["tvs_y"], 180)  # TVS 阴极朝列心
    at(Dtw, cx + ROW["d_ww"],      ROW["tvs_y"], 0)
    at(Dfc, cx + ROW["d_cw"],      ROW["fw_y"], 0)     # 续流阴极朝列外
    at(Dfw_, cx + ROW["d_ww"],     ROW["fw_y"], 180)
    at(Rgc, cx + ROW["rg_cw"],     ROW["r5_y"], 0)
    at(Rpc, cx + ROW["rpd_cw"],    ROW["r5_y"], 0)
    at(Cm,  cx + ROW["cm"],        ROW["r5_y"], 0)
    at(Rpw, cx + ROW["rpd_ww"],    ROW["r5_y"], 180)
    at(Rgw, cx + ROW["rg_ww"],     ROW["r5_y"], 180)
    at(Qc, cx + ROW["q_cw"],       ROW["mos_y"], 180)
    at(Qw, cx + ROW["q_ww"],       ROW["mos_y"], 180)
    at(J,  cx,                     ROW["term_y"], 0)

# ---------------- D0 入电保护区 x 101–130 y 54–147(电流自下而上)----------------
at("PTC1", 126.0,  56.73, 180)  # V24_PROT(右)→ V24_LOGIC(左),沿右板边上行去 buck
at("U1",  109.25,  63.98, 180)  # INA237:IN+/IN− 朝下正对 RS1,x 取到两脚等距
at("C6",   117.0,  63.98, 0)
at("C46",  102.6,  71.21, 0)    # V24_BUS 高频陶瓷(1210,4.68 宽)
at("RS1",  110.0,  71.21, 180)  # 2mΩ:右脚 V24_PROT 进、左脚 V24_BUS 出 → 直接向左进脊椎
at("C45",  120.0,  71.21, 0)    # V24_PROT 高频陶瓷
at("TP2",  126.5,  76.5)        # (见 TPS)
at("C5",   107.3,  79.74, 0)   # 体电容三排:C1/C2 排在最靠近 J1 的一排
at("D1",   120.7,  79.74, 0)   # SMBJ26A
at("C3",   107.3,  90.84, 0)
at("C4",   120.7,  90.84, 0)
at("C1",   107.3, 101.94, 0)
at("C2",   120.7, 101.94, 0)
at("Q1",   107.0, 112.54, 90)   # 防反接 P-MOS:漏极片朝下迎 F1,源极/栅极朝上
at("Q2",   115.0, 112.54, 90)
at("DZ1",  123.0, 108.5, 0)     # Vgs 钳位
at("R1",   123.0, 112.5, 0)
at("TP8",  123.0, 116.5)        # (见 TPS)
at("F1",   116.0, 127.31, 0)    # 双联 ATO 15A(19.82 宽)
at("C44",  110.0, 135.30, 0)    # 进线阻尼 RC(挂 V24_FUSED)
at("R68",  117.0, 135.30, 0)
at("J1",   116.0, 141.20, 0)    # 24V 输入,与六个输出端子同一 y

# ============================================================================
# 分区表(§A3)—— 逐个元件核对用
# ============================================================================
ZONES = {
    "A0": ("天线净空区",        (0, 8),     (0, 25)),
    "A1": ("主控区",            (0, 40),    (0, 62)),
    "A2": ("USB / 串口区",      (40, 66),   (0, 62)),
    "A3": ("传感器 / 干接点区", (66, 130),  (0, 26)),
    "A4": ("低压电源区",        (66, 130),  (26, 54)),
    "A5": ("栅极驱动区",        (4, 101),   (49, 60)),
    "B0": ("24V 分配脊椎",      (8.5, 100), (65, 77)),
    "C1": ("功率通道列 CH1",    (84, 103),  (77, 147)),
    "C2": ("功率通道列 CH2",    (68, 84),  (77, 147)),
    "C3": ("功率通道列 CH3",    (52, 68),  (77, 147)),
    "C4": ("功率通道列 CH4",    (36, 52),  (77, 147)),
    "C5": ("功率通道列 CH5",    (20, 36),  (77, 147)),
    "C6": ("功率通道列 CH6",    (4, 20),  (77, 147)),
    "D0": ("入电保护区",        (101, 130), (54, 147)),
    "E0": ("下板边支撑带",      (0, 130),   (147, 164)),
}

ZONE_OF = {}
for r in ("U4", "C10", "C11", "C12", "LED1", "R4", "R5", "R8", "SW1", "SW2"):
    ZONE_OF[r] = "A1"
for r in ("C13", "J2", "Q4", "Q5", "R9", "R10", "R11", "R12", "U5"):
    ZONE_OF[r] = "A2"
for r in ("J9", "J10", "J11", "R52", "R53") + tuple(f"R{i}" for i in range(54, 62)) \
        + tuple(f"C{i}" for i in range(28, 32)):
    ZONE_OF[r] = "A3"
for r in tuple(f"C{i}" for i in range(32, 44)) + ("D2", "D3", "D4", "L1", "U2", "U3",
                                                  "TP3", "TP4", "TP9") \
        + tuple(f"R{i}" for i in range(62, 68)):
    ZONE_OF[r] = "A4"
for r in ("C14", "C15", "Q6", "R13", "R14", "R15", "U6", "U7", "Q3", "R2", "R3", "TP7"):
    ZONE_OF[r] = "A5"
ZONE_OF["TP1"] = "B0"
for (n, F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw) in CH_TABLE:
    for r in (F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw):
        ZONE_OF[r] = f"C{n}"
ZONE_OF["TP5"] = "C1"
ZONE_OF["TP6"] = "C1"
for r in ("C1", "C2", "C3", "C4", "C5", "C6", "C44", "C45", "C46", "D1", "DZ1", "F1",
          "J1", "PTC1", "Q1", "Q2", "R1", "R68", "RS1", "TP2", "TP8", "U1"):
    ZONE_OF[r] = "D0"

# 与 floorplan-v2.md §A3.3 那张 205 个的表相比,本轮**有意的偏离**(逐条给理由)
DEVIATIONS = {
    "Q3": "总断路改到 /OE 之后 Q3 是逻辑件,不再属于功率输入级 → D0 搬到 A5(见 floorplan §C 结办表)",
    "R2": "同 Q3(MASTER_OFF_TP → 基极串阻)",
    "R3": "同 Q3(基极默认关断下拉)",
    "TP5": "CH1_CW_GR 的测试点必须挨着栅阻才有意义(floorplan §C6 原话「栅阻紧贴栅极,TP5 就在旁边」)→ A5 改到 C1",
    "TP6": "CH1_CW_D 是漏极节点,只存在于 C1 列 → 保持在 C1(floorplan §A6 也是这么说的)",
    "TP7": "新增件,总断路控制焊盘,必须挨着 R2 → A5",
    "TP8": "新增件,PMOS_GATE 探测点 → D0",
    "TP9": "新增件,buck 就近地参考 → A4",
    "C44": "新增件,进线阻尼电容 → D0",
    "C45": "新增件,V24_PROT 高频陶瓷 → D0",
    "C46": "新增件,V24_BUS 高频陶瓷。floorplan §C3 建议放脊椎最远端(C6),"
           "但那里最近的 GND 在 40mm 外,旁路电容的回路会长到失去意义 → 改放 D0 分配点旁,"
           "紧挨 C4/C5 的地端,回路 <5mm",
    "R68": "新增件,进线阻尼电阻 → D0",
}

# ============================================================================
# 建板
# ============================================================================
board = pcbnew.CreateEmptyBoard()
nets = {}


def net_of(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n
    return nets[name]


# ---- 无极性两端贴片件:去掉封装自带的装饰性丝印外框 ----
# 为什么:0603 的 F.SilkS 外框比 courtyard 大一整圈(2.93×1.47 vs 1.69×0.89),
# 而位号避障判据量的正是这个外框。留着它,密集行里位号**物理上排不下**
# —— 现版 28 个元件没位号,根子就在这儿。这些件没有极性、没有方向,
# 外框纯装饰(`gen_strip_res_silk.py` 早就对 12 颗灯的限流电阻这么做过)。
# **有极性/有方向的一个都不动**:LED、二极管、电解、IC、三极管、端子、保险丝座。
NO_SILK_FP = {"R0603", "C0603", "C0805", "C1210", "R1206", "R2512"}
_stripped = 0


def dress(fp, fpname, hide_ref=False):
    """统一位号字号、隐藏 Value。(去外框那一步走文本层,见 strip_silk。)"""
    tr = fp.Reference()
    tr.SetTextSize(VECTOR2I(FromMM(0.7), FromMM(0.7)))
    tr.SetTextThickness(FromMM(0.12))
    tr.SetVisible(not hide_ref)
    fp.Value().SetVisible(False)


missing_pos, missing_pad = [], []
for ref, (cid, padnets) in sorted(ref_padnets.items()):
    fpname = fp_of(ref, cid)
    fp = pcbnew.FootprintLoad(PRETTY, fpname)
    if fp is None:
        raise SystemExit(f"footprint 载入失败: {ref} / {fpname}")
    fp.SetReference(ref)
    fp.SetValue(cid)
    dress(fp, fpname)
    if ref not in POS:
        missing_pos.append(ref)
        fp.SetPosition(VECTOR2I(FromMM(140), FromMM(10 + 5 * len(missing_pos))))
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

for ref, netname, x, y in TPS:
    fp = pcbnew.FootprintLoad(KISYS + "/TestPoint.pretty", "TestPoint_Pad_D1.5mm")
    if fp is None:
        raise SystemExit("TestPoint 封装载入失败")
    fp.SetReference(ref)
    fp.SetValue(netname)
    dress(fp, "TestPoint_Pad_D1.5mm")
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    board.Add(fp)
    for p in fp.Pads():
        p.SetNet(net_of(netname))

for ref, x, y in HOLES:
    fp = pcbnew.FootprintLoad(KISYS + "/MountingHole.pretty", "MountingHole_3.2mm_M3")
    if fp is None:
        raise SystemExit("MountingHole 封装载入失败")
    fp.SetReference(ref)
    fp.SetValue("M3")
    dress(fp, "MountingHole_3.2mm_M3")
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    board.Add(fp)

# ---- 板框 ----
def edge(x1, y1, x2, y2):
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    seg.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    seg.SetLayer(pcbnew.Edge_Cuts)
    seg.SetWidth(FromMM(0.1))
    board.Add(seg)


edge(0, 0, BOARD_W, 0)
edge(BOARD_W, 0, BOARD_W, BOARD_H)
edge(BOARD_W, BOARD_H, 0, BOARD_H)
edge(0, BOARD_H, 0, 0)

# ---- A0 天线净空:双面禁铜 / 禁过孔 / 禁走线(rule area)----
# 现版这块是被 GND 覆铜**双面填满**的,板上一条 keepout 都没有(floorplan §A7 第 2 条实测)。
# 不禁「元件」—— U4 自己的天线段就在这块里,禁了会把它自己判成违规。
ka = pcbnew.ZONE(board)
ka.SetIsRuleArea(True)
ka.SetDoNotAllowZoneFills(True)
ka.SetDoNotAllowVias(True)
ka.SetDoNotAllowTracks(True)
ka.SetDoNotAllowPads(False)   # U4 自己的地脚就在这块里,禁了会把它判成违规
ka.SetDoNotAllowFootprints(False)
_ls = pcbnew.LSET()
_ls.AddLayer(pcbnew.F_Cu)
_ls.AddLayer(pcbnew.B_Cu)
ka.SetLayerSet(_ls)
ka.SetZoneName("A0 天线净空(双面禁铜/禁过孔/禁走线)")
pts = pcbnew.SHAPE_POLY_SET()
pts.NewOutline()
for (px, py) in ((0, 0), (8, 0), (8, 25), (0, 25)):
    pts.Append(FromMM(px), FromMM(py))
ka.SetOutline(pts)
board.Add(ka)

out = str(HERE / "cct-main.kicad_pcb")

# ⚠️ `SaveBoard()` 会把同名的 .kicad_pro 一起重写成**出厂默认** —— 5 个网络类
# (TRUNK/PWR2/PWR1/GND)和 14 条 netclass_patterns 会被静默清空,`min_text_height`
# 从 0.5 变回 0.8。README 里那一节讲的是「GUI 会干这件事」,无头 SaveBoard 同样会。
# 所以存盘前后把工程文件原样存回来,并在末尾跑 check-netclasses.py 复核。
_pro = HERE / "cct-main.kicad_pro"
_pro_backup = _pro.read_bytes() if _pro.exists() else None
pcbnew.SaveBoard(out, board)
if _pro_backup is not None:
    _pro.write_bytes(_pro_backup)


def strip_silk(path):
    """把 NO_SILK_FP 里那些封装的 F.SilkS 图形从板文件里删掉(文本层,幂等)。

    **为什么不用 pcbnew 的 `FOOTPRINT.Remove()`**:调用之后同一个进程里的
    SWIG 对象会集体失效(`'SwigPyObject' object has no attribute ...`),
    存盘再 LoadBoard 也救不回来 —— `gen_led_silk.py` 的 docstring 记过这个坑。
    """
    src = Path(path).read_text(encoding="utf-8")
    outbuf, i, n, cut = [], 0, len(src), 0
    while True:
        j = src.find("\t(footprint \"", i)
        if j < 0:
            outbuf.append(src[i:]); break
        outbuf.append(src[i:j])
        name = src[j + 13:src.index('"', j + 13)]
        # 找到这个 footprint 块的结束括号
        d, k = 0, j
        while k < n:
            if src[k] == "(":
                d += 1
            elif src[k] == ")":
                d -= 1
                if d == 0:
                    k += 1
                    break
            k += 1
        blk = src[j:k]
        if name in NO_SILK_FP:
            keep, m = [], 0
            while m < len(blk):
                g = -1
                for tag in ("(fp_line", "(fp_circle", "(fp_rect", "(fp_arc", "(fp_poly"):
                    q = blk.find(tag, m)
                    if q >= 0 and (g < 0 or q < g):
                        g = q
                if g < 0:
                    keep.append(blk[m:]); break
                dd, e = 0, g
                while e < len(blk):
                    if blk[e] == "(":
                        dd += 1
                    elif blk[e] == ")":
                        dd -= 1
                        if dd == 0:
                            e += 1
                            break
                    e += 1
                sub = blk[g:e]
                if '"F.SilkS"' in sub:
                    keep.append(blk[m:g]); cut += 1
                else:
                    keep.append(blk[m:e])
                m = e
            blk = "".join(keep)
        outbuf.append(blk)
        i = k
    Path(path).write_text("".join(outbuf), encoding="utf-8")
    return cut


_stripped = strip_silk(out)
print(f"[silk] 去掉无极性贴片件的装饰外框 {_stripped} 条")

# ============================================================================
# 摆位自检 —— 每一条都打印实测数,不达标就退出码 1
# ============================================================================
board = pcbnew.LoadBoard(out)
problems = []


def crt(fp):
    """**真实包络**(焊盘 ∪ 丝印 ∪ courtyard,不含文字),(l, t, r, b),mm。

    ⚠️ 不能只用 courtyard。本工程的封装是 easyeda2kicad 下来的,好几个的
    **焊盘伸到 courtyard 外面**:TO-252 的散热片焊盘 6.5mm 高、courtyard 只有 6.14;
    8mm 铝电解的焊盘左右各伸出 6.02mm、courtyard 只有 4.20。只按 courtyard 查重叠,
    会漏掉「栅阻的焊盘压在 MOS 栅极焊盘上」这种实打实的做不出来。
    `GetBoundingBox(False, False)` 取的正是位号避障脚本量的那个框,两边口径一致。
    """
    bb = fp.GetBoundingBox(False, False)
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
            pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))


fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
env = {r: crt(f) for r, f in fps.items()}

print("=" * 78)
print(f"v2 摆位自检  板框 {BOARD_W} × {BOARD_H} mm")
print("=" * 78)

# --- 1. 元件数 ---
expect = len(ref_padnets) + len(TPS) + len(HOLES)
print(f"\n【1】元件数:采购件 {len(ref_padnets)} + 测试焊盘 {len(TPS)} + 安装孔 {len(HOLES)}"
      f" = {expect};板上实到 {len(fps)}")
print(f"     其中「212 个元件」= 采购件 {len(ref_padnets)} + TP {len(TPS)} + 老的 4 个安装孔"
      f" = {len(ref_padnets) + len(TPS) + 4};本轮新增 H5–H9 五个孔")
if len(fps) != expect:
    problems.append(f"元件数对不上:期望 {expect},实到 {len(fps)}")
if missing_pos:
    problems.append(f"没给坐标(被扔到板外):{missing_pos}")
if missing_pad:
    problems.append(f"焊盘号不匹配:{missing_pad}")

# --- 2. courtyard 重叠 ---
refs = sorted(env)
bad = []
for i in range(len(refs)):
    for j in range(i + 1, len(refs)):
        a, b = env[refs[i]], env[refs[j]]
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        if ox > 0.001 and oy > 0.001:
            bad.append((refs[i], refs[j], round(ox, 2), round(oy, 2)))
print(f"\n【2】courtyard 重叠:{len(bad)} 对")
for a, b, ox, oy in bad[:40]:
    print(f"     ❌ {a} × {b}   x 重 {ox}mm / y 重 {oy}mm")
if bad:
    problems.append(f"{len(bad)} 对包络相交")

# --- 3. 逐个元件核对它落在哪个区 ---
print("\n【3】分区归属")
off = []
for r in sorted(env):
    if r.startswith("H"):
        continue
    z = ZONE_OF.get(r)
    if z is None:
        off.append((r, "没有指定区", ""))
        continue
    (xr, yr) = ZONES[z][1], ZONES[z][2]
    l, t, rr, bb = env[r]
    cx, cy = (l + rr) / 2, (t + bb) / 2
    if not (xr[0] <= cx <= xr[1] and yr[0] <= cy <= yr[1]):
        off.append((r, z, f"中心 ({cx:.1f},{cy:.1f}) 不在 x{xr} y{yr} 内"))
cnt = {}
for r, z in ZONE_OF.items():
    cnt[z] = cnt.get(z, 0) + 1
for z in sorted(ZONES):
    if z in ("A0", "E0"):
        print(f"     {z} {ZONES[z][0]:<18} 0 个元件(设计如此)")
    else:
        print(f"     {z} {ZONES[z][0]:<18} {cnt.get(z,0):>3} 个")
print(f"     MH 安装孔              {len(HOLES):>3} 个")
if off:
    for r, z, why in off:
        print(f"     ❌ {r} 应在 {z}:{why}")
    problems.append(f"{len(off)} 个元件不在它被指定的区里")
else:
    print("     ✅ 每个元件都落在它在分区表里被指定的那个区")

print("\n     相对 floorplan §A3.3 那张 205 个的表,有意的偏离:")
for r, why in sorted(DEVIATIONS.items()):
    print(f"       {r:<5} → {ZONE_OF[r]}  {why}")

# --- 4. E0 支撑带 ---
# E0 分两段:上半 y 147–154 是「插头外伸避让区」(留给 J3–J8 的插头体往下伸),
# 下半 y 154–164 才是支撑孔区。J1 是螺钉端子,它的**接线口本来就朝下** ——
# 座体伸进上半段和插头伸进上半段是同一回事,所以这里按段分别判。
e0_hole_band = [r for r, (l, tt, rr, bb) in env.items()
                if not r.startswith("H") and bb > 154.0]
e0_plug_band = [r for r, (l, tt, rr, bb) in env.items()
                if not r.startswith("H") and bb > 147.0 and bb <= 154.0]
print(f"\n【4】E0 支撑带")
print(f"     下半「支撑孔区」y 154–164:伸进来的元件 {len(e0_hole_band)} 个 {e0_hole_band}")
print(f"     上半「插头外伸避让区」y 147–154:{len(e0_plug_band)} 个 {e0_plug_band}"
      + ("(J1 是螺钉端子,接线口朝下,座体下沿 %.2f,离孔区上沿还有 %.2f mm)"
         % (env["J1"][3], 154.0 - env["J1"][3]) if "J1" in e0_plug_band else ""))
print(f"     9 个安装孔:{', '.join(f'{h[0]}({h[1]:g},{h[2]:g})' for h in HOLES)}")
if e0_hole_band:
    problems.append(f"支撑孔区里有元件:{e0_hole_band}")

# --- 5. 六列等距同行 ---
print("\n【5】六列功率级「等距同行」")
rows = {"保险丝": [], "电解": [], "TVS(CW)": [], "续流(CW)": [], "栅阻(CW)": [],
        "MOS(CW)": [], "端子": []}
for (n, F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw) in CH_TABLE:
    rows["保险丝"].append(fps[F]); rows["电解"].append(fps[Ce])
    rows["TVS(CW)"].append(fps[Dtc]); rows["续流(CW)"].append(fps[Dfc])
    rows["栅阻(CW)"].append(fps[Rgc]); rows["MOS(CW)"].append(fps[Qc])
    rows["端子"].append(fps[J])
for name, items in rows.items():
    ys = [round(pcbnew.ToMM(f.GetPosition().y), 3) for f in items]
    xs = [pcbnew.ToMM(f.GetPosition().x) for f in items]
    pitch = sorted({round(xs[i] - xs[i + 1], 3) for i in range(len(xs) - 1)})
    okrow = len(set(ys)) == 1 and pitch == [16.0]
    print(f"     {'✅' if okrow else '❌'} {name:<10} y={ys[0]:<8} 列距 {pitch}")
    if not okrow:
        problems.append(f"{name} 行没有等距同行:y={ys} 列距={pitch}")

# --- 6. 硬约束 ---
print("\n【6】硬约束逐条")


def gap(a, b):
    """两个 courtyard 的最小净距(负数=相交)。"""
    A, B = env[a], env[b]
    dx = max(A[0] - B[2], B[0] - A[2])
    dy = max(A[1] - B[3], B[1] - A[3])
    if dx >= 0 and dy >= 0:
        return (dx ** 2 + dy ** 2) ** 0.5
    return max(dx, dy)


def pad_xy(ref, num):
    for p in fps[ref].Pads():
        if p.GetNumber() == num:
            return pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
    return None


def chk(ok, text):
    print(f"     {'✅' if ok else '❌'} {text}")
    if not ok:
        problems.append(text)


# 6.1 天线净空
u4 = env["U4"]
ant_intruders = [r for r, e in env.items()
                 if r != "U4" and e[0] < 8.0 and e[1] < 25.0]
chk(not ant_intruders,
    f"A0 天线净空 x0–8/y0–25:除 U4 天线段外无元件(实测侵入 {ant_intruders});"
    f"最近的螺丝 H1(4,36) 距净空区下沿 {36 - 25:.0f}mm;已下 rule area 双面禁铜/禁孔/禁线")

# 6.2 INA237 开尔文
rs_l = pad_xy("RS1", "2"); rs_r = pad_xy("RS1", "1")
inp = None; inn = None
for p in fps["U1"].Pads():
    if p.GetNetname() == "V24_PROT":
        inp = (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
    if p.GetNetname() == "V24_BUS":
        inn = (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
d_p = ((inp[0] - rs_r[0]) ** 2 + (inp[1] - rs_r[1]) ** 2) ** 0.5
d_n = ((inn[0] - rs_l[0]) ** 2 + (inn[1] - rs_l[1]) ** 2) ** 0.5
chk(max(d_p, d_n) <= 8.0 and abs(d_p - d_n) <= 1.5,
    f"INA237 开尔文:U1 紧贴 RS1,IN+ 到 RS1 上游脚 {d_p:.2f}mm、IN− 到下游脚 {d_n:.2f}mm,"
    f"长度差 {abs(d_p-d_n):.2f}mm(目标 ≤0.5mm,布线时用等长走线补足)")

# 6.3 buck 开关环路面积(C32 → U2 VIN → SW → D2 → GND 的包络)
loop = [env["C32"], env["U2"], env["D2"]]
lx = min(e[0] for e in loop); rx = max(e[2] for e in loop)
ty = min(e[1] for e in loop); by = max(e[3] for e in loop)
area = (rx - lx) * (by - ty) / 100.0
chk(area < 2.0, f"buck 开关环路:C32/U2/D2 三者的外包络 {rx-lx:.1f}×{by-ty:.1f}mm "
                f"= {area:.2f} cm²(要求 <2 cm²)")
chk(gap("C32", "U2") <= 3.0, f"C32 到 U2 边到边 {gap('C32','U2'):.2f}mm(要求 ≤2–3mm)")
chk(gap("R62", "U2") <= 3.0, f"R62(RT/CLK)到 U2 {gap('R62','U2'):.2f}mm")

# 6.4 保险丝镊子空间 —— 逐颗看**它自己正下方**那一块(x 要有交集才算挡住镊子)
fuse_bot = env["F2"][3]
below = []
for fr in ("F2", "F3", "F4", "F5", "F6", "F7"):
    fl, _ft, frr, fb = env[fr]
    for r, e in env.items():
        if r.startswith("H") or r == fr:
            continue
        if e[1] < fb + 8.49 and e[3] > fb and e[0] < frr and e[2] > fl:
            below.append(f"{fr}↓{r}")
chk(not below, f"F2–F7 各自正下方 8.50mm(y {fuse_bot:.2f}–{fuse_bot+8.5:.2f})内无任何元件"
               f"(实测侵入 {below});硬要求是 ≥8mm,余量 0.5mm。上方到脊椎带下沿 2.00mm 是光铜面")
chk(env["Q7"][1] - env["F2"][3] > 35.0,
    f"保险丝行到 MOS 行 {env['Q7'][1]-env['F2'][3]:.1f}mm(现版 18.6mm)")

# 6.5 F1 与 Q1/Q2
chk(gap("F1", "Q1") >= 4.5 and gap("F1", "Q2") >= 4.5,
    f"F1 到 Q1/Q2 净距 {gap('F1','Q1'):.2f} / {gap('F1','Q2'):.2f}mm(现版 3.3mm)")

# 6.6 体电容到 J1
j1p = pad_xy("J1", "1")
c1p = pad_xy("C1", "1")
dc = ((c1p[0] - j1p[0]) ** 2 + (c1p[1] - j1p[1]) ** 2) ** 0.5
chk(dc < 45.0, f"体电容 C1 正极到 J1 进线脚 {dc:.1f}mm(现版 83–101mm)")
c44p = pad_xy("C44", "1")
d44 = ((c44p[0] - j1p[0]) ** 2 + (c44p[1] - j1p[1]) ** 2) ** 0.5
chk(d44 <= 9.0, f"进线阻尼 C44 到 J1 进线脚 {d44:.1f}mm(§C1 要求 ≤8mm 量级)")

# 6.7 全部元件顶层单面
bot = [fp.GetReference() for fp in board.GetFootprints() if fp.IsFlipped()]
chk(not bot, f"全部元件顶层单面贴装(底面 {len(bot)} 个)")

# 6.8 驱动器压在它所驱动的负载质心上
u6x = pcbnew.ToMM(fps["U6"].GetPosition().x)
u7x = pcbnew.ToMM(fps["U7"].GetPosition().x)
c14 = sum(COL_X[i] for i in (1, 2, 3, 4)) / 4
c56 = sum(COL_X[i] for i in (5, 6)) / 2
chk(abs(u6x - c14) < 1.0 and abs(u7x - c56) < 1.0,
    f"U6 x={u6x:g} vs CH1–4 质心 {c14:g};U7 x={u7x:g} vs CH5–6 质心 {c56:g}"
    f"(现版 U7 在 x=54 却驱动 x=24/10)")

# 6.9 板框内
oob = [r for r, e in env.items()
       if e[0] < -0.01 or e[1] < -0.01 or e[2] > BOARD_W + 0.01 or e[3] > BOARD_H + 0.01]
chk(not oob, f"所有元件包络都在板框内(越界 {oob})")

# --- 汇总 ---
print("\n" + "=" * 78)
if problems:
    print(f"❌ 摆位自检 {len(problems)} 处不过:")
    for p in problems:
        print(f"   · {p}")
    sys.exit(1)
import subprocess
_nc = subprocess.run([sys.executable.replace("bin/python3", "bin/python3"),
                      str(HERE / "check-netclasses.py")], capture_output=True, text=True)
print("\n【7】工程文件网络类/设计规则(SaveBoard 会把它重置,这里复核已还原)")
for line in _nc.stdout.strip().splitlines():
    print("     " + line)
if _nc.returncode != 0:
    problems.append("cct-main.kicad_pro 的网络类/设计规则被 SaveBoard 重置了,没还原成功")
    print(f"❌ 摆位自检 {len(problems)} 处不过:")
    for _p in problems:
        print(f"   · {_p}")
    sys.exit(1)

print(f"✅ 摆位自检全过。已保存 {out}")
print(f"   网络 {len(nets)} 个;下一步:gen_route_v2.py 布线")
sys.exit(0)
