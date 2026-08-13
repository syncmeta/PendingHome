#!/usr/bin/env python3
"""把板文件里各元件的 Value 字段同步成 `gen_sch.py` 里的真实 C 编号。

**为什么需要它。** 本工程的料号只有一个源头:`gen_sch.py` 的 `part(ref, cid, ...)` 表
—— `gen_bom.py` 就是直接解析它来出 BOM 的。但板文件里每个封装还各自带一份 Value
字段,那是当初布局时写进去的,**没有任何一步会去更新它**。于是 2026-08-07 把 6 个
精密电阻 + 1 个 C0G 电容从占位料号换成真实料号时,只改了 `gen_sch.py`,板文件里的
Value 就此停在旧值:

    R62 C25804→C25811   R63 C25803→C402870  R64 C25804→C22892   R65 C23162→C25972
    R66 C25803→C23208   R67 C25804→C12447   C40 C14663→C107035

BOM 是对的(它读 gen_sch.py),但**板文件和原理图对不上**:重新生成原理图时,
KiCad 的 schematic-parity 会逐个报「Value (R62) doesn't match symbol value」。
这就是"重生成原理图会让 parity 从 205 涨到 209"的真正原因 —— 不是生成器写错了,
是板文件那份 Value 落后了六天。

**出货影响:零。** Value 字段画在 `F.Fab` 层,不在任何出货 Gerber 里;
`cpl-jlc.csv` 不含 Value 列;`bom-jlc.csv` 读的是 gen_sch.py。唯一会变的是
`pos-raw.csv` 的 `Val` 列(KiCad 原始导出,仅供人看)。

幂等:同步完再跑一次会报「0 处需要同步」。建议改完 `gen_sch.py` 的料号后顺手跑一遍。

用法:
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_sync_values.py
    ... --check    只报告差异,不写盘(可用于提交前自检)
"""
import gc
import re
import sys
from pathlib import Path

gc.disable()
import pcbnew

HERE = Path(__file__).parent
BOARD = str(HERE / "cct-main.kicad_pcb")
CHECK_ONLY = "--check" in sys.argv

# ---- 直接执行 gen_sch.py 的元件表,拿到准确的 (位号 → C 编号) ----
# 早先这里是用正则去抠 part("R62","C25811",...) 的,但 6 个通道是在循环里写的
# `part(Rlc, "C12447", ...)` —— **位号是变量,正则抠不到**,于是那 12 个指示灯电阻
# 的料号一直同步不到板上。改成把 gen_sch.py 的头部(到 def gen 之前)执行一遍,
# 直接读它的 P 表,准确且不会再因为写法变化而漏。
_src = (HERE / "gen_sch.py").read_text().split("def gen()")[0]
_ns = {"__file__": str(HERE / "gen_sch.py")}
exec(compile(_src, "gen_sch.py", "exec"), _ns)
parts = {ref: cid for ref, cid, _pins in _ns["P"]}
print(f"gen_sch.py 里解析到 {len(parts)} 个元件的料号")

board = pcbnew.LoadBoard(BOARD)
drift = []
for fp in board.GetFootprints():
    ref = fp.GetReference()
    want = parts.get(ref)
    if want and fp.GetValue() != want:
        drift.append((ref, fp.GetValue(), want))

if not drift:
    print("✅ 板文件 Value 与 gen_sch.py 完全一致,0 处需要同步")
    raise SystemExit(0)

print(f"发现 {len(drift)} 处不一致:")
for ref, old, want in sorted(drift):
    print(f"    {ref:<5} 板上 {old:<10} → gen_sch.py {want}")

if CHECK_ONLY:
    print("(--check:只报告,没有写盘)")
    raise SystemExit(1)

for fp in board.GetFootprints():
    ref = fp.GetReference()
    if parts.get(ref) and fp.GetValue() != parts[ref]:
        fp.SetValue(parts[ref])
pcbnew.SaveBoard(BOARD, board)
print(f"✅ 已同步 {len(drift)} 处 Value(F.Fab 层文字,不进任何出货 Gerber)")
