#!/usr/bin/env python3
"""从网表数据生成 KiCad 原理图(.kicad_sch)。

方法:每个元件按功能块网格摆放,每个引脚原位放置 global_label —— 标签与引脚端点
重合即构成电气连接。排版朴素但网表精确,正确性由 kicad-cli ERC + 网表导出比对保证。

用法:
  python3 gen_sch.py            # 生成 cct-main.kicad_sch + 打印统计
  python3 gen_sch.py --check    # 只做库完整性与引脚映射检查,不生成
"""
import json, math, re, sys, uuid
from pathlib import Path

HERE = Path(__file__).parent
LIB = HERE / "kicad-lib" / "cct.kicad_sym"

# ============================================================================
# 1. 网表数据 —— 与 netlist-spec.md 一一对应(唯一的人工转录环节,靠导出比对复核)
#    每条: (位号, C编号, {规格书引脚名: 网络名})
#    规格书引脚名用别名表映射到符号库实际引脚名/号。
# ============================================================================
P = []  # parts

def part(ref, cid, pins):
    P.append((ref, cid, pins))

# ---- Block A ----
part("J1", "C707824", {"1": "V24_IN", "2": "GND"})
part("F1", "C352820", {"1": "V24_IN", "2": "V24_FUSED"})
# 2026-08-15:D 与 S 对调。P 沟道的体二极管是「漏(阳)→源(阴)」,要防反接就必须让它
# 顺着正常负载电流的方向 —— 也就是漏极接进线侧。原来的接法(源接进线)是负载开关接法,
# 反接时体二极管正偏导通,根本挡不住。详见 netlist-spec.md Block A「更正 1」。
for r in ("Q1", "Q2"):
    part(r, "C3281500", {"G": "PMOS_GATE", "D": "V24_FUSED", "S": "V24_PROT"})
part("R1", "C25803", {"1": "PMOS_GATE", "2": "GND"})
# DZ1 必须跨在栅-源之间。源极已改到 V24_PROT,钳位管的阴极要跟着走;
# 留在 V24_FUSED 的话反接时 DZ1 正偏会把栅极拉到 −23V,MOS 反而全开。
part("DZ1", "C19077410", {"K": "V24_PROT", "A": "PMOS_GATE"})
# Q3 从「拉栅极到地」(错的,见更正 2)降级成 /OE 的电平转换:
# 导通 → 把 OE_B 拉低 → Q6 关断 → OE_N 被 R13 拉高 → 12 路输出全高阻 → 全灭。
# 好处:不掉 MCU 的电、压得过固件、不占 GPIO、零新增元件。
part("Q3", "C20526", {"B": "MASTER_OFF_B", "C": "OE_B", "E": "GND"})
part("R2", "C25804", {"1": "MASTER_OFF_TP", "2": "MASTER_OFF_B"})   # 基极串阻(来自 TP7)
part("R3", "C25803", {"1": "MASTER_OFF_B", "2": "GND"})             # 默认关断下拉
part("D1", "C19077580", {"K": "V24_PROT", "A": "GND"})
for i in range(1, 6):
    part(f"C{i}", "C2836439", {"+": "V24_PROT", "-": "GND"})
# 进线阻尼 RC(2026-08-15 新增):V24_IN 上原本一颗电容都没有,第一颗要走到 83mm 外。
# 放在 F1 **下游**而不是 V24_IN 上:陶瓷片裂了短路时还有主保险丝管;电气上只差一个保险丝座。
# 只能用陶瓷 —— 这个节点在防反接 MOS 上游,反接时是 −24V,电解会炸。
part("C44", "C381466", {"1": "V24_FUSED", "2": "SNUB_MID"})          # 4.7µF/100V X7R 1210
part("R68", "C17928", {"1": "SNUB_MID", "2": "GND"})                 # 1Ω 1206 阻尼电阻(起始值)
part("RS1", "C459679", {"1": "V24_PROT", "2": "V24_BUS"})           # C500614 已停产,换 TCR 更好的合金件
# 母线高频去耦:24V 母线上原来只有铝电解,12 只 MOS 在 19.5kHz 下的高频电流只能靠 ESR 供。
part("C45", "C381466", {"1": "V24_PROT", "2": "GND"})
part("C46", "C381466", {"1": "V24_BUS", "2": "GND"})
part("U1", "C2864837", {"IN+": "V24_PROT", "IN-": "V24_BUS", "VS": "V3P3",
                        "GND": "GND", "SDA": "I2C_SDA", "SCL": "I2C_SCL",
                        "A0": "GND", "A1": "GND", "VBUS": "V24_BUS",
                        "ALERT": "NC_U1_ALERT"})
