# 6 路 CCT 灯带驱动板 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一块可下单生产的 6 路 CCT(12 路 PWM)24V LED 驱动板 —— 完整原理图、PCB、BOM,以及经 `esphome config` 验证的固件配置。

**Architecture:** ESP32-WROOM-32E 的 12 路 LEDC PWM → 2× 74HCT245 电平转换(3.3→5V)→ 12× 60V 逻辑电平 NMOS 低边斩灯带负极。主回路 15A 连续承载能力、12A 运行预算,由 INA237 高边监测 + 固件软限流约束;硬保护为 15A 主保险丝 + 每路 4A 慢断可更换保险丝。用户零焊接:插件件由嘉立创代焊。

**Tech Stack:** 嘉立创EDA 专业版(已安装于 `/Applications/嘉立创EDA(专业版).app`)、嘉立创经济型 SMT、ESPHome(esp-idf 框架)、Home Assistant。

**设计依据:** [设计文档 v7](../specs/2026-07-29-led-cct-driver-design.md) —— 本计划中所有元件型号、C 编号、电路细节均以该文档为准,冲突时以设计文档为准。

## Global Constraints

以下为项目级约束,**每个任务都隐含包含**:

- **所有元件(贴片 + 插件)必须布置在顶层单面** —— 嘉立创经济型 SMT 仅支持单面焊接。背面只做覆铜与走线。
- **Type-C 必须选普通贴板式,不可用沉板式** —— 经济型不支持沉板/夹板结构。
- **铜厚 1oz**;主电流脊椎按 **15A 连续**设计,正常运行预算 **≤12A @ 24V**。
- **扩展库元件种类 ≤11 种** —— 官方限制"单次订单通常 10~13 种",超出可能被要求拆单或转标准型。每新增一种扩展库料需从别处砍掉一种。
- **PWM 频率 19531Hz,12-bit 分辨率**(LEDC 在该频率下的分辨率上限)。
- **GPIO 分配锁定**,不得更改:PWM ×12 = GPIO 4/5/13/14/16/17/18/19/21/22/23/25;I2C = 32(SDA)/33(SCL);UART2 = 26(TX)/27(RX);干接点 = 34/35/36/39;/OE 控制 = 15;UART0 = 1/3;状态 LED = 2;BOOT = 0。
- **strapping 脚 GPIO 0/2/12/15 不承担 PWM 或总线职能**;GPIO12 全程悬空不接。
- **单位与命名**:原理图位号用 `功能前缀+序号`(见各任务);网络名全大写下划线(如 `V24_BUS`、`CH1_CW_G`)。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `firmware/cct-driver.yaml` | ESPHome 主配置:12 路 PWM、6 个 cwww 灯、INA237、干接点、/OE 时序 |
| `firmware/secrets.yaml.example` | WiFi/API 密钥模板(真实 `secrets.yaml` 不入库) |
| `hardware/netlist-spec.md` | 原理图网表规格书 —— 逐块列出位号、C 编号、连接关系,绘图与核验的唯一依据 |
| `hardware/bom-jlc.csv` | 嘉立创 SMT 下单用 BOM(Comment/Designator/Footprint/LCSC) |
| `hardware/layout-guide.md` | PCB 布局指导:分区、走线宽度、禁铜区、测试点位置 |
| `hardware/order-checklist.md` | 下单前逐项确认清单 |
| `cct-driver.epro` | 嘉立创EDA 工程(二进制,由 EDA 生成) |

---

## Task 1: ESPHome 骨架与 12 路 PWM 输出

**Files:**
- Create: `firmware/cct-driver.yaml`
- Create: `firmware/secrets.yaml.example`
- Create: `firmware/.gitignore`

**Interfaces:**
- Produces: 12 个 `output` id —— `pwm_ch1_cw` `pwm_ch1_ww` … `pwm_ch6_cw` `pwm_ch6_ww`(后续任务的灯与限流逻辑依赖这些 id)
- Produces: `switch` id `hct245_enable`(Task 2 的上电时序依赖)

- [x] **Step 1: 建立 venv 并确认 esphome 可用**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver
python3 -m venv .venv
./.venv/bin/pip install -q esphome
./.venv/bin/esphome version
```

预期:输出版本号。**本计划的 YAML 已在 esphome 2025.5.2 上实测通过 `esphome config`**,若你的版本更新出现差异,以官方文档为准。

- [x] **Step 2: 写 secrets 模板与 gitignore**

`firmware/secrets.yaml.example`:
```yaml
wifi_ssid: "YOUR_SSID"
wifi_password: "YOUR_PASSWORD"
api_encryption_key: "GENERATE_WITH_openssl_rand_-base64_32"
ota_password: "YOUR_OTA_PASSWORD"
```

`firmware/.gitignore`:
```
secrets.yaml
.esphome/
```

- [x] **Step 3: 写主配置的骨架 + 12 路 ledc 输出**

`firmware/cct-driver.yaml`:
```yaml
substitutions:
  device_name: "cct-driver-01"
  friendly_name: "CCT 驱动板 01"
  pwm_frequency: "19531Hz"

esphome:
  name: ${device_name}
  friendly_name: ${friendly_name}

esp32:
  board: esp32dev
  framework:
    type: esp-idf

logger:
  level: INFO

api:
  encryption:
    key: !secret api_encryption_key

ota:
  - platform: esphome
    password: !secret ota_password

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:
    ssid: "${device_name} Fallback"

captive_portal:

# ---- HCT245 输出使能 ----
# GPIO15 高 -> NPN 导通 -> /OE 拉低 -> 12 路输出使能
# 上电默认 OFF:硬件上 /OE 被 10k 上拉到 5V,输出高阻,灯带不亮
switch:
  - platform: gpio
    id: hct245_enable
    pin: GPIO15
    restore_mode: ALWAYS_OFF
    internal: true

# ---- 12 路 PWM ----
# CW/WW 成对相位错开 180°,降低总线纹波峰值
output:
  - platform: ledc
    id: pwm_ch1_cw
    pin: GPIO4
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch1_ww
    pin: GPIO5
    frequency: ${pwm_frequency}
    phase_angle: 180deg
  - platform: ledc
    id: pwm_ch2_cw
    pin: GPIO13
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch2_ww
    pin: GPIO14
    frequency: ${pwm_frequency}
    phase_angle: 180deg
  - platform: ledc
    id: pwm_ch3_cw
    pin: GPIO16
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch3_ww
    pin: GPIO17
    frequency: ${pwm_frequency}
    phase_angle: 180deg
  - platform: ledc
    id: pwm_ch4_cw
    pin: GPIO18
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch4_ww
    pin: GPIO19
    frequency: ${pwm_frequency}
    phase_angle: 180deg
  - platform: ledc
    id: pwm_ch5_cw
    pin: GPIO21
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch5_ww
    pin: GPIO22
    frequency: ${pwm_frequency}
    phase_angle: 180deg
  - platform: ledc
    id: pwm_ch6_cw
    pin: GPIO23
    frequency: ${pwm_frequency}
    phase_angle: 0deg
  - platform: ledc
    id: pwm_ch6_ww
    pin: GPIO25
    frequency: ${pwm_frequency}
    phase_angle: 180deg
```

- [x] **Step 4: 验证配置能通过**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver/firmware
cp secrets.yaml.example secrets.yaml
sed -i '' 's|GENERATE_WITH_openssl_rand_-base64_32|'"$(openssl rand -base64 32)"'|' secrets.yaml
../.venv/bin/esphome config cct-driver.yaml
```

预期:输出完整展开的配置,末尾打印 `INFO Configuration is valid!`。

