# Zigbee 接入 —— 用一个 Zigbee 开关控餐厅灯

第一个目标就一件事：**按下那个 Zigbee 开关，餐厅灯亮/灭**。跑通了再谈别的。

## 现场情况（2026-08-12 实地核过）

| | |
|---|---|
| 在跑的 HA | `ha-home` 这套 —— `192.168.1.29`（`homeassistant.local`），HA **2026.8.1**，Docker + `network_mode: host` |
| 没在跑的 | Mac 试验台 `ha-lab`（Lima 虚拟机 Stopped）、另一个房子的 `ha-t630` |
| 配置目录 | 宿主机 `/opt/ha/config`（容器里是 `/config`） |
| 协调器 | **`ZBGW7688`** — `192.168.1.32:6636`，`radio_type=ezsp`，序列号 `120000abd1c8` |
| 餐厅灯 | `light.yeelink_cn_56292508_mono1_s_2_light`（米家集成 `xiaomi_home`，Yeelight mono1）|

协调器是**自己在局域网里找到的**，不用猜：它按 mDNS 的 `_zigbee-coordinator._tcp`
服务类型自报家门，在 HA 那台机器上跑

```bash
avahi-browse -at --resolve | grep -A4 zigbee-coordinator
```

就能看到上表那一行。端口连通性也验过（`192.168.1.32:6636` TCP 可连）。

## 为什么用 ZHA，不用 Zigbee2MQTT

**ZHA。** 两条理由：

1. **不用多养一个进程。** Z2M 必须再起一个 MQTT broker（外加 HA 的 mqtt 集成），
   为了跑通第一个开关而多铺两层，不划算。ZHA 是 HA 内置的，什么都不用装。
2. **这只协调器已经在按 ZHA 的规矩打招呼了。** 上面那条 `_zigbee-coordinator._tcp`
   广播正是 ZHA 的 zeroconf 发现所消费的格式，`radio_type=ezsp` 也直接对上
   ZHA 的 EZSP（Silicon Labs EmberZNet）驱动。接进去几乎是零配置。

> 将来要是设备多了、想要 Z2M 那套更细的设备数据库和 OTA，再迁不迟 —— 但那是
> 另一件事，不该挡住第一个开关。

**网络型协调器不需要 `devices:` 映射。** 它不是插在主机上的 USB dongle，
走的是 TCP（`socket://192.168.1.32:6636`），所以 `../docker-compose.yml` **一行都不用改**。

## 配置落在哪里

- **ZHA 集成本身**：HA 的 `.storage/core.config_entries`（由配置流程写入，不是手写文件）。
  这份是 HA 内部状态，跟着 `backup.sh` 的备份走，本仓库不放副本。
- **开关 → 灯的联动**：`/opt/ha/config/automations.yaml`
  （`configuration.yaml` 里是 `automation: !include automations.yaml`）。
  本目录下会放一份可读的副本，见下。

## 为什么必须走「自动化」而不是 Zigbee 直接绑定

Zigbee 有个 binding 机制，能让开关**不经过 HA** 直接指挥灯 —— 但那要求灯本身
也是 Zigbee 设备。餐厅灯是**米家的 Wi-Fi 灯**，不在 Zigbee 网里，绑不了。

所以链路是：

```
物理开关按下 → 协调器 → ZHA → HA 收到 zha_event → 自动化 → 米家集成 → 餐厅灯
```

多绕一层 HA，代价是 HA 挂了开关就不灵。这是设备决定的，不是选择。

## 家规

- **只做氛围和提示，不做自动开关灯。** 这条仍然作数 —— 这里是「人按物理开关，灯响应」，
  是人的主动操作，不是 HA 自作主张。
- **手动永远优先。** 这个自动化只在收到按键事件时动一下，不做任何状态巡检、
  不会把你在 App 或鼠标上的手动操作顶回去。

## 配对进来的第一个设备不是开关