part("C6", "C14663", {"1": "V3P3", "2": "GND"})

# ---- Block B ----
part("PTC1", "C70119", {"1": "V24_PROT", "2": "V24_LOGIC"})
part("U2", "C524806", {"BOOT": "BOOT", "VIN": "V24_LOGIC", "EN": "EN_BUCK",
                       "RT/CLK": "RT_CLK", "FB": "FB_5V", "COMP": "COMP",
                       "GND": "GND", "SW": "SW_NODE", "PAD": "GND"})
part("L1", "C9400", {"1": "SW_NODE", "2": "V5_BUCK"})
part("D2", "C35490", {"A": "GND", "K": "SW_NODE"})
part("C32", "C381466", {"1": "V24_LOGIC", "2": "GND"})
part("C33", "C381466", {"1": "V24_LOGIC", "2": "GND"})
part("C34", "C14663", {"1": "V24_LOGIC", "2": "GND"})
part("C35", "C2836439", {"+": "V24_LOGIC", "-": "GND"})
part("C36", "C309062", {"1": "V5_BUCK", "2": "GND"})
part("C37", "C309062", {"1": "V5_BUCK", "2": "GND"})
part("C38", "C14663", {"1": "BOOT", "2": "SW_NODE"})
part("R62", "C25811", {"1": "RT_CLK", "2": "GND"})     # 占位:实为200k,C编号下单前替换
part("R63", "C22858", {"1": "V5_BUCK", "2": "FB_5V"})   # 102k;原 C402870 库存仅 1977,换同值大库存件
part("R64", "C22892", {"1": "FB_5V", "2": "GND"})      # 占位:实为18.2k
part("R65", "C25972", {"1": "COMP", "2": "COMP_Z"})    # 占位:实为4.75k
part("C39", "C21117", {"1": "COMP_Z", "2": "GND"})
part("C40", "C107035", {"1": "COMP", "2": "GND"})       # 占位:实为120pF C0G
part("R66", "C23208", {"1": "V24_LOGIC", "2": "EN_BUCK"})  # 占位:实为590k
part("R67", "C12447", {"1": "EN_BUCK", "2": "GND"})    # 占位:实为40.2k
part("D3", "C35490", {"A": "V5_BUCK", "K": "V5_SYS"})
part("D4", "C35490", {"A": "USB_VBUS", "K": "V5_SYS"})
part("C41", "C45783", {"1": "V5_SYS", "2": "GND"})
part("U3", "C6186", {"VIN": "V5_SYS", "VOUT": "V3P3", "GND": "GND"})
part("C42", "C15850", {"1": "V3P3", "2": "GND"})
part("C43", "C14663", {"1": "V3P3", "2": "GND"})

