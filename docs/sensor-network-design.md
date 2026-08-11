# PendingHome 传感网络设计

> 状态:**方案文档,待人点头**。
> `sensor-nodes/firmware/` 和 `ha-t630/homeassistant/config/` 下已写好的配置**尚未按本文档修改** ——
> 本文第 10 节列了两者的全部差异。点头之后再动固件。
>
> 目标不是"装一堆传感器",是让房子**知道当前是什么状况**,然后少做、做对。

---

## 1. 三条自动化原则

这三条决定了后面所有设计。技术选型可以换,这三条不能。

### 原则一 · 优先做「删掉动作」,别做「替人决定」

| 该做 | 不该做 |
|---|---|
| 进屋灯自己亮 —— 删掉了"摸开关" | 系统觉得你该睡了,自己关灯 |
| 走了一段时间灯自己灭 —— 删掉了"回头关灯" | 系统觉得屋里闷,自己开窗/开新风 |
| 日光变了色温跟着走 —— 删掉了"手动调色温" | 系统觉得你在看书,自己调亮 |

判据很简单:**这个动作,人本来就会做、而且每次都做同一件事吗?** 是,就自动化掉;
不是,那是在猜人的意图,猜错的代价远大于猜对的收益。

CO2 高只发提醒不做动作,就是这条 —— 开不开窗是人的决定,系统只负责让人知道。

### 原则二 · 手动永远优先,且带超时

人手动改过之后,相关自动化**闭嘴一段时间**(建议两小时,或到该区域转为空置为止,
以先到者为准)。没有这条,人和系统会互相打架,而人一定会赢 —— 赢的方式是把整套系统关掉。

日光同步里那个防正反馈门闩,是这条原则的一个特例(冻结的对象是传感器读数而不是人的操作)。

### 原则三 · 成功要无感,失败要静默

自动化做对的时候,人不该注意到它发生过。做错的时候,代价必须小到人懒得抱怨。
**宁可少做一次,别多做一次** —— 漏一次开灯,人自己按一下就完了;
半夜误判有人把灯打开,这套系统就到头了。

具体到参数上:所有"触发动作"的阈值往保守调,所有"停止动作"的延时往长了调。

---

## 2. 架构:四层,自动化只碰最上面一层

```
┌─ 4. 自动化层  ── 只读语义状态,不读原始数字
│                  「客厅空置且天黑 → 关灯」
├─ 3. 语义层    ── 房间占用 / 光环境 / 空气 / 家状态
│                  有限个离散状态,人能一眼看懂
├─ 2. 证据层    ── HA 侧派生:Bayesian 融合、CO2 变化率、平滑与迟滞
├─ 1. 原始层    ── ESPHome 实体:ppm / lux / K / 有目标 / 有动作 / 窗开合
└──────────────────────────────────────────────────
```

**为什么值得多这两层。** 你说"以后可能不仅仅是这几个传感器"—— 这一句就决定了架构。

自动化如果直接写 `sensor.node_living_co2 > 1000`,那么以后每加一个传感器、每换一个型号、
每挪一次位置,都要回去改所有自动化,而且改漏了不报错,只是某条自动化悄悄失效。

自动化写 `sensor.ph_living_air == '闷'` 的话,加传感器只改**推导逻辑那一处**,
自动化原封不动。语义层就是一个防火墙,把"传感器怎么变"和"房子怎么反应"隔开。

**代价要说清楚**:多一层意味着排查问题时多一跳(灯没亮 → 是自动化没触发,还是语义状态没变,
还是传感器没数)。所以每个语义状态都必须**在 HA 里是一个看得见的实体**,能一眼看到它现在是什么、
上次什么时候变的。不要用 Jinja 在自动化内部临时算语义 —— 那样就没法排查了。

---

## 3. 节点与传感器

