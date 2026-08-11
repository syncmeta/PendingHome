# cct-driver

6 通道 CCT（色温可调）LED 灯带驱动板 —— 24V 输入、单板 12A 连续设计，ESP32 + ESPHome，
接入 Home Assistant。用户零焊接：贴片与插件件全部由嘉立创代焊，收到即成品。

| 目录 | 内容 |
|---|---|
| `hardware/` | KiCad 工程、生产文件（Gerber / BOM / 坐标）、亚克力外壳切割图、各版改板脚本 |
| `firmware/` | ESPHome 配置（`cct-driver.yaml` 正式板、`cct-driver-devboard.yaml` 开发板） |
| `docs/` | 设计规格书与实施计划 |

## 上手

```sh
git clone https://github.com/syncmeta/cct-driver.git
cd cct-driver
git config core.hooksPath .githooks     # ← 必做，见下一节
```

**`git config core.hooksPath .githooks` 这一句不能漏。** Git 的钩子不随仓库克隆自动生效，
不执行这句，下面那个防护就是摆设。

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
经 `.githooks/pre-commit` 在每次提交前自动跑。

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

## 生产文件

下单用的三个文件都在 `hardware/`：

| 文件 | 用途 |
|---|---|
| `cct-main-gerber.zip` | Gerber |
| `bom-jlc.csv` | BOM（嘉立创格式） |
| `cpl-jlc.csv` | 元件坐标（嘉立创格式） |

下单前逐项核对 `hardware/order-checklist.md` —— 里面记着表面工艺、阻焊颜色、
容易选错的料号等一批会咬人的地方。
