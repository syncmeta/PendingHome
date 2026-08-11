# mouse-bridge —— 用无线鼠标当灯的开关

两个无线鼠标，每个控一盏灯：

| 操作 | 效果 |
|---|---|
| 左键 | 开/关（切换） |
| 右键 | 开/关（切换）—— 和左键**完全相同**，这是刻意的 |
| 滚轮滚动 | 调节当前模式的值（亮度 或 色温） |
| 中键（滚轮按下） | 在「调亮度」和「调色温」之间切换 |
| 中键（灯不支持色温时） | 不做任何事 —— 没有第二个模式可切，滚轮始终只调亮度 |

## 为什么分成两层

```
   鼠标事件源（平台相关）              控灯逻辑（平台无关）
   ┌────────────────────┐             ┌──────────────────┐
   │ macos/mouse-source │  JSON 一行   │    bridge.py     │   HTTP
   │      (Swift)       │ ──一个事件─▶ │  logic.py        │ ──────▶  Home Assistant
   │ linux/evdev-source │             │  ha_client.py    │
   └────────────────────┘             └──────────────────┘
```

苹果的虚拟化框架**不支持 USB 透传**，鼠标接收器插在 Mac 上没法透进虚拟机
（lima 也不支持，社区方案要 QEMU + root，不可用）。所以试验阶段只能在 Mac 上读鼠标。

但读鼠标这件事是平台相关的，控灯逻辑不是。中间用**一行一个 JSON 事件**的管道隔开后：

- Mac 上用 `macos/mouse-source`（Swift + IOHIDManager）
- T630 上换成 `linux/evdev-source.py`（读 `/dev/input/event*`）
- **`logic.py` 一行都不用改**

顺带的好处：不接鼠标、不接灯也能把逻辑验一遍（见下面「不接硬件也能测」）。

事件格式，两个适配器输出完全一致：

```json
{"device":"046d:c534","type":"button","button":"left","action":"down"}
{"device":"046d:c534","type":"wheel","delta":-1}
```

`device` 是「厂商编号:型号编号」。两个鼠标型号不同，所以这个标识唯一，
**换 USB 口、重新配对都不会变** —— 不需要"插左边那个口"这类约定。

## 用起来

### 1. 找出两个鼠标的标识

```bash
./macos/build.sh          # 编译，用系统自带 Swift，不装任何东西
./macos/mouse-source --list
```

会列出所有鼠标。**这一步不会弹权限框**（只枚举设备，不读事件）。
挪动其中一个鼠标、对照名称，认出哪个是哪个。

### 2. 写配置

```bash
cp config.example.json config.json
# 填进两个鼠标标识 + 两盏灯的实体 ID（在 HA 的 开发者工具 → 状态 里查）
```

令牌不写在配置里，走环境变量，配置文件因此可以安全分享。

### 3. 先干跑一遍

```bash
set -a; source ../.env; set +a          # 载入 HA_TOKEN
python3 bridge.py --config config.json --check
```

会打印每个鼠标绑到哪盏灯、那盏灯支不支持色温（也就是中键有没有用），
但不做任何动作。绑错了在这一步就能看出来。

### 4. 真的跑起来

```bash
set -a; source ../.env; set +a
./macos/mouse-source --device <标识A> --device <标识B> --seize \
  | python3 bridge.py --config config.json
```

> ⚠️ **首次运行会弹一个「输入监控」的系统权限框** —— 因为要读鼠标的原始事件。
> 给权限的地方：系统设置 → 隐私与安全性 → 输入监控，勾上你的终端。
> **改完权限要把终端完全退出再重开**才生效。

`--seize` 是独占模式：这两个鼠标不再移动光标、点击也不传给别的程序，变成纯遥控器。
**先别加**，确认事件能正常读到、灯有反应之后再加 —— 万一独占后想停，
鼠标已经不听使唤了，得靠键盘 Ctrl-C。

## 不接硬件也能测

逻辑层是纯的，18 个用例覆盖了上面表格里的每一条：

```bash
python3 -m unittest test_logic -v
```

也可以手喂事件，走完整链路去点真的灯：

```bash
set -a; source ../.env; set +a
printf '%s\n' \
  '{"device":"046d:c534","type":"button","button":"left","action":"down"}' \
  | python3 bridge.py --config config.json
```

## 几个实现上的取舍

**只在按下时动作。** 按下和抬起都响应的话，一次点击会触发两次开关。

**连续滚动会合并。** 滚轮转一下能出十几个事件，逐个调 HA 又慢又抖。
按 (灯, 模式) 累加 80 毫秒再发一次（`coalesce_ms` 可调）。
一上一下正好抵消时干脆不发请求。

**切模式时先把攒着的调节发出去。** 否则刚滚的亮度会被当成色温发出去 —— 这是个真会踩的坑，
有对应的测试用例盯着。

**色温只能读-改-写。** HA 有 `brightness_step_pct` 这种相对调节，色温没有，
只能先读当前值再写绝对值，并夹在灯自己上报的区间内。灯关着没上报色温时，
从区间中点起步，避免跳到极端值。

**单次调用失败不会让桥挂掉。** 灯离线、HA 重启都是常事，记一行日志继续跑。

## 搬到实体机（Linux）

换个事件源就行，其余不动：

```bash
sudo ./linux/evdev-source.py --list
sudo ./linux/evdev-source.py --device <标识A> --device <标识B> --grab \
  | python3 bridge.py --config config.json
```

`--grab` 等价于 macOS 那边的 `--seize`。设备标识格式两边一致，**config.json 可以直接照搬**。

读 `/dev/input/event*` 要 root，或者把用户加进 `input` 组：
`sudo usermod -aG input $USER`（重新登录生效）。

`evdev-source.py` 不依赖任何第三方库，直接读原始事件结构，装完系统就能跑。

> **装成开机自启的系统服务**（专用账号 + systemd 单元 + 令牌怎么放）见
> `../../ha-home/mouse-bridge/README.md`。那份文档里还有一次针对
> `linux/evdev-source.py` 的完整审查记录 —— 2026-08-11 在 Linux 上用假设备实跑验过，
> 并修掉了一个「设备断开后 79% CPU 空转」的真 bug。
