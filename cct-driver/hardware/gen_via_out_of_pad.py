#!/usr/bin/env python3
"""把 5 个压在贴片焊盘底下的过孔挪出焊盘,只做局部改线。

背景:嘉立创 SMT DFM「元件焊脚到孔」查出全板 31 处贴片焊盘压金属化孔
(见 hardware/dfm-smt-triage.md §14)。其中 5 处的孔腔容积相对该焊盘的钢网锡量
偏大,回流时焊料会被孔吃走,有虚焊风险。本项目的立项前提是**用户零焊接**
(为此砍掉了调试排针、全部选预焊件),"烙铁补一下"这个兜底不成立,所以本批就改。

只动这 5 个过孔的位置和它们各自的引出线;
**不动网络拓扑、不动任何元件位置、不动焊盘尺寸**,其余 26 处压孔一律不碰。

判定口径:孔口(钻孔圆周)离开该焊盘铜面 ≥0.30mm。

用 KiCad 自带 python 运行(不要开图形界面,见 README):
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\
Versions/Current/bin/python3 hardware/gen_via_out_of_pad.py
"""
import gc
import sys
from pathlib import Path

gc.disable()
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

HERE = Path(__file__).parent
mm = ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu

# ——每条改动:过孔旧位 → 新位,以及要跟着改的走线——
#   move_track: (旧端点) → 新过孔位置,把这些走线的该端点拖过去
#   drop_track: 整段删掉(原来那截压在焊盘里的引出线)
#   add_track:  新增引出线 (起点, 终点, 线宽, 层)
MOVES = [
    dict(
        tag="U2.1 BOOT",
        net="BOOT",
        old=(30.100, 109.800), new=(30.250, 107.800),
        # 往上挪到 1 脚焊盘与散热盘之间的空当。往下(3 个脚的下方)才是最短路径,
        # 但那块空当被 SW_NODE 1mm 走线和 FB_5V 斜线夹成一条窄缝,
        # BOOT 与 V24_LOGIC 两颗过孔挤不进去(实测最小裕量掉到 0.00mm)。
        move_track=[(30.100, 109.800)],
        drop_track=[],
        add_track=[((30.250, 108.600), (30.250, 107.800), 0.30, F)],
    ),
    dict(
        tag="U2.2 V24_LOGIC",
        net="V24_LOGIC",
        old=(31.370, 109.800), new=(31.820, 110.600),
        move_track=[(31.370, 109.800)],
        drop_track=[],
        add_track=[((31.500, 110.000), (31.820, 110.600), 0.40, F)],
    ),
    dict(
        tag="R56.2 SW_IN3",
        net="SW_IN3",
        old=(63.850, 137.300), new=(63.050, 138.300),
        move_track=[(63.850, 137.300)],
        drop_track=[((63.800, 137.500), (63.850, 137.320))],
        add_track=[((63.600, 137.700), (63.050, 138.300), 0.25, F)],
    ),
    dict(
        tag="R10.1 CC2",
        net="CC2",
        old=(69.600, 135.450), new=(70.600, 136.000),
        move_track=[(69.600, 135.450)],
        drop_track=[((69.600, 135.750), (69.600, 135.450))],
        add_track=[((69.850, 135.900), (70.600, 136.000), 0.25, F)],
    ),
    dict(
        tag="C43.2 GND",
        net="GND",
        old=(46.700, 134.550), new=(46.700, 134.000),
        # 这颗就在 C43 的 GND 引出线上,顺着原线往上挪即可,不新增任何铜。
        move_track=[(46.700, 134.098)],
        drop_track=[],
        add_track=[],
    ),
]

EPS = FromMM(0.0005)


def same(p, xy):
    return abs(p.x - FromMM(xy[0])) < EPS and abs(p.y - FromMM(xy[1])) < EPS


def main():
    path = HERE / "cct-main.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))

    for m in MOVES:
        net = m["net"]
        old, new = m["old"], m["new"]

        via = None
        for t in board.GetTracks():
            if t.Type() != pcbnew.PCB_VIA_T:
                continue
            if t.GetNetname() == net and same(t.GetPosition(), old):
                via = t
                break
        assert via is not None, f"{m['tag']}: 没找到 {old} 处的过孔"
        via.SetPosition(VECTOR2I(FromMM(new[0]), FromMM(new[1])))

        # 删掉压在焊盘里的旧引出线
        for seg in m["drop_track"]:
            hit = [t for t in board.GetTracks()
                   if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() == net
                   and ((same(t.GetStart(), seg[0]) and same(t.GetEnd(), seg[1]))
                        or (same(t.GetStart(), seg[1]) and same(t.GetEnd(), seg[0])))]
            assert len(hit) == 1, f"{m['tag']}: 待删走线 {seg} 命中 {len(hit)} 条"
            board.Remove(hit[0])

        # 把连在旧孔位上的走线端点拖到新孔位
        moved = 0
        for anchor in m["move_track"]:
            for t in board.GetTracks():
                if t.Type() != pcbnew.PCB_TRACE_T or t.GetNetname() != net:
                    continue
                if same(t.GetStart(), anchor):
                    t.SetStart(VECTOR2I(FromMM(new[0]), FromMM(new[1])))
                    moved += 1
                elif same(t.GetEnd(), anchor):
                    t.SetEnd(VECTOR2I(FromMM(new[0]), FromMM(new[1])))
                    moved += 1
        assert moved >= 1, f"{m['tag']}: 没有走线连到 {m['move_track']}"

        # 新引出线
        for (p1, p2, w, layer) in m["add_track"]:
            tr = pcbnew.PCB_TRACK(board)
            tr.SetStart(VECTOR2I(FromMM(p1[0]), FromMM(p1[1])))
            tr.SetEnd(VECTOR2I(FromMM(p2[0]), FromMM(p2[1])))
            tr.SetWidth(FromMM(w))
            tr.SetLayer(layer)
            tr.SetNet(board.FindNet(net))
            board.Add(tr)

        print(f"  {m['tag']:<16} {old} → {new}  "
              f"改线 {moved} 段 / 删 {len(m['drop_track'])} 段 / 增 {len(m['add_track'])} 段")

    board.Save(str(path))
    print(f"已保存 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