⚠️ **2026-08-13 记录，别踩同一个坑。**

ZHA 接好之后开了配对窗口，进来一个设备 —— 但它不是要找的那个开关：

| | |
|---|---|
| 型号 | `LH79221`，厂商字段是空的 |
| IEEE | `00:15:8d:00:05:4e:2f:5a`（`00:15:8d` 是 Lumi/绿米的 OUI）|
| 端点指纹 | profile `0x0104`，device_type **`0x0402`**，输入簇含 **`0x0500`** |
| ZHA 给的端点名 | **`IAS_ZONE`** |
| 供电 | 电池 |
| 信号 | LQI 156 / RSSI −61（很好，不是信号问题）|

`0x0402` + `0x0500` 就是 **IAS Zone 安防传感器**那一族 —— 门窗磁、人体感应、
水浸、烟感都长这样。**它身上没有任何开关该有的簇**（没有 OnOff `0x0006`，
也没有 Multistate Input），所以按它不会发出"我被按了"的信号。

实测也印证了：入网那一下 `binary_sensor.lh79221` 从 `off` 翻到 `on`，
**之后再没上报过任何状态**。设备本身活着（`last_seen` 一直在更新），
就是不报按键。人按了说"没反应"，是因为 HA 这头根本没收到东西。

> 顺带排除掉两个嫌疑：**灯是好的**（`light.yeelink_...mono1...` 实测在线可控），
> **自动化也是好的**（装上了、能加载）。断点在最上游的设备本身。

**读设备指纹的办法**（不用开网页，命令行就能查）：

```bash
# HA_TOKEN 走环境变量，别写进文件
python3 ws_cmd.py '{"type":"zha/device","ieee":"00:15:8d:00:05:4e:2f:5a"}'
```

看返回里的 `signature.endpoints.*.device_type`、`input_clusters` 和
`endpoint_names` —— 设备自称是什么，比包装盒上印的字可靠。

## 协调器的地址会漂，而 ZHA 不会自己跟上

⚠️ **2026-08-13 记录。** 上面那张表里的 `192.168.1.32` **已经不作数了**。

协调器的 IP 是路由器 DHCP 发的，会变。2026-08-13 01:04（HA 里
`binary_sensor.lh79221` 转 `unavailable` 的那一刻）它从 `.32` 漂到了 `.28`，
于是 ZHA 的配置项一直连不上、卡在 `setup_retry`：

```
zha | state=setup_retry | reason=[Errno 113] Connect call failed ('192.168.1.32', 6636)
```

**整个 Zigbee 在这期间是死的** —— 人按开关"没反应"，有一半是这个原因，
不全是设备身份的问题。查的时候先看这一条，别一上来就怀疑设备。

确认还是同一只盒子，不是换了硬件：

| 判据 | 值 |
|---|---|
| mDNS 广播 | `ZBGW7688._zigbee-coordinator._tcp`，`serial_number=120000abd1c8`，`radio_type=ezsp` |
| MAC | `12:00:00:ab:d1:c8` —— 跟序列号逐字节对上 |

**ZHA 不会自愈,别等它。** 翻了一眼 HA 2026.8.1 里 ZHA 的配置流程
(`homeassistant/components/zha/config_flow.py`),zeroconf 发现只有在配置项是
`SOURCE_IGNORE`(被忽略的发现)时才会更新 device path;正常配置项一律
`single_instance_allowed` 直接 abort。也没有 reconfigure 步骤。也就是说
**IP 一漂,只能人工改配置项,或者根本别让它漂**。

所以正确的解法是后者:**在路由器上给协调器做 DHCP 静态地址分配**
(`12:00:00:AB:D1:C8` → `192.168.1.32`)。这样 HA 侧零改动、以后也不会再断。

改 HA 侧那条路(把 `.storage/core.config_entries` 里的 path 改成新 IP,
需要停 HA 再改)是治标 —— 下次还会漂。

