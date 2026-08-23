#!/usr/bin/env python3
"""布线收尾:导入 freerouting 结果 → 主干覆铜 → GND 双面覆铜 → 缝合过孔 → 保存。

用 KiCad 自带 python 运行。前置:cct.ses(freerouting 输出)存在。
主干路径(15A):J1 → F1 → Q1/Q2 → RS1 → 经 B.Cu 立管与顶部横带 → F2..F7。
"""
import sys
from pathlib import Path
import pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = Path(__file__).parent
board = pcbnew.LoadBoard(str(HERE / "cct-main.kicad_pcb"))

# ---- 1. 导入自动布线结果 ----
ses = HERE / "cct.ses"
if ses.exists():
    ok = pcbnew.ImportSpecctraSES(board, str(ses))
    print("SES 导入:", ok)
else:
    print("⚠️ 无 cct.ses,跳过导入(仅生成覆铜)")

# 删除布线阶段的禁布区(它们的使命已完成)
_ko = [z for z in board.Zones() if z.GetIsRuleArea()]
for z in _ko:
    board.Remove(z)
print(f"删除禁布区 {len(_ko)} 个")

def net(name):
    n = board.FindNet(name)
    assert n is not None, name
    return n

def pad_of(ref, num):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            for p in fp.Pads():
                if p.GetNumber() == str(num):
                    return p
    raise SystemExit(f"pad not found {ref}.{num}")

def mm(v): return pcbnew.ToMM(v)

def add_zone(netname, layer, pts, priority, min_w=0.3, clearance=0.3, name=""):
    z = pcbnew.ZONE(board)
    z.SetNet(net(netname))
    z.SetLayer(layer)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)   # 功率区直连,不用热焊盘
    z.SetIsFilled(False)
    ol = z.Outline()
    ol.NewOutline()
    for (x, y) in pts:
        ol.Append(FromMM(x), FromMM(y))
    z.SetZoneName(name or f"{netname}_{'F' if layer==pcbnew.F_Cu else 'B'}")
    board.Add(z)
    return z

def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