> `ledc` 的 `phase_angle` 已在 **esphome 2025.5.2 实测支持**。若你的版本报错不认此项,删除全部 `phase_angle` 行并在文件顶部注释记录原因,重跑本步。

- [x] **Step 5: 提交**

```bash
git add firmware/cct-driver.yaml firmware/secrets.yaml.example firmware/.gitignore
git commit -m "feat(fw): ESPHome skeleton with 12 LEDC PWM outputs"
```

---

## Task 2: 6 个 CCT 灯实体 + 上电时序

**Files:**
- Modify: `firmware/cct-driver.yaml`

**Interfaces:**
- Consumes: Task 1 的 12 个 `output` id、`hct245_enable`
- Produces: 6 个 `light` id —— `light_ch1` … `light_ch6`(Task 3 的限流逻辑依赖)

- [x] **Step 1: 追加 6 个 cwww 灯**

在 `output:` 段之后追加。`constant_brightness: true` 保证 CW+WW 合计 duty ≤100%,使每条灯带平均电流不超过单通道满载值。

```yaml
light:
  - platform: cwww
    id: light_ch1
    name: "通道 1"
    cold_white: pwm_ch1_cw
    warm_white: pwm_ch1_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
  - platform: cwww
    id: light_ch2
    name: "通道 2"
    cold_white: pwm_ch2_cw
    warm_white: pwm_ch2_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
  - platform: cwww
    id: light_ch3
    name: "通道 3"
    cold_white: pwm_ch3_cw
    warm_white: pwm_ch3_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
  - platform: cwww
    id: light_ch4
    name: "通道 4"
    cold_white: pwm_ch4_cw
    warm_white: pwm_ch4_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
  - platform: cwww
    id: light_ch5
    name: "通道 5"
    cold_white: pwm_ch5_cw
    warm_white: pwm_ch5_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
  - platform: cwww
    id: light_ch6
    name: "通道 6"
    cold_white: pwm_ch6_cw
    warm_white: pwm_ch6_ww
    cold_white_color_temperature: 6500 K
    warm_white_color_temperature: 2700 K
    constant_brightness: true
    gamma_correct: 2.2
    default_transition_length: 500ms
    restore_mode: RESTORE_DEFAULT_OFF
```

> **`restore_mode` 是待用户确认项**(设计文档 v7 头部):`RESTORE_DEFAULT_OFF` = 恢复断电前状态、无记录时关;若用户选择"来电一律不亮",全部改为 `ALWAYS_OFF`。

- [x] **Step 2: 追加上电时序**

在 `esphome:` 段内追加 `on_boot`。优先级 `-100` 在所有组件(含 light 状态恢复)之后执行,保证使能 /OE 时 PWM 已是正确值,不会出现上电闪光。

```yaml
esphome:
  name: ${device_name}
  friendly_name: ${friendly_name}
  on_boot:
    - priority: -100
      then:
        - logger.log: "所有 PWM 已初始化,使能 HCT245 输出"
        - switch.turn_on: hct245_enable
```

- [x] **Step 3: 验证**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver/firmware
../.venv/bin/esphome config cct-driver.yaml | grep -E "^(light|switch|output):" -A2
```

预期:能看到 6 个 light、1 个 switch、12 个 output,且无 ERROR。

- [x] **Step 4: 提交**

```bash
git add firmware/cct-driver.yaml
git commit -m "feat(fw): 6 CCT light entities and power-on enable sequence"
```

---

## Task 3: INA237 监测与软限流

**Files:**
- Modify: `firmware/cct-driver.yaml`

**Interfaces:**
- Consumes: Task 1 的 12 个 output id、`hct245_enable`
- Produces: sensor id `bus_current`、`bus_power`;global `power_scale`

**背景:** 设计文档 §3 —— 6 条灯带理论峰值 17.5A 超过 12A 运行预算,需固件按实测电流动态降额。**此为运行管理,不是安全保护**;短路由硬件保险丝承担。

- [x] **Step 1: 追加 I2C 与 INA237**

```yaml
i2c:
  sda: GPIO32
  scl: GPIO33
  frequency: 100kHz
  scan: true

sensor:
  - platform: ina2xx_i2c
    model: INA237
    address: 0x40
    shunt_resistance: 0.002 ohm
    max_current: 20 A
    adc_range: 1        # ±40.96mV 档 -> 2mΩ 下满量程 20.48A
    update_interval: 1s
    current:
      name: "总电流"
      id: bus_current
      accuracy_decimals: 2
    power:
      name: "总功率"
      id: bus_power
      accuracy_decimals: 1
    bus_voltage:
      name: "母线电压"
      id: bus_voltage
      accuracy_decimals: 2

  - platform: wifi_signal
    name: "WiFi 信号"
    update_interval: 60s
```

- [x] **Step 2: 追加限流逻辑**

`set_max_power()` 直接缩放 PWM 输出上限,不改变灯在 HA 中上报的亮度 —— 这正是保护限幅该有的行为。

```yaml
globals:
  - id: power_scale
    type: float
    restore_value: false
    initial_value: '1.0'
  - id: ina_fault_count
    type: int
    restore_value: false
    initial_value: '0'

script:
  - id: apply_power_scale
    mode: single
    then:
      - lambda: |-
          float s = id(power_scale);
          id(pwm_ch1_cw).set_max_power(s);
          id(pwm_ch1_ww).set_max_power(s);
          id(pwm_ch2_cw).set_max_power(s);
          id(pwm_ch2_ww).set_max_power(s);
          id(pwm_ch3_cw).set_max_power(s);
          id(pwm_ch3_ww).set_max_power(s);
          id(pwm_ch4_cw).set_max_power(s);
          id(pwm_ch4_ww).set_max_power(s);
          id(pwm_ch5_cw).set_max_power(s);
          id(pwm_ch5_ww).set_max_power(s);
          id(pwm_ch6_cw).set_max_power(s);
          id(pwm_ch6_ww).set_max_power(s);

interval:
  - interval: 1s
    then:
      - lambda: |-
          float i = id(bus_current).state;

          // INA237 读数异常:连续 5 次 NaN 则切断输出
          if (isnan(i)) {
            id(ina_fault_count) += 1;
            if (id(ina_fault_count) >= 5) {
              ESP_LOGE("guard", "INA237 连续 5 次读数无效,切断输出");
              id(hct245_enable).turn_off();
            }
            return;
          }
          id(ina_fault_count) = 0;

          float s = id(power_scale);
          if (i > 12.0f) {
            s -= 0.05f;              // 超预算:每秒降 5%
            if (s < 0.30f) s = 0.30f;
          } else if (i < 11.0f && s < 1.0f) {
            s += 0.02f;              // 回落:每秒恢复 2%,带 1A 迟滞避免振荡
            if (s > 1.0f) s = 1.0f;
          } else {
            return;                  // 在 11~12A 死区内不动作
          }
          id(power_scale) = s;
          ESP_LOGW("guard", "总电流 %.2fA,输出限幅至 %.0f%%", i, s * 100.0f);
      - script.execute: apply_power_scale
```

- [x] **Step 3: 验证**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver/firmware
../.venv/bin/esphome config cct-driver.yaml > /tmp/cfg.txt && echo "CONFIG OK" && grep -c "ledc" /tmp/cfg.txt
```

预期:打印 `CONFIG OK`。