| | node-window | node-living | node-bedroom |
|---|---|---|---|
| 位置 | 窗边(全屋唯一一扇窗) | 客厅靠里 | 卧室 |
| MCU | ESP32-C3 SuperMini | ESP32-C3 SuperMini | ESP32-C3 SuperMini |
| CO2 | — | SCD41 | SCD41 |
| 色温/照度 | TCS34725 | — | — |
| 照度 | (TCS34725 自带) | BH1750 | BH1750 |
| 存在 | — | LD2410C + PIR | LD2410C + PIR |
| 窗户 | 有线门磁 | — | — |
| 供电 | USB-C 常电 | USB-C 常电 | USB-C 常电 |

**烟感、水浸买成品走 Zigbee**,不进这套 WiFi 节点。协调器人已经有了,边际成本几乎为零。
理由:烟感是安全设备,价值在认证和"断网也自己响";水浸探头位置刁钻(柜子深处),
成品 IP67 + 电池两年更省事。这两类**不能依赖 HA 在线**,所以本来就不该挂在这套系统上。

---

## 4. 选型:三处推翻了之前的方案

### 4.1 MCU 换成 ESP32-C3 SuperMini(¥10,原 XIAO ¥35)

三个节点省 ¥75。常电、室内、不跑重活,XIAO 的做工在这里换不来任何东西。

**但有两个坑必须先知道:**

- **天线**。SuperMini 是廉价克隆板,PCB 天线的净空区设计有问题是社区公认的,
  不同批次差别很大,WiFi 信号可能明显弱于 XIAO。**到货第一件事是在三个实际安装位置
  测 RSSI**(固件里已经有 `WiFi 信号` 诊断实体),低于 -75dBm 就别硬上。
  这也是买 SuperMini 的真实风险 —— 省下的 ¥75 换来的是"可能要重买"。
- **GPIO8 接着板载 LED,GPIO2/8/9 是 strapping 脚**,别拿来接传感器。

### 4.2 窗边节点不装 SCD41

**窗边是全屋测 CO2 最没有意义的位置。** 开窗时它直接掉到室外值 ——
这时候它测的是窗外,不是屋里。而"该不该通风"恰恰要靠屋里的值来判断,
窗边这个数只会把全屋最高值拉低,让判断失真。

CO2 只在**客厅靠里**和**卧室**两个点。这两个点测的才是"最不通风的那块空气"。
省一颗 SCD41,¥70。

> 附带影响:`sensor.ph_co2_max` 的取值范围从三个变成两个。见第 10 节。

### 4.3 色温只留 TCS34725,不买 AS7341

推翻"两个都买做对照"。理由:

**这里绝对精度不重要,要的是重复性和单调性。** 最终用途是把窗外色温映射到灯带色温,
中间必然有一条人工调出来的映射曲线。传感器读 6490K 还是读 8000K 无所谓,
只要**同样的光永远读出同样的数**(重复性)、**光变暖时读数一定变小**(单调性),
系统偏差就会被映射曲线整个吸收掉。

TCS34725 被诟病的是绝对精度差,不是重复性差。而 AS7341 贵的那 ¥50 买的正好是绝对精度 ——
在这个用途上是白买的。

> 已经写好的 `common/as7341.yaml` **不删**,留在仓库里。以后若发现 TCS34725 的单调性
> 在某些光下也出问题(比如阴天和 LED 混光时),换过去只要改一行 packages。
> 那份文件里的色温算法已经拿黑体谱验算过,不是废稿。

### 4.4 人体存在:LD2410C + PIR 融合,不用 PIR 单干

**PIR 测的是移动,不是存在。** 坐着不动就判无人、灯啪一下灭 —— 这是家庭自动化第一号翻车点。

- **LD2410C**(¥25–35,UART,ESPHome 原生 `ld2410`):毫米波,测真存在,静坐和睡着都还在
- **PIR**(AM312,¥4,3.3V 原生):补 LD2410 的短板 —— 毫米波对"刚进门那一下"的响应
  比 PIR 慢,而且容易被风扇、窗帘飘动、隔壁房间的人骗到

两个一起用不是冗余,是**测的东西不一样**:mmWave 回答"屋里有没有人",PIR 回答"刚刚有没有动作"。
第 5 节讲怎么融合。

**LD2410 的坑,按踩到的概率排序:**

