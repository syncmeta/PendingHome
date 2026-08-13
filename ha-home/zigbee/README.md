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

## 状态

⏳ **两个断点，串在一起。**

1. ❌ **协调器连不上** —— IP 漂了，见上一节。等路由器做完静态绑定。
2. ❌ **真正的开关还没配上** —— 见下。

- ✅ ZHA 集成配好了（网络也组好了），但**当前连不上协调器**
- ✅ 餐厅灯在 HA 里，实测可控
- ✅ 自动化写好了，但**已停用** —— 见 `automations.dining-switch.yaml` 顶部说明
- ❌ **那个能按的 Zigbee 开关还没配上**

顺带一条旁证：`LH79221` 在 HA 里生成的实体叫 `update.lh79221_ren_ti`、
`binary_sensor.lh79221` —— 名字里那个**「人体」**是设备自己报上来的，
跟前面读出的 IAS Zone 指纹对得上。基本可以断定它是个人体感应器。

**为什么把自动化停掉**：它现在指着 `binary_sensor.lh79221`。万一那真是门窗磁
或人体感应，开个门、走过去，餐厅灯就会**自己动** —— 那正是家规第一条
（只做氛围和提示、不做自动开关灯）要禁的。身份没确认之前宁可停着。

**下一步**：确认 `LH79221` 到底是什么、以及那个真正要按的开关是哪个物件，
把它配进来，再把触发器换成它。**真的按钮类设备多半发 `zha_event`**，
那样触发器要从 `state` 类型改成 `event` 类型。
