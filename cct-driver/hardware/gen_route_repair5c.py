#!/usr/bin/env python3
import gc, math
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM
board = pcbnew.LoadBoard("cct-main.kicad_pcb")
mm = pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu
def is_via(t): return t.Type()==pcbnew.PCB_VIA_T
def ends(t): return mm(t.GetStart().x),mm(t.GetStart().y),mm(t.GetEnd().x),mm(t.GetEnd().y)

# —— 先取所有需要的数据 ——
px = py = None
for fp in board.GetFootprints():
    if fp.GetReference()=="PTC1":
        for p in fp.Pads():
            if p.GetNumber()=="1":
                px,py = mm(p.GetPosition().x), mm(p.GetPosition().y)
gnd = board.FindNet("GND").GetNetCode()
items = []
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetCode()==gnd:
            items.append((mm(p.GetPosition().x),mm(p.GetPosition().y)))
SNAP = list(board.GetTracks())

# —— 删除 ——
n=0
for t in SNAP:
    if is_via(t): continue
    nm = t.GetNetname()
    x1,y1,x2,y2 = ends(t)
    if nm=="V24_PROT" and max(x1,x2)<20 and min(y1,y2)>97.5:
        board.Remove(t); n+=1
    elif nm=="GND" and 39.5<min(x1,x2) and max(x1,x2)<42.5 and 56<min(y1,y2) and max(y1,y2)<61 and t.GetLayer()==F:
        board.Remove(t); n+=1
print(f"删除 {n} 条")

# —— 新增 PTC1 直通 ——
t = pcbnew.PCB_TRACK(board)
t.SetStart(VECTOR2I(FromMM(px),FromMM(py))); t.SetEnd(VECTOR2I(FromMM(px),FromMM(95.0)))
t.SetWidth(FromMM(1.5)); t.SetLayer(F); t.SetNet(board.FindNet("V24_PROT")); board.Add(t)
print(f"PTC1.1 ({px:.2f},{py:.2f}) → 直通 y95")

# —— 重填 ——
filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones(): zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard("cct-main.kicad_pcb", board)

# —— GND 连接点合并线端后做孤岛探测 ——
for t in board.GetTracks():
    if t.GetNetCode()!=gnd: continue
    if is_via(t):
        items.append((mm(t.GetPosition().x),mm(t.GetPosition().y)))
    else:
        e=ends(t); items.append((e[0],e[1])); items.append((e[2],e[3]))
for z in board.Zones():
    if z.GetIsRuleArea() or z.GetNetCode()!=gnd: continue
    ly = F if z.GetZoneName()=="GND_F" else B
    sps = z.GetFilledPolysList(ly)
    for i in range(sps.OutlineCount()):
        bb = sps.Outline(i).BBox()
        x1,y1,x2,y2 = mm(bb.GetLeft()),mm(bb.GetTop()),mm(bb.GetRight()),mm(bb.GetBottom())
        hit = 0
        for (qx,qy) in items:
            if x1-0.1<qx<x2+0.1 and y1-0.1<qy<y2+0.1:
                if sps.Contains(VECTOR2I(FromMM(qx),FromMM(qy)), i):
                    hit += 1
                    if hit>1: break
        if hit<=1 and (x2-x1)*(y2-y1)>4:
            print(f"  孤岛 {z.GetZoneName()}[{i}]: ({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f}) 接触{hit}")
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