> **已实测(esphome 2025.5.2)**:`platform: ina2xx_i2c` + `model: INA237` + `adc_range: 1` + `shunt_resistance: 0.002 ohm` 通过校验。
> **已实测**:C++ 侧 `esphome::output::FloatOutput::set_max_power(float)` 确实存在(`components/output/float_output.h:39`),故 Step 2 的 lambda 限流机制成立。
> 注意 `esphome config` 只做配置校验,**不编译 lambda**。首次 `esphome compile` 时若报 `set_max_power` 未定义,改用 `id(x)->set_level(...)` 直接写占空比,并相应调整逻辑。

- [x] **Step 4: 提交**

```bash
git add firmware/cct-driver.yaml
git commit -m "feat(fw): INA237 monitoring with dynamic current limiting"
```

---

## Task 4: 干接点输入与本地控制

**Files:**
- Modify: `firmware/cct-driver.yaml`

**Interfaces:**
- Consumes: Task 2 的 6 个 light id

**背景:** 设计文档 §9 —— 墙壁开关联动必须是**板内本地自动化**,WiFi/HA 挂掉时物理开关仍可控灯。

- [x] **Step 1: 追加 4 路干接点**

GPIO34/35/36/39 为纯输入脚,**内部无上拉**,依赖板上 10k 外部上拉;`delayed_on` 兜底 GPIO36/39 的 errata 毛刺。

```yaml
binary_sensor:
  - platform: gpio
    id: sw1
    name: "墙壁开关 1"
    pin:
      number: GPIO34
      inverted: true      # 闭合接地 -> 逻辑真
    filters:
      - delayed_on: 30ms
      - delayed_off: 30ms
    on_click:
      - min_length: 20ms
        max_length: 500ms
        then:
          - light.toggle: light_ch1
    on_press:
      - delay: 1s
      - while:
          condition:
            binary_sensor.is_on: sw1
          then:
            - light.dim_relative:
                id: light_ch1
                relative_brightness: 5%
            - delay: 200ms

  - platform: gpio
    id: sw2
    name: "墙壁开关 2"
    pin:
      number: GPIO35
      inverted: true
    filters:
      - delayed_on: 30ms
      - delayed_off: 30ms
    on_click:
      - min_length: 20ms
        max_length: 500ms
        then:
          - light.toggle: light_ch2

  - platform: gpio
    id: sw3
    name: "墙壁开关 3"
    pin:
      number: GPIO36
      inverted: true
    filters:
      - delayed_on: 30ms
      - delayed_off: 30ms
    on_click:
      - min_length: 20ms
        max_length: 500ms
        then:
          - light.toggle: light_ch3

  - platform: gpio
    id: sw4
    name: "墙壁开关 4"
    pin:
      number: GPIO39
      inverted: true
    filters:
      - delayed_on: 30ms
      - delayed_off: 30ms
    on_click:
      - min_length: 20ms
        max_length: 500ms
        then:
          - light.toggle: light_ch4
```

- [x] **Step 2: 追加状态灯**

```yaml
  - platform: status
    name: "运行状态"

light:
  - platform: status_led
    id: status_light
    pin: GPIO2
    internal: true
```

> 注意:`- platform: status` 属于 `binary_sensor:` 段(接在上一步的 sw4 之后),`status_led` 属于 `light:` 段(接在 6 个 cwww 灯之后)。合并时保持段落唯一。

