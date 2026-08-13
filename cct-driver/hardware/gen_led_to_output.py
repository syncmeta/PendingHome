#!/usr/bin/env python3
"""12 颗通道指示灯:改成从输出端取信号,并挪到保险丝与端子之间那条带上。

改之前:灯接在 74HCT245 的输出侧(`CHn_xx_G`,栅阻之前),阴极经 4.7k 到 GND;
位置由 gen_pcb.py 里一串手写的 x 槽位决定,跟通道列毫无关系 —— 这就是"灯排得
对不上是哪一路"的根因(CH5 那一对甚至被劈开 45mm)。

改之后:灯跨在本路输出端子的 **V+ 与漏极之间**,与灯带并联:

    CHn_VOUT ──▶| LEDn ──[ 40.2k ]── CHn_CW_D / CHn_WW_D ──▶ MOS 漏极

  · MOS 导通 → 灯亮;MOS 断开 → 漏极被拉到 V+,灯两端 0V → 灭。
  · **V+ 取自支路保险丝下游**(V24_BUS 与 CHn_VOUT 之间只隔着 F2–F7 一个器件),
    所以支路丝一断,那一路的灯直接灭 —— 这正是下单清单里记着的那个
    「支路丝断 = 逻辑全正常、只有输出不通 = 最容易被误判成坏板」的坑。
  · 与灯带**并联**不是串联:不接灯带照常亮,灯带也不会有残光。
  · 限流 40.2k(C12447,R67 已在用,不新增料号):(24−2.6)/40.2k ≈ 0.53mA,
    与原来 5V+4.7k 的 0.51mA 亮度基本一致;0603 上压降 21.4V、功耗 11mW(额定 100mW)。
    28V(电源调到顶)时 0.63mA / 16mW,仍有余量。

摆位:保险丝 courtyard 底边 y=128.90、端子 courtyard 上沿 y=133.96,中间 5.06mm,
全板宽度上除 TP6 外没有任何元件。每路两条链一行排开,链路顺着电流方向从左到右:

    VOUT(x=列心−3.81) ── LED ── 电阻 ── CW_D(x=列心)      ← CW 那条,天然一左一右
    VOUT ──(过孔下底层,横过 CW_D,再上来)── LED ── 电阻 ── WW_D  ← WW 那条

底层这条带上原本一根信号线都没有(只有 GND 覆铜),所以 WW 那条的跨接走底层最干净。

⚠️ **CH1 是唯一的例外**:TP6(CH1_CW_D 的测试点)就在 (80, 132.5),正压在常规行上。
把 CH1 的 CW 那条链单独抬到 y=130.0 避开它;TP6 本身不动,收板实操单里
它那两条判据照旧成立。

幂等:重复运行结果一致。运行:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_led_to_output.py
"""
import gc

gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM, EDA_ANGLE, DEGREES_T

BOARD = "cct-main.kicad_pcb"
board = pcbnew.LoadBoard(BOARD)
mm = pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu

COL = {1: 80.0, 2: 66.0, 3: 52.0, 4: 38.0, 5: 24.0, 6: 10.0}
CH = {  # 通道 → (CW 灯, CW 电阻, WW 灯, WW 电阻)
    1: ("LED2", "R20", "LED3", "R21"), 2: ("LED4", "R26", "LED5", "R27"),
    3: ("LED6", "R32", "LED7", "R33"), 4: ("LED8", "R38", "LED9", "R39"),
    5: ("LED10", "R44", "LED11", "R45"), 6: ("LED12", "R50", "LED13", "R51"),
}
# 元件行取 y=130.55 —— 这条带看着有 5.06mm(保险丝底 128.90 → 端子顶 133.96),
# 实际可用只有中间一小段,上下各被两样东西吃掉:
#   · 每路 2 个 V24_BUS 缝合过孔:y=129.04、**Ø1.0mm** → 下沿 129.54,加 0.2 间距,
#     元件上沿不能高于 129.74
#   · TP6(仅 CH1):原 courtyard 2.59×2.60,上沿 y=131.20
# 两头一夹,CH1 只剩 1.46mm,而 0805 灯的 courtyard 就要 1.34mm —— 放不下灯+电阻。
# 解法不是搬 TP6,而是把它那个明显偏大的 courtyard 收到 IPC 该有的尺寸(见下),
# 上沿退到 131.50,CH1 就和其余五路一样,四个件整排落在 TP6 上方。
# 130.55 这一行:上距过孔 0.34mm、下距 TP6 0.28mm、离端子还有 2.7mm。
Y_ROW = 130.55
DX_LED_CW = -2.95
DX_R_CW = DX_LED_CW + 2.10      # CW 链:V+ 在左、CW_D 在右,天然顺流
# CH6 例外:它的 V+ 主铜在 y<130 处斜着往右拐(6.19→7.50,2.0mm 宽),
# 那条斜线的边缘正好蹭到常规位置上灯的阴极盘(实测只差 0.004mm)。
# CH6 的 CW_D 又比别路靠右(列心+0.9),所以整条链右移 0.55mm,两头都松开:
# 阴极离斜线 0.42mm、电阻 2 脚照样落在 CW_D 主铜上。
DX_CW_OVERRIDE = {6: (-2.40, -2.40 + 2.10)}
PITCH = 2.10   # 灯与电阻的中心距:courtyard 之间留 0.21mm。
               # 两者的**封装丝印外框**在这个距离下会压在一起,由 gen_strip_res_silk.py
               # 去掉电阻那一侧的外框来解决(电阻无极性,外框纯装饰);
               # 拉开到 2.6mm 也能分开外框,但会把电阻推到别的铜上(clearance 4→10),
               # 所以选择去外框而不是拉距离。**灯的外框与极性标记完整保留。**
Y_JUMP = 132.4           # V+ 跨到右边用的底层跳线(TP6 是纯贴片盘,底层从它下面过没问题)
DX_VIA_IN = -3.81        # 跳线左端过孔:直接落在 V+ 那条 2.0mm 主铜上
W_SIG = 0.3              # 指示灯支路线宽(0.53mA,0.3mm 绰绰有余)
VIA_D, VIA_DRILL = 0.6, 0.3

# ---------- 0. 把 TP6 的 courtyard 收到 IPC 尺寸 ----------
# TP6 是个 1.5mm 的裸铜测试盘,没有本体,原 courtyard 却画到 2.59×2.60。
# IPC 的算法是"焊盘外沿 + 0.25mm",对 1.5mm 盘就是 2.0×2.0。
# **这纯粹是 DRC 用的构造层(F.CrtYd),不是铜、不是阻焊、不进任何出货文件,
# 实物一点不变** —— 收了它只是不再虚占 0.6mm 的地方。
TP6_CRTYD = 2.0
tp6 = next(f for f in board.GetFootprints() if f.GetReference() == "TP6")
for g in tp6.GraphicalItems():
    if g.GetLayer() == pcbnew.F_CrtYd and g.GetClass() == "PCB_SHAPE":
        bb = g.GetBoundingBox()
        cxx = (mm(bb.GetLeft()) + mm(bb.GetRight())) / 2
        cyy = (mm(bb.GetTop()) + mm(bb.GetBottom())) / 2
        g.SetShape(pcbnew.SHAPE_T_RECT)
        g.SetStart(VECTOR2I(FromMM(cxx - TP6_CRTYD / 2), FromMM(cyy - TP6_CRTYD / 2)))
        g.SetEnd(VECTOR2I(FromMM(cxx + TP6_CRTYD / 2), FromMM(cyy + TP6_CRTYD / 2)))
b0 = tp6.GetCourtyard(pcbnew.F_CrtYd).BBox()
print(f"TP6 courtyard 收到 {mm(b0.GetRight())-mm(b0.GetLeft()):.2f}×{mm(b0.GetBottom())-mm(b0.GetTop()):.2f}mm"
      f"(上沿 y={mm(b0.GetTop()):.2f}) —— 纯 DRC 构造,不动铜不动实物")