# ---- Block C ----
ESP_PINS = {
    "3V3": "V3P3", "GND": "GND", "EN": "EN", "IO0": "IO0",
    "TXD0": "U0TXD", "RXD0": "U0RXD", "IO2": "LED_STATUS",
    "IO4": "CH1_CW", "IO5": "CH1_WW", "IO13": "CH2_CW", "IO14": "CH2_WW",
    "IO15": "OE_CTRL", "IO16": "CH3_CW", "IO17": "CH3_WW",
    "IO18": "CH4_CW", "IO19": "CH4_WW", "IO21": "CH5_CW", "IO22": "CH5_WW",
    "IO23": "CH6_CW", "IO25": "CH6_WW", "IO26": "UART2_TX", "IO27": "UART2_RX",
    "IO32": "I2C_SDA", "IO33": "I2C_SCL",
    "IO34": "SW_IN1", "IO35": "SW_IN2", "IO36": "SW_IN3", "IO39": "SW_IN4",
    "IO12": "NC_IO12",
}
part("U4", "C701341", ESP_PINS)
part("C10", "C15850", {"1": "V3P3", "2": "GND"})
part("C11", "C14663", {"1": "V3P3", "2": "GND"})
part("R4", "C25804", {"1": "V3P3", "2": "EN"})
part("C12", "C15850", {"1": "EN", "2": "GND"})
part("R5", "C25804", {"1": "V3P3", "2": "IO0"})
part("SW1", "C318884", {"1": "IO0", "2": "GND"})
part("SW2", "C318884", {"1": "EN", "2": "GND"})
part("LED1", "C2286", {"A": "LED_STATUS", "K": "LED1_K"})
part("R8", "C21190", {"1": "LED1_K", "2": "GND"})
part("U5", "C84681", {"VCC": "V3P3", "V3": "V3P3", "GND": "GND",
                      "UD+": "USB_DP", "UD-": "USB_DM",
                      "TXD": "U0RXD", "RXD": "U0TXD",
                      "DTR": "DTR", "RTS": "RTS"})
part("C13", "C14663", {"1": "V3P3", "2": "GND"})
part("J2", "C165948", {"VBUS": "USB_VBUS", "GND": "GND", "DP": "USB_DP",
                       "DM": "USB_DM", "CC1": "CC1", "CC2": "CC2",
                       "SHELL": "GND"})
part("R9", "C23186", {"1": "CC1", "2": "GND"})
part("R10", "C23186", {"1": "CC2", "2": "GND"})
part("Q4", "C2146", {"B": "RTS_B", "C": "EN", "E": "GND"})
part("Q5", "C2146", {"B": "DTR_B", "C": "IO0", "E": "GND"})
part("R11", "C25804", {"1": "DTR", "2": "RTS_B"})
part("R12", "C25804", {"1": "RTS", "2": "DTR_B"})

# ---- Block D ----
HCT_A = ["CH1_CW", "CH1_WW", "CH2_CW", "CH2_WW", "CH3_CW", "CH3_WW", "CH4_CW", "CH4_WW"]
part("U6", "C52140501", {
    "VCC": "V5_SYS", "GND": "GND", "DIR": "V5_SYS", "OE": "OE_N",
    **{f"A{i+1}": HCT_A[i] for i in range(8)},
    **{f"B{i+1}": HCT_A[i] + "_G" for i in range(8)},
})
HCT2_A = ["CH5_CW", "CH5_WW", "CH6_CW", "CH6_WW", "GND", "GND", "GND", "GND"]
HCT2_B = ["CH5_CW_G", "CH5_WW_G", "CH6_CW_G", "CH6_WW_G",
          "NC_U7_B5", "NC_U7_B6", "NC_U7_B7", "NC_U7_B8"]
part("U7", "C52140501", {
    "VCC": "V5_SYS", "GND": "GND", "DIR": "V5_SYS", "OE": "OE_N",
    **{f"A{i+1}": HCT2_A[i] for i in range(8)},
    **{f"B{i+1}": HCT2_B[i] for i in range(8)},
})
part("C14", "C14663", {"1": "V5_SYS", "2": "GND"})
part("C15", "C14663", {"1": "V5_SYS", "2": "GND"})
part("R13", "C25804", {"1": "V5_SYS", "2": "OE_N"})
part("Q6", "C20526", {"B": "OE_B", "C": "OE_N", "E": "GND"})
part("R14", "C25804", {"1": "OE_CTRL", "2": "OE_B"})
part("R15", "C25803", {"1": "OE_B", "2": "GND"})