def add_via(x, y, netname, dia=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetDrill(FromMM(drill))
    v.SetWidth(FromMM(dia))
    v.SetNet(net(netname))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    board.Add(v)

def add_track(x1, y1, x2, y2, netname, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    t.SetWidth(FromMM(w))
    t.SetLayer(layer)
    t.SetNet(net(netname))
    board.Add(t)

# ---- 2. 主干几何(从实际焊盘取坐标)----
# 保险丝行:F2..F7 的 pad1(V24_BUS 侧)
f_pads = [pad_of(f, 1) for f in ["F2", "F3", "F4", "F5", "F6", "F7"]]
bus_y = sum(mm(p.GetPosition().y) for p in f_pads) / 6
bus_xs = [mm(p.GetPosition().x) for p in f_pads]
print(f"保险丝 pad1:y≈{bus_y:.1f},x={[round(x,1) for x in bus_xs]}")

rs1_p2 = pad_of("RS1", "2")
rs1_x, rs1_y = mm(rs1_p2.GetPosition().x), mm(rs1_p2.GetPosition().y)
print(f"RS1.2 (V24_BUS 起点): ({rs1_x:.1f},{rs1_y:.1f})")

# V24_BUS:B.Cu 顶部横带(在端子排与保险丝行之间)+ B.Cu 立管 + 过孔
STRIP_Y1, STRIP_Y2 = bus_y - 5.5, bus_y - 1.8      # 保险丝行上方的水平带
RISER_X1, RISER_X2 = 22.0, 26.0                    # 左列与 CH1 列之间的立管
add_zone("V24_BUS", pcbnew.B_Cu,
         rect(RISER_X1, STRIP_Y1, max(bus_xs) + 4, STRIP_Y2), 2, name="BUS_STRIP")
add_zone("V24_BUS", pcbnew.B_Cu,
         rect(RISER_X1, STRIP_Y1, RISER_X2, rs1_y + 2.5), 2, name="BUS_RISER")
# F.Cu 立管并联(同一路径,双面分流)
add_zone("V24_BUS", pcbnew.F_Cu,
         rect(RISER_X1, STRIP_Y1, RISER_X2, rs1_y + 2.5), 2, name="BUS_RISER_F")
# RS1.pad2 → 立管(F.Cu 粗线)
add_track(rs1_x, rs1_y, RISER_X2, rs1_y, "V24_BUS", 3.5)
# 每个保险丝 pad1 打 2 个过孔下潜到 B.Cu 横带
for x in bus_xs:
    py = mm(f_pads[0].GetPosition().y)
    add_track(x, py, x, STRIP_Y2 + 0.2, "V24_BUS", 2.0)       # pad1 → 带上缘
    add_via(x - 0.9, STRIP_Y2 - 0.9, "V24_BUS", 1.0, 0.5)
    add_via(x + 0.9, STRIP_Y2 - 0.9, "V24_BUS", 1.0, 0.5)
# 立管顶部与横带交汇处 + 立管底部:过孔阵
for yy in [STRIP_Y1 + 1.0, STRIP_Y2 - 1.0]:
    for xx in [RISER_X1 + 1.0, RISER_X2 - 1.0]:
        add_via(xx, yy, "V24_BUS", 1.0, 0.5)
for yy in [rs1_y - 1.0, rs1_y + 1.5]:
    for xx in [RISER_X1 + 1.0, RISER_X2 - 1.0]:
        add_via(xx, yy, "V24_BUS", 1.0, 0.5)

# V24_PROT:F.Cu 左列上带(Q1/Q2 漏极片 + RS1.pad1 + D1)+ B.Cu 左立管 + 电解排带
q1_tab = pad_of("Q1", "2"); q2_tab = pad_of("Q2", "2")
tab_y1 = min(mm(q1_tab.GetBoundingBox().GetTop()), mm(q2_tab.GetBoundingBox().GetTop()))
rs1_p1 = pad_of("RS1", "1")
prot_bot = mm(rs1_p1.GetBoundingBox().GetBottom())
add_zone("V24_PROT", pcbnew.F_Cu, rect(0.8, tab_y1 - 0.8, 21.5, prot_bot + 1.0), 2, name="PROT_L")
# B.Cu 左立管:从左列下行至电解排(避开 H1 由填充器自动退让)
c_pads = [pad_of(c, 1) for c in ["C1", "C2", "C3", "C4", "C5"]]
bulk_y1 = min(mm(p.GetBoundingBox().GetTop()) for p in c_pads) - 1.0
bulk_y2 = max(mm(p.GetBoundingBox().GetBottom()) for p in c_pads) + 1.0
bulk_x2 = max(mm(p.GetBoundingBox().GetRight()) for p in c_pads) + 2.0
add_zone("V24_PROT", pcbnew.B_Cu, rect(0.8, tab_y1, 13.0, bulk_y2), 2, name="PROT_RISER_B")
add_zone("V24_PROT", pcbnew.F_Cu, rect(0.8, bulk_y1, bulk_x2, bulk_y2), 2, name="PROT_BULK")
# 立管过孔阵(上带与下带各一排)
for xx in [2.0, 5.0, 8.0, 11.0]:
    add_via(xx, tab_y1 + 2.0, "V24_PROT", 1.0, 0.5)
    add_via(xx, bulk_y1 + 2.0, "V24_PROT", 1.0, 0.5)

# ---- 3. GND 双面整板覆铜(低优先级)----
W = mm(board.GetBoardEdgesBoundingBox().GetWidth())
H = mm(board.GetBoardEdgesBoundingBox().GetHeight())
gz_b = add_zone("GND", pcbnew.B_Cu, rect(0.5, 0.5, W - 0.5, H - 0.5), 0,
                min_w=0.25, clearance=0.25, name="GND_B")
gz_f = add_zone("GND", pcbnew.F_Cu, rect(0.5, 0.5, W - 0.5, H - 0.5), 0,
                min_w=0.25, clearance=0.25, name="GND_F")
gz_b.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
gz_f.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)

# MOS 源极旁 GND 缝合过孔(每列两处)
for qref in ["Q7","Q8","Q9","Q10","Q11","Q12","Q13","Q14","Q15","Q16","Q17","Q18"]:
    try:
        sp = pad_of(qref, "3")   # S 脚
        x, y = mm(sp.GetPosition().x), mm(sp.GetPosition().y)
        add_via(x + 2.2, y, "GND", 0.8, 0.4)
    except SystemExit:
        print("skip", qref)

# 通用 GND 缝合网格(边缘一圈)
for xx in [5, 30, 55, 80, 105]:
    for yy in [3, 142]:
        add_via(xx, yy, "GND", 0.8, 0.4)

# ---- 4. 填充与保存 ----
filler = pcbnew.ZONE_FILLER(board)
zones = pcbnew.ZONES()
for z in board.Zones():
    zones.append(z)
filler.Fill(zones)
pcbnew.SaveBoard(str(HERE / "cct-main.kicad_pcb"), board)
print("✅ 覆铜完成并保存")

# 未布线统计
conn = board.GetConnectivity()
board.BuildConnectivity()
unrouted = conn.GetUnconnectedCount(True)
print(f"未连接数(飞线): {unrouted}")