fps = {f.GetReference(): f for f in board.GetFootprints()}
nets = {n: board.FindNet(n) for n in
        [f"CH{c}_{s}" for c in COL for s in ("VOUT", "CW_D", "WW_D")] +
        [f"LED{i}_K" for i in range(2, 14)]}


def pad(ref, num):
    return next(p for p in fps[ref].Pads() if p.GetNumber() == str(num))


def place(ref, x, y, rot):
    fp = fps[ref]
    fp.SetOrientationDegrees(0)
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    fp.SetOrientationDegrees(rot)


def track(x1, y1, x2, y2, layer, net, w=W_SIG):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
    t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
    t.SetWidth(FromMM(w))
    t.SetLayer(layer)
    t.SetNet(net)
    t.thisown = 0
    board.Add(t)


def via(x, y, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetWidth(FromMM(VIA_D))
    v.SetDrill(FromMM(VIA_DRILL))
    v.SetNet(net)
    v.thisown = 0
    board.Add(v)



def copper_x_at(netname, y, xlo, xhi):
    """量出某网络的顶层主铜在 y 这一行的实际 x(取落在 [xlo,xhi] 内、最粗的那段)。"""
    best = None
    for t in board.GetTracks():
        if t.GetNetname() != netname or t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() != F:
            continue
        s_, e_ = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = mm(s_.x), mm(s_.y), mm(e_.x), mm(e_.y)
        if min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6:
            x = x1 if abs(y2 - y1) < 1e-9 else x1 + (x2 - x1) * (y - y1) / (y2 - y1)
            if xlo <= x <= xhi and (best is None or mm(t.GetWidth()) > best[1]):
                best = (x, mm(t.GetWidth()))
    return best[0] if best else None


# ---------- 1. 清掉这 24 个件的旧走线 ----------
# 旧接法留下的:LEDn_K 那 12 段短线,以及 CHn_xx_G 上通往旧灯位的支线。
# 做法:先删 LEDn_K 全部走线;CHn_xx_G 的悬空支线在最后统一按"连不到任何焊盘"清理。
KNETS = {f"LED{i}_K" for i in range(2, 14)}   # 只动 12 颗通道指示灯,LED1(ESP32 状态灯)不碰
old = [t for t in board.GetTracks() if t.GetNetname() in KNETS]
for t in old:
    board.Remove(t)
print(f"清掉旧的 LEDn_K 走线 {len(old)} 段")

# ---------- 2. 改网络 + 摆位 + 布线 ----------
for ch, cx in COL.items():
    led_cw, r_cw, led_ww, r_ww = CH[ch]
    vout, cwd, wwd = nets[f"CH{ch}_VOUT"], nets[f"CH{ch}_CW_D"], nets[f"CH{ch}_WW_D"]

    cwx = copper_x_at(f"CH{ch}_CW_D", Y_ROW, cx - 3.0, cx + 3.0)
    wwx = copper_x_at(f"CH{ch}_WW_D", Y_ROW, cx + 3.0, cx + 9.0)
    assert cwx is not None and wwx is not None, f"CH{ch} 在 y={Y_ROW} 这行量不到漏极主铜"
    # 跳线右端过孔要离 CW_D 主铜(半宽 0.6)+ 过孔半径 0.3 + 间距 0.2 ≥ 1.1mm
    vx_out = max(cx + 1.65, cwx + 1.35)   # 过孔离 CW_D 主铜:半宽0.6 + 孔半径0.3 + 间距0.45
    dx_led_ww = (vx_out + 1.05) - cx      # 灯阳极正好落在过孔上
    dx_r_ww = dx_led_ww + PITCH
    for led, res, drain, dx_led, dx_r, y in (
            (led_cw, r_cw, cwd) + DX_CW_OVERRIDE.get(ch, (DX_LED_CW, DX_R_CW)) + (Y_ROW,),
            (led_ww, r_ww, wwd, dx_led_ww, dx_r_ww, Y_ROW)):
        pad(led, 1).SetNet(vout)      # 阳极 → 本路 V+
        pad(res, 2).SetNet(drain)     # 电阻另一端 → 本路漏极(原来是 GND)
        place(led, cx + dx_led, y, 180)   # 灯:阳极在左、阴极在右
        place(res, cx + dx_r, y, 0)       # 电阻:1 脚在左(接阴极)、2 脚在右(接漏极)
        # 阴极 ↔ 电阻 1 脚
        a, b_ = pad(led, 2).GetPosition(), pad(res, 1).GetPosition()
        track(mm(a.x), mm(a.y), mm(b_.x), mm(b_.y), F, nets[f"{led}_K"])
        # 电阻 2 脚 ↔ 漏极主铜
        c = pad(res, 2).GetPosition()
        dx_target = copper_x_at(drain.GetNetname(), mm(c.y), cx - 2.0, cx + 8.0)
        assert dx_target is not None, f"{drain.GetNetname()} 在 y={mm(c.y):.2f} 这一行找不到主铜"
        track(mm(c.x), mm(c.y), dx_target, mm(c.y), F, drain)

    # CW 那条:阳极直接落在 V+ 主铜上,补一小段确认连接
    a = pad(led_cw, 1).GetPosition()
    track(mm(a.x), mm(a.y), cx - 3.81, mm(a.y), F, vout)
    # WW 那条:V+ 从底层横过 CW_D
    via(cx + DX_VIA_IN, Y_JUMP, vout)
    via(vx_out, Y_JUMP, vout)
    track(cx + DX_VIA_IN, Y_JUMP, vx_out, Y_JUMP, B, vout)
    aw = pad(led_ww, 1).GetPosition()
    track(vx_out, Y_JUMP, mm(aw.x), mm(aw.y), F, vout)

print(f"12 颗灯改接输出端并就位(每路 CW/WW 各一条链)")



# ---------- 3. 剪掉栅极网上那截通往旧灯位的残枝 ----------
# 灯从 CHn_xx_G 上摘走之后,原来伸过去的那一小段走线就成了悬空残枝(还挂在同一个网上,
# 电气无害,但等于给栅极挂了根天线)。只在这 12 个栅极网上做"叶子剪枝":反复删掉
# 那些有一头既不接焊盘、也不接同网其它走线的段,直到剪不动为止。
# **只剪这 12 个网** —— GND / V24_BUS 这些是靠覆铜连的,用同样的判据会误伤一大片。
GNETS = [f"CH{c}_{s}_G" for c in COL for s in ("CW", "WW")]

def prune():
    """只在 12 个栅极网上做:走线/过孔/焊盘连成若干块,**不含任何焊盘**的整块删掉。
    只敢在这 12 个网上这么干 —— GND / V24_BUS 那些是靠覆铜连的,同样判据会误伤一大片。"""
    total = 0
    for netname in GNETS:
        items = [t for t in board.GetTracks() if t.GetNetname() == netname]
        if not items:
            continue
        parent = {}

        def find(a):
            while parent.setdefault(a, a) != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b_):
            ra, rb = find(a), find(b_)
            if ra != rb:
                parent[ra] = rb

        ends = []
        for t in items:
            if t.Type() == pcbnew.PCB_VIA_T:
                q = t.GetPosition()
                n1 = (round(mm(q.x), 3), round(mm(q.y), 3), "F.Cu")
                n2 = (round(mm(q.x), 3), round(mm(q.y), 3), "B.Cu")
            else:
                a_, b2 = t.GetStart(), t.GetEnd()
                lay = board.GetLayerName(t.GetLayer())
                n1 = (round(mm(a_.x), 3), round(mm(a_.y), 3), lay)
                n2 = (round(mm(b2.x), 3), round(mm(b2.y), 3), lay)
            union(n1, n2)
            ends.append((t, n1, n2))

        # 焊盘:落在焊盘范围内的节点并成一组
        keep = set()
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() != netname:
                    continue
                bb = p.GetBoundingBox()
                l, t_, r, b_ = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
                lays = {board.GetLayerName(x) for x in p.GetLayerSet().Seq()}
                for n in [n for n in list(parent)]:
                    if l - 0.05 <= n[0] <= r + 0.05 and t_ - 0.05 <= n[1] <= b_ + 0.05 and n[2] in lays:
                        keep.add(find(n))
        for t, n1, n2 in ends:
            if find(n1) not in keep and find(n2) not in keep:
                board.Remove(t)
                total += 1
    return total

