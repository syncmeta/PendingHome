# 鼠标桥在 Linux 上怎么接

两只无线鼠标当灯的开关，接收器插在这台实体机上。

| 鼠标 | 设备标识 | 控哪盏 | 滚轮能调 |
|---|---|---|---|
| MI Wireless Mouse | `2717:003b` | 吸顶灯 `light.yeelink_cn_476282703_ceiling23_s_2_light` | 亮度 + 色温（中键切换）|
| MiMouse 2 | `2717:501f` | 餐厅灯 `light.yeelink_cn_56292508_mono1_s_2_light` | 只有亮度（这灯不支持色温）|

操作方式跟 Mac 上验通的完全一样：左键/右键都是开关切换，滚轮调当前模式的值，
中键在「调亮度 / 调色温」之间切换。

## 跟 Mac 上有什么不一样

**只换了最下面那一层。** 这套东西当初就是照「换台机器只换一个零件」设计的：

```
   事件源（平台相关）                 控灯逻辑（平台无关，一行不改）
   ┌────────────────────┐            ┌──────────────────┐
   │ macos/mouse-source │            │    bridge.py     │
   │      (Swift)       │  JSON 一行 │    logic.py      │  HTTP
   │        ↓ 换成       │ ──────────▶│    ha_client.py  │ ──────▶ Home Assistant
   │ linux/evdev-source │            └──────────────────┘
   └────────────────────┘
```

两个具体差别：

- **不弹权限框。** macOS 那个「输入监控」授权是苹果特有的。Linux 上靠文件权限：
  `/dev/input/event*` 是 `root:input 0660`，所以进程要么是 root、要么在 `input` 组里。
  这里用的是后者 —— `install.sh` 建了一个专用账号 `mousebridge` 放进 `input` 组，
  **不需要 root**。
- **设备标识格式一样**，`2717:003b` 这种「厂商编号:型号编号」两边通用，
  `config.json` 直接照搬，换 USB 口、重新配对都不会变。

## 装

```bash
# 接收器先插好
cd ~/ha-home/mouse-bridge
sudo ./linux/evdev-source.py --list      # 先确认系统认到了这两只
./install.sh
```

`install.sh` 干这些事，都可重复执行：

| 装到哪 | 什么 |
|---|---|
| 系统账号 `mousebridge` | 专用账号，加进 `input` 组，`nologin` 不能登录 |
| `/opt/mouse-bridge/` | 代码（root 所有，服务只读）|
| `/opt/mouse-bridge/config.json` | 从 `config.json` 复制，**自动把 `ha_url` 改成 `http://127.0.0.1:8123`** |
| `/etc/ha-home/mouse-bridge.env` | 令牌，`root:root 0600` |
| `/etc/systemd/system/mouse-bridge.service` | 开机自启单元 |

装完**默认不自动启动** —— 先干跑一遍验配置（脚本会把命令打出来），确认绑定关系
和连通性没问题再 `sudo systemctl start mouse-bridge`。

### 令牌怎么过来

**迁移过 `.storage` 之后，试验台上那个长期令牌在新机器上继续有效**（令牌就存在
`.storage/auth` 里，跟着一起搬过来了），不用重新签发。

两种传法，选一种：

```bash
# A) 在 Mac 上，部署时顺手带过去（令牌只走管道，不落临时文件、不打印）
./deploy.sh <用户名>@homeassistant.local --with-token

# B) 在新机器上手敲
sudo install -d -m 0700 /etc/ha-home
sudo tee /etc/ha-home/mouse-bridge.env >/dev/null   # 粘贴 HA_TOKEN=xxx 后按 Ctrl-D
sudo chmod 600 /etc/ha-home/mouse-bridge.env
```

## 开机自启是怎么做的

`mouse-bridge.service` 有几处是刻意的，改之前先看一眼理由：

- **`User=mousebridge` + `SupplementaryGroups=input`** —— 不跑 root。这个进程要读你
  所有的鼠标输入，权限给小一点是对的。
- **不能加 `PrivateDevices=true`** —— 那会把 `/dev/input` 挡在外面，桥就瞎了。
  这是整个单元里唯一必须留的口子，其余的加固项（`ProtectSystem=strict`、
  `ProtectHome`、`NoNewPrivileges` 等）都开着。
- **`Restart=always` + `RestartSec=5`** —— 这就是热插拔和开机时序的解决方案：
  接收器被拔了、开机时 USB 还没枚举完、HA 还没起来，进程退出后 5 秒重来一次，
  自己就绕回去了。
- **设备标识只写在 `config.json` 一处**，单元里不重复。`run.sh` 会从配置里读出来
  拼成 `--device` 参数 —— 换鼠标只改配置文件。

### 独占模式（可选，先别开）

`GRAB=1` 会让这两只鼠标**不再移动光标、点击也不传给别的程序**，变成纯遥控器。
这台机器是没有桌面的服务器，光标本来也没人看，所以开不开都行。

