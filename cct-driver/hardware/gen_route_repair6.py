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

def trk(pts,netname,w,layer=F):
    for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2)))
        t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(board.FindNet(netname))
        board.Add(t)
def via(x,y,netname="GND",dia=0.8,drill=0.4):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x),FromMM(y)))
    v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
    v.SetNet(board.FindNet(netname)); v.SetLayerPair(F,B)
    board.Add(v)

def via_clear(x,y,r=0.4,margin=0.25):
    for t in board.GetTracks():
        if t.GetNetname()=="GND": continue
        if is_via(t):
            p=t.GetPosition()
            if math.hypot(mm(p.x)-x,mm(p.y)-y) < r+tw(t)/2+margin: return False
        else:
            e=ends(t)
            if spd(x,y,*e) < r+tw(t)/2+margin: return False
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode()==board.FindNet("GND").GetNetCode(): continue
            bb=p.GetBoundingBox()
            cx,cy=(mm(bb.GetLeft())+mm(bb.GetRight()))/2,(mm(bb.GetTop())+mm(bb.GetBottom()))/2
            rad=math.hypot(mm(bb.GetWidth()),mm(bb.GetHeight()))/2
            if math.hypot(cx-x,cy-y) < r+rad+margin: return False
    return True

# 1. U1 pad7 起始段
trk([(9.5,49.5),(9.5,52.0)],"GND",0.3)
# 2. 干接点区 GND 明线网缝合过孔
for (x,y) in [(46.7,134.55),(67.7,131.3)]:
    if via_clear(x,y): via(x,y)
    else: print(f"⚠️ 过孔位 ({x},{y}) 不净空")
# 3. U2 旁 F 小岛
if via_clear(33.2,105.1): via(33.2,105.1)
else: print("⚠️ (33.2,105.1) 不净空")
# 4. F[19] 小条:加宽重叠线吞并
trk([(13.2,41.23),(14.4,41.23)],"GND",0.7)
# 5. 两块 B 大岛:含内点测试 + 净空测试后打 2 孔
gnd = board.FindNet("GND").GetNetCode()
targets = []
for z in board.Zones():
    if z.GetIsRuleArea() or z.GetNetCode()!=gnd or z.GetZoneName()!="GND_B": continue
    sps = z.GetFilledPolysList(B)
    for i in range(sps.OutlineCount()):
        bb = sps.Outline(i).BBox()
        w,h = mm(bb.GetWidth()), mm(bb.GetHeight())
        if w>20 and h>20 and mm(bb.GetLeft())>30:   # 两块大岛
            targets.append((sps,i,mm(bb.GetLeft()),mm(bb.GetTop())))
CANDS = [(50,97),(45,95),(55,100),(48,108),(52,93),(65,93),(70,96),(75,100),(62,90),(58,95),(68,104),(60,108)]
for (sps,i,bx,by) in targets:
    placed = 0
    for (x,y) in CANDS:
        if placed>=2: break
        if sps.Contains(VECTOR2I(FromMM(x),FromMM(y)), i) and via_clear(x,y):
            via(x,y); placed += 1
            print(f"B 岛[{i}] 缝合 ({x},{y})")
    if placed==0:
        print(f"⚠️ B 岛[{i}] 无缝合点")

filler = pcbnew.ZONE_FILLER(board)
zs = pcbnew.ZONES()
for z in board.Zones(): zs.append(z)
filler.Fill(zs)
pcbnew.SaveBoard("cct-main.kicad_pcb", board)
board.BuildConnectivity()
print("未连接数:", board.GetConnectivity().GetUnconnectedCount(True))