**排查这一段用得上的命令**：

```bash
# 协调器现在在哪个 IP（在同一局域网的任意机器上跑）
dns-sd -Z _zigbee-coordinator._tcp local     # macOS
avahi-browse -at --resolve | grep -A4 zigbee-coordinator   # Linux

# ZHA 配置项是不是活着（HA_TOKEN 走环境变量）
python3 ws_cmd.py '{"type":"config_entries/get"}'   # 看 domain=zha 那条的 state
```

> 注意 `zha/devices` 这条 websocket 命令在配置项没加载时会直接返回
> `unknown_error`，**看着像 API 坏了，其实是集成没起来**。先查
> `config_entries/get` 再查设备，顺序反了会误判。

## 静态绑定做完了，协调器回到 `.32`

✅ **2026-08-13 11:49 实测。** 路由器上给 `12:00:00:AB:D1:C8` 做了 DHCP 静态
地址分配、盒子断电重插之后：

| 判据 | 结果 |
|---|---|
| ARP | `192.168.1.32` ← `12:0:0:ab:d1:c8`（`.28` 已空）|
| TCP `192.168.1.32:6636` | 可连（在此之前 HA 报 `[Errno 113] No route to host`）|
| ZHA 配置项 | `state=loaded`、`reason=null`（此前是 `setup_retry`）|

**重连 ZHA 不用重启 HA**，命令行调一次服务就行：

```bash
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
     -d '{"entry_id":"01KZTW8EN38M2P4EK4E3TREQ2T"}' \
     http://192.168.1.29:8123/api/services/homeassistant/reload_config_entry
```

> 盒子那会儿还有个附带症状：它赖在 `.28` 时，`6636` 端口**既不拒绝也不应答**
> （TCP 连接超时，而 `80` 端口正常回 RST）。断电重插一次两个问题一起好，
> 所以遇到"端口不响应"别急着怀疑固件，先重插。

## LH79221 到底是什么：原始射频帧说了算

⚠️ **2026-08-13 12:02 实测，推翻了上一节的"基本可以断定是人体感应器"。**

打开 ZHA 的深度日志（`zigpy` / `zigpy.zcl` / `bellows` / `homeassistant.components.zha`
全设 `debug`）之后，抓到了这只设备的原始 ZCL 帧：

```
[0x77DA:1:0x0500] IasZone:status_change_notification(zone_status=<ZoneStatus.Test: 256>)    → is_on: False
[0x77DA:1:0x0500] IasZone:status_change_notification(zone_status=<ZoneStatus.Alarm_1: 1>)   → is_on: True
```

`Test`(bit 8) 是它上电自检报的，`Alarm_1`(bit 0) 才是"我被触发了"。设备本身
**活得很好**：入网握手完整（`Device_annce` + `Basic` 属性 `model=LH79221`、
`app_version=31`、`hw_version=100`），信号 LQI 244 / RSSI −38。

所以**光凭 IAS Zone 指纹判不出它是传感器还是按钮** —— 这一族廉价无线按钮就是
借 IAS Zone 的告警位来上报按压的，指纹和门窗磁、人体感应长得一模一样。
人坚持说它是"单键自回弹的 Zigbee 无线开关"，与帧数据并不矛盾。

**打开深度日志的办法**（运行时生效，重启 HA 即恢复，不改配置文件）：

```bash
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
     -d '{"zigpy":"debug","zigpy.zcl":"debug","bellows":"debug","homeassistant.components.zha":"debug"}' \
     http://192.168.1.29:8123/api/services/logger/set_level
# 然后拉日志看原始帧
curl -s -H "Authorization: Bearer $HA_TOKEN" http://192.168.1.29:8123/api/error_log \
  | grep '0x0500.*Decoded ZCL frame: IasZone'
```

### 为什么这类设备**不会**发 `zha_event`

日志里这一行是关键：

