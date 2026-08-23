#!/usr/bin/env python3
"""整板绕板心旋转 180°,让文件坐标系直接等于上墙安装姿态(接线端子在下方)。

背景:板子是倒装的 —— 端子那条边朝下挂在墙上。此前的做法是把丝印文字预转
180° 来"补偿"这个安装姿态,但 KiCad 对封装自带文字有 keep-upright 保护,
绘图时会把倒过来的位号又扶正,于是 33 条独立标注转过去了、205 个位号没转,
出货 Gerber 里位号在安装姿态下是倒的。

治本做法就是本脚本:把整块板(封装/走线/过孔/覆铜/图形/文字/板框)绕板心
(55, 72.5) 转 180°,此后**文件里看到的方向就是装上墙看到的方向**,所有丝印
文字回归自然角度,不需要任何人工补偿,也不用关掉 keep-upright。

板框正好 0–110 × 0–145,绕板心 180° 后自映射,原点不变。
物理上真正改变的只有 205 个位号相对铜箔转了 180°(这正是要修的那件事);
铜层/阻焊/钢网/钻孔/板框旋转回去后与旧版逐点一致。

一次性脚本:再跑一次会把板子转回去。运行:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_rotate180.py
"""
import gc
gc.disable()
import pcbnew
from pcbnew import VECTOR2I, FromMM, EDA_ANGLE, DEGREES_T

BOARD = "cct-main.kicad_pcb"
BOARD_W, BOARD_H = 110.0, 145.0

board = pcbnew.LoadBoard(BOARD)
mm = pcbnew.ToMM

center = VECTOR2I(FromMM(BOARD_W / 2), FromMM(BOARD_H / 2))
half = EDA_ANGLE(180.0, DEGREES_T)

# ---------- 1. 几何整体旋转 ----------
n_fp = n_tr = n_dr = n_zn = 0
for fp in board.GetFootprints():
    fp.Rotate(center, half)
    n_fp += 1
for tr in board.GetTracks():          # 走线 + 过孔 + 圆弧
    tr.Rotate(center, half)
    n_tr += 1
for dr in board.GetDrawings():        # 板框 / 白油块 / 功能标注文字
    dr.Rotate(center, half)
    n_dr += 1
for zn in board.Zones():              # 覆铜(轮廓与已填充多边形一起转)
    zn.Rotate(center, half)
    n_zn += 1
print(f"旋转:封装 {n_fp} / 走线过孔 {n_tr} / 图形文字 {n_dr} / 覆铜 {n_zn}")

# 辅助原点(钻孔/贴片文件的可选基准)也跟着转,免得日后启用时对不上
ds = board.GetDesignSettings()
for get, set_ in ((ds.GetAuxOrigin, ds.SetAuxOrigin), (ds.GetGridOrigin, ds.SetGridOrigin)):
    p = get()
    if p.x or p.y:
        set_(VECTOR2I(FromMM(BOARD_W) - p.x, FromMM(BOARD_H) - p.y))
        print(f"  辅助/栅格原点已跟随旋转: ({mm(p.x)}, {mm(p.y)}) → "
              f"({BOARD_W - mm(p.x)}, {BOARD_H - mm(p.y)})")

# ---------- 2. 丝印文字回归自然角度 ----------
# 旋转把每条文字的角度都 +180° 了。既然文件坐标系现在就是安装姿态,
# 这些补偿角度全部作废:位号与横排标注归 0°,右缘那条竖排标注归 90°。
VERTICAL = "FUSE 4A-T x6 / MAIN 15A"   # 右缘竖排(旋转后到了左缘)

n_ref = 0
for fp in board.GetFootprints():
    fp.Reference().SetTextAngleDegrees(0)   # keep-upright 保持开启,不动
    n_ref += 1

n_txt = n_vert = 0
for dr in board.GetDrawings():
    if dr.GetClass() != "PCB_TEXT":
        continue
    if dr.GetText() == VERTICAL:
        dr.SetTextAngleDegrees(90)
        n_vert += 1
    else:
        dr.SetTextAngleDegrees(0)
    n_txt += 1
print(f"文字角度:位号 {n_ref} 条归 0°,独立标注 {n_txt} 条(其中竖排 {n_vert} 条归 90°,余归 0°)")

# ---------- 3. 自检 ----------
bb = board.GetBoardEdgesBoundingBox()
l, t, r, b = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
print(f"板框包围盒: ({l}, {t}) – ({r}, {b})")
assert abs(l + 0.05) < 1e-6 and abs(t + 0.05) < 1e-6, "板框左上角不在原点附近"
assert abs(r - (BOARD_W + 0.05)) < 1e-6 and abs(b - (BOARD_H + 0.05)) < 1e-6, "板框尺寸变了"

terminals = {}
for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref in ("J1", "J3", "J8", "J2", "J9", "J11"):
        terminals[ref] = round(mm(fp.GetPosition().y), 2)
print("端子 y 坐标(应全部落在板子下半部 y>72.5):", terminals)
assert all(y > BOARD_H / 2 for ref, y in terminals.items() if ref in ("J1", "J3", "J8")), \
    "接线端子没有落到板子下方"

pcbnew.SaveBoard(BOARD, board)
print("✅ 整板已转正:文件坐标系 = 上墙姿态(端子朝下)")
