#!/usr/bin/env python3
"""贴片坐标文件:pos-raw.csv(KiCad 原始)+ cpl-jlc.csv(嘉立创格式)。

原来这两个文件是手工导的,没有脚本。整板转 180° 之后 195 个元件的坐标和
角度全变了,`cpl-jlc.csv` 是唯一一个不重导就会**贴错**的文件,所以把导出
过程固化下来,以后跟着板子一起重跑。

嘉立创格式与 KiCad 原始导出的差别只有写法:
  Designator = Ref, Mid X/Mid Y = PosX/PosY 加 "mm" 后缀(4 位小数),
  Layer = top→Top / bottom→Bottom, Rotation = Rot(1 位小数),CRLF 行尾。
坐标系与钻孔文件一致(板文件原点,Y 取负)。

用系统 python3 跑即可(不需要 pcbnew,内部调 kicad-cli):
    python3 hardware/gen_cpl.py
"""
import csv
import io
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
BOARD = HERE / "cct-main.kicad_pcb"
RAW = HERE / "pos-raw.csv"
JLC = HERE / "cpl-jlc.csv"

subprocess.run([CLI, "pcb", "export", "pos", "-o", str(RAW),
                "--format", "csv", "--units", "mm", "--side", "both", str(BOARD)],
               check=True, stdout=subprocess.DEVNULL)

rows = list(csv.DictReader(io.StringIO(RAW.read_text())))
out = io.StringIO(newline="")
w = csv.writer(out, lineterminator="\r\n")
w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
for r in rows:
    w.writerow([r["Ref"],
                "%.4fmm" % float(r["PosX"]),
                "%.4fmm" % float(r["PosY"]),
                r["Side"].capitalize(),
                "%.1f" % float(r["Rot"])])
JLC.write_text(out.getvalue())
print(f"✅ pos-raw.csv / cpl-jlc.csv 已重导,{len(rows)} 个元件")
