# cct-driver

6 通道 CCT（色温可调）LED 灯带驱动板 —— 24V 输入、单板 12A 连续设计，ESP32 + ESPHome，
接入 Home Assistant。用户零焊接：贴片与插件件全部由嘉立创代焊，收到即成品。

| 目录 | 内容 |
|---|---|
| `hardware/` | KiCad 工程、生产文件（Gerber / BOM / 坐标）、亚克力外壳切割图、各版改板脚本 |
| `firmware/` | ESPHome 配置（`cct-driver.yaml` 正式板、`cct-driver-devboard.yaml` 开发板） |
| `docs/` | 设计规格书与实施计划 |

> 这块板子原来是一个独立仓库，2026-08-23 连同全部提交历史并进了 PendingHome，
> 现在是它的一个子目录。原仓库 <https://github.com/syncmeta/cct-driver> 保留为归档，
> 不再更新；合库时提交哈希做过重写，本文与脚本里提到的旧哈希指的是那边的。

## 上手

```sh
git clone https://github.com/syncmeta/PendingHome.git
cd PendingHome
git config core.hooksPath .githooks     # ← 必做，见下一节
cd cct-driver
```

**`git config core.hooksPath .githooks` 这一句不能漏**（在仓库根执行，不是在本目录）。
Git 的钩子不随仓库克隆自动生效，不执行这句，下面那个防护就是摆设。

**下文所有命令都在 `cct-driver/` 目录下执行**，除非另有说明。

改板脚本要用 KiCad 自带的 Python（系统 `python3` 里没有 `pcbnew`）：

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/gen_xxx.py
```

## ⚠️ KiCad 工程文件会被 GUI 悄悄重置

**这个坑踩过一次，而且是静默的 —— 不会报错，不会提示，只有 diff 里看得见。**

用 KiCad 图形界面打开本工程后，`hardware/cct-main.kicad_pro` 里的这些东西可能被重置成出厂默认：

- 5 个网络类（`Default` / `TRUNK` / `PWR2` / `PWR1` / `GND`）被砍成只剩 `Default`
- 14 条 `netclass_patterns`（把 `V24_*`、`CH*_VOUT`、`GND` 等网络分配到各类的规则）被清空
- `Default` 的 `track_width` 从 0.25 掉到 0.2、`min_text_height` 从 0.5 变成 0.8

**危害**：板子已经布完线，铜箔的实际线宽不受影响，**这一版生产文件是安全的**。但之后任何一次改板，
DRC 都会按错误的规则跑 —— 主电流脊椎按 3.5mm 设计的走线，会被当成 0.2mm 的普通线校验，
真正的问题反而查不出来。

**排查结论**（2026-08-11）：不是脚本干的，也不是 KiCad 10 的格式迁移有问题。
对照实验证明，用无头 `pcbnew` 走一遍 `LoadBoard` + `SaveBoard`，
`net_settings` 从 v4 迁到 v5 是**完全无损**的，5 个类和 14 条规则一条不少。
真凶是图形界面那一侧（旁证：只有 GUI 会写的 `cct-main.kicad_prl` 同时被改了）。

**防护**：`hardware/check-netclasses.py` 断言这些值仍是基准值，
经仓库根的 `.githooks/pre-commit` 在每次提交前自动跑。

**检查失败时该怎么办**：

```sh
# 情况一（绝大多数）：你并没有故意改这些设置，是 GUI 干的 —— 直接退回
git checkout -- hardware/cct-main.kicad_pro

