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
def tw(t):
    try: return mm(t.GetWidth(F)) if is_via(t) else mm(t.GetWidth())
    except TypeError: return mm(t.GetWidth())
def spd(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1; L2=dx*dx+dy*dy
    if L2==0: return math.hypot(px-x1,py-y1)
    t=max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L2))
    return math.hypot(px-(x1+t*dx),py-(y1+t*dy))
gndcode = board.FindNet("GND").GetNetCode()
def via_clear(x,y,r=0.4,margin=0.25):
    for t in board.GetTracks():
        if t.GetNetname()=="GND": continue
        if is_via(t):
            p=t.GetPosition()
            if math.hypot(mm(p.x)-x,mm(p.y)-y) < r+tw(t)/2+margin: return False
        else:
            if spd(x,y,*ends(t)) < r+tw(t)/2+margin: return False
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode()==gndcode: continue
            bb=p.GetBoundingBox()
            cx,cy=(mm(bb.GetLeft())+mm(bb.GetRight()))/2,(mm(bb.GetTop())+mm(bb.GetBottom()))/2
            rad=math.hypot(mm(bb.GetWidth()),mm(bb.GetHeight()))/2
            if math.hypot(cx-x,cy-y) < r+rad+margin: return False
    return True
def via(x,y,dia=0.8,drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x),FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(board.FindNet("GND")); v.SetLayerPair(F,B)
    board.Add(v)

zF = zB = None
for z in board.Zones():
    if z.GetIsRuleArea() or z.GetNetCode()!=gndcode: continue
    if z.GetZoneName()=="GND_F": zF = z.GetFilledPolysList(F)
    elif z.GetZoneName()=="GND_B": zB = z.GetFilledPolysList(B)

# GND_F 主 outline = 面积最大
fmain, fbest = 0, -1
for i in range(zF.OutlineCount()):
    bb = zF.Outline(i).BBox()
    a = mm(bb.GetWidth())*mm(bb.GetHeight())
    if a > fbest: fbest, fmain = a, i
def in_f_main(x,y):
    return zF.Contains(VECTOR2I(FromMM(x),FromMM(y)), fmain)
# GND_B 主 outline
bmain, bbest = 0, -1
for i in range(zB.OutlineCount()):
    bb = zB.Outline(i).BBox()
    a = mm(bb.GetWidth())*mm(bb.GetHeight())
    if a > bbest: bbest, bmain = a, i

# 待缝合 B 岛(>20mm 宽,非主)
targets = []
for i in range(zB.OutlineCount()):
    if i==bmain: continue
    bb = zB.Outline(i).BBox()
    if mm(bb.GetWidth())>15 and mm(bb.GetHeight())>15:
        targets.append(("B",i,bb))
# F 孤岛 [6] 附近(32.7-33.8,104.9-108.1):找 B 主内的点
for i in range(zF.OutlineCount()):
    if i==fmain: continue
    bb = zF.Outline(i).BBox()
    if 32<mm(bb.GetLeft())<34 and 104<mm(bb.GetTop())<106:
        targets.append(("F",i,bb))

import itertools
for kind,i,bb in targets:
    x1,y1,x2,y2 = mm(bb.GetLeft()),mm(bb.GetTop()),mm(bb.GetRight()),mm(bb.GetBottom())
    placed = []
    step = 0.8 if kind=="F" else 1.5
    xs = [x1+step*k for k in range(int((x2-x1)/step)+1)]
    ys = [y1+step*k for k in range(int((y2-y1)/step)+1)]
    for y in ys:
        for x in xs:
            if len(placed)>=2: break
            if placed and math.hypot(x-placed[0][0],y-placed[0][1])<8: continue
            pt = VECTOR2I(FromMM(x),FromMM(y))
            if kind=="B":
                if not (zB.Contains(pt,i) and in_f_main(x,y)): continue
            else:
                if not (zF.Contains(pt,i) and zB.Contains(pt,bmain)): continue
            r = 0.3 if kind=="F" else 0.4
            if via_clear(x,y,r=r,margin=0.22):
                via(x,y, dia=(0.6 if kind=="F" else 0.8), drill=(0.3 if kind=="F" else 0.4))
                placed.append((x,y))
        if len(placed)>=2: break
    print(f"{kind}岛[{i}] ({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f}): 缝 {len(placed)} 孔 {[(round(a,1),round(b,1)) for a,b in placed]}")

filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones(): zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard("cct-main.kicad_pcb", board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