1. **穿墙、穿玻璃。** 它看得见隔壁房间的人和窗外走过的人。这是毫米波的物理特性,不是故障。
   → 装的时候必须避开:别对着门口外面,**别正对窗**,别对着共用墙的另一侧沙发
2. **距离门要现场调。** LD2410 把 0–6m 分成 9 个门(gate 0–8,默认每门 0.75m),
   每个门的移动/静止灵敏度都能单独设。出厂默认在小房间里太灵敏。
   ESPHome 的 `ld2410` 组件把这些门做成了 `number` 实体,**可以在 HA 界面上直接拖着调,
   不用重刷固件** —— 这是选它的一个实际好处。调法:人离开房间,把误报的那几个门的
   灵敏度降到不再误报为止;然后人进去坐着不动,确认还能检出
3. **供电电压看清楚。** LD2410C 裸模块是 3.0–3.6V 供电,部分转接板才带 5V 稳压。
   买之前问清楚,接错烧模块
4. **蓝牙默认开着**,能耗和干扰都没必要。ESPHome 的 `ld2410` 有 `bluetooth` 开关实体,装好关掉

### 4.5 光照 BH1750(¥8)

客厅和卧室各一个。窗边不用 —— TCS34725 自带照度。
用途:判断"这个房间现在够不够亮",决定进屋要不要开灯。

BH1750 挂在同一条 I2C 总线上(0x23),不占额外引脚。

---

## 5. 语义状态层

这是这份文档的核心。**每个状态都是 HA 里一个看得见的实体。**

### 5.1 房间占用 · `sensor.ph_<room>_occupancy`

三态:`有人活动` / `有人静止` / `空置`

| 证据 | 来源 | 说明 |
|---|---|---|
| mmWave 有目标 | `binary_sensor.node_living_presence` | LD2410 的 `has_target` |
| mmWave 有静止目标 | `binary_sensor.node_living_still` | `has_still_target` |
| PIR 动作 | `binary_sensor.node_living_motion` | AM312 |
| CO2 上升 | `sensor.ph_living_co2_trend` | derivative 集成算出的 ppm/min |
| 窗户开合 | `binary_sensor.node_window_window` | 只作为"刚有人操作过"的旁证 |

**实现分两步,别合成一步。**

**第一步:Bayesian 融合出「有没有人」**

```yaml
binary_sensor:
  - platform: bayesian
    name: "客厅有人 (原始)"
    unique_id: ph_living_occupied_raw
    prior: 0.35                    # 客厅一天中有人的时间占比,按自家作息估
    probability_threshold: 0.75    # 往高了调 —— 原则三:宁可漏判
    observations:
      - platform: state
        entity_id: binary_sensor.node_living_presence
        to_state: "on"
        prob_given_true: 0.95
        prob_given_false: 0.10     # 0.10 而不是 0.02:承认它会被窗帘/隔壁骗到
      - platform: state
        entity_id: binary_sensor.node_living_motion
        to_state: "on"
        prob_given_true: 0.55      # 人在但不动的时候 PIR 是灭的,所以不能高
        prob_given_false: 0.02     # 但 PIR 亮了基本就是真有动作
      - platform: numeric_state
        entity_id: sensor.ph_living_co2_trend
        above: 3                   # ppm/min,一个人在密闭房间大致这个量级
        prob_given_true: 0.60
        prob_given_false: 0.10
```

**第二步:加延时,再定三态**

Bayesian 传感器是**瞬时**的 —— 它没有记忆,证据一撤就立刻翻转。直接拿它当占用会闪。
外面套一层 `delay_off`:

```yaml
template:
  - binary_sensor:
      - name: "客厅有人"
        unique_id: ph_living_occupied
        device_class: occupancy
        state: "{{ is_state('binary_sensor.ph_living_occupied_raw', 'on') }}"
        delay_off: "00:05:00"      # 原则三:停止动作的延时往长了调
  - sensor:
      - name: "客厅占用状态"
        unique_id: ph_living_occupancy
        state: >
          {% if not is_state('binary_sensor.ph_living_occupied', 'on') %}空置
          {% elif is_state('binary_sensor.node_living_motion', 'on')
               or is_state('binary_sensor.node_living_moving', 'on') %}有人活动
          {% else %}有人静止{% endif %}
```

