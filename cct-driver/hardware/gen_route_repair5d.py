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

gnd = board.FindNet("GND").GetNetCode()
items = []
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetCode()==gnd:
            items.append((mm(p.GetPosition().x),mm(p.GetPosition().y)))
SNAP = list(board.GetTracks())

# 删:坏 PTC1 直通线 + 孤儿过孔 (4.15,125.64)
for t in SNAP:
    if t.GetNetname()!="V24_PROT": continue
    if is_via(t):
        x,y = mm(t.GetPosition().x),mm(t.GetPosition().y)
        if abs(x-4.15)<0.2 and abs(y-125.64)<0.2:
            board.Remove(t)
    else:
        x1,y1,x2,y2 = ends(t)
        if abs(x1-4.15)<0.1 and abs(x2-4.15)<0.1 and min(y1,y2)>94 and max(y1,y2)<99.5:
            board.Remove(t)

def via(x,y,netname,dia=0.8,drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x),FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(board.FindNet(netname)); v.SetLayerPair(F,B)
    board.Add(v)
def trk(pts,netname,w,layer=F):
    for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(board.FindNet(netname))
        board.Add(t)

# PTC1.1 盘内双过孔 + B 层桥接小铜(接 PROT_RISER_B 底部)
z = pcbnew.ZONE(board)
z.SetNet(board.FindNet("V24_PROT")); z.SetLayer(B)
z.SetAssignedPriority(3)
z.SetLocalClearance(FromMM(0.3)); z.SetMinThickness(FromMM(0.3))
z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
ol = z.Outline(); ol.NewOutline()
for (x,y) in [(0.8,94.0),(8.2,94.0),(8.2,101.3),(0.8,101.3)]:
    ol.Append(FromMM(x),FromMM(y))
z.SetZoneName("PROT_PTC1_B"); board.Add(z)
via(3.7,99.3,"V24_PROT"); via(4.6,99.3,"V24_PROT")

# U1 GND 链冗余桥:x12.7 → x17 过孔带
trk([(12.7,54.5),(17.0,54.5)],"GND",0.4)
via(17.4,54.5,"GND")
trk([(17.0,54.5),(17.4,54.5)],"GND",0.4)

filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z2 in board.Zones(): zs.append(z2)
filler.Fill(zs)
pcbnew.SaveBoard("cct-main.kicad_pcb", board)

# 孤岛探测(不设面积门槛,打印接触点)
for t in board.GetTracks():
    if t.GetNetCode()!=gnd: continue
    if is_via(t):
        items.append((mm(t.GetPosition().x),mm(t.GetPosition().y)))
    else:
        e=ends(t); items.append((e[0],e[1])); items.append((e[2],e[3]))
for z2 in board.Zones():
    if z2.GetIsRuleArea() or z2.GetNetCode()!=gnd: continue
    ly = F if z2.GetZoneName()=="GND_F" else B
    sps = z2.GetFilledPolysList(ly)
    for i in range(sps.OutlineCount()):
        bb = sps.Outline(i).BBox()
        x1,y1,x2,y2 = mm(bb.GetLeft()),mm(bb.GetTop()),mm(bb.GetRight()),mm(bb.GetBottom())
        touch = []
        for (qx,qy) in items:
            if x1-0.1<qx<x2+0.1 and y1-0.1<qy<y2+0.1:
                if sps.Contains(VECTOR2I(FromMM(qx),FromMM(qy)), i):
                    touch.append((round(qx,1),round(qy,1)))
                    if len(touch)>3: break
        if len(touch)<=3:
            print(f"  {z2.GetZoneName()}[{i}] ({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f}) 接触{len(touch)}: {touch[:3]}")
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
