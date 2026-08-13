#!/usr/bin/env python3
"""把板文件绘图设置里的 `subtractmaskfromsilk` 打开(文本层,幂等)。

**背景。** 「丝印压在裸露焊盘上」这件事,出货包里**本来就已经处理掉了** ——
我们的导出命令一直带着 `--subtract-soldermask`,`cct-main-F_Silkscreen.gto` 里
有一个 `%LPC*%`(清极性)块,后面跟着 **571 个挖空闪光,正好等于 F_Mask 的 571 个
开窗**,也就是每一个阻焊开窗都从丝印里挖掉了。所以实际印出来的板子上,
丝印一点都不会落在裸铜上。

**但板文件里存的绘图设置是 `(subtractmaskfromsilk no)`。** 命令行的 flag 盖过了它,
于是出货包是对的;可**只要有人从图形界面导出、或者忘了带这个 flag,导出来的丝印
就是没挖空的那一版**(437,780 字节,而不是 458,749)。这是个静默的坑,和 README 里
记的那几个同类。

本脚本把这个设置改成 `yes`,让板文件自己就是对的,不再依赖"记得加 flag"。
**对现有出货文件零影响** —— 我们本来就在加 flag,导出结果逐字节不变。

幂等:改完再跑会报"已经是 yes"。用法:
    python3 hardware/gen_plot_subtract_mask.py
    python3 hardware/gen_plot_subtract_mask.py --check   只报告,不写盘
"""
import sys
from pathlib import Path

BOARD = Path(__file__).parent / "cct-main.kicad_pcb"
CHECK_ONLY = "--check" in sys.argv

text = BOARD.read_text(encoding="utf-8")
OLD = "(subtractmaskfromsilk no)"
NEW = "(subtractmaskfromsilk yes)"

if OLD not in text:
    if NEW in text:
        print("✅ 板文件里 subtractmaskfromsilk 已经是 yes,无需处理")
        sys.exit(0)
    print("❌ 板文件里找不到 subtractmaskfromsilk,先查清楚再改")
    sys.exit(2)

n = text.count(OLD)
print(f"板文件绘图设置:{OLD} → {NEW}({n} 处)")
print("  说明:出货包本来就是挖空的(命令行带 --subtract-soldermask),")
print("  改这一处只是让板文件自己也对,避免有人从 GUI 导出时拿到没挖空的丝印。")

if CHECK_ONLY:
    print("(--check:只报告,没有写盘)")
    sys.exit(1)

BOARD.write_text(text.replace(OLD, NEW), encoding="utf-8")
print("✅ 已写回板文件")