**三个必须知道的事:**

1. **朴素贝叶斯假设各条证据互相独立,而 PIR 和 mmWave 显然不独立**(都对移动有反应)。
   人一动两个同时亮,后验概率会被算得比真实置信度高。补偿办法就是上面那样:
   **把 PIR 的 `prob_given_false` 压低、`prob_given_true` 也压低**,让它只起"加一点分"的作用,
   别让它单独就能顶过阈值
2. **`prior` 要按房间分别估**。卧室白天基本空着(prior 0.2),客厅晚上基本有人(prior 0.35)。
   估错了不会坏,只是阈值要跟着重调 —— 所以先估个数跑一周,看误报漏报再改
3. **这些概率是猜的,必须实测校准**。方法:跑一周,在 HA 里把
   `binary_sensor.ph_living_occupied` 和实际情况对照,数误报和漏报各几次,再调

### 5.2 光环境 · `sensor.ph_light_context`

三态:`明亮` / `昏暗` / `夜`

以窗边照度为准(它测的是自然光),不用室内照度 —— 室内照度包含了自己开的灯,又是一个正反馈。

| 状态 | 判据 |
|---|---|
| 夜 | 太阳在地平线下 **且** 窗边照度 < 5 lx |
| 昏暗 | 窗边照度 < 150 lx(阴天、黄昏、清晨) |
| 明亮 | 其余 |

**必须带迟滞。** 照度在阈值附近抖动(云飘过)会让灯一闪一闪,这是原则三里"失败要静默"
的反面教材。HA 的 template 实体里可以用 `this.state` 读到自己上一次的状态,
用它做迟滞是正规做法:

```yaml
  - sensor:
      - name: "光环境"
        unique_id: ph_light_context
        state: >
          {% set lux = states('sensor.node_window_lux_tcs34725') | float(-1) %}
          {% set prev = this.state if this is defined else '明亮' %}
          {% if lux < 0 %}{{ prev }}
          {% elif is_state('sun.sun','below_horizon') and lux < 5 %}夜
          {# 迟滞:从"昏暗"回到"明亮"要 200lx,从"明亮"掉到"昏暗"才 150lx #}
          {% elif lux < 150 %}昏暗
          {% elif lux < 200 and prev == '昏暗' %}昏暗
          {% else %}明亮{% endif %}
```

> 传感器读不到数(`lux < 0`)时**保持上一个状态**,不要 fallback 到某个默认值。
> 传感器掉线时让房子维持现状,比让它突然以为天黑了要安全 —— 这是原则三。

### 5.3 空气 · `sensor.ph_<room>_air` 与 `sensor.ph_air_worst`

三态:`好` / `该通风` / `闷`

| 状态 | CO2 | 迟滞 |
|---|---|---|
| 好 | < 800 | 从"该通风"降回来要 < 750 |
| 该通风 | 800–1500 | |
| 闷 | > 1500 | 降回"该通风"要 < 1400 |

已写好的 `pendinghome_co2_ventilation.yaml` 里的 1400 迟滞就是这个,搬进语义层即可。

`sensor.ph_air_worst` 取两个房间里较差的那个,自动化盯它。
**窗边不参与**(见 4.2)。

### 5.4 家状态 · `input_select.ph_home_mode`

四态:`在家` / `离家` / `睡觉` / `访客`

这个和上面三个不一样 —— 它是 **`input_select` 而不是 template sensor**,因为:

- 人必须能**手动改**它(要出门了、有客人来了),而 template sensor 是只读的
- 它的推导带时间和序列(不是当前证据的纯函数),template sensor 表达不了

自动化去推它,但人的手动设置优先(原则二):

