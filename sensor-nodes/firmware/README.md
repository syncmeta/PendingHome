# 传感节点固件(ESPHome)

三个 XIAO ESP32-C3 节点的 ESPHome 配置。硬件还没到货,这里是"到货直接刷"的模板。

```
firmware/
├── node-window.yaml     窗边:SCD41 + AS7341 + TCS34725 + 门磁
├── node-living.yaml     客厅靠里:SCD41
├── node-bedroom.yaml    卧室:SCD41
├── common/              公共部分,三个节点用 packages 复用,不复制粘贴
│   ├── base.yaml        esphome / esp32 / wifi / api / ota / 诊断实体
│   ├── i2c.yaml         I2C 总线(GPIO6/7)
│   ├── scd41.yaml       CO2 + 温湿度(含强制校准按钮)
│   ├── as7341.yaml      8 通道光谱 → 色温(自己算的,见文件头)
│   ├── tcs34725.yaml    RGB → 色温(对照组)+ 补光灯开关
│   └── reed-window.yaml 窗户开合
├── secrets.yaml.example
└── .gitignore
```

节点文件本身只有一个 `packages:` 块 —— 所有实际配置都在 `common/` 里,
三个节点的差异只体现在"引入了哪几个包"。要改 WiFi/OTA 的写法,只改 `common/base.yaml`。

## 一、刷机

```bash
cd sensor-nodes/firmware
cp secrets.yaml.example secrets.yaml && $EDITOR secrets.yaml
# 或者跟 cct-driver 共用一份:
#   ln -s ../../cct-driver/firmware/secrets.yaml secrets.yaml

esphome run node-window.yaml      # 首刷插 USB;之后 OTA
esphome run node-living.yaml
esphome run node-bedroom.yaml
```

`secrets.yaml` 的键名跟 `cct-driver/firmware/` 完全一致,可以直接共用。

> **本机没装 esphome,这套配置没跑过 `esphome config` 静态校验。**
> 详见文末「没能验证的部分」。首刷前先在装了 esphome 的机器上跑一次
> `esphome config node-window.yaml`,它会把所有 schema 错误一次性列出来。

## 二、接线

XIAO ESP32-C3 的丝印是 D0–D10,和 GPIO 编号不是一回事。ESPHome 里必须写 GPIO 号。

| 丝印 | GPIO | 接什么 |
|---|---|---|
| D1 | GPIO3 | 门磁一根线(另一根接 GND) |
| D2 | GPIO4 | TCS34725 模块的 `LED` 脚 |
| D4 | GPIO6 | I2C **SDA** —— SCD41 / AS7341 / TCS34725 三个模块并接 |
| D5 | GPIO7 | I2C **SCL** —— 同上 |
| 5V | — | 三个传感器模块的 VIN(模块自带稳压) |
| GND | — | 共地 |

避开了 GPIO2 / GPIO8 / GPIO9 —— ESP32-C3 的 strapping 脚,上电时的电平会影响启动模式。

**I2C 地址**:SCD41 `0x62`,AS7341 `0x39`,TCS34725 `0x29`。三个不冲突,同一条总线并排挂。

**供电(采购清单第三节第 1 条)**:SCD41 测量瞬间吃约 205mA,和 WiFi 发射峰值撞上会把
XIAO 拖复位。模块走 **5V 脚**(不是 3V3),并在模块电源脚并一颗 100–470µF 电解电容。

## 三、到货第一天要做的三件事

### 1. 关掉色温模块的板载白光 LED

**不关就是传感器自己照自己,色温读数全废。**

- **TCS34725**(GY-33 等):板上有一颗白光 LED。把模块的 `LED` 脚接到 D2/GPIO4,
  固件里的「TCS34725 补光灯」实体默认常关。
  Adafruit 版默认用一道焊桥把 LED 脚吊高(上电就亮),**必须先割断那道焊桥**。
  如果你不打算做补光对照实验,最干净的做法是把 `LED` 脚直接焊到 GND ——
  连上电那 200ms(GPIO 尚未驱动、处于高阻)的一闪都省了。
- **AS7341**:补光 LED 由芯片内部的 LED 寄存器控制,复位后默认关闭,
  ESPHome 从不写这个寄存器,所以软件侧不用管。但**拿眼睛确认一次**:
  部分模块(如 Adafruit 4698)另有一道 LED 焊桥会绕过芯片直接点亮。亮着就割断。

### 2. SCD41 强制校准(**每个节点都要做**)

三个节点的自动自校准(ASC)**全部关闭**,包括窗边那个。
理由写在 `common/scd41.yaml` 文件头 —— 简单说:全屋只有一扇窗,ASC 的前提
("每周至少见一次室外空气")在这里是赌用户的开窗习惯,而它失效的方向恰好是
**越缺氧显示得越正常**,是最坏的那种错。所以统一关掉、统一手动校准。

**这一步不做,CO₂ 读数就是错的,而且看不出来错。**

每个节点:

1. 节点通电,把它拿到室外通风处(避开车流,避开自己呼气,别放墙角)
2. 原地放 **5 分钟以上**(SCD41 要求校准前在稳定浓度下连续测 3 分钟以上)
3. 在 HA 里按下这个节点的「**SCD41 强制校准到 420ppm**」按钮
4. 拿回室内装好

420ppm 是 2026 年的室外本底值。校准完读数会跳一下,正常。以后每年复校一次。

### 3. 温度偏移标定