```
[0x77DA:1:0x0500] No explicit handler for cluster command 0x00: status_change_notification(...)
```

zigpy 没有为 IAS Zone 的 `status_change_notification` 挂专门的命令处理器，
ZHA 也就**不会**把它转成 `zha_event`。所以上一节那句"真按钮多半发 `zha_event`、
触发器要改成 event 类型"**对这只设备不成立** —— 它的按键信息只存在于
`binary_sensor` 的状态位里，事件总线上什么都没有。

### 排查这类问题的一个坑：`state_reported` 订阅不了

设备重复上报**同一个值**时，HA 只更新实体的 `last_reported`，不会触发
`state_changed`。想在事件层看见这种"又说了一遍"，只能听 `state_reported` ——
但 HA 的 websocket **拒绝无过滤订阅**它：

```json
{"type":"subscribe_events","event_type":"state_reported"}
→ {"success": false, "error": {"code":"home_assistant_error",
   "message":"Event filter is required for event state_reported"}}
```

所以靠 `subscribe_events` 盯按键**天生有盲区**，会把"设备发了但值没变"误判成
"设备没发"。可靠的办法是轮询 REST 的 `/api/states/<entity>` 比对 `last_reported`，
或者直接看上面那份 ZHA 深度日志的原始帧。

### 上报历史（`/api/history/period`）

| 时间 (CST) | 状态 | 备注 |
|---|---|---|
| 08-13 00:16:49 | `off` | 配对后基线 |
| 08-13 00:17:39 | `on` | 人第一次按，收到 |
| 08-13 01:04:05 | `unavailable` | 协调器 IP 漂移，Zigbee 全断 |
| 08-13 11:04:39 | `off` | 协调器修好，设备回网 |
| 08-13 11:11:14 | `on` | 人按，收到 |
| 08-13 11:19:36 → 37 | `off` → `on` | 一秒内一个脉冲 |

人在 00:20、00:51 明确说"按完了"，**历史里一条记录都没有**；11:19–11:49 连续
盯了 30 分钟（事件订阅 + 每 1.5 秒轮询 `last_reported`）同样**零上报**。

**读作**：它按完会 latch 在 `on` 上，此后重复同一个动作**至少在 HA 这一层
看不到任何东西**。"第一下有反应、之后全死"是这么来的，不是自动化写错。

## `Test` 是心跳，不是自检 —— 它才是唯一的复位来源

⚠️ **2026-08-13 15:22 定论。这一条是理解这只设备的关键，前面几节的推测以它为准。**

一开始以为 `zone_status=Test`(bit 8) 是设备上电自检。**不是。** 把 `zigpy.zcl`
留在 debug、其余降回 warning 之后，`Test` 帧的间隔一目了然：

```
15:01:31.480   Test
15:11:58.169   Test      ← 10m27s
15:22:24.829   Test      ← 10m26s
```

**每 ~10.4 分钟一次，雷打不动的心跳。** 早先的数据也全对得上：
13:17:35 → 13:38:13 正好两个周期，13:38:13 → 15:01:31 正好八个。

于是这只设备的完整行为是：

| 事件 | zone_status | `binary_sensor.lh79221` |
|---|---|---|
| 人按一下 | `Alarm_1` (bit 0) | → `on`，**并停在 on 不动** |
| 每 ~10.4 分钟 | `Test` (bit 8) | → `off` ← **唯一的复位来源** |

**后果：一个心跳周期内只有第一次按压能产生 `off → on` 边沿。**
14:44:29–14:45:15 之间人连按八下，日志里八帧 `Alarm_1` 一帧不少，
但只有第一帧赶上了 `off` 起点、触发了自动化，后面七帧全被吞。

这不是能用的电灯开关。

### HA 侧无解，必须在 ZHA 那一层修

