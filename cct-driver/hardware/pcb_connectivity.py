#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按**真实的铜**算连通性:焊盘 / 走线 / 过孔 / 每一片填充覆铜岛,两两做几何碰撞。

## 为什么不用 KiCad 自己的连通性

KiCad 的 ratsnest 会告诉你「有 19 条没连上」,但它把一块被切碎的覆铜按 item 报,
读出来是「覆铜 GND ↔ 覆铜 GND」,看着像记账问题,于是一路被当成
「覆铜分片,电气上通,靠底层地平面」放过去。**这块板 2026-08-17 就栽在这上面**:
碎铜里正好夹着 ESP32 的 EN 上拉和上电延时电容,那几只脚是真浮着的,
DRC 一条错误都没报。

这里换个粒度:**把每一片填充岛当成一个独立节点**,自己做并查集。
于是「哪几只焊盘落在同一块铜里」「这块铜有没有过孔通到另一层」
「这块铜到底跟主体连没连上」这三个问题都能直接回答。

判据(check-floating-pads.py 用,gen_gnd_stitch.py 也用同一套):
  · 一块连通铜里**只有焊盘和覆铜岛、没有任何走线和过孔** → 里面的焊盘是浮脚
  · 一块连通铜里没有焊盘也没有走线,只有过孔 → 悬空过孔
  · 一个网络的焊盘落在两块以上连通铜里 → 这个网络是断的

碰撞用 pcbnew 的 GetEffectiveShape().Collide(),不是包围盒近似;
包围盒只用来先粗筛,省时间。
"""
import collections

import pcbnew

IU = 1e6            # nm / mm


def mm(v):
    return v / IU


class Node:
    __slots__ = ("kind", "label", "net", "layers", "shapes", "bbox")

    def __init__(self, kind, label, net, layers, shapes, bbox):
        self.kind, self.label, self.net = kind, label, net
        self.layers, self.shapes, self.bbox = layers, shapes, bbox


def _bbox(shape):
    b = shape.BBox()
    return (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())


def collect(board, only_net=None):
    """→ {网络名: [Node]}。only_net 给了就只收那一个网络(快很多)。"""
    nodes = collections.defaultdict(list)

    def want(net):
        return net and (only_net is None or net == only_net)

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            net = pad.GetNetname()
            if not want(net):
                continue
            ls = [l for l in pad.GetLayerSet().CuStack()]
            sh = {l: pad.GetEffectiveShape(l) for l in ls}
            if not sh:
                continue
            p = pad.GetPosition()
            nodes[net].append(Node(
                "pad", f"{ref}.{pad.GetNumber()}@({mm(p.x):.2f},{mm(p.y):.2f})",
                net, set(ls), sh, _bbox(next(iter(sh.values())))))

    for t in board.GetTracks():
        net = t.GetNetname()
        if not want(net):
            continue
        if t.GetClass() == "PCB_VIA":
            ls = [l for l in t.GetLayerSet().CuStack()]
            sh = {l: t.GetEffectiveShape(l) for l in ls}
            p = t.GetPosition()
            kind, lbl = "via", f"过孔@({mm(p.x):.2f},{mm(p.y):.2f})"
        else:
            lay = t.GetLayer()
            ls, sh = [lay], {lay: t.GetEffectiveShape(lay)}
            a, b = t.GetStart(), t.GetEnd()
            kind = "track"
            lbl = (f"走线 {board.GetLayerName(lay)} "
                   f"({mm(a.x):.2f},{mm(a.y):.2f})→({mm(b.x):.2f},{mm(b.y):.2f})")
        if not sh:
            continue
        nodes[net].append(Node(kind, lbl, net, set(ls), sh,
                               _bbox(next(iter(sh.values())))))

    for z in board.Zones():
        net = z.GetNetname()
        if not want(net) or z.GetIsRuleArea():
            continue
        for layer in z.GetLayerSet().CuStack():
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET()
                one.AddOutline(polys.Outline(i))
                for h in range(polys.HoleCount(i)):
                    one.AddHole(polys.Hole(i, h), 0)
                bb = one.BBox()
                nodes[net].append(Node(
                    "zone",
                    f"覆铜「{z.GetZoneName() or '(无名)'}」{board.GetLayerName(layer)} "
                    f"第{i + 1}片 {one.Area() / (IU * IU):.2f}mm²",
                    net, {layer}, {layer: one},
                    (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())))
    return nodes


def touches(a, b):
    if a.bbox[2] < b.bbox[0] or b.bbox[2] < a.bbox[0]:
        return False
    if a.bbox[3] < b.bbox[1] or b.bbox[3] < a.bbox[1]:
        return False
    for l in a.layers & b.layers:
        if a.shapes[l].Collide(b.shapes[l], 0):
            return True
    return False


def components(items):
    """→ ([每块连通铜的下标列表], {下标: [直接贴着的下标]})"""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    adj = collections.defaultdict(list)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if touches(items[i], items[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
                adj[i].append(j)
                adj[j].append(i)
    groups = collections.defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    return list(groups.values()), adj