`common/scd41.yaml` 里 `temperature_offset: 4.0` 是 Sensirion 的出厂默认值。
装进外壳后自发热会变,拿一支靠谱温度计对一次,差多少改多少。
**这个值偏了,CO₂ 读数会跟着偏** —— SCD41 内部用温度做补偿。

## 四、实体重命名表

ESPHome 实体名是中文,HA 转成 entity_id 的结果不好预测(可能是拼音,也可能被裁掉)。
HA 那边的自动化用的是下面这套统一命名,**接进 HA 后照表改一次**:

> 设置 → 设备与服务 → ESPHome → 点进设备 → 点实体 → 齿轮 → 改 entity ID

### 自动化真正依赖的(**必须改**)

| 节点 | 实体显示名 | 改成 |
|---|---|---|
| 窗边 | CO₂ | `sensor.node_window_co2` |
| 窗边 | 窗户 | `binary_sensor.node_window_window` |
| 窗边 | 窗外色温 (AS7341) | `sensor.node_window_cct_as7341` |
| 窗边 | 窗外色温 (TCS34725) | `sensor.node_window_cct_tcs34725` |
| 窗边 | 窗外照度 (TCS34725) | `sensor.node_window_lux_tcs34725` |
| 客厅 | CO₂ | `sensor.node_living_co2` |
| 卧室 | CO₂ | `sensor.node_bedroom_co2` |

### 其余(建议改,方便画图和排查)

| 节点 | 实体显示名 | 改成 |
|---|---|---|
| 窗边 | 温度 / 湿度 | `sensor.node_window_temperature` / `_humidity` |
| 窗边 | AS7341 415nm … 680nm | `sensor.node_window_as7341_415nm` …(照波长) |
| 窗边 | AS7341 Clear / NIR | `sensor.node_window_as7341_clear` / `_nir` |
| 窗边 | AS7341 相对亮度 | `sensor.node_window_as7341_y` |
| 窗边 | TCS34725 Clear 通道 | `sensor.node_window_tcs34725_clear` |
| 客厅 | 温度 / 湿度 | `sensor.node_living_temperature` / `_humidity` |
| 卧室 | 温度 / 湿度 | `sensor.node_bedroom_temperature` / `_humidity` |

按这套命名的话,HA 里排除原始光谱记录可以直接用 `sensor.node_window_as7341_*` 通配。

不想改名也行 —— 那就把 `ha-t630/homeassistant/config/packages/` 下两个 yaml 里的
这些 ID 整体替换成 HA 实际生成的。

## 五、两颗色温传感器怎么比

窗边节点同时跑 AS7341(主选)和 TCS34725(对照)。两个都出 `窗外色温` 实体。

比的方法:在 HA 里把两条曲线画在同一张图上,跑一周,重点看这几个时刻 ——

- **正午晴天**:两条应该都在 5500–6500K 附近,差得远说明有一颗不对
- **日落前一小时**:真实色温会明显往下走(3000K 甚至更低)。跟不上的那颗是钝的
- **阴天**:实际会偏高(7000K+),这是天光散射,不是错
- **晚上开灯之后**:这是 TCS34725 最容易翻车的场景(社区实测有 6490K 读成 11000K 的)

选定之后:定板时只留胜出的那颗;`common/as7341.yaml` 里那套 CIE 权重换成 AMS
应用笔记 AN000633 的出厂相关矩阵,精度还能再上一档。

## 六、没能验证的部分

硬件没到货,本机也没装 esphome(按要求没有自行安装),所以:

**完全没验证的**

- 真机行为:一样都没跑过。所有传感器读数、I2C 时序、供电稳定性、WiFi 表现全是纸面的
- `esphome config` 静态校验没跑过。组件选项是逐个对着 ESPHome 官方文档核过的
  (scd4x / tcs34725 / as7341 / packages 四个页面),但 schema 级的错误只有
  真跑一次校验才能全抓出来
- 编译:C++ lambda(AS7341 那两段)没编译过

**验证过的**

- YAML 语法:12 个文件(固件 9 + HA 3)全部用 Python 的 yaml 解析器过了一遍,
  `!include` / `!secret` 这类 ESPHome 自定义标签注册了占位构造器,0 错误。
  这只能保证"不是语法错误",保证不了"ESPHome 认得这些字段"
- AS7341 的色温算法:拿 Planck 公式生成黑体谱在 8 个通道上的理论值,回代算法看
  能不能还原原始温度。这一步抓出了一个真问题 —— 最初按等权重写的版本在 6500K 处
  高估 861K,改成按通道带宽 Δλ 加权后降到 -270K。修正后的残差(偏低 3~5%,
  随色温升高变大)记在 `common/as7341.yaml` 文件头
- HA 侧的 Jinja 模板**没有**做解析校验(本机没装 jinja2,同样没有自行安装)。
  配置放进去之后先走一遍「开发者工具 → YAML → 检查配置」

**明确是估算、需要实测才能定的**

- `as7341.yaml` 里的色温算法:CIE 权重是按通道中心波长取的标准观察者值 × 通道带宽,
  没有做通道响应度归一化,是"够用的近似",不是标定过的测量。文件头写了局限
- `temperature_offset: 4.0`、`glass_attenuation_factor: 1.0`:都是默认值占位,等标定
- HA 侧的死区 300K、门闩 90s、照度门槛 30lx、CO₂ 的 1000/1500 阈值:
  都是有依据的起点,不是实测值。这正是"先原型后画板"要换来的东西