# ---- Block E(6 通道) ----
CH_TABLE = [  # (ch, F, J, Q_cw, Q_ww, Rg_cw, Rg_ww, Rpd_cw, Rpd_ww, Dfw_cw, Dfw_ww, Dtvs_cw, Dtvs_ww, Cel, Cmlcc, LEDcw, LEDww, Rl_cw, Rl_ww)
    (1, "F2", "J3", "Q7", "Q8", "R16", "R17", "R18", "R19", "D5", "D6", "D7", "D8", "C16", "C17", "LED2", "LED3", "R20", "R21"),
    (2, "F3", "J4", "Q9", "Q10", "R22", "R23", "R24", "R25", "D9", "D10", "D11", "D12", "C18", "C19", "LED4", "LED5", "R26", "R27"),
    (3, "F4", "J5", "Q11", "Q12", "R28", "R29", "R30", "R31", "D13", "D14", "D15", "D16", "C20", "C21", "LED6", "LED7", "R32", "R33"),
    (4, "F5", "J6", "Q13", "Q14", "R34", "R35", "R36", "R37", "D17", "D18", "D19", "D20", "C22", "C23", "LED8", "LED9", "R38", "R39"),
    (5, "F6", "J7", "Q15", "Q16", "R40", "R41", "R42", "R43", "D21", "D22", "D23", "D24", "C24", "C25", "LED10", "LED11", "R44", "R45"),
    (6, "F7", "J8", "Q17", "Q18", "R46", "R47", "R48", "R49", "D25", "D26", "D27", "D28", "C26", "C27", "LED12", "LED13", "R50", "R51"),
]
for (n, F, J, Qc, Qw, Rgc, Rgw, Rpc, Rpw, Dfc, Dfw_, Dtc, Dtw, Ce, Cm, Lc, Lw, Rlc, Rlw) in CH_TABLE:
    V, CW, WW = f"CH{n}_VOUT", f"CH{n}_CW", f"CH{n}_WW"
    part(F, "C108518", {"1": "V24_BUS", "2": V})
    part(J, "C441333", {"1": V, "2": CW + "_D", "3": WW + "_D"})
    part(Qc, "C2890395", {"G": CW + "_GR", "D": CW + "_D", "S": "GND"})
    part(Qw, "C2890395", {"G": WW + "_GR", "D": WW + "_D", "S": "GND"})
    part(Rgc, "C22775", {"1": CW + "_G", "2": CW + "_GR"})
    part(Rgw, "C22775", {"1": WW + "_G", "2": WW + "_GR"})
    part(Rpc, "C25804", {"1": CW + "_GR", "2": "GND"})
    part(Rpw, "C25804", {"1": WW + "_GR", "2": "GND"})
    part(Dfc, "C35490", {"A": CW + "_D", "K": V})
    part(Dfw_, "C35490", {"A": WW + "_D", "K": V})
    part(Dtc, "C19077580", {"K": CW + "_D", "A": "GND"})
    part(Dtw, "C19077580", {"K": WW + "_D", "A": "GND"})
    part(Ce, "C2836439", {"+": V, "-": "GND"})
    part(Cm, "C14663", {"1": V, "2": "GND"})
    # 通道指示灯:跨在本路 V+ 与漏极之间(与灯带并联),不再从栅极取信号。
    # MOS 导通→灯亮;MOS 断→漏极被拉到 V+,灯两端 0V→灭。
    # V+ 取自支路保险丝**下游**,所以支路丝一断,那一路的灯直接灭。
    # 限流 40.2k(C12447,R67 已在用,不新增料号):(24-2.6)/40.2k≈0.53mA,
    # 与原来 5V+4.7k 的 0.51mA 亮度基本一致;0603 压降 21.4V、功耗 11mW(额定 100mW)。
    part(Lc, "C2297", {"A": V, "K": Lc + "_K"})
    part(Lw, "C2297", {"A": V, "K": Lw + "_K"})
    part(Rlc, "C12447", {"1": Lc + "_K", "2": CW + "_D"})
    part(Rlw, "C12447", {"1": Lw + "_K", "2": WW + "_D"})

