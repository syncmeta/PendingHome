#!/usr/bin/env python3
"""出货文件是不是比板子旧?旧就报错。

**为什么有这个检查。** 2026-08-13 那天板子改了三轮(整板转正 → U2/J2 修正 →
指示灯改造),每一轮都很小心地验了 DRC/网表,**但出货包一次都没跟着重导** ——
差一点就把停在三个提交之前的 `cct-main-gerber.zip` 和写着旧料号的 `bom-jlc.csv`
传去下单。靠人记是记不住的,所以写成检查。

判据:下面每个出货文件的修改时间,都必须**不早于**板文件与相关生成脚本。
只看时间戳,便宜、够用 —— 它抓的是"忘了重导"这一类错,不是内容比对。

用法:
    python3 hardware/check-outputs-fresh.py          落后就打印清单并以 1 退出
    python3 hardware/check-outputs-fresh.py --quiet  只给退出码
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
QUIET = "--quiet" in sys.argv

# 出货文件 → 它依赖的东西(任何一个比它新,它就过期了)
BOARD = HERE / "cct-main.kicad_pcb"
SCH = HERE / "cct-main.kicad_sch"
OUTPUTS = {
    "cct-main-gerber.zip": [BOARD],
    "gerber/cct-main-F_Cu.gtl": [BOARD],
    "gerber/cct-main-F_Silkscreen.gto": [BOARD],
    "gerber/cct-main-PTH.drl": [BOARD],
    "cpl-jlc.csv": [BOARD, HERE / "gen_cpl.py"],
    "pos-raw.csv": [BOARD, HERE / "gen_cpl.py"],
    "bom-jlc.csv": [BOARD, HERE / "gen_sch.py", HERE / "gen_bom.py", HERE / "netlist-spec.md"],
    "bom.csv": [BOARD, HERE / "gen_sch.py", HERE / "gen_bom.py", HERE / "netlist-spec.md"],
    "render-top.png": [BOARD],
    "render-bottom.png": [BOARD],
}

REDO = """
重导命令(在 hardware/ 下跑):
    CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
    KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
    rm -f gerber/*
    $CLI pcb export gerbers -o gerber --layers F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,Edge.Cuts --subtract-soldermask cct-main.kicad_pcb
    $CLI pcb export drill   -o gerber --excellon-separate-th cct-main.kicad_pcb
    rm -f cct-main-gerber.zip && (cd gerber && zip -q -X ../cct-main-gerber.zip *)
    python3 gen_cpl.py
    $KP gen_bom.py
    $CLI pcb render -o render-top.png    --side top    --quality high -w 1600 -h 900 cct-main.kicad_pcb
    $CLI pcb render -o render-bottom.png --side bottom --quality high -w 1600 -h 900 cct-main.kicad_pcb
"""

stale = []
for out, deps in OUTPUTS.items():
    p = HERE / out
    if not p.exists():
        stale.append((out, "不存在", ""))
        continue
    t = p.stat().st_mtime
    for d in deps:
        if d.exists() and d.stat().st_mtime > t + 1:      # 1 秒容差
            stale.append((out, f"比 {d.name} 旧",
                          f"{int(d.stat().st_mtime - t)} 秒"))
            break

if not stale:
    if not QUIET:
        print(f"✅ {len(OUTPUTS)} 个出货文件都不比板文件旧")
    sys.exit(0)

if not QUIET:
    print(f"❌ {len(stale)} 个出货文件已过期 —— **别拿去下单/跑 DFM**:")
    for out, why, gap in stale:
        print(f"    {out:<34} {why} {gap}")
    print(REDO)
sys.exit(1)