重复的 `Alarm_1` 在 HA 状态机里**根本不存在** —— 值不变时 ZHA 干脆不写状态，
连 `last_reported` 都不动（实测：`:32.016` 和 `:35.165` 两帧重发期间，
`last_reported` 全程停在 `05:23:31.292900`）。所以**任何基于 state / template /
event 的触发器都救不了**，这不是写法问题。

正解是给它配一个 **ZHA quirk**，让 `Alarm_1` 之后自动把 zone_status 复位
（`zhaquirks` 里的 `reset_s` 那套），这样每按一次都产生干净的 `off → on`。

落地步骤：

1. quirk 放宿主机 `/opt/ha/config/custom_zha_quirks/`（容器里是 `/config/...`）
2. `configuration.yaml` 加 `zha: custom_quirks_path: /config/custom_zha_quirks`
3. 重启 HA

推文件走 `../deploy.sh`。**写 quirk 之前先核对主机上实际装的 `zhaquirks` 版本**
—— `reset_s` 那套 API 在版本之间改过，凭记忆写等于埋雷。

## 第三个独立故障点：餐厅灯自己会掉线

⚠️ **2026-08-13 记录。跟 Zigbee 无关，但会让整条链路看起来"没反应"。**

`light.yeelink_cn_56292508_mono1_s_2_light`（米家 `xiaomi_home` 集成）
会反复进入 `unavailable`：

| 时间 (CST) | 状态 |
|---|---|
| 08-13 06:00 → 10:24 | `unavailable` |
| 10:24 → 14:20 | `on` |
| 14:20 → 14:44 | `unavailable` |
| 14:44 → | `on` |

14:44:02 那次按压**整条链路都是通的** —— ZHA 收到 `Alarm_1`、边沿产生、
自动化 `last_triggered` 有值 —— 但 `light.toggle` 正好打进了灯的掉线窗口，
指令落空。**排查时先看灯那一刻在不在线**，别把这个算到 Zigbee 头上。

## 状态

⏳ **链路已经全程打通过一次，但可用性不达标。**

- ✅ 协调器固定在 `192.168.1.32`（路由器静态绑定），ZHA `state=loaded`
- ✅ `LH79221` 在网、信号好，按压走 IAS Zone `Alarm_1`，原始帧已抓到
- ✅ 自动化已改成单边沿触发、已启用，**实测触发过**
  （`last_triggered=2026-08-13T06:44:02Z`）
- ⚠️ **但一个心跳周期(~10.4 分钟)内只有第一次按压有效** —— 见上面那节，
  必须配 ZHA quirk 才能根治
- ⚠️ 餐厅灯会自己掉线，掉线窗口内按了也没用 —— 见上面那节
- ❌ **还没有一次"人按下去、灯当场翻"的完整成功记录**

**下一步取决于那个未验证项**（正挂着原始帧监听等人连按 3 下）：

- **重复按会发帧** → 帧到了但 HA 状态不动，改 HA 侧：别盯 `state`，
  改盯 `last_reported`（或用模板/事件过滤的方式接原始上报）。
- **重复按不发帧** → 是设备自身 latch，得给它配一个 **ZHA quirk**：
  把 `Alarm_1` 映射成带自动复位（`reset_s`）的实体，这样每按一次都产生
  干净的 `off → on` 边沿，现有那条 `state` 触发器就能一直用下去。
  quirk 放 `/opt/ha/config/custom_zha_quirks/`，在 `configuration.yaml` 里
  用 `zha: custom_quirks_path:` 指过去，需要重启 HA。推文件走 `../deploy.sh`。

**启用自动化之前仍然必须先定身份。** 只要还没排除"它是门窗磁 / 人体感应"，
就不能启用 —— 开门或走过去会让餐厅灯自己动，违反家规第一条。
现有帧数据（单个 `Alarm_1`，无 `Zone Status` 周期上报）跟按钮相符，但**没到
可以拿家里的灯去赌的程度**；等那 3 下连按的数据到了再定。
