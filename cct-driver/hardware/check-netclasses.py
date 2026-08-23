#!/usr/bin/env python3
"""校验 cct-main.kicad_pro 里的网络类与设计规则没有被重置。

背景见 README「KiCad 工程文件会被 GUI 悄悄重置」一节。
简单说:用 KiCad 图形界面打开本工程时,曾经把 5 个网络类砍成只剩 Default、
把 netclass_patterns 清空、把若干设计规则改回出厂默认。板子已布完线,
铜箔不受影响,但之后再改板 DRC 会按错的规则跑,而且改动是静默的。

基准值取自被重置之前的工程文件(commit 9d2baea 及更早)。
不符合就非零退出并打印差在哪。

用法:
    python3 hardware/check-netclasses.py            # 校验工作区文件
    python3 hardware/check-netclasses.py <路径>      # 校验指定文件
"""
import json
import os
import sys

# —— 基准:被 GUI 重置之前的实际值 ——
# track_width 这五档跟板上实际走线的宽度分布对得上(0.25/0.5/1.0/2.0/3.5mm),
# 是这份基准可信的旁证。
EXPECT_CLASSES = {
    "Default": {"track_width": 0.25, "clearance": 0.2,  "via_diameter": 0.6, "via_drill": 0.3},
    "TRUNK":   {"track_width": 3.5,  "clearance": 0.2,  "via_diameter": 1.2, "via_drill": 0.6},
    "PWR2":    {"track_width": 2.0,  "clearance": 0.25, "via_diameter": 1.0, "via_drill": 0.5},
    "PWR1":    {"track_width": 1.0,  "clearance": 0.2,  "via_diameter": 0.8, "via_drill": 0.4},
    "GND":     {"track_width": 0.5,  "clearance": 0.2,  "via_diameter": 0.8, "via_drill": 0.4},
}
EXPECT_PATTERN_COUNT = 14
EXPECT_MIN_TEXT_HEIGHT = 0.5      # 注意:0.8 是 KiCad 出厂默认,正是被重置后的值

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cct-main.kicad_pro")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as f:
            proj = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ 读不了工程文件 {path}: {e}")
        return 1

    problems = []

    # —— 网络类 ——
    # meta.version 在 KiCad 9(v4) 与 KiCad 10(v5) 之间会变,这是正常迁移,不校验版本号;
    # 只校验内容有没有丢。
    net = proj.get("net_settings") or {}
    classes = {c.get("name"): c for c in net.get("classes") or []}

    missing = [n for n in EXPECT_CLASSES if n not in classes]
    if missing:
        problems.append(f"网络类丢失: {', '.join(missing)}(应有 {len(EXPECT_CLASSES)} 个,现有 {len(classes)} 个)")

    for name, expect in EXPECT_CLASSES.items():
        got = classes.get(name)
        if got is None:
            continue
        for key, want in expect.items():
            have = got.get(key)
            if have is None or abs(float(have) - want) > 1e-9:
                problems.append(f"网络类 {name}.{key}: 应为 {want},实为 {have}")

    extra = [n for n in classes if n not in EXPECT_CLASSES]
    if extra:
        problems.append(f"多出未登记的网络类: {', '.join(extra)}(新增网络类请同步更新本脚本的基准)")

    # —— netclass 匹配规则 ——
    patterns = net.get("netclass_patterns")
    n_pat = len(patterns) if isinstance(patterns, list) else 0
    if n_pat != EXPECT_PATTERN_COUNT:
        problems.append(f"netclass_patterns 应有 {EXPECT_PATTERN_COUNT} 条,实为 {n_pat} 条")

    # —— 设计规则 ——
    rules = ((proj.get("board") or {}).get("design_settings") or {}).get("rules") or {}
    mth = rules.get("min_text_height")
    if mth is None or abs(float(mth) - EXPECT_MIN_TEXT_HEIGHT) > 1e-9:
        problems.append(f"min_text_height: 应为 {EXPECT_MIN_TEXT_HEIGHT},实为 {mth}"
                        f"{'(0.8 是 KiCad 出厂默认,说明被重置了)' if mth == 0.8 else ''}")

    if problems:
        print(f"❌ 工程文件的网络类/设计规则被改动了:{path}")
        for p in problems:
            print(f"   · {p}")
        print()
        print("   最可能的原因:有人用 KiCad 图形界面打开过本工程,它把这些设置重置成了默认值。")
        print("   若你并没有故意改这些设置,直接退回即可:")
        print("       git checkout -- hardware/cct-main.kicad_pro")
        print("   若是有意调整(例如新增了网络类),请同步更新 hardware/check-netclasses.py 里的基准值。")
        print("   详见 README「KiCad 工程文件会被 GUI 悄悄重置」一节。")
        return 1

    print(f"✅ 网络类与设计规则正常({len(EXPECT_CLASSES)} 个类 / {EXPECT_PATTERN_COUNT} 条匹配规则)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