n = prune()
print(f"剪掉栅极网上通往旧灯位的悬空残枝(含随之悬空的过孔){n} 段")


# ---------- 4. 剪掉栅极网上通往旧灯位的残枝 ----------
# 灯摘走之后,原来伸过去的那截走线(和它带的过孔)还挂在网上,DRC 报 track_dangling /
# via_dangling。只在这 12 个栅极网上剪 —— GND / V24_BUS 那些是靠覆铜连的,不能这么判。
#
# ⚠️ 写法上有个坑:一边 board.Remove() 一边再去 GetTracks()/GetStart(),SWIG 代理会失效
#    (报 'SwigPyObject' object has no attribute 'x')。所以先把几何快照成纯 Python 数据,
#    在内存里迭代算完"哪些该死",最后一次性删。
def prune_gate_stubs():
    GN = {f"CH{c}_{x}_G" for c in COL for x in ("CW", "WW")}
    snap = []          # (obj, netname, kind, layer, p1, p2)
    for t in board.GetTracks():
        n = t.GetNetname()
        if n not in GN:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            q = t.GetPosition()
            snap.append([t, n, "via", None, (round(mm(q.x), 3), round(mm(q.y), 3)), None, True])
        else:
            a_, b_ = t.GetStart(), t.GetEnd()
            snap.append([t, n, "trk", t.GetLayer(),
                         (round(mm(a_.x), 3), round(mm(a_.y), 3)),
                         (round(mm(b_.x), 3), round(mm(b_.y), 3)), True])
    padbox = {}
    for fp in board.GetFootprints():
        for q in fp.Pads():
            n = q.GetNetname()
            if n in GN:
                bb = q.GetBoundingBox()
                padbox.setdefault(n, []).append(
                    (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))

    def on_pad(n, pt):
        return any(l - 0.03 <= pt[0] <= r + 0.03 and t_ - 0.03 <= pt[1] <= b_ + 0.03
                   for (l, t_, r, b_) in padbox.get(n, []))

    while True:
        changed = False
        for it in snap:
            if not it[6] or it[2] != "trk":
                continue
            for pt in (it[4], it[5]):
                if on_pad(it[1], pt):
                    continue
                touch = False
                for o in snap:
                    if o is it or not o[6] or o[1] != it[1]:
                        continue
                    if o[2] == "via":
                        if abs(o[4][0] - pt[0]) < 0.03 and abs(o[4][1] - pt[1]) < 0.03:
                            touch = True; break
                    elif o[3] == it[3] and (
                            (abs(o[4][0] - pt[0]) < 0.03 and abs(o[4][1] - pt[1]) < 0.03) or
                            (abs(o[5][0] - pt[0]) < 0.03 and abs(o[5][1] - pt[1]) < 0.03)):
                        touch = True; break
                if not touch:
                    it[6] = False; changed = True; break
        for it in snap:                       # 只剩单层有铜的过孔也没用了
            if not it[6] or it[2] != "via":
                continue
            lays = {o[3] for o in snap if o[6] and o[2] == "trk" and o[1] == it[1] and
                    (abs(o[4][0] - it[4][0]) < 0.03 and abs(o[4][1] - it[4][1]) < 0.03 or
                     abs(o[5][0] - it[4][0]) < 0.03 and abs(o[5][1] - it[4][1]) < 0.03)}
            if len(lays) < 2:
                it[6] = False; changed = True
        if not changed:
            break

    dead = [it for it in snap if not it[6]]
    for it in dead:
        board.Remove(it[0])
    return sum(1 for it in dead if it[2] == "trk"), sum(1 for it in dead if it[2] == "via")

_t, _v = prune_gate_stubs()
print(f"剪掉栅极网上通往旧灯位的残枝:走线 {_t} 段 + 过孔 {_v} 个")


pcbnew.SaveBoard(BOARD, board)
print("✅ 铜这一层完成(摆位/改网/布线/剪枝)。丝印请接着跑 gen_led_silk.py")
