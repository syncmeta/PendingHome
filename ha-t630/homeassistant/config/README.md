# Home Assistant 配置 · PendingHome 自动化

`packages/` 下是 PendingHome 的自动化骨架。硬件到货前就能先放进去 —— 引用的实体
不存在时 HA 不会报致命错误,只是那几条自动化跑不起来。

## 一、启用(只做一次)

HA 首次启动会自己生成 `configuration.yaml`。**别用本仓库覆盖它**(会打断引导流程)。
引导走完之后,在 `configuration.yaml` 里加两行:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

如果已经有 `homeassistant:` 段,就只加 `packages:` 那一行,注意缩进对齐。

然后「开发者工具 → YAML → 检查配置」,通过后重启 HA。

## 二、文件

| 文件 | 干什么 |
|---|---|
| `packages/pendinghome_notify.yaml` | 通知出口。所有提醒都经过这一个脚本,换推送方式只改这里 |
| `packages/pendinghome_co2_ventilation.yaml` | CO₂ 分级提醒(>1000 / >1500),带"窗开着就别念叨"的联动 |
| `packages/pendinghome_daylight_cct.yaml` | 窗边色温 → CCT 灯带日光同步,含防正反馈门闩 |

## 三、必须替换的占位符

每个文件开头都有一段 `⚠️ 需要替换` 的清单,这里是汇总。

### 1. 通知推给谁 —— `pendinghome_notify.yaml`

默认只在 HA 网页里创建持久通知,**手机上收不到**。
要推手机就把 `script.ph_notify` 里的 action 换成 `notify.mobile_app_<你的手机>`,
文件里写了现成的写法。

### 2. 灯组 —— `pendinghome_daylight_cct.yaml`

`light.cct_daylight_group` **现在不存在,必须你自己建**:

> 设置 → 设备与服务 → 助手 → 新建助手 → 分组 → 灯光

把 CCT 驱动板里要跟日光走的那几路拖进去,名字取成 `cct daylight group`
(HA 会生成 `light.cct_daylight_group`)。

用灯组而不是直接写死某一路,是因为哪几路该跟日光是装修完才知道的事;
以后增减灯只改灯组,不用动自动化。

### 3. 传感器实体 ID

自动化里用的是这套统一命名:

| 自动化里写的 | 是哪个 |
|---|---|
| `sensor.node_window_co2` | 窗边 CO₂ |
| `sensor.node_living_co2` | 客厅 CO₂ |
| `sensor.node_bedroom_co2` | 卧室 CO₂ |
| `binary_sensor.node_window_window` | 窗户开合(有线门磁) |
| `sensor.node_window_cct_as7341` | 窗边色温(AS7341,主选) |
| `sensor.node_window_cct_tcs34725` | 窗边色温(TCS34725,对照) |
| `sensor.node_window_lux_tcs34725` | 窗边照度 |

**ESPHome 自动生成的 entity_id 不长这样。** 节点固件里实体名是中文,
HA 会按自己的规则转写(可能是拼音,也可能被裁掉),结果不好预测。
两条路选一条:

- **推荐**:设备接进 HA 后,到「设置 → 设备与服务 → ESPHome → 对应设备」,
  逐个把实体的 entity_id 改成上表左列的值。一次性工作,之后自动化就一直可读。
- 或者:把上表左列在两个 yaml 文件里整体搜索替换成 HA 实际生成的 ID。

详细对照表在 `sensor-nodes/firmware/README.md` 的「实体重命名表」。

## 四、几个能在界面上调的开关

启用后会多出这几个助手实体:

| 实体 | 作用 |
|---|---|
| `input_boolean.ph_co2_snooze` | CO₂ 提醒静音。装修、做饭这种明知会超标的时候打开 |
| `input_boolean.ph_daylight_sync` | 日光同步总开关。**默认是关的,要手动打开一次** |
| `input_boolean.ph_daylight_latch` | 门闩状态(只读性质,自动化自己控制)。想确认防震荡有没有在工作就看它 |

日光同步的其余参数(死区、门闩时长、照度门槛、渐变时长)写在
`pendinghome_daylight_cct.yaml` 的 `variables:` 里,改完在
「开发者工具 → YAML → 重新加载自动化」就生效,不用重启 HA、更不用重刷固件。

## 五、原型期可能想加的一条

AS7341 有 10 个原始通道实体,每 60s 更新一次。一周比对下来数据库会长不少。
不想记录原始光谱的话,在 `configuration.yaml` 里:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.node_window_as7341_*
```

但注意:比对期间这些数据**恰恰是你要的证据**(晴天/阴天/黄昏的光谱形状差别),
真要排除,等选完传感器再排除。