- [x] **Step 3: 验证**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver/firmware
../.venv/bin/esphome config cct-driver.yaml > /dev/null && echo "CONFIG OK"
```

预期:`CONFIG OK`。若 `light:` 或 `binary_sensor:` 段重复定义会报 YAML 错误,合并到唯一段落后重跑。

- [x] **Step 4: 提交**

```bash
git add firmware/cct-driver.yaml
git commit -m "feat(fw): dry-contact wall switch inputs with local control"
```

### ✅ Task 1–4 实际执行结果(2026-08-02)

固件已合并为单文件 `firmware/cct-driver.yaml`(未按计划拆成 4 次提交,因四部分强耦合于同一文件)。

| 验证 | 命令 | 结果 |
|---|---|---|
| 配置合法性 | `esphome config cct-driver.yaml` | ✅ `INFO Configuration is valid!`,**0 warning** |
| 实体数量 | grep 计数 | ✅ 12× ledc、6× cwww、1× switch |
| **C++ 编译** | `esphome compile cct-driver.yaml` | ✅ **SUCCESS(160s)** —— `set_max_power()` 等 lambda 调用全部合法 |
| 资源占用 | 编译输出 | RAM 10.2%(33.5KB/320KB);Flash 55.2%(0.97MB / 1.75MB OTA 分区) |

**连带确认的 BOM 决策**:ESP32-WROOM-32E-**N4**(4MB)容量充足,OTA 双分区有余量,无需升级 N8。

**发现并修正的问题**:设计文档 §5 原称 PWM 引脚"全非 strapping",实为 **GPIO5 是 strapping 脚**。已在 §5 补充三个被占用 strapping 脚(GPIO5/2/15)的逐一安全性论证,并在固件中显式声明 `ignore_strapping_warning: true` + 理由注释。

**尚未验证(需硬件)**:PWM 实际频率与波形、INA237 通信与读数、上电有无闪光、HA 实体呈现、干接点实际响应。列入收板后的样机测试。

---

## Task 5: 原理图网表规格书 —— 电源输入与保护块

**Files:**
- Create: `hardware/netlist-spec.md`

**Interfaces:**
- Produces: 网络名 `V24_IN`、`V24_PROT`、`V24_BUS`、`GND`;位号 `J1` `F1` `Q1` `Q2` `D1` `C1` `C2` `R1`–`R4` `DZ1` `U1` `RS1` `Q3`

**背景:** 设计文档 §6.2。本块是全板唯一承载 15A 的部分。

- [ ] **Step 1: 写规格书头部与本块网表**

`hardware/netlist-spec.md`:
````markdown
# 原理图网表规格书

本文件是绘制与核验原理图的唯一依据。绘图完成后从嘉立创EDA导出网表,与本文件逐条比对(见 Task 11)。

**约定**
- 网络名全大写下划线;`GND` 为唯一地网络(功率地与信号地单点连接,见 layout-guide)
- 元件位号:`J`=连接器 `F`=保险丝 `Q`=晶体管/MOS `D`=二极管 `C`=电容 `R`=电阻 `L`=电感 `U`=IC `RS`=采样电阻 `DZ`=稳压管 `SW`=按键 `LED`=指示灯 `TP`=测试点
- 所有元件放顶层

---

## Block A:电源输入与保护

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| J1 | KF7.62-2P 输入端子 | C707824 | 1 → `V24_IN`;2 → `GND` |
| F1 | 15A ATO 片式保险丝 + 座 | 待核实 | 1 → `V24_IN`;2 → `V24_FUSED` |
| Q1 | SUD50P06-15 P-MOS 防反接 | 待核实 | S → `V24_FUSED`;D → `V24_PROT`;G → `PMOS_GATE` |
| Q2 | SUD50P06-15(与 Q1 并联) | 待核实 | S → `V24_FUSED`;D → `V24_PROT`;G → `PMOS_GATE` |
| R1 | 100kΩ 0603 | C25803 | 1 → `PMOS_GATE`;2 → `GND` |
| DZ1 | BZT52C12 稳压管 SOD-123 | 待核实 | 阴极 → `V24_FUSED`;阳极 → `PMOS_GATE` |
| Q3 | MMBT3904 NPN(总断路控制) | 待核实 | C → `PMOS_GATE`;E → `GND`;B → `MASTER_OFF_B` |
| R2 | 10kΩ 0603 | C25804 | 1 → `MASTER_OFF_B`;2 → `MCU_MASTER_OFF`(备用,首版接 `GND` 使 Q3 常关) |
| R3 | 100kΩ 0603 | C25803 | 1 → `MASTER_OFF_B`;2 → `GND` |
| D1 | SMBJ26A TVS | C19077580 | 阴极 → `V24_PROT`;阳极 → `GND` |
| C1 | 470µF/50V 电解 | 待核实 | + → `V24_PROT`;− → `GND` |
| C2 | 470µF/50V 电解 | 待核实 | + → `V24_PROT`;− → `GND` |
| RS1 | 2mΩ 2512 采样电阻 | C500614 | 1 → `V24_PROT`;2 → `V24_BUS` |
| U1 | INA237 VSSOP-10 | 待核实 | IN+ → `V24_PROT`(开尔文);IN− → `V24_BUS`(开尔文);VS → `V3P3`;GND → `GND`;SDA → `I2C_SDA`;SCL → `I2C_SCL`;A0 → `GND`;A1 → `GND`;ALERT → NC |
| C3 | 100nF 0603 | C14663 | 1 → `V3P3`;2 → `GND`(U1 去耦,紧贴 VS 脚) |
| TP1 | 测试焊盘 | — | `V24_BUS` |
| TP2 | 测试焊盘 | — | `GND` |

**关键约束**
- Q1/Q2 是 **P-MOS 高边防反**:源极接电源侧、漏极接负载侧,体二极管方向使反接时不导通。栅极经 R1 拉低(相对源极为负 → 导通),DZ1 把 Vgs 钳在 12V 以内(器件 Vgs 上限 ±20V)。
- Q3 导通时把 `PMOS_GATE` 拉到 GND(即 Vgs=0)→ P-MOS 关断 → **切断全部灯带供电**。首版 R2 的另一端接 `GND`(Q3 常关,功能预留焊盘);确认可用后改接一个 MCU GPIO。
- RS1 必须**开尔文接法**:U1 的 IN+/IN− 从采样电阻两端焊盘单独引细线,不得从大电流覆铜上任取一点。
- C1/C2 尽量靠近 J1,抑制上电浪涌与长线感抗。
````

- [ ] **Step 2: 自检本块**

逐条核对下列问题,不通过则修正规格书:
1. `V24_IN` / `V24_FUSED` / `V24_PROT` / `V24_BUS` 四段是否严格串联,没有跳接?
2. 每个元件的每个引脚是否都指定了网络(NC 也要写明)?
3. U1 的 I2C 地址脚 A0/A1 接法是否与 Task 3 的 `address: 0x40` 一致?(A0=GND、A1=GND → 0x40)

- [ ] **Step 3: 提交**

```bash
git add hardware/netlist-spec.md
git commit -m "docs(hw): netlist spec Block A - input power and protection"
```

---

## Task 6: 网表规格书 —— 低压电源链与主控块

**Files:**
- Modify: `hardware/netlist-spec.md`

**Interfaces:**
- Consumes: Block A 的 `V24_PROT`、`GND`、`I2C_SDA`、`I2C_SCL`
- Produces: `V5_SYS`、`V3P3`、`EN`、`IO0`、`U0TXD`、`U0RXD`

**背景:** 设计文档 §6.5 —— buck 与 USB VBUS 各经一颗 SS34 汇入 `V5_SYS` 形成双向隔离;CH340C 用 3.3V 供电。

- [ ] **Step 1: 追加 Block B(低压电源链)**

在 `netlist-spec.md` 末尾追加:
````markdown
## Block B:低压电源链

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| PTC1 | 1A 自恢复保险丝 1812 | 待核实 | 1 → `V24_PROT`;2 → `V24_LOGIC` |
| U2 | TX4144 降压 IC | 待核实 | VIN → `V24_LOGIC`;SW → `SW_NODE`;FB → `FB_5V`;GND → `GND`;EN → `V24_LOGIC` |
| L1 | 33µH ≥2A 一体成型电感 | 待核实 | 1 → `SW_NODE`;2 → `V5_BUCK` |
| D2 | SS34 续流 SMA | C8678 | 阳极 → `GND`;阴极 → `SW_NODE` |
| C4 | 22µF/50V 1210 MLCC | 待核实 | 1 → `V24_LOGIC`;2 → `GND` |
| C5 | 22µF/16V 0805 MLCC | 待核实 | 1 → `V5_BUCK`;2 → `GND` |
| R4 | 上分压电阻(按 TX4144 datasheet 计算,目标 5.25V) | 待核实 | 1 → `V5_BUCK`;2 → `FB_5V` |
| R5 | 下分压电阻(同上) | 待核实 | 1 → `FB_5V`;2 → `GND` |
| D3 | SS34(buck 侧 OR) | C8678 | 阳极 → `V5_BUCK`;阴极 → `V5_SYS` |
| D4 | SS34(USB 侧 OR) | C8678 | 阳极 → `USB_VBUS`;阴极 → `V5_SYS` |
| C6 | 22µF/16V 0805 | 待核实 | 1 → `V5_SYS`;2 → `GND` |
| U3 | AMS1117-3.3 SOT-223 | C6186 | VIN → `V5_SYS`;VOUT → `V3P3`;GND → `GND` |
| C7 | 10µF/25V 0805 | C15850 | 1 → `V3P3`;2 → `GND` |
| C8 | 100nF 0603 | C14663 | 1 → `V3P3`;2 → `GND` |
| TP3 | 测试焊盘 | — | `V5_SYS` |
| TP4 | 测试焊盘 | — | `V3P3` |

**关键约束**
- **D3 与 D4 缺一不可**:只隔离 USB 侧会让 USB 反灌 buck 输出。两颗都装才形成真正的双向隔离 diode-OR。
- TX4144 输出设为 **5.25V**,经 SS34 压降后 `V5_SYS` 落在 4.8~5.1V;样板实测后微调 R4/R5。
- U2 的开关环路(U2-SW → L1 → C5 → GND → U2-GND)必须最小,见 layout-guide。

## Block C:主控与 USB

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| U4 | ESP32-WROOM-32E-N4 | C701341 | 3V3 → `V3P3`;GND → `GND`;EN → `EN`;IO0 → `IO0`;TXD0(IO1) → `U0TXD`;RXD0(IO3) → `U0RXD`;IO2 → `LED_STATUS`;IO4 → `CH1_CW`;IO5 → `CH1_WW`;IO13 → `CH2_CW`;IO14 → `CH2_WW`;IO16 → `CH3_CW`;IO17 → `CH3_WW`;IO18 → `CH4_CW`;IO19 → `CH4_WW`;IO21 → `CH5_CW`;IO22 → `CH5_WW`;IO23 → `CH6_CW`;IO25 → `CH6_WW`;IO26 → `UART2_TX`;IO27 → `UART2_RX`;IO32 → `I2C_SDA`;IO33 → `I2C_SCL`;IO34 → `SW_IN1`;IO35 → `SW_IN2`;IO36 → `SW_IN3`;IO39 → `SW_IN4`;IO15 → `OE_CTRL`;**IO12 → NC(必须悬空)** |
| C9 | 10µF/25V 0805 | C15850 | 1 → `V3P3`;2 → `GND`(紧贴 U4 的 3V3 脚) |
| C10 | 100nF 0603 | C14663 | 1 → `V3P3`;2 → `GND` |
| R6 | 10kΩ 0603 | C25804 | 1 → `V3P3`;2 → `EN` |
| C11 | 10µF/25V 0805 | C15850 | 1 → `EN`;2 → `GND`(上电复位延时) |
| R7 | 10kΩ 0603 | C25804 | 1 → `V3P3`;2 → `IO0` |
| SW1 | 轻触开关 TS-1187A | C318884 | 1 → `IO0`;2 → `GND`(BOOT 键) |
| SW2 | 轻触开关 TS-1187A | C318884 | 1 → `EN`;2 → `GND`(RESET 键) |
| LED1 | 0603 红 | C2286 | 阳极 → `LED_STATUS`;阴极 → `R8` |
| R8 | 1kΩ 0603 | C21190 | 1 → LED1 阴极;2 → `GND` |
| U5 | CH340C SOP-16 | C84681 | VCC → `V3P3`;V3 → `V3P3`;GND → `GND`;UD+ → `USB_DP`;UD− → `USB_DM`;TXD → `U0RXD`;RXD → `U0TXD`;DTR → `DTR`;RTS → `RTS` |
| C12 | 100nF 0603 | C14663 | 1 → `V3P3`;2 → `GND`(U5 去耦) |
| J2 | Type-C 16P **贴板式** | C165948 | VBUS → `USB_VBUS`;GND → `GND`;D+ → `USB_DP`;D− → `USB_DM`;CC1 → `CC1`;CC2 → `CC2`;SBU/其余 → NC;外壳 → `GND` |
| R9 | 5.1kΩ 0603 | 待核实 | 1 → `CC1`;2 → `GND` |
| R10 | 5.1kΩ 0603 | 待核实 | 1 → `CC2`;2 → `GND` |
| Q4 | S8050 SOT-23 | C2146 | B → `RTS_B`;C → `EN`;E → `GND` |
| Q5 | S8050 SOT-23 | C2146 | B → `DTR_B`;C → `IO0`;E → `GND` |
| R11 | 10kΩ 0603 | C25804 | 1 → `DTR`;2 → `RTS_B` |
| R12 | 10kΩ 0603 | C25804 | 1 → `RTS`;2 → `DTR_B` |

**关键约束**
- **CH340C 必须用 3.3V 供电**(VCC 与 V3 都接 `V3P3`),否则 TXD 输出 5V 电平直接打进 ESP32 的 3.3V 引脚。
- **CC1/CC2 各一颗 5.1k 下拉必装** —— 缺了会导致 C-to-C 线不供电,是开源板高频翻车点。
- **IO12 必须悬空**:上电被拉高会令 ESP32 按 1.8V flash 电压启动,板子无法开机。
- 自动下载电路的交叉接法(DTR→Q4 控制 EN、RTS→Q5 控制 IO0)是标准 esptool 时序,不可对调。
````

- [ ] **Step 2: 自检**

1. Block C 中 12 个 PWM 网络名(`CH1_CW`…`CH6_WW`)与 Task 1 YAML 的 GPIO 分配是否逐一对应?
2. `IO12` 是否明确标注 NC?
3. CH340C 的 TXD/RXD 与 ESP32 的 U0RXD/U0TXD 是否**交叉**(TXD→U0RXD)?

- [ ] **Step 3: 提交**

```bash
git add hardware/netlist-spec.md
git commit -m "docs(hw): netlist spec Blocks B and C - LDO chain and MCU"
```

---

## Task 7: 网表规格书 —— 电平转换与功率级

**Files:**
- Modify: `hardware/netlist-spec.md`

**Interfaces:**
- Consumes: Block C 的 `CH1_CW`…`CH6_WW`、`OE_CTRL`、`V5_SYS`
- Produces: `CHn_CW_G`/`CHn_WW_G`(栅极网络)、`CHn_VOUT`

**背景:** 设计文档 §6.1、§6.3。

- [ ] **Step 1: 追加 Block D(电平转换)**

````markdown
## Block D:电平转换与 /OE 控制

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| U6 | 74HCT245PW TSSOP-20 | C52140501 | VCC → `V5_SYS`;GND → `GND`;DIR → `V5_SYS`(A→B 方向固定);/OE → `OE_N`;A1..A8 → `CH1_CW`,`CH1_WW`,`CH2_CW`,`CH2_WW`,`CH3_CW`,`CH3_WW`,`CH4_CW`,`CH4_WW`;B1..B8 → `CH1_CW_G`,`CH1_WW_G`,`CH2_CW_G`,`CH2_WW_G`,`CH3_CW_G`,`CH3_WW_G`,`CH4_CW_G`,`CH4_WW_G` |
| U7 | 74HCT245PW TSSOP-20 | C52140501 | VCC → `V5_SYS`;GND → `GND`;DIR → `V5_SYS`;/OE → `OE_N`;A1..A4 → `CH5_CW`,`CH5_WW`,`CH6_CW`,`CH6_WW`;A5..A8 → `GND`;B1..B4 → `CH5_CW_G`,`CH5_WW_G`,`CH6_CW_G`,`CH6_WW_G`;B5..B8 → NC |
| C13 | 100nF 0603 | C14663 | 1 → `V5_SYS`;2 → `GND`(U6 去耦) |
| C14 | 100nF 0603 | C14663 | 1 → `V5_SYS`;2 → `GND`(U7 去耦) |
| R13 | 10kΩ 0603 | C25804 | 1 → `V5_SYS`;2 → `OE_N` |
| Q6 | MMBT3904 NPN | 待核实 | C → `OE_N`;E → `GND`;B → `OE_B` |
| R14 | 10kΩ 0603 | C25804 | 1 → `OE_CTRL`;2 → `OE_B` |
| R15 | 100kΩ 0603 | C25803 | 1 → `OE_B`;2 → `GND` |

**关键约束(这是全板最容易出错的地方)**
- **`OE_CTRL`(GPIO15)绝对不可直接连到 `OE_N`** —— `OE_N` 被 R13 上拉到 5V,而 GPIO15 是 3.3V 引脚(绝对最大 3.6V),直连会通过 ESD 二极管持续灌流损坏引脚。必须经 Q6 隔离。
- 行为验证表:

  | 状态 | Q6 基极 | Q6 | `OE_N` | 12 路输出 |
  |---|---|---|---|---|
  | ESP32 未上电 | R15 拉低 | 关断 | 5V(高) | **高阻** |
  | 5V 已起、3.3V 未起 | 同上 | 关断 | 高 | **高阻** |
  | 启动中 GPIO15 未定义 | R15 保持低 | 关断 | 高 | **高阻** |
  | 固件拉高 GPIO15 | 高 | 导通 | 低 | 使能 |
  | **看门狗复位/崩溃** | GPIO15 转高阻 → R15 拉低 | 关断 | 高 | **自动关灯** |

  最后一行是硬件自动失效安全,不依赖固件执行任何代码。
- U7 未使用的输入 A5..A8 **必须接 GND**,不可悬空(CMOS 输入悬空会自激振荡、增加功耗)。
````

- [ ] **Step 2: 追加 Block E(功率级 + 输出),给出通道 1 的完整网表 + 复制规则**

````markdown
## Block E:功率级与输出(×6 通道,每通道 2 路)

**通道 1 完整网表**(CH2..CH6 完全同构,位号按 +10 递增:CH2 用 Q17/Q18/D17/D18…,依此类推)

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| F2 | 4A 慢断保险丝 + 座(DC ≥32V) | 待核实 | 1 → `V24_BUS`;2 → `CH1_VOUT` |
| J3 | KF2EDGV-3.81-3P 针座 | C441333 | 1 → `CH1_VOUT`;2 → `CH1_CW_D`;3 → `CH1_WW_D` |
| Q7 | NTD5865NLT4G TO-252 | 待核实 | D → `CH1_CW_D`;S → `GND`;G → `CH1_CW_GR` |
| Q8 | NTD5865NLT4G TO-252 | 待核实 | D → `CH1_WW_D`;S → `GND`;G → `CH1_WW_GR` |
| R16 | 100Ω 0603 栅阻 | C22775 | 1 → `CH1_CW_G`;2 → `CH1_CW_GR` |
| R17 | 100Ω 0603 栅阻 | C22775 | 1 → `CH1_WW_G`;2 → `CH1_WW_GR` |
| R18 | 10kΩ 0603 栅源下拉 | C25804 | 1 → `CH1_CW_GR`;2 → `GND` |
| R19 | 10kΩ 0603 栅源下拉 | C25804 | 1 → `CH1_WW_GR`;2 → `GND` |
| D5 | SS36 续流 SMB | 待核实 | 阳极 → `CH1_CW_D`;阴极 → `CH1_VOUT` |
| D6 | SS36 续流 SMB | 待核实 | 阳极 → `CH1_WW_D`;阴极 → `CH1_VOUT` |
| D7 | SMBJ26A TVS | C19077580 | 阴极 → `CH1_CW_D`;阳极 → `GND` |
| D8 | SMBJ26A TVS | C19077580 | 阴极 → `CH1_WW_D`;阳极 → `GND` |
| C15 | 100µF/35V 电解 | 待核实 | + → `CH1_VOUT`;− → `GND` |
| C16 | 100nF 0603 | C14663 | 1 → `CH1_VOUT`;2 → `GND` |
| LED2 | 0603 绿 | 待核实 | 阳极 → `CH1_CW_G`;阴极 → R20 |
| R20 | 4.7kΩ 0603 | 待核实 | 1 → LED2 阴极;2 → `GND` |
| LED3 | 0603 绿 | 待核实 | 阳极 → `CH1_WW_G`;阴极 → R21 |
| R21 | 4.7kΩ 0603 | 待核实 | 1 → LED3 阴极;2 → `GND` |
| TP5 | 测试焊盘 | — | `CH1_CW_GR`(栅极实测点) |
| TP6 | 测试焊盘 | — | `CH1_CW_D`(漏极实测点) |

**复制规则**:CH2..CH6 复制上表,把所有 `CH1_` 前缀替换为 `CH2_`..`CH6_`,位号顺序递增。栅极测试点 TP5/TP6 只在 CH1 保留,其余通道不设(节省板面)。

**关键约束**
- **续流二极管 D5/D6 的方向**:阳极接漏极、阴极接 V+。MOS 关断瞬间灯带线缆电感的电流经此路径泄回母线。方向接反会在正常工作时直接短路灯带 —— 这是本块最严重的可能错误。
- **指示灯接在 HCT245 输出侧(`CHn_xx_G`,栅阻之前)**,不碰功率回路。4.7k 限流使 LED 电流约 0.5mA,不影响栅极驱动。
- 每路 V+ 的本地去耦 C15/C16 尽量靠近端子 J3。
- 保险丝座 F2..F7 远离 MOSFET 发热区,并留出更换操作空间。
````

- [ ] **Step 3: 自检**

1. 12 个栅极网络 `CHn_xx_G` 是否都从 HCT245 的 B 侧引出、经栅阻变成 `CHn_xx_GR` 再到 MOS 栅极?
2. 6 个 `CHn_VOUT` 是否都经各自的保险丝从 `V24_BUS` 取电,没有直接短接到 `V24_BUS`?
3. 续流二极管方向是否全部为"阳极→漏极、阴极→V+"?

- [ ] **Step 4: 提交**

```bash
git add hardware/netlist-spec.md
git commit -m "docs(hw): netlist spec Blocks D and E - level shift and power stage"
```

---

## Task 8: 网表规格书 —— 接口块 + BOM 导出

**Files:**
- Modify: `hardware/netlist-spec.md`
- Create: `hardware/bom-jlc.csv`

- [ ] **Step 1: 追加 Block F(传感器与开关接口)**

````markdown
## Block F:传感器与干接点接口

| 位号 | 元件 | C 编号 | 引脚 → 网络 |
|---|---|---|---|
| J4 | Qwiic JST-SH 1.0mm 4P 卧贴 | 待核实 | 1 → `GND`;2 → `V3P3`;3 → `I2C_SDA`;4 → `I2C_SCL` |
| R22 | 4.7kΩ 0603 | 待核实 | 1 → `V3P3`;2 → `I2C_SDA`(总线上拉) |
| R23 | 4.7kΩ 0603 | 待核实 | 1 → `V3P3`;2 → `I2C_SCL` |
| J5 | XH2.54-4P 立式 | C37815 | 1 → `V5_SYS`;2 → `GND`;3 → `UART2_TX`;4 → `UART2_RX` |
| J6 | KF128-2.54-5P 端子 | C474923 | 1 → `SW_IN1`;2 → `SW_IN2`;3 → `SW_IN3`;4 → `SW_IN4`;5 → `GND` |
| R24–R27 | 10kΩ 0603 ×4 上拉 | C25804 | 各:1 → `V3P3`;2 → `SW_IN1..4` |
| R28–R31 | 1kΩ 0603 ×4 串阻 | C21190 | 各:串在 J6 引脚与 `SW_INn` 之间(ESD 限流) |
| C17–C20 | 100nF 0603 ×4 | C14663 | 各:1 → `SW_IN1..4`;2 → `GND`(RC 消抖) |

**关键约束**
- **接口物理防呆**:I2C 只走 Qwiic(3.3V),UART 只走 XH2.54(5V),两者互不可插。丝印必须标注各自电压。
- GPIO34/35/36/39 是纯输入脚且**内部无上拉**,R24–R27 的外部上拉是必需的,不是可选。
- I2C 上拉 R22/R23 取 4.7k 对应 100kHz;若后续挂载设备多需提速,改 2.2k。
````

- [ ] **Step 2: 生成嘉立创 BOM CSV**

从设计文档 §8.1/§8.2 与本网表规格书汇总,写 `hardware/bom-jlc.csv`,列头必须是嘉立创 SMT 接受的格式:

```csv
Comment,Designator,Footprint,LCSC Part #
ESP32-WROOM-32E-N4,U4,ESP32-WROOM-32E,C701341
74HCT245PW,"U6,U7",TSSOP-20,C52140501
CH340C,U5,SOP-16,C84681
AMS1117-3.3,U3,SOT-223,C6186
2mR 2512,RS1,2512,C500614
SMBJ26A,"D1,D7,D8,D9,D10,D11,D12,D13,D14,D15,D16,D17,D18",SMB,C19077580
SS34,"D2,D3,D4",SMA,C8678
100R 0603,"R16,R17,...",0603,C22775
10K 0603,"R2,R6,R7,R11,R12,R13,R14,R18,R19,R24,R25,R26,R27,...",0603,C25804
100K 0603,"R1,R3,R15",0603,C25803
1K 0603,"R8,R28,R29,R30,R31",0603,C21190
100nF 0603,"C3,C8,C10,C12,C13,C14,C16,C17,C18,C19,C20",0603,C14663
10uF 0805,"C7,C9,C11",0805,C15850
S8050,"Q4,Q5",SOT-23,C2146
TS-1187A,"SW1,SW2",SMD-4P,C318884
LED Red 0603,LED1,0603,C2286
Type-C 16P,J2,TYPE-C-31-M-12,C165948
KF2EDGV-3.81-3P,"J3,J7,J8,J9,J10,J11",KF2EDGV-3.81-3P,C441333
KF7.62-2P,J1,KF7.62-2P,C707824
KF128-2.54-5P,J6,KF128-2.54-5P,C474923
XH2.54-4P,J5,XH-4A,C37815
```

> **未定 C 编号的元件**(NTD5865、SUD50P06、TX4144、INA237、4A 保险丝座、SS36、Qwiic 座、470µF/100µF 电解、BZT52C12、MMBT3904、5.1k/4.7k 电阻、绿色 LED、33µH 电感)在 Task 12 下单前统一核实后补入。CSV 中先留占位行并在 `LCSC Part #` 列写 `TBD-<元件名>`,便于最后 grep 检查。

