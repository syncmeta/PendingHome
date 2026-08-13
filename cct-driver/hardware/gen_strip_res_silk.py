#!/usr/bin/env python3
"""去掉 12 个指示灯串联电阻的封装丝印外框(文本层操作,幂等)。

**为什么要去掉。** 指示灯改到保险丝与端子之间那条带之后(见 `gen_led_to_output.py`),
每路是「0805 灯 + 0603 电阻」并排,中心距 2.1mm。courtyard 是够的(留 0.21mm),
但两者**封装自带的丝印外框**会压在一起 —— DRC 里几十条 `silk_overlap` 就是它。
把中心距拉到 2.6mm 能分开外框,但电阻会被推到别的铜上(clearance 从 4 涨到 10)。
电阻没有极性、外框纯装饰,去掉它是这条带里唯一两头都不得罪的解法。

**灯的外框与极性标记一个都不动** —— 贴片厂核极性、收板核方向都要靠它。

**为什么走文本层而不用 pcbnew。** `FOOTPRINT.GraphicalItems()` 这个接口
**在脚本动过任何封装的位置/朝向之后就不能再迭代**,会抛
`TypeError: 'swig_runtime_data5.SwigPyObject' object is not iterable`;
把这一步挪到脚本最前面(任何摆位之前)也一样抛。踩过一次,记在这儿当路标。
板文件是 s-expression 文本,直接改它稳定可靠,也不受这个 API 的脾气影响。

幂等:改完再跑一次会报「0 处需要处理」。用法:
    python3 hardware/gen_strip_res_silk.py
    python3 hardware/gen_strip_res_silk.py --check    只报告,不写盘
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
BOARD = HERE / "cct-main.kicad_pcb"
CHECK_ONLY = "--check" in sys.argv

# 12 个指示灯的串联限流电阻(每路 CW/WW 各一个),与 gen_led_to_output.py 的 CH 表一致
TARGETS = ["R20", "R21", "R26", "R27", "R32", "R33",
           "R38", "R39", "R44", "R45", "R50", "R51"]
SILK_ITEMS = ("fp_line", "fp_arc", "fp_circle", "fp_poly", "fp_rect", "fp_curve")


def block_end(text, start):
    """从 text[start] 的 '(' 出发,返回配对的 ')' 之后的下标(跳过字符串里的括号)。"""
    depth, i, in_str = 0, start, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("括号不配对")


def strip(text):
    """返回 (新文本, {位号: 删掉的图元数})。"""
    removed = {}
    out, pos = [], 0
    for m in re.finditer(r'\(footprint ', text):
        if m.start() < pos:
            continue
        end = block_end(text, m.start())
        blk = text[m.start():end]
        ref_m = re.search(r'\(property "Reference" "([^"]+)"', blk)
        ref = ref_m.group(1) if ref_m else None
        if ref not in TARGETS:
            continue
        # 在这个封装块里找 F.SilkS 上的图元,整块删掉
        newblk, p, n = [], 0, 0
        while True:
            # 注意:板文件里图元是 "(fp_line\n" 这种换行写法,不能按 "(fp_line " 找
            m2 = re.compile(r'\((?:' + "|".join(SILK_ITEMS) + r')[\s(]').search(blk, p)
            if m2 is None:
                break
            k = m2.start()
            e = block_end(blk, k)
            item = blk[k:e]
            if '(layer "F.SilkS")' in item:
                newblk.append(blk[p:k].rstrip(" \t"))   # 连同前面的缩进一起去掉
                p = e
                while p < len(blk) and blk[p] in " \t":
                    p += 1
                if p < len(blk) and blk[p] == "\n":
                    p += 1                                # 整行删掉,不留空行
                n += 1
            else:
                newblk.append(blk[p:e])
                p = e
        newblk.append(blk[p:])
        if n:
            removed[ref] = n
            out.append(text[pos:m.start()])
            out.append("".join(newblk))
            pos = end
    out.append(text[pos:])
    return "".join(out), removed


text = BOARD.read_text(encoding="utf-8")
new, removed = strip(text)

if not removed:
    print("✅ 那 12 个电阻的封装里已经没有 F.SilkS 图元,0 处需要处理")
    raise SystemExit(0)

print(f"要去掉封装丝印外框的位号({len(removed)} 个):")
for ref in TARGETS:
    print(f"    {ref:<5} {removed.get(ref, 0)} 个图元" + ("" if ref in removed else "   ← 本来就没有"))
extra = sorted(set(removed) - set(TARGETS))
assert not extra, f"动到了不该动的位号:{extra}"
print(f"  合计删除 {sum(removed.values())} 个图元;**只动这 12 个电阻,灯的外框与极性标记一个没碰**")

if CHECK_ONLY:
    print("(--check:只报告,没有写盘)")
    raise SystemExit(1)

BOARD.write_text(new, encoding="utf-8")
print("✅ 已写回板文件")