# 情况二：你确实有意调整了网络类/设计规则 —— 同步更新脚本里的基准值，别绕过检查
$EDITOR hardware/check-netclasses.py
```

**不要用 `git commit --no-verify` 糊弄过去。** 这个检查存在的唯一理由，
就是这类改动看起来人畜无害、而代价要到下一次改板才显形。

**用 GUI 前后的习惯**：开之前确认 `cct-main.kicad_pro` 已提交（工作区干净），
关掉之后 `git diff hardware/cct-main.kicad_pro` 看一眼再决定要不要留。

## ⚠️ 料号只有一个源头：`gen_sch.py`

`hardware/gen_sch.py` 里的 `part(位号, C编号, {引脚: 网络})` 表是**全工程唯一的料号出处** ——
`gen_bom.py` 直接解析它来出 BOM。板文件里每个封装虽然也带一份 Value 字段，但那只是
`F.Fab` 层上给人看的文字，**不进任何出货 Gerber，也没有任何一步会自动更新它**。

改完料号请顺手跑这两条：

```bash
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP hardware/gen_sync_values.py     # 把板文件 Value 同步成 gen_sch.py 里的真实料号
$KP hardware/gen_sch.py             # 重新生成原理图（顺便验证生成器还跑得动）
```

**为什么专门写这一条**：2026-08-07 把 6 个精密电阻 + 1 个 C0G 电容换成真实料号时，
只改了 `gen_sch.py`。结果 ——

- `gen_sch.py` 从那天起**一跑就报「库缺失 7 个」**（那 7 个料号的符号没下进符号库），
  也就是说**原理图整整六天没法重新生成，而且没人发现** —— 因为没有任何一步会去碰它；
- 板文件里那 7 个 Value 停在旧料号，重新生成原理图时 KiCad 的 schematic-parity
  会逐个报 `Value (R62) doesn't match symbol value`。

两件都已修好（符号别名表 + `gen_sync_values.py`）。**`gen_sch.py` 能不能跑通，
本身就是一个健康检查** —— 改完原理图相关的东西，跑一次它，比什么都省事。

> 📌 `--check` 模式只报告不写盘：`$KP hardware/gen_sync_values.py --check`，
> 适合提交前自检。

## 生产文件

> ⚠️ **传出去之前先跑这一条:**
> ```bash
> python3 hardware/check-outputs-fresh.py
> ```
> 它检查 Gerber / CPL / BOM / 渲染图有没有比板文件旧。**2026-08-13 那天板子改了三轮,
> 出货包一次都没跟上** —— 每一轮都仔细验了 DRC 和网表,却差点把停在三个提交之前的
> 包和写着旧料号的 BOM 传去下单。靠人记是记不住的,所以写成检查。

> 📌 **封装里那个 `LCSC Part` 属性不是料号,别读它。** 它是 `easyeda2kicad` 下载封装时
> 记下的**来源**——比如所有 0603 电阻共用一个从 `C21190` 下载来的 `R0603` 封装,于是
> R18(实为 `C25804` 10k)的 `LCSC Part` 就写着 `C21190`。195 个封装里有 80 个对不上,
> **这是正常的**。料号只有一个源头:`gen_sch.py` 的 part 表(见上一节)。
> (v1.1 可以考虑把这个属性整批删掉,免得再有人误读;它不进任何出货文件,不急。)


下单用的三个文件都在 `hardware/`：

| 文件 | 用途 |
|---|---|
| `cct-main-gerber.zip` | Gerber |
| `bom-jlc.csv` | BOM（嘉立创格式） |
| `cpl-jlc.csv` | 元件坐标（嘉立创格式） |

下单前逐项核对 `hardware/order-checklist.md` —— 里面记着表面工艺、阻焊颜色、
容易选错的料号等一批会咬人的地方。

## 收到板子之后

照 **`docs/bring-up-checklist.md`** 从头打勾执行 —— 从开测前要买什么，到上电前量阻抗、
仅 USB 刷固件、24V 空载、12A 满载热测、人为短路验保险丝，最后到「什么条件下才能放行
剩下 3 片」。每一项都写了用什么表、点哪个测试点、读到多少算过、不过了怎么办
（全部不需要动烙铁）。**器材要提前几天买，第 0 章就是采购清单。**
