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

## 状态

⏳ **进行中。** 已确认的到上表为止；ZHA 尚未接入、开关尚未配对。
配对那一步需要人动手按开关上的配对键 —— 到时候会说清楚按哪个、按多久。