要开就在 `/etc/ha-home/mouse-bridge.env` 里加一行 `GRAB=1` 再重启服务。
**建议先不开**，等一切顺手了再说 —— 开了之后想用这两只鼠标干别的就没法了。

## 排查

```bash
sudo systemctl status mouse-bridge
sudo journalctl -u mouse-bridge -f          # 实时日志，按键会打出来做了什么

# 系统认到哪些鼠标
sudo /opt/mouse-bridge/linux/evdev-source.py --list

# 只验配置和 HA 连通性，不碰灯
sudo -u mousebridge HA_TOKEN=$(sudo sed -n 's/^HA_TOKEN=//p' /etc/ha-home/mouse-bridge.env) \
  python3 /opt/mouse-bridge/bridge.py --config /opt/mouse-bridge/config.json --check

# 只看事件源吐什么（动动鼠标，应该一行一个 JSON）
sudo /opt/mouse-bridge/linux/evdev-source.py --device 2717:003b
```

| 症状 | 多半是 |
|---|---|
| `--list` 里根本没有那两只 | 接收器没插好 / 插在不供电的口上；`lsusb` 看看在不在 |
| 服务反复重启 | 看 journal：多半是 HA 还没起来（连不上 8123）或者令牌没配 |
| 按键有日志但灯不动 | 灯离线，或实体 ID 变了（迁移做对了就不会变） |
| 一次点击灯闪两下 | 见下面「一只鼠标对应多个设备节点」 |

---

## 代码审查记录（`linux/evdev-source.py`）

这个文件写好之后**从没在真的 Linux 上跑过**。这次审了一遍，并且在试验台虚拟机里
造了一个假鼠标设备真跑了一遍。

### 怎么验的

虚拟机的云内核没有 `uinput` 模块，造不了标准虚拟鼠标。所以换了个办法：在一个私有
mount namespace 里，用一个 FIFO 冒充 `/dev/input/event9`、用一棵手工目录树冒充
`/sys/class/input/`，然后**灌入真正的 `input_event` 二进制结构**。
除了「设备不是内核造的」以外，走的都是真代码路径：真 Linux、真 Python 3.11、
真 sysfs 解析、真结构体解包。

### 验过没问题的

- **设备识别**：从 sysfs 读出 `2717:003b`，格式和 macOS 版一致 ✅
- **鼠标筛选**：能力位图解析正确 —— 在虚拟机**真实的** sysfs 上跑 `--list`，
  正确地把「电源按钮」这种非鼠标设备排除掉了 ✅
- **事件解析**：左键按下/抬起、右键、中键、滚轮上下，全部正确 ✅
- **该丢的都丢了**：长按重复（`value=2`）不重复发、鼠标移动（`REL_X`）忽略、
  同步包（`EV_SYN`）忽略 ✅
- **输出格式**和 macOS 那版逐字节一致，所以 `logic.py` 确实一行都不用改 ✅
- **控灯逻辑**的 18 项测试在 Linux 的 Python 3.11 上全绿 ✅

### 顺手修掉的一个真 bug

**设备断开后会 79% CPU 空转。** 原来的代码读到 EOF 时是 `continue`，但 EOF 之后
`select` 会永远报「可读」，于是变成死循环。实测占满一个核 —— 这台是双核奔腾，
一个核被占死是要命的。

已改成：读到 EOF 就打一行日志退出，交给 systemd 的 `Restart=always` 重新拉起并
重新枚举设备。改完两个回归都过了（正常事件流不变；EOF 之后进程干净退出，CPU 归零）。

改的是 `../ha-lab/mouse-bridge/linux/evdev-source.py`（唯一的一份源码），
`deploy.sh` 会把它推到这台机器上。

### 还没验、需要留意的三条风险

1. **一只鼠标可能对应多个设备节点。** 无线接收器在 Linux 上常常生成好几个
   `/dev/input/event*`（鼠标一个、多媒体键一个……）。脚本是**按设备标识匹配、
   匹配到几个就开几个**，如果同一个 `2717:003b` 对应两个都长得像鼠标的节点，
   一次点击就会发两个事件 → **灯闪两下**。
   👉 插上之后先跑 `--list`，**看同一个标识是不是出现了两行**。出现了告诉我，
   加一个按节点挑选的参数就行（十分钟的事）。

2. **高分辨率滚轮。** 脚本读的是传统的 `REL_WHEEL`。少数新鼠标只发
   `REL_WHEEL_HI_RES` 不发 `REL_WHEEL`，那样滚轮就没反应。
   这两只是老式滚轮，Mac 上滚轮工作正常，**大概率没问题**，但没在 Linux 上验过。
   👉 症状是「按键管用、滚轮不管用」。

3. **只配到一只鼠标时不会报错。** 如果只有一只被认出来，脚本会安静地只桥那一只。
   👉 启动时 journal 里会有「在读 /dev/input/eventN (标识) 名称」的行，
   **数一下是不是两行**。