# ---- Block F ----
part("J9", "C2906270", {"1": "GND", "2": "V3P3", "3": "I2C_SDA", "4": "I2C_SCL"})
part("R52", "C23162", {"1": "V3P3", "2": "I2C_SDA"})
part("R53", "C23162", {"1": "V3P3", "2": "I2C_SCL"})
part("J10", "C37815", {"1": "V5_SYS", "2": "GND", "3": "UART2_TX", "4": "UART2_RX"})
part("J11", "C474923", {"1": "SW_T1", "2": "SW_T2", "3": "SW_T3", "4": "SW_T4", "5": "GND"})
for i in range(1, 5):
    part(f"R{53+i}", "C21190", {"1": f"SW_T{i}", "2": f"SW_IN{i}"})   # R54-57 1k
    part(f"R{57+i}", "C25804", {"1": "V3P3", "2": f"SW_IN{i}"})       # R58-61 10k
    part(f"C{27+i}", "C14663", {"1": f"SW_IN{i}", "2": "GND"})        # C28-31

# ============================================================================
# 2. 引脚名别名 —— 规格书用名 → 符号库可能出现的名字(全大写比较)
# ============================================================================

# 借用符号形状的占位料号 → 借谁的形状(只影响原理图画出来的符号,不影响 Value / 网表 / BOM)
CID_SYMBOL_ALIAS = {
    "C25811":  "C25804",   # 200k  0603  R62(RT)
    "C402870": "C25804",   # 102k  0603  R63(FB 上)
    "C22892":  "C25804",   # 18.2k 0603  R64(FB 下)
    "C25972":  "C25804",   # 4.75k 0603  R65(COMP)
    "C23208":  "C25804",   # 590k  0603  R66(UVLO 上)
    "C12447":  "C25804",   # 40.2k 0603  R67(UVLO 下)
    "C107035": "C14663",   # 120pF C0G 0603  C40(COMP)
    "C22858":  "C25804",   # 102k  0603  R63(FB 上,替代 C402870)
    "C17928":  "C25804",   # 1Ω    1206  R68(进线阻尼)
    "C459679": "C500614",  # 2mΩ   2512  RS1(替代已停产的 C500614)
}

ALIASES = {
    "G": ["G", "GATE", "1"], "D": ["D", "DRAIN"], "S": ["S", "SOURCE"],
    "A": ["A", "ANODE", "+", "A1"], "K": ["K", "C", "CATHODE", "-", "K/C"],
    "+": ["+", "POSITIVE", "1", "A"], "-": ["-", "NEGATIVE", "2", "C", "K"],
    "B": ["B", "BASE"], "C": ["C", "COLLECTOR"], "E": ["E", "EMITTER"],
    "OE": ["OE", "~OE", "OE#", "/OE", "!OE", "NOE"],
    "PAD": ["PAD", "EP", "EPAD", "THERMAL", "9", "TAB"],
    "RT/CLK": ["RT/CLK", "RT_CLK", "RT"],
    "IN+": ["IN+", "INP", "VINP"], "IN-": ["IN-", "INN", "VINN"],
    "ALERT": ["ALERT", "ALERT/", "!ALERT", "~ALERT"],
    "DP": ["DP", "D+", "DP1", "DP2"], "DM": ["DM", "D-", "DN", "DN1", "DN2"],
    "SHELL": ["SHELL", "SHIELD", "EP", "MH", "MP"],
    "TXD0": ["TXD0", "IO1", "TX0", "U0TXD"], "RXD0": ["RXD0", "IO3", "RX0", "U0RXD"],
    "UD+": ["UD+", "DP", "D+"], "UD-": ["UD-", "DM", "D-"],
}