| 转换 | 条件 |
|---|---|
| → 离家 | 所有房间空置 > 15 分钟 |
| → 在家 | 任一房间转为有人 |
| → 睡觉 | 卧室有人 **且** 客厅空置 > 20 分钟 **且** 22:00–07:00 **且** 卧室灯关着 |
| → 在家 | 从"睡觉"转出:卧室有人活动 **且** 时间 > 06:00 |
| 访客 | **只能人手动设**。设了之后所有"自动关灯/自动进入睡觉"全部停用 |

> `离家` 判据里**故意没有用手机 device_tracker**。以后要加很容易,
> 但先只靠存在传感器跑一段时间 —— 手机定位漂移会造成"人在家却判离家"的误动作,
> 而这类误动作正好是最烦人的那种。

### 5.5 全部语义实体一览

| 实体 | 类型 | 取值 |
|---|---|---|
| `binary_sensor.ph_living_occupied` | template + delay_off | on/off |
| `binary_sensor.ph_bedroom_occupied` | 同上 | on/off |
| `sensor.ph_living_occupancy` | template | 有人活动/有人静止/空置 |
| `sensor.ph_bedroom_occupancy` | template | 同上 |
| `sensor.ph_light_context` | template(带迟滞) | 明亮/昏暗/夜 |
| `sensor.ph_living_air` / `ph_bedroom_air` | template(带迟滞) | 好/该通风/闷 |
| `sensor.ph_air_worst` | template | 同上 |
| `input_select.ph_home_mode` | input_select | 在家/离家/睡觉/访客 |

---

## 6. 手动优先怎么实现(原则二)

每个可被自动化操作的区域配一个"人工接管"标志:

```yaml
input_boolean:
  ph_living_manual_hold:
    name: "客厅 · 人工接管中"
```

- **置位**:自动化监听灯的 `state` 变化,凡是 `context.user_id` 不为空的(= 人在 UI/开关上操作的),
  就把 hold 打开。`context` 能区分"人改的"和"自动化改的",这是关键
- **复位**:两小时后,或该区域转为 `空置`,以先到者为准
- **所有会动灯的自动化都加一条 `condition: state ph_living_manual_hold == off`**

日光同步那条自动化的门闩(`input_boolean.ph_daylight_latch`)是同一个模式,
只不过它防的是传感器正反馈而不是人机冲突。两者并存,互不替代。

---

## 7. 安装位置

| 传感器 | 位置要求 | 为什么 |
|---|---|---|
| **LD2410C** | 挂墙 **1.5–2m** 高,俯视覆盖活动区(沙发、床) | 太低看不全,太高近处有盲区 |
| | **别正对窗** | 会看见窗外走过的人 |
| | 别对着门口朝外 | 会看见走廊里路过的人 |
| | 避开与邻室共用的墙 | 毫米波穿墙 |
| | 别对着风扇、飘动的窗帘、鱼缸 | 周期性运动会被当成人 |
| **PIR (AM312)** | 和 LD2410 同侧,朝向门口方向 | 它的强项是"刚进门那一下" |
| | 避开空调出风口、阳光直射 | PIR 测红外,热气流会误触发 |
| **SCD41** | **呼吸高度**(坐姿 1.1m / 卧姿齐床面) | 测的应该是人吸的那层空气 |
| | 避开空调直吹、门口、窗口 | 直吹会读到室外值,不是房间状态 |
| | 离 MCU 和电源发热处远一点 | 温度偏了 CO2 跟着偏 |
| | 卧室的别贴脸(离床 1–2m) | 直接吹到呼气会读出假高值 |
| **TCS34725** | 室内朝窗,加乳白漫射片 | 要测的就是"照进屋里的光" |
| | **别直视太阳** | 饱和之后色温就废了 |
| | **别让它照到自己控制的灯** | 正反馈震荡的根源。软件门闩是兜底,物理遮挡才是正解 |
| **BH1750** | 朝上或朝房间中央,别朝灯 | 同上,别测到自己开的灯 |
| **门磁** | 磁铁在窗扇、簧管在窗框,间隙 < 15mm | 太远关窗也判开 |

---

## 8. 引脚分配(ESP32-C3 SuperMini)