- [ ] **Step 3: 校验 CSV 无遗漏**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver
grep -c "TBD-" hardware/bom-jlc.csv
awk -F',' 'NR>1 {print $4}' hardware/bom-jlc.csv | sort | uniq -d
```

预期:第一条打印待核实项数量(记录下来,Task 12 要清零);第二条**无输出**(同一 C 编号不应出现在多行,否则是拆分错误,应合并 Designator)。

- [ ] **Step 4: 提交**

```bash
git add hardware/netlist-spec.md hardware/bom-jlc.csv
git commit -m "docs(hw): netlist Block F and JLC BOM export"
```

---

## Task 9: 在嘉立创EDA 中绘制原理图

**Files:**
- Create: `cct-driver.epro`(由 EDA 生成,二进制)
- Create: `hardware/netlist-export.txt`(从 EDA 导出,用于比对)

**这是本计划中唯一必须人工在 GUI 中完成的任务。** 网表规格书已消除全部设计判断,此处只做机械录入。

- [ ] **Step 1: 建工程并按块绘制**

打开 `/Applications/嘉立创EDA(专业版).app`,新建工程 `cct-driver`。按 `hardware/netlist-spec.md` 的 Block A → F 顺序绘制,每块画完立即用 EDA 的"网络高亮"抽查 3~5 个网络。

元件放置方式:在元件库搜索框输入 C 编号直接放置(嘉立创EDA 与立创商城库直通)。`待核实` 的元件先用同封装的通用符号占位,Task 12 核实后替换。

- [ ] **Step 2: 运行 ERC**

EDA 菜单:设计 → 检查 DRC/ERC。

预期:0 error。常见 warning 及处理:
- "引脚未连接" → 只允许出现在规格书里标注 NC 的引脚上,其余必须修正
- "电源引脚无驱动" → 给 `V24_BUS`/`V5_SYS`/`V3P3`/`GND` 放置电源标志
- "输出引脚短接" → 一定是接错,必须修正

- [ ] **Step 3: 导出网表**

EDA 菜单:导出 → 网表 → 选择 "Spice" 或 "通用网表",保存为 `hardware/netlist-export.txt`。

- [ ] **Step 4: 网表比对(本任务的验收测试)**

```bash
cd /Users/hey/Untitled/PendingHome/cct-driver
# 抽取导出网表里的所有网络名
grep -oE '^\S+' hardware/netlist-export.txt | sort -u > /tmp/nets-actual.txt
# 抽取规格书里出现的所有反引号网络名
grep -oE '`[A-Z0-9_]+`' hardware/netlist-spec.md | tr -d '`' | sort -u > /tmp/nets-spec.txt
diff /tmp/nets-spec.txt /tmp/nets-actual.txt
```

预期:`diff` 无输出,或差异仅为规格书中的说明性文字被误抓。**逐条解释每一处差异**;凡是"规格书有、导出没有"的网络,一定是漏画,必须补上后重跑。

- [ ] **Step 5: 提交**

```bash
git add cct-driver.epro hardware/netlist-export.txt
git commit -m "feat(hw): complete schematic in JLCEDA, netlist verified against spec"
```

---

## Task 10: PCB 布局指导文档

**Files:**
- Create: `hardware/layout-guide.md`

- [ ] **Step 1: 写布局指导**

````markdown
# PCB 布局指导

**板尺寸目标:** 约 100 × 115mm,四角 M3 安装孔(距边 5mm)。
**层数/铜厚:** 2 层,1oz。
**⚠️ 所有元件必须放顶层** —— 嘉立创经济型 SMT 只支持单面焊接。背面仅覆铜与走线。

## 分区(从板子一侧到另一侧)

| 区 | 深度 | 内容 |
|---|---|---|
| 输出区 | ~42mm | 6× 端子 J3/J7..J11 沿板边一字排开(每个占 13mm,共 78mm)→ 各自的保险丝座 → 2× MOSFET + 续流管 + TVS + 本地去耦 |
| 驱动区 | ~18mm | U6/U7 两片 HCT245 + 24 颗栅阻/下拉 + 12 颗通道指示灯 |
| 功率脊椎 | ~25mm | J1 输入端子、F1 保险丝座、Q1/Q2 防反管、RS1 采样电阻、U1 INA237、C1/C2 大电解 |
| 控制区 | ~30mm | U4 ESP32(含天线净空)、U5 CH340C、J2 Type-C、SW1/SW2、J4 Qwiic、J5 XH、J6 开关端子 |

## 走线宽度(1oz)

| 网络 | 最小宽度 | 说明 |
|---|---|---|
| `V24_IN`/`V24_FUSED`/`V24_PROT`/`V24_BUS` 主脊椎 | **双面 ≥20mm 覆铜 + 过孔缝合** | 按 15A 连续设计。IPC-2152 下 1oz 单面 12A@ΔT10℃ 约需 20mm;双面对折后余量充足 |
| `CHn_VOUT`(过保险丝后) | ≥3mm | 每路 ≤3A |
| `CHn_xx_D`(MOS 漏极到端子) | ≥3mm | 同上 |
| `GND` 回流 | 整面覆铜 | 功率地与信号地在 RS1 附近单点连接 |
| `V5_SYS` | ≥1mm | <0.5A |
| `V3P3` | ≥1mm | <0.7A(WiFi 突发) |
| 信号线 | 0.25mm | |

主脊椎另加:阻焊开窗区(供波峰焊加锡增厚)+ **2× M3 孔位**,实测温升超预期时可外拧铜排旁路。

## 关键布局约束

1. **ESP32 天线净空**:U4 的天线段悬出板边,或其下方与两侧 ≥15mm 禁铜(顶层、底层、内层全禁),且远离功率区。
2. **TX4144 开关环路最小**:U2-SW → L1 → C5 → GND → U2-GND 构成的环路面积尽可能小,D2 紧贴 U2。
3. **INA237 开尔文采样**:U1 的 IN+/IN− 用 0.25mm 细线从 RS1 两端焊盘**单独引出**,不得从大电流覆铜任取一点。两条线并行走、长度接近。
4. **保险丝座远离 MOSFET**,并留出镊子更换空间。
5. **MOSFET 散热**:每只 TO-252 漏极焊盘下打过孔阵列(0.3mm 孔、1mm 间距)到背面覆铜;按高温 0.3W/只预留铜面,不得紧密挤压。Q1/Q2 防反管另设独立散热铜面。
6. **去耦电容紧贴引脚**:C9/C10(ESP32)、C13/C14(HCT245)、C3(INA237)、C12(CH340C)的走线长度 <5mm。

## 丝印要求

- 每个输出端子标注 `CH1 V+ / CW / WW` 等,含极性
- 输入端子旁标 `24V IN  MAX 12A` 与极性
- Qwiic 座旁标 `I2C 3.3V`,XH 座旁标 `UART 5V`
- 保险丝座旁标 `4A SLOW`
- 板边标注版本号与日期

## 测试点

裸铜焊盘(1.5~2.0mm 圆盘,阻焊开窗),丝印标注信号名:
`V24_BUS`、`V5_SYS`、`V3P3`、`GND`(至少 2 处)、`CH1_CW_GR`(栅极波形)、`CH1_CW_D`(漏极波形)、`U0TXD`、`U0RXD`、`I2C_SDA`、`I2C_SCL`
````

- [ ] **Step 2: 提交**

```bash
git add hardware/layout-guide.md
git commit -m "docs(hw): PCB layout guide with 15A spine and keepout rules"
```

---

## Task 11: PCB 布局布线与 DRC

**Files:**
- Modify: `cct-driver.epro`

- [ ] **Step 1: 按 layout-guide 完成布局**

在嘉立创EDA 中从原理图更新到 PCB,按分区表摆放元件。先摆连接器(位置固定板框),再摆功率器件,最后摆小信号件。

- [ ] **Step 2: 布线与覆铜**

按走线宽度表布线。主脊椎用覆铜而非走线。顶层底层各铺一块 `GND` 铜,用过孔阵列缝合(间距 ≤5mm)。

- [ ] **Step 3: 运行 DRC**

EDA 菜单:设计 → 检查 DRC。规则设置:最小线宽 0.127mm、最小间距 0.127mm、最小孔径 0.3mm(嘉立创常规工艺能力)。

预期:0 error。

- [ ] **Step 4: 三项人工复查(DRC 查不出来的)**

- [ ] 天线净空区内确认无铜、无走线(切换各层目视 + 用 EDA 的区域选择工具确认)
- [ ] 主脊椎从 J1 到分配点全程宽度 ≥20mm 等效,无瓶颈(用 EDA 测量工具量最窄处)
- [ ] 所有元件在顶层(切到底层视图,应只见覆铜与走线,无任何元件)

- [ ] **Step 5: 提交**

```bash
git add cct-driver.epro
git commit -m "feat(hw): PCB layout and routing, DRC clean"
```

---

## Task 12: 下单前核实与出图

**Files:**
- Create: `hardware/order-checklist.md`
- Modify: `hardware/bom-jlc.csv`(补齐全部 TBD)

- [ ] **Step 1: 核实所有 TBD 元件**

```bash
grep "TBD-" hardware/bom-jlc.csv
```

对每一项:在立创商城/嘉立创元件库搜索,确认 **C 编号、价格、库存、基础库/扩展库**,填入 CSV。

必须核实的清单:NTD5865NLT4G、SUD50P06-15、TX4144、INA237、4A 慢断保险丝 + 座(DC ≥32V)、15A ATO 保险丝座、SS36、Qwiic JST-SH 4P 卧贴、470µF/50V 电解、100µF/35V 电解、BZT52C12、MMBT3904、5.1kΩ/4.7kΩ 0603、绿色 0603 LED、33µH ≥2A 电感、22µF MLCC。

- [ ] **Step 2: 统计扩展库种类数**

```bash
awk -F',' 'NR>1 {print $4}' hardware/bom-jlc.csv | grep -c "^C"
```

然后在嘉立创元件库逐一查库别,统计**扩展库**种类数。

**验收条件:≤11 种。** 超出则必须从设计中砍掉元件种类(优先候选:通道指示灯改用与状态灯相同的型号、Qwiic 座改用已有的 XH 系列、电解电容统一为单一型号),直到达标。这是硬约束 —— 官方限制"单次订单通常 10~13 种扩展库物料"。

- [ ] **Step 3: 写下单核对清单**

`hardware/order-checklist.md`:
````markdown
# 下单前核对清单

## PCB
- [ ] 层数 2、尺寸约 100×115mm、板厚 1.6mm
- [ ] **铜厚 1oz**(不是 2oz —— v7 已改,避开经济型 SMT 的铜厚限制与未公布加价)
- [ ] 表面处理:沉金(本板尺寸下仅约 ¥8)
- [ ] 阻焊绿色(经济型对颜色有限制)
- [ ] 数量 5 片

## SMT
- [ ] 选择**经济型**(工程费 ¥50)
- [ ] 确认**单面贴装**,所有元件在顶层
- [ ] 勾选**插件焊接/手工焊接**服务(工程费 ¥20 + ¥0.1/焊点)
- [ ] 扩展库种类 ≤11(见 Step 2)
- [ ] **Type-C 确认为普通贴板式,不是沉板式**
- [ ] 上传 BOM 与坐标文件,核对每个位号的元件与方向

## 需向客服确认(官方文档未明确)
- [ ] 最高元件高度(本板最高为电解电容约 13mm、3.81mm 端子约 10mm)是否在经济型可接受范围
- [ ] 焊点单价的实际计费(贴片 ¥0.01/点、手焊 ¥0.1/点,以系统报价为准)

## 板外同期采购
- [ ] 明纬 LRS-350-24(C95189,¥117.8)
- [ ] **明纬 TBC-09 端子盖**(嘉立创FA商城搜 TBC-09;买不到则 3D 打印 Thingiverse thing:5615932)
- [ ] 通风箱体(见外壳方案文档)
- [ ] 亚克力面板 2 片 110×125mm 2.8mm(立创面板 szlcmb.com,可能符合免费打样)
- [ ] M3 铜柱、螺丝
- [ ] 线材:BVR 2.5mm² 红黑各 4m、RVV 3×0.75~1.0mm² 约 45m(淘宝散买)
- [ ] 管型端子套装盒、叉形端子 UT2.5-4、压线钳(淘宝)
- [ ] 4A 慢断保险丝备件 ×10
````

- [ ] **Step 3: 导出生产文件**

EDA 菜单:导出 → PCB 制版文件(Gerber)、坐标文件、BOM。

- [ ] **Step 4: 提交**

```bash
git add hardware/bom-jlc.csv hardware/order-checklist.md
git commit -m "chore(hw): resolve all TBD parts, add pre-order checklist"
```

---

## 计划自检结果

**1. 规格覆盖检查** —— 对照设计文档 v7 逐节:

| 设计文档章节 | 对应任务 |
|---|---|
| §3 电流预算 | Task 3(软限流) |
| §4 系统架构 | Task 5–8(网表分块) |
| §5 GPIO 分配 | Task 1(YAML)+ Task 6(Block C) |
| §6.1 功率级 | Task 7(Block E) |
| §6.2 输入保护 | Task 5(Block A) |
| §6.3 电平转换 | Task 7(Block D) |
| §6.4 功率监测 | Task 3 + Task 5(U1) |
| §6.5 USB 与电源链 | Task 6(Block B/C) |
| §6.6 传感器与开关接口 | Task 4 + Task 8(Block F) |
| §6.7 WiFi 天线 | Task 10(净空规则) |
| §7 布局要点 | Task 10、Task 11 |
| §8 BOM | Task 8、Task 12 |
| §8.5 嘉立创下单说明 | Task 12 |
| §9 ESPHome 配置 | Task 1–4 |
| §11 验证计划 | **不在本计划内** —— 属打样收板后的样机测试,另立执行文档 |

**2. 占位符扫描** —— 本计划中的"待核实"仅出现在元件 C 编号上,且 Task 12 Step 1/2 强制清零并有可执行的校验命令。无 "TODO"、"稍后实现"、"类似 Task N" 等表述。

**3. 类型/命名一致性** —— 网络名在 Block A–F 之间的跨块引用已核对:`V24_BUS`(A→E)、`V3P3`/`V5_SYS`(B→C/D/F)、`I2C_SDA`/`I2C_SCL`(A→C→F)、`CHn_xx`(C→D)、`CHn_xx_G`(D→E)、`OE_CTRL`(C→D)。ESPHome 的 12 个 output id 与 Block C 的 12 个 PWM 网络名一一对应。

**4. 已知缺口** —— §11 的样机验证(短路熔断实测、12A 温升、栅极波形、上电闪光复测)不在本计划范围,需在收板后另立执行文档。这是有意的:验证任务的前置条件是拿到实物板。