# 每元件专属引脚名映射(优先于通用别名;解决 HCT245 的 A0/A1 索引错位等)
PART_PIN_OVERRIDE = {
    "C52140501": {  # 74HCT245PW: 符号用 A0-A7/B0-B7,规格书用 A1-A8/B1-B8
        **{f"A{i}": f"A{i-1}" for i in range(1, 9)},
        **{f"B{i}": f"B{i-1}" for i in range(1, 9)},
        "OE": "OE",
    },
    "C701341": {"IO36": "SENSOR_VP", "IO39": "SENSOR_VN"},  # ESP32 模组引脚本名
    "C165948": {"SHELL": "EH"},  # Type-C 外壳脚 ×4
}

def norm(n):
    """归一化引脚名:剥 KiCad 上划线记法 ~{X},统一破折号,大写。"""
    return n.replace("~{", "").replace("}", "").replace("\u2013", "-").replace("\u2014", "-").upper()

# ============================================================================
# 3. 解析符号库:符号名、每引脚 (编号, 名字, x, y, 角度)
# ============================================================================
def parse_lib():
    txt = LIB.read_text(encoding="utf-8")
    # 顶层符号切分
    blocks = re.split(r'\n  \(symbol "', txt)[1:]
    syms = {}
    for b in blocks:
        name = b.split('"')[0]
        if ":" in name:
            continue
        pins = []
        for m in re.finditer(
            r'\(pin [\w-]+ \w+\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\)\s*'
            r'\(length [\d.]+\)\s*(?:\(hide[^)]*\)\s*)?'
            r'\(name "([^"]*)"[^\n]*\n\s*\(number "([^"]*)"', b):
            x, y, ang, pname, pnum = m.groups()
            pins.append((pnum, pname, float(x), float(y), int(ang)))
        ds = re.search(r'\(property\s*"Datasheet"\s*"([^"]*)"', b)
        syms[name] = {"pins": pins, "datasheet": ds.group(1) if ds else ""}
    return syms

def build_cid_map(syms):
    """C编号 → 符号名。优先从符号名后缀/Datasheet URL 提取。"""
    m = {}
    for name, info in syms.items():
        found = re.findall(r'(C\d{4,})', name + " " + info["datasheet"])
        for c in found:
            m.setdefault(c, name)
    return m

def resolve_pin(symname, syms, want, cid=None):
    """规格书引脚名 → 符号库引脚元组。可能返回多个(如 GND 多脚)。"""
    pins = syms[symname]["pins"]
    ov = PART_PIN_OVERRIDE.get(cid, {})
    if want in ov:
        tgt = norm(ov[want])
        return [p for p in pins if norm(p[1]) == tgt]
    cands = [norm(c) for c in ALIASES.get(want, [want])]
    hits = [p for p in pins if norm(p[1]) in cands or norm(p[0]) in cands]
    if not hits:
        hits = [p for p in pins if p[0] == want]
    return hits