避开 GPIO2 / GPIO8 / GPIO9(strapping,GPIO8 还接着板载 LED)。

### node-living / node-bedroom

| GPIO | 接什么 |
|---|---|
| GPIO6 | I2C **SDA** — SCD41(0x62) + BH1750(0x23) |
| GPIO7 | I2C **SCL** — 同上 |
| GPIO21 | UART **TX** → LD2410C 的 RX |
| GPIO20 | UART **RX** ← LD2410C 的 TX |
| GPIO3 | PIR OUT |
| 5V | SCD41 VIN(模块自带稳压) |
| 3V3 | BH1750、PIR、LD2410C(**确认你买的版本是不是 3.3V 供电**) |

**LD2410C 的 UART 参数是硬性的**:`baud_rate: 256000`,`parity: NONE`,`stop_bits: 1`
(ESPHome 的 `ld2410` 组件对后两项有强制要求)。`cct-driver/firmware/cct-driver.yaml`
底部那段注释掉的 UART 配置正好是这个参数,可以直接抄。

> GPIO20/21 是芯片 UART0 的默认脚,板子丝印也写着 RX/TX,接线最直观。
> 代价:上电瞬间 ROM 引导日志会从 GPIO21 吐出去,LD2410 会收到 200ms 垃圾 —— 无害。
> 固件里 logger 已经设成 `USB_SERIAL_JTAG`,不会持续占用这两个脚。
> 实在介意就换 GPIO10/GPIO5,C3 的 UART 可以映射到任意 GPIO。

### node-window

| GPIO | 接什么 |
|---|---|
| GPIO6 | I2C **SDA** — TCS34725(0x29) |
| GPIO7 | I2C **SCL** |
| GPIO4 | TCS34725 模块的 `LED` 脚(常关,见固件 README) |
| GPIO3 | 门磁(另一根线接 GND) |

I2C 脚沿用已写固件的 GPIO6/7,换 MCU 不用改 `common/i2c.yaml`。

**供电**:SCD41 测量瞬间约 205mA,和 WiFi 发射峰值撞上会把板子拖复位。
模块走 **5V 脚**,并在模块电源脚并一颗 100–470µF 电解电容。

---

## 9. 采购增量

以 `sensor-nodes/purchase-list.md` 为基准。

### 减

| 项 | 数量变化 | 金额 |
|---|---|---|
| XIAO ESP32-C3 → ESP32-C3 SuperMini | ×3,¥35 → ¥10 | **−¥75** |
| SCD41 | ×3 → ×2(窗边不装) | **−¥70** |
| AS7341 | ×1 → ×0 | **−¥70** |
| | | **小计 −¥215** |

### 加

| 项 | 规格 | 数量 | 单价估 | 小计 |
|---|---|---|---|---|
| LD2410C 毫米波 | UART 版,确认供电电压 | 2 | ¥30 | ¥60 |
| PIR | **AM312**(3.3V 原生,小体积) | 2 | ¥4 | ¥8 |
| BH1750 | GY-302 等 | 2 | ¥8 | ¥16 |
| | | | | **小计 +¥84** |

> PIR 别买 HC-SR501:5V 供电、体积大、还带两个容易被碰到的电位器。AM312 更适合常电小节点。

### 新总价

| | 金额 |
|---|---|
| 原方案(AS7341 + TCS34725) | ¥518 |
| 增减 | −¥215 + ¥84 = **−¥131** |
| **新方案合计** | **约 ¥387** |
| 其中 USB 充电头 ¥36 + 数据线 ¥24 若用手头闲置 | **约 ¥327** |

传感器本身(SCD41×2 + TCS34725 + LD2410C×2 + PIR×2 + BH1750×2 + 门磁)约 ¥252,
MCU ¥30,其余是供电和面包板台面。

**Zigbee 侧另算,不在此表**:烟感、水浸探头/水浸绳买成品。协调器已有。

---

## 10. 相对已写代码的差异(⚠️ 未执行)

`sensor-nodes/firmware/` 和 `ha-t630/homeassistant/config/` 里的东西**一行都没改**。
点头之后要做的:

### 固件

| 文件 | 改什么 |
|---|---|
| `common/base.yaml` | `board:` 从 `seeed_xiao_esp32c3` 改成 `esp32-c3-devkitm-1`(SuperMini 没有专属板型定义,通用 C3 板型即可);`logger` 的 `USB_SERIAL_JTAG` 保持不变,SuperMini 同样是原生 USB |
| `node-window.yaml` | 移除 `scd41` 和 `as7341` 两个包 |
| `node-living.yaml` / `node-bedroom.yaml` | 增加 `ld2410`、`pir`、`bh1750` 三个新包 |
| `common/as7341.yaml` | **保留不删**(见 4.3),只是暂时没有节点引用它 |
| 新建 `common/ld2410.yaml` | 存在/移动/静止 + 距离能量 + 距离门 number 实体 + 关蓝牙 |
| 新建 `common/pir.yaml` | GPIO3 binary_sensor,`device_class: motion` |
| 新建 `common/bh1750.yaml` | 0x23,照度 |

### HA

| 文件 | 改什么 |
|---|---|
| `pendinghome_co2_ventilation.yaml` | `sensor.ph_co2_max` 去掉 `sensor.node_window_co2`(窗边不再有 CO2) |
| 新建 `pendinghome_states.yaml` | 第 5 节的全部语义实体 |
| 新建 `pendinghome_manual_hold.yaml` | 第 6 节的人工接管 |
| `pendinghome_daylight_cct.yaml` | 加一条 `ph_living_manual_hold == off` 的条件 |
| 各自动化 | 触发/条件从原始实体改读语义实体 |

**建议的落地顺序**(不要一次全上):

1. 先只上**原始层**:三个节点刷好,所有实体在 HA 里能看到数。**什么自动化都不做**
2. 跑一周,期间只做一件事:**调 LD2410 的距离门**,把误报调掉
3. 上**语义层**,但仍然不接自动化。再看几天 `占用` / `光环境` 状态跳得对不对
4. 语义层稳了,才开始一条一条接自动化。从最"删掉动作"的那条开始(进屋灯亮)

理由是原则三:直接全上的话,某个自动化误动作时,你分不清是传感器、语义推导还是自动化的锅。

---

## 11. 未决与已知风险

| 事项 | 状态 |
|---|---|
| SuperMini 天线弱 | **最大的单点风险**。到货先在三个安装位测 RSSI,不行就退回 XIAO |
| LD2410 穿墙误报 | 已知会发生。靠位置 + 距离门调。调不掉的话得加物理遮挡(金属背板) |
| Bayesian 那几个概率 | 全是估的,必须跑一周实测校准 |
| TCS34725 的单调性 | 4.3 的整个论证压在"重复性和单调性够好"上。实测若不成立,换 AS7341(配置已在仓库里) |
| CO2 阈值 800/1500 | 通用值,不是你家实测值。跑一周看卧室夜间实际能到多少再定 |
| 色温 → 灯带色温的映射曲线 | **还完全没有**。这是原型期最主要的产出,必须实测 |
| 房间数 | 现在按客厅+卧室两个占用区设计。以后加房间,语义层照抄一份即可 |

---

## 附:参考

- [ESPHome `ld2410`](https://esphome.io/components/sensor/ld2410.html)
- [ESPHome `bh1750`](https://esphome.io/components/sensor/bh1750.html)
- [ESPHome `tcs34725`](https://esphome.io/components/sensor/tcs34725.html)
- [ESPHome `scd4x`](https://esphome.io/components/sensor/scd4x.html)
- [HA Bayesian binary sensor](https://www.home-assistant.io/integrations/bayesian/)
- [HA Derivative 集成](https://www.home-assistant.io/integrations/derivative/)(CO2 变化率)
- [HA Template 实体中的 `this`](https://www.home-assistant.io/integrations/template/#self-referencing)(做迟滞用)
- 采购基准:`sensor-nodes/purchase-list.md`
- 已写固件:`sensor-nodes/firmware/README.md`
