#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全板浮脚体检 —— 判据:**碎铜里夹着焊盘却没有过孔和走线,那只脚就是浮的**。

必须用 KiCad 自带 python 运行:
  $KP check-floating-pads.py [板文件] [只看某个网络]

## 为什么要单写这一条

KiCad 的 DRC 把「未连接」按 item 对报,一块填充覆铜被走线切碎之后每一小片都是
独立 item,读出来长这样:

    [unconnected_items]: 覆铜 GND 顶层 ↔ 覆铜 GND 顶层

看上去像是记账问题(「电气上通,靠底层地平面」),就被一路放过去了。
**但如果那一小片碎铜里正好夹着一只焊盘、而这片铜上没有任何过孔或走线通向网络的
其余部分,那只焊盘就是真的浮着的** —— 板子上那个器件根本没接。

这块板 2026-08-17 栽过一次:C11 两只脚、R4 的 3V3 脚、C12 的地脚全趴在一块
1–3mm² 的孤立顶层碎铜上,而那是 ESP32 的 EN 上拉和上电延时电容,悬空则整板起不来。
**DRC 一条错误都没报。**

判据和连通性算法在 pcb_connectivity.py 里,gen_gnd_stitch.py 用的是同一套。

## 报什么

  ❌ 浮脚        某块连通铜里只有焊盘和覆铜岛,没有走线也没有过孔
  ⚠️ 悬空过孔    某块连通铜里没有焊盘也没有走线,只有过孔
  ⚠️ 网络被切开  一个网络的焊盘落在两块以上连通铜里(逐块列出成员,自己判是不是真断)

三项全空才返回 0。
"""
import collections
import sys

import pcbnew

from pcb_connectivity import collect, components

BOARD = sys.argv[1] if len(sys.argv) > 1 else "cct-main.kicad_pcb"
DUMP = sys.argv[2] if len(sys.argv) > 2 else None


def dump(board, items):
    """把一个网络逐块摊开 —— 「这只脚到底连到哪条线、哪颗过孔」就看这个。"""
    comps, adj = components(items)
    comps.sort(key=len, reverse=True)
    print(f"网络 {DUMP}:{len(items)} 个节点,{len(comps)} 块连通铜")
    for k, c in enumerate(comps, 1):
        print(f"\n── 第{k}块({len(c)} 个节点)")
        for i in sorted(c, key=lambda i: (items[i].kind != "pad", items[i].label)):
            print(f"   [{items[i].kind}] {items[i].label}")
            if items[i].kind != "pad":
                continue
            for j in adj[i]:
                print(f"        └ 贴着 {items[j].label}")
            if not adj[i]:
                print("        └ ⚠️ 什么都没贴着")


def main():
    board = pcbnew.LoadBoard(BOARD)
    if DUMP:
        dump(board, collect(board, DUMP)[DUMP])
        return 0

    nets = collect(board)
    floating, split, dangling, detail = [], [], [], {}
    for net in sorted(nets):
        items = nets[net]
        comps, _ = components(items)
        detail[net] = (items, comps)
        if len([c for c in comps if any(items[i].kind == "pad" for i in c)]) > 1:
            split.append(net)
        for c in comps:
            kinds = collections.Counter(items[i].kind for i in c)
            pads = [items[i] for i in c if items[i].kind == "pad"]
            if pads and not kinds["track"] and not kinds["via"]:
                floating.append((net, pads,
                                 [items[i] for i in c if items[i].kind == "zone"]))
            if not pads and kinds["via"] and not kinds["track"]:
                dangling += [(net, items[i]) for i in c if items[i].kind == "via"]

    print("=" * 78)
    print(f"全板浮脚体检 · {BOARD}")
    print(f"网络 {len(nets)} 个 · 节点 {sum(len(v) for v in nets.values())} 个")
    print("=" * 78)

    if floating:
        print(f"\n❌ 浮脚 {sum(len(p) for _, p, _ in floating)} 只"
              f" —— 所在那块铜里没有任何走线和过孔,只有碎铜托着:")
        for net, pads, zones in floating:
            print(f"  · {net}")
            for p in pads:
                print(f"      焊盘 {p.label}")
            for z in zones:
                print(f"      趴在 {z.label}")
    else:
        print("\n✅ 浮脚 0 只(每一只焊盘所在的铜块里都有走线或过孔)")

    if dangling:
        print(f"\n⚠️  悬空过孔 {len(dangling)} 颗 —— 那一块里没有焊盘也没有走线:")
        for net, v in dangling:
            print(f"  · {net:<12} {v.label}")
    else:
        print("✅ 悬空过孔 0 颗")

    if split:
        print(f"\n⚠️  焊盘被切在两块以上连通铜里的网络 {len(split)} 个:")
        for net in split:
            items, comps = detail[net]
            pc = sorted((c for c in comps
                         if any(items[i].kind == "pad" for i in c)),
                        key=len, reverse=True)
            print(f"  · {net} —— {len(pc)} 块")
            for k, c in enumerate(pc, 1):
                pads = [items[i].label for i in c if items[i].kind == "pad"]
                kinds = collections.Counter(items[i].kind for i in c)
                print(f"      第{k}块: 焊盘 {len(pads)} / 走线 {kinds['track']} /"
                      f" 过孔 {kinds['via']} / 覆铜岛 {kinds['zone']}")
                for lb in pads[:8]:
                    print(f"          {lb}")
                if len(pads) > 8:
                    print(f"          …… 另外 {len(pads) - 8} 只")
    else:
        print("\n✅ 没有焊盘被切在两块以上连通铜里的网络")

    ok = not floating and not dangling and not split
    print("\n✅ 全绿" if ok else "\n❌ 上面这些要处理完才算通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