# ============================================================================
# 4. 生成 .kicad_sch
# ============================================================================
def gen():
    syms = parse_lib()
    cmap = build_cid_map(syms)
    # 7 个"占位"料号(2026-08-07 加的 6 个精密电阻 + 1 个 C0G 电容)的符号没下进库里,
    # 于是 gen_sch.py 从那天起就跑不动了(报"库缺失 7 个"),原理图一直没法重新生成。
    # 它们都是普通两脚无源件,原理图上的**符号形状**与同封装同类件一模一样,这里只借形状:
    # Value 字段写的仍是真实 C 编号(见下面 property "Value" "{cid}"),网表 / BOM / 封装都不受影响。
    for cid, like in CID_SYMBOL_ALIAS.items():
        if cid not in cmap and like in cmap:
            cmap[cid] = cmap[like]
    missing = sorted({cid for _, cid, _ in P} - set(cmap))
    if missing:
        print(f"❌ 库缺失 {len(missing)} 个: {missing}")
        return False
    errors = []
    # 引脚映射预检
    for ref, cid, pins in P:
        sn = cmap[cid]
        for want in pins:
            hits = resolve_pin(sn, syms, want, cid)
            if not hits:
                avail = [(p[0], p[1]) for p in syms[sn]["pins"]]
                errors.append(f"{ref}({cid}/{sn}): 引脚 '{want}' 无匹配。可用: {avail}")
    if errors:
        print(f"❌ 引脚映射失败 {len(errors)} 处:")
        for e in errors[:20]:
            print("  ", e)
        return False
    if "--check" in sys.argv:
        print(f"✅ 检查通过:{len(P)} 个元件,库、引脚映射全部可解析")
        return True

    # 布局:每块一列,元件竖排
    out = []
    out.append('(kicad_sch (version 20231120) (generator "gen_sch") (generator_version "1.0")')
    out.append(f'  (uuid "{uuid.uuid4()}")')
    out.append('  (paper "A2")')
    out.append('  (lib_symbols')
    # 内嵌用到的符号定义(从库拷贝)
    txt = LIB.read_text(encoding="utf-8")
    used_syms = {cmap[cid] for _, cid, _ in P}
    for sn in sorted(used_syms):
        m = re.search(r'\n  (\(symbol "' + re.escape(sn) + r'".*?)\n  \(symbol "', txt, re.S)
        if not m:
            m = re.search(r'\n  (\(symbol "' + re.escape(sn) + r'".*)\n\)\s*$', txt, re.S)
        body = m.group(1)
        body = body.replace('(symbol "' + sn + '"', '(symbol "cct:' + sn + '"', 1)
        out.append("    " + body)
    out.append('  )')

    x0, y0 = 30, 30
    col_w, row_h = 90, 0  # row_h 按符号高度动态
    x, y = x0, y0
    max_y = 520
    for ref, cid, pins in P:
        sn = cmap[cid]
        spins = syms[sn]["pins"]
        ymin = min((p[3] for p in spins), default=0)
        ymax = max((p[3] for p in spins), default=0)
        h = max(ymax - ymin + 15, 15)
        if y + h > max_y:
            y = y0
            x += col_w
        u = uuid.uuid4()
        x = round(x / 1.27) * 1.27
        y = round(y / 1.27) * 1.27
        out.append(f'  (symbol (lib_id "cct:{sn}") (at {x:.2f} {y:.2f} 0) (unit 1)')
        out.append(f'    (in_bom yes) (on_board yes) (uuid "{u}")')
        out.append(f'    (property "Reference" "{ref}" (at {x} {y-ymax-3} 0) (effects (font (size 1.27 1.27))))')
        out.append(f'    (property "Value" "{cid}" (at {x} {y-ymin+3} 0) (effects (font (size 1.27 1.27))))')
        for p in spins:
            out.append(f'    (pin "{p[0]}" (uuid "{uuid.uuid4()}"))')
        out.append('  )')
        # 每个引脚放 global_label(坐标: 符号原点 + (px, -py))
        for want, net in pins.items():
            for pnum, pname, px, py, pang in resolve_pin(sn, syms, want, cid):
                gx, gy = x + px, y - py
                lang = (pang + 180) % 360  # 标签朝向引脚外侧
                if net.startswith("NC_"):
                    out.append(f'  (no_connect (at {gx} {gy}) (uuid "{uuid.uuid4()}"))')
                else:
                    out.append(f'  (global_label "{net}" (shape passive) (at {gx} {gy} {lang})'
                               f' (effects (font (size 1.27 1.27)) (justify left))'
                               f' (uuid "{uuid.uuid4()}"))')
        # 未在网表中的引脚 → no_connect(防 ERC 报未连接;若属遗漏,导出比对会暴露)
        mapped = set()
        for want in pins:
            for hit in resolve_pin(sn, syms, want, cid):
                mapped.add(hit[0])
        for p in spins:
            if p[0] not in mapped:
                out.append(f'  (no_connect (at {x + p[2]} {y - p[3]}) (uuid "{uuid.uuid4()}"))')
        y += h
    out.append(')')
    Path(HERE / "cct-main.kicad_sch").write_text("\n".join(out), encoding="utf-8")
    print(f"✅ 生成 cct-main.kicad_sch: {len(P)} 元件")
    return True

if __name__ == "__main__":
    ok = gen()
    sys.exit(0 if ok else 1)
