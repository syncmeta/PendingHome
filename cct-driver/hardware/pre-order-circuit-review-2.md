# 下单前电路复核（第二轮：从失效、固件和设计承诺倒查）

日期：2026-08-18

复核基线：`main` / `c7cfa12`

结论：**🔴 4 条 / 🟡 4 条 / 🟢 9 条。当前不建议下单。**

这轮没有重新做第一轮已经完成的 INA237 工作范围、buck 稳态工作点、栅极驱动损耗、MOS/保险丝热账等器件正向复核；只在新发现需要它们时引用第一轮数据。复核入口是“板子出现某种故障时，实际电流和控制路径会怎样”，并把原理图逐脚网表、固件和原始设计承诺放在同一条证据链里。

---

## 0. 证据边界与复现方法

### 0.1 网表只从当前原理图导出

实际执行：

```bash
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli sch export netlist \
  --format kicadsexpr -o /tmp/nl.net hardware/cct-main.kicad_sch
```

导出结果：**199 个 component、146 个 net、555 个 node**。随后从 `/tmp/nl.net` 解析 `ref.pin → net`；下文所有连接关系都来自该文件，不以 `hardware/netlist-spec.md` 为证据。

本轮特别核过的原始网表片段：

```text
Q1  1=PMOS_GATE  2=V24_FUSED  3=V24_PROT
Q2  1=PMOS_GATE  2=V24_FUSED  3=V24_PROT
R1  1=PMOS_GATE  2=GND
Q3  1=MASTER_OFF_B  2=GND  3=OE_B
Q6  1=OE_B  2=GND  3=OE_N
F2  1=V24_BUS  2=CH1_VOUT              （F3–F7 同构）
U1  1=GND 2=GND 3=NC 4=SDA 5=SCL 6=3V3 7=GND
    8=V24_BUS(VBUS) 9=V24_BUS(IN-) 10=V24_PROT(IN+)
U4  GPIO12=NC；GPIO34/35/36/39=SW_IN1/2/3/4；其余见 🟢-1
```

### 0.2 固件做了两条真实工具链验证

| 工具链 | 命令与结果 |
|---|---|
| 仓库现有 venv：ESPHome **2025.5.2** | `esphome config` 通过；`esphome compile` 通过；RAM **33,500 / 327,680 B（10.2%）**，Flash **1,013,385 / 1,835,008 B（55.2%）** |
| 复核日可取得版本：ESPHome **2026.7.4** | `esphome config` **失败**：`总电流` 与 `总功率` 都转成 ASCII ID `___`，判定为重复实体名 |

这说明“旧环境能编译”是真的，但并不能证明按验板文档所写的 `pip install esphome` 在今天还能刷机。

### 0.3 数据手册边界

本轮重新查询的主要原始资料：

- 明纬 [LRS-350 官方规格书，2025-09-12 版](https://www.meanwell.com/Upload/PDF/LRS-350/LRS-350-SPEC.PDF)，第 1 页 Protection / Note 7。
- 明纬 [LRS-350-24 官方测试报告](https://display.meanwell.com/Upload/PDF/LRS-350/LRS-350-24-rpt.pdf)，第 5 页 Protection Function Test。
- Littelfuse [452/454 Series NANO2 Slo-Blo 数据表，2025-10-16 版](https://www.littelfuse.com/assetdocs/fuse-452-and-454-datasheet?assetguid=8c87aa93-80a7-4ea8-8749-a19ba03901c2)，第 1–2 页。
- TI [INA237 数据表 SBOSA20A](https://www.ti.com/lit/ds/symlink/ina237.pdf)，第 5、18、21–23 页。
- Espressif [ESP32 硬件设计指南](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/pcb-layout-design.html)、[GPIO 文档](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html)及 [ESP32 芯片勘误 GPIO-3.11](https://docs.espressif.com/projects/esp-chip-errata/en/latest/esp32/03-errata-description/esp32/gpio-inputs-pulled-down.html)。
- ESPHome 当前官方 [Output](https://esphome.io/components/output/)、[LEDC](https://esphome.io/components/output/ledc/)、[INA2xx](https://esphome.io/components/sensor/ina2xx/) 文档、[2026.5 breaking change](https://developers.esphome.io/blog/2026/05/14/floatoutput-power-scaling-fields-gated-behind-use_output_float_power_scaling/)及 [2026.7.4 `float_output.cpp`](https://raw.githubusercontent.com/esphome/esphome/2026.7.4/esphome/components/output/float_output.cpp)。

没有实物板，所以射频、短路脉冲、模拟精度、波形和热都只能列为“需实测”；查不到的数据不拿推测代替。

---

## 1. 从症状倒推的总表

| 到手后的症状 | 倒查的原因 | 本板结论 |
|---|---|---|
| 24V 插上，3.3V 不起 | F1 / 防反 P-MOS / PTC1 / buck / diode-OR / AMS1117 断链；反接；5V 口短路 | 网表路径连续，第一轮工作点复核仍适用；没有新接错。见 🟢-9 |
| ESP32 能启动但连不上 Wi‑Fi | strapping 错、GPIO12 被拉高、供电跌落、天线净空/箱体/LRS 金属壳遮挡 | 启动脚对；**RF 净空未满足官方 15 mm 推荐，需整机实测**。见 🟡-3 |
| 某路灯不亮 | 固件 GPIO 对错、HCT 方向/OE、支路保险丝、端子 CW/WW、MOS 栅漏源 | 12 路 GPIO 与实际网表逐路一致；端子/保险丝路径一致。见 🟢-1、🟢-3 |
| 灯常亮、怎么关都关不掉 | /OE 失效、栅极浮空、低边 MOS D-S 短路 | 健康 MOS 可由 /OE 关；**D-S 短路时没有真正的高边总断路**。见 🔴-2 |
| 六路全开超过 12A | 静态配置没封顶、动态限流没真正写回 PWM、采样太慢 | **三项均成立**。见 🔴-3、🟡-1 |
| 调光闪烁/爬行 | PWM 分辨率/定时器冲突、控制环路使用陈旧样本、1 Hz 阶梯调节 | PWM 配置正确；采样全周期 1.582 s，必须调环路并实测。见 🟢-3、🟡-1 |
| HA 里没有/读数不对 | 固件不生成、I²C 地址错、量程错、误差未校准、没有告警实体 | 当前 ESPHome 已在配置阶段失败；硬件地址/量程对；精度需校准；11A/12A HA 告警没有实现。见 🔴-4、🔴-3、🟡-2、🟢-4 |
| 某输出短路 | 电源限流模式与保险丝曲线不配合；逻辑随母线重启 | **现有资料不能保证保险丝熔断，设计所写的动作时间也不成立。**见 🔴-1 |
| 24V 插反 | 防反 MOS 方向/栅极钳位错误 | 网表与第一轮已核方向一致；本轮没有发现新矛盾。见 🟢-9 |

---

# 🔴 下单前必须改（4 条）

## 🔴-1 LRS-350-24 是 hiccup 短路保护；4A 慢熔保险丝不能据现有资料保证熔断

### 设计承诺

设计文档 §6.1 写的是：LRS-350 故障电流 **15–19A**，等于 4A 保险丝的 **3.8–4.8 倍**，所以保险丝会在 **0.05–0.5 s** 切断；验板文档据此要求某一路硬短路后 **<1 s 熔断，其余通道恢复正常**。

### 官方资料实际写了什么

1. LRS-350-24 额定 **24V / 14.6A / 350.4W**。
2. LRS-350 官方规格书第 1 页 Protection：3.3–36V 型号在 **110–140% rated output power** 时进入 **hiccup mode**，故障移除后自动恢复；Note 7 只允许 12–48V 型号承受 **150% 峰值最多 1 s**，超过 1 s 也进入 hiccup。
3. 官方 LRS-350-24 测试报告第 5 页实际测得过载动作点为 **125.89%（230VAC）/ 125.61%（115VAC）**，保护类型明确是 hiccup；“短接输出 1 小时”的结果也是 **hiccup、无损坏**，不是恒流持续输出。
4. 当前支路丝是 `0452004.MRL`，Littelfuse 452/454 数据表第 1 页给出的系列保证窗口是：
   - 100%：**至少 4 h**；
   - 200%：**1–60 s**；
   - 300%：**0.2–3 s**；
   - 800%：**0.002–0.1 s**。
5. 同数据表第 2 页给 4A 档 nominal melting I²t = **34.40 A²s**。LRS 的 hiccup 脉冲宽度、重复周期和每个脉冲 I²t 在规格书/测试报告中**查不到**，因此不能证明重复脉冲会积累到保险丝熔断。

设计文档的 **0.05–0.5 s** 不在 Littelfuse 的保证表内：即便真的连续有 12A（3×额定），厂家仍允许最长 **3 s**；而实际电源又不是连续供流。

### 从故障倒推的实际后果

`F2–F7` 任一路下游短路会经 2mΩ RS1 直接拖低 `V24_PROT/V24_BUS`。逻辑 buck 也从同一个 `V24_PROT` 取电。于是 LRS 进入 hiccup 时，5V/3.3V、ESP32、HCT245 与所有灯会一起掉电/重启；在支路丝没有被证实熔断之前，不能承诺“坏一路隔离、其余五路继续工作”。

**必须处理：**在下单前重新定义并验证短路保护组合。若继续使用 LRS-350-24 且仍要求确定性的支路隔离，应加入有明确限流/关断/锁存规格的支路电子保险或等效硬件；若想保留 PCB，至少必须先用选定电源 + 选定保险丝做板外短路脉冲实测，证明最坏输入电压、温度和样品离散下都能可靠分断，再把结论写回规格书。仅凭现有两份手册不能放行。

**是否需要重出 PCB：按当前“LRS + 保证支路隔离”的产品承诺，需重出。**只有改成经板外实测/资料证明可配合的外部电源与保险丝组合，才可能不改 PCB；目前没有这份证据。

---

## 🔴-2 “P-MOS 兼作 MCU 可控总断路、应对 MOS 短路常亮”没有落到原理图

### 原始承诺与实际网表

设计文档首页 v7 变更摘要第 2 条明确写：**防反接 P-MOS 兼作 MCU 可控总断路开关，应对 MOS 短路导致的通道常亮。**

实际网表却是：

```text
Q1/Q2 gate = PMOS_GATE
R1: PMOS_GATE → GND
Q3: collector → OE_B；emitter → GND；base → MASTER_OFF_B
TP7/R2/R3 → Q3 → OE_B → Q6 → OE_N
```

也就是说，Q1/Q2 的栅极只有 R1 永久拉地和 DZ1 钳位，**没有 MCU、Q3 或 TP7 能把它们关断**。所谓 `MASTER_OFF` 只是在关 74HCT245 的 `/OE`，并不是断 24V。

### 为什么支路保险丝救不了这种故障

若任一低边 MOS（Q7–Q18）发生 D-S 短路，灯带负极被永久接地；HCT `/OE`、栅极 10k 下拉、ESP32 看门狗和 TP7 都不再有控制权。5m 灯带额定电流是 **2.92A**，只等于 4A 保险丝额定的 **73%**。Littelfuse 只保证 100% 额定时至少 4 h 不开，73% 更没有动作条件。因此这是“亮度正常但永久常亮”，不是能靠熔丝切掉的过流故障。

**必须处理：**若“控制器失效仍可全灭”是产品要求，应在逻辑取电分支之后、六路负载之前加入默认关断的高边总开关/继电器/电子保险，并让 MCU 与外部急停都能关它；不能继续把 TP7 `/OE` 称为总断路。若决定放弃这项安全要求，必须把设计文档和验板说明改成“只能关健康 MOS，D-S 短路会永久点亮直至人工断电”。

**是否需要重出 PCB：需要。**除非接受外置、免焊且同等级的总断电模块；现板本身无法实现承诺。

---

## 🔴-3 12A 运行预算没有被静态封顶，现有动态限流也不会立即改变已点亮 PWM

这是固件逻辑错误，不是“参数还需调一调”。

### 三条互相独立的证据

1. 设计文档 §3 要求“按实测灯带电流设置每条最大输出比例，使总配置上限 ≤12A”。当前 6 组输出没有任何静态 `max_power`。六条 5m 灯带理论满载是：

   ```text
   6 × 2.92A = 17.52A
   12 / 17.52 = 0.6849
   ```

   若六条相同，作为保守初值，每条实际 PWM 上限必须约 **68.5%** 才能从配置上保证 12A；当前初值是 100%。最终值应按每条实测电流重新分配，不能照抄 68.5%。

2. `apply_power_scale` 只调用 12 次 `set_max_power(s)`。ESPHome 2026.7.4 官方源码 `float_output.cpp` 第 10–12 行显示，`set_max_power()` 只给 `max_power_` 赋值；真正的比例换算和 `write_state()` 只发生在之后的 `set_level()`（第 24–40 行）。仓库现有 2025.5.2 编译产物中的同名源码也呈现相同行为，所以这不是升级后才出现的回归。灯已经稳定点亮后，即使每秒把 `power_scale` 从 1.00 降到 0.30，**当前硬件占空比仍不会变化**，直到下一次 light 状态/亮度/过渡重新写输出。

   典型失败序列是：六路在 0.5 s 过渡后稳定到满亮 → INA 稍后读到 >12A → `max_power_` 被更新 → 没有后续 `set_level()` → 电流继续保持 17.5A。HA 里还会看到日志声称“输出限幅至 95%/90%…”，形成假成功。

3. INA 失效处理只在 `ina_fault_count == 5` 时关一次 `/OE`。若用户在 HA 里重新打开暴露出来的“输出使能”开关，而 INA 仍是 NaN，计数已经变成 6、7……，以后永远不再满足 `== 5`，输出可被重新打开。这里必须使用 `>= 5` 加锁存，或在有效读数恢复前禁止重新使能。

另外，设计文档要求 **11A 预警、12A 降亮度并向 HA 告警**；当前只有 `>12A` 的日志，没有 11A 预警实体/事件，也没有 HA 告警。

**必须处理：**刷机前同时完成：

- 依据每条灯带实测值设置静态上限，使任何正常组合的配置总上限 ≤12A；
- 把动态控制改为会在每次控制周期**立即重写实际输出**的实现，并用钳流表验证稳态满亮时也能从 17.5A 降到目标；
- INA 故障改为锁存关断，只有读数恢复并经过明确条件后才能重新使能；
- 增加 11A/12A 的 HA 可见告警，并给阈值留出 🟡-2 的测量误差余量。

**是否需要重出 PCB：不需要，必须改固件。**

---

## 🔴-4 当前 ESPHome 2026.7.4 不能通过配置；修完实体名后还会撞 2026.5 的编译期变更

实际运行 ESPHome 2026.7.4：

```text
Duplicate sensor entity with name '总功率' found.
Conflicts with entity '总电流' ...
Both convert to ASCII ID: '___'
```

`总电流`、`总功率`、`母线电压` 都是纯中文 name；即使显式 C++ `id` 不同，当前校验器仍要求平台内实体名转换后的 ASCII ID 唯一。验板文档写的是直接 `pip install esphome`，没有版本锁，因此新机器照文档操作会在刷机之前停止。

还有第二个确定的后继阻断：ESPHome 2026.5 起把 `FloatOutput` 的 runtime power scaling 做成按需编译。官方 breaking-change 文档明确说：lambda 里调用 `set_max_power()`、但 YAML 从未出现 `min_power` / `max_power` / `zero_means_zero` 或对应 action 时，编译会触发 `static_assert`。当前 12 个 output 正是这个组合。

旧 venv 的 2025.5.2 仍能配置并编译成功，只证明旧快照可用；不能作为无版本锁生产流程的依据。

**必须处理：**给三个传感器 name 加唯一 ASCII 部分（例如 `总电流 Current` / `总功率 Power` / `母线电压 Voltage`）；按当前官方要求启用 runtime scaling 编译，同时处理 🔴-3 的实际写回问题；最后锁定并记录 ESPHome 版本，在干净环境重跑 `config` + `compile`。

**是否需要重出 PCB：不需要，必须改固件与刷机文档。**

---

# 🟡 带着上板，但验板时必测（4 条）

## 🟡-1 INA237 当前一次完整新样本要 1.582 s，1 s 控制周期会重复读旧值

YAML 只写了 `update_interval: 1s`，没有显式写 `adc_time`、`adc_averaging`。ESPHome 官方 INA2xx 文档给出的默认值是每项 **4120µs**、平均 **128** 次；生成的 C++ 也把 bus、shunt、temperature 三项都设成 4120µs。TI 数据表 Table 7-6 说明连续模式依次转换这三项，平均完成后才更新寄存器，因此：

```text
单项 = 4.120ms × 128 = 527.36ms
三项完整周期 = 527.36ms × 3 = 1,582.08ms
```

1s 轮询并不等于 1s 新鲜样本；一次电流阶跃到被固件看到，最坏约为 **1.582s + 1s = 2.582s**。修好 🔴-3 后，1 Hz、每次 −5% 的离散控制还可能出现肉眼可见的阶梯/爬行。

**验板动作：**先显式尝试 `adc_time: 540us`、`adc_averaging: 64`（三项完整周期 **103.68ms**），再以 0→12A、12→6A 阶跃记录 INA/钳流表/实际 PWM 时间线；如噪声太大再提高平均数。验收指标必须包含最大响应时间和稳态摆幅，不能只看 HA 每秒有没有新数字。

**是否需要重出 PCB：不需要；固件参数 + 实测。**

---

## 🟡-2 12A 阈值的最坏未校准误差约 ±0.18A（25℃），高温可接近 ±0.27A

定稿 RS1 `RLP25FEGR002` 是 **2mΩ ±1%、TCR ±50ppm/℃**；TI INA237 数据表第 5 页给 shunt gain error **±0.3% max**、offset **±50µV max**、gain drift **±50ppm/℃ max**、offset drift **±0.02µV/℃ max**。

12A 时 shunt 信号为 24mV。25℃未校准的保守相加误差：

```text
RS1 1% + INA gain 0.3% + 50µV / 24mV 0.208% = 1.508%
12A × 1.508% = 0.181A
```

若器件从 25℃ 升到 100℃，再加 RS1 与 INA 各 `50ppm/℃ × 75℃ = 0.375%`，以及 1.5µV offset drift，总和约 **2.26% = 0.27A**。这不是说典型一定偏这么多，而是当前没有校准时不能把显示的 `12.00A` 当作物理硬边界。

**验板动作：**在约 0A、3A、6A、9A、12A 五点，以校准过的钳流表/分流表对 INA 做偏移和增益拟合，并在热稳态再复测 12A；固件阈值按误差和安全裕量下移。1A 的迟滞大于该误差，不易仅因误差自激，但“单板绝不超过 12A”的承诺仍需留裕量。

**是否需要重出 PCB：不需要；校准与固件阈值。**

---

## 🟡-3 天线下方禁铜做了，但离 Espressif 推荐的 15mm 整机净空仍很远

PCB 实际数据：U4 原点 `(16.6, 12.6)`；封装里的 PCB 天线区约为局部 `x=-16.48…-10.19, y=-9…9`，换算成板坐标约 `x=0.12…6.41, y=3.6…21.6`。板上确有双层 keepout `x=0…7, y=0…25`，并禁止走线、过孔和覆铜，说明“天线正下方不铺铜”做到了。

但天线仍压在基板上，没有伸出/切掉底板；keepout 相对天线边缘只有约 **0.6mm（内侧）/ 3.4–3.6mm（上下）**。Espressif ESP32 Hardware Design Guidelines 的 Module Placement 明确建议优先把天线伸出板边；做不到时应切掉下方底板并保证天线周围所有方向至少 **15mm** 净空，最后必须测整机 throughput 与通信距离。最终系统旁边还有 LRS 金属外壳，单看 PCB DRC 不能证明 Wi‑Fi 可用。

**验板动作：**按最终相对位置装入通风箱/书架，LRS 通电、六路 PWM 满载噪声同时存在时，分别记录 1m/5m/隔墙 RSSI、丢包、OTA 成功率和 HA 重连时间；转动板/电源方向做最坏姿态。若不达标，优先改用 32UE 外置天线或改板让 32E 天线伸出边缘。

**是否需要重出 PCB：本轮先不重出；若整机 RF 不达标则需要（或换 32UE + 合规外置天线方案）。**

---

## 🟡-4 `RESTORE_DEFAULT_OFF` 会恢复上次 ON 状态，“来电一律不亮”并未实现

六个 light 都显式设置 `RESTORE_DEFAULT_OFF`。ESPHome 官方定义是“尝试恢复上次状态，无法恢复时才默认 OFF”，不是“每次上电都 OFF”。`on_boot priority: -100` 又会在 light 状态恢复后打开 HCT `/OE`，所以停电前亮着的灯在来电后会重新点亮；硬件 `/OE` 只保证复位窗口内关闭，不改变最终恢复策略。

设计文档第 24 行仍把 `ALWAYS_OFF` 与 `RESTORE_DEFAULT_OFF` 标成未决偏好。这个取舍不要求改板，但必须在下单/交付前明确，否则验板时“上电自动亮”会被误判成硬件闪灯，或反过来把不期望的自动复亮当成正常。

**验板动作：**分别在六灯全关、单灯开、六灯开三种保存状态下断电 10 次；量复位期间是否始终无脉冲，并确认最终状态符合选定策略。若要求来电不亮，改 `ALWAYS_OFF`。

**是否需要重出 PCB：不需要；产品决策 + 固件。**

---

# 🟢 查过没问题（9 条）

## 🟢-1 固件中的全部 GPIO 与当前网表一一对应

| 功能 | YAML | 当前网表回到 U4 | 结果 |
|---|---|---|---|
| CH1 CW / WW | GPIO4 / 5 | `CH1_CW` / `CH1_WW` → U6 A0/A1 | ✅ |
| CH2 CW / WW | GPIO13 / 14 | `CH2_CW` / `CH2_WW` → U6 A2/A3 | ✅ |
| CH3 CW / WW | GPIO16 / 17 | `CH3_CW` / `CH3_WW` → U6 A4/A5 | ✅ |
| CH4 CW / WW | GPIO18 / 19 | `CH4_CW` / `CH4_WW` → U6 A6/A7 | ✅ |
| CH5 CW / WW | GPIO21 / 22 | `CH5_CW` / `CH5_WW` → U7 A0/A1 | ✅ |
| CH6 CW / WW | GPIO23 / 25 | `CH6_CW` / `CH6_WW` → U7 A2/A3 | ✅ |
| I²C | GPIO32 / 33 | `I2C_SDA` / `I2C_SCL` → U1/J9 | ✅ |
| UART2 | GPIO26 / 27 | `UART2_TX` / `UART2_RX` → J10 | ✅（当前注释） |
| 干接点 | GPIO34/35/36/39 | `SW_IN1/2/3/4` | ✅ |
| HCT `/OE` | GPIO15 | `OE_CTRL` → R14/Q6 → `OE_N` | ✅ |
| 状态灯 | GPIO2 | `LED_STATUS` | ✅ |
| UART0 | GPIO1 / 3 | `U0TXD` / `U0RXD` → CH340C | ✅ |
| BOOT | GPIO0 | `IO0` → SW1/自动下载 | ✅ |
| GPIO12 | 未使用 | U4 pad 14 明确 NC | ✅ |

没有出现 YAML 用了悬空脚、一个 GPIO 驱了两个功能、CW/WW 交换或通道错位。

**是否需要重出 PCB：不需要。**

---

## 🟢-2 strapping 脚与 GPIO34–39 只输入限制均处理正确

ESP32 的 strapping 脚是 GPIO0/2/5/12/15；当前网表逐项为：GPIO0 有 10k 上拉和 BOOT 键，GPIO2 只接状态 LED，GPIO5 只进 HCT 高阻输入，GPIO12 NC，GPIO15 经 R14=10k 与 R15=4.7k 形成外部下拉。没有 I²C 上拉误挂 GPIO12 之类的启动致命错误。

GPIO34/35/36/39 按 Espressif 文档只能输入且没有软件上拉；板上每路都有 **10k 外部上拉、1k 串联、100nF 对地**，YAML 也全配成 binary input。

GPIO36/39 的官方勘误 GPIO-3.11 是 RTC 外设上电时约 **80ns** 拉低。硬件 RC 时间常数 `10k × 100nF = 1ms`，软件又要求连续 **30ms**；分别比 80ns 长 **12,500× / 375,000×**，足以拒绝该毛刺。仍应在常规功能验收中同时跑 Wi‑Fi 与 INA，但这里没有发现需要改板的新错误。

**是否需要重出 PCB：不需要。**

---

## 🟢-3 12 路 LEDC 数量、频率、分辨率和相位配对正确

经典 ESP32 有 **16 个 LEDC channel**，本板使用 12 个；ESPHome 官方表中 **19,531Hz 对应 12-bit / 4096 级**。官方还说明相邻两个 channel 共用一个 timer，可不同 duty/phase 但必须同频。

YAML 按 CH1 CW、CH1 WW、CH2 CW、CH2 WW……连续声明，自动分配后每对恰好占相邻 channel；每对同为 19,531Hz，phase 为 0°/180°。旧版 2025.5.2 的完整编译也已通过。没有 timer 频率冲突或 channel 数超限。

**是否需要重出 PCB：不需要。**

---

## 🟢-4 INA237 型号、地址、极性和量程与硬件一致

- U1 A1/A0（pin1/pin2）都接 GND；TI Table 7-2 对应二进制 `1000000` = **0x40**，与 YAML 相同。
- IN+ 接 `V24_PROT`、IN− 接 `V24_BUS`，正向负载电流读正值；VBUS 接负载侧 `V24_BUS`。
- `adc_range: 1` 是 ±40.96mV；2mΩ 下满量程 `40.96mV / 2mΩ = 20.48A`，与 `max_current: 20A` 匹配。
- 12A 时信号 24mV，占满量程 **58.6%**；15A 验证时 30mV，占 **73.2%**，都不削顶。
- ALERT pin 3 明确 NC，所以本板只有软件轮询，没有伪装成硬件过流关断。

**是否需要重出 PCB：不需要。**

---

## 🟢-5 I²C 电气连接与速率没有冲突

SDA/SCL 分别是 GPIO32/33，R52/R53 各 **4.7kΩ** 上拉到 3.3V；低电平静态电流约 `3.3/4.7k = 0.70mA`。YAML 使用 **100kHz**，低于 INA237 数据表第 7 页 fast-mode **400kHz** 上限。J9 Qwiic 与 U1 同总线且供电是 3.3V，没有 5V 混接。

**是否需要重出 PCB：不需要。**

---

## 🟢-6 预留 LD2410 UART 的引脚和串口参数正确

J10 网表是 pin1=5V、pin2=GND、pin3=`UART2_TX`、pin4=`UART2_RX`；注释中的 YAML 是 GPIO26 TX / GPIO27 RX、**256000 baud、NONE、1 stop bit**。ESPHome LD2410 官方文档与 Hi-Link LD2410 手册都给出相同默认串口参数；Hi-Link 还明确模块 5V 供电、UART IO **3.3V**，所以直接进入 ESP32 合法。

结论只适用于 LD2410/明确 3.3V UART 电平的传感器；J10 的“5V”是供电，不代表 GPIO27 可承受 5V TTL。

**是否需要重出 PCB：不需要。**

---

## 🟢-7 第一轮发现的 USB 自动下载接错已在当前网表中消失

当前 Q4 是 B=`RTS_B`、E=`RTS`、C=`EN`；Q5 是 B=`DTR_B`、E=`DTR`、C=`IO0`，不再是两个发射极接 GND。R11/R12 也分别把 DTR/RTS 交叉送往对方基极路径。EN 侧 R7=10k、C12=1µF，手动 BOOT/EN 仍是独立兜底。

这里只确认修复确实进入当前原理图；不重复第一轮的真值表推导。

**是否需要重出 PCB：不需要；现版已包含修复。**

---

## 🟢-8 R15=4.7k 后，健康输出在复位时确实由硬件关断

当前 BOM/网表已是 R14=10k、R15=4.7k、Q6 集电极到 `OE_N`，而 U6/U7 pin19 共接 `OE_N`、R13=10k 上拉到 5V。按 ESP32 strapping 内部上拉最坏 75µA，R15 在 0.7V 时能吸 `0.7/4.7k = 149µA`，Q6 不会在复位时误导通；`OE_N` 被拉高，HCT 输出高阻，12 个 MOS 栅极再由各自 10k 拉低。

这条只覆盖“控制链健康、MOS 没有 D-S 短路”的失效安全；不能替代 🔴-2 的真正负载总断路。

**是否需要重出 PCB：不需要；现版已包含修复。**

---

## 🟢-9 3.3V 不起与反接故障树里没有发现新的网表断链

24V 逻辑路径实际是 `J1 → F1 → Q1/Q2 → V24_PROT → PTC1 → U2 → D3 → V5_SYS → U3 → V3P3`；USB 刷机路径是 `J2 USB_VBUS → D4 → V5_SYS → U3 → V3P3`。D3/D4 是双路 diode-OR，24V 与 USB 单独供电都能到逻辑侧。Q1/Q2 为 D=`V24_FUSED`、S=`V24_PROT`、G=`PMOS_GATE`，R1 把 gate 拉地，方向与第一轮确认的防反拓扑一致。

所以若实板 3.3V 不起，优先按上述节点逐级量测，而不是怀疑 YAML GPIO；若 24V 反接，现网表没有绕过 Q1/Q2 的旁路。buck/AMS1117 的电压、热和上电时序数字沿用第一轮，不在本轮重复。

**是否需要重出 PCB：不需要。**

---

## 6. 下单门槛

在以下四项全部关闭之前，本轮结论是**不要下单**：

1. 为 LRS hiccup 与支路短路重新选定有证据的保护架构；
2. 决定是否保留“单颗 MOS 短路仍可全灭”的承诺；保留则加入真正高边总断路；
3. 修复并实测 12A 静态/动态限流和 INA 故障锁存；
4. 让当前 ESPHome 工具链通过 config + compile，并锁版本。

第一轮漏掉的最大一块不是某颗器件参数，而是**系统级保护协调与固件运行语义**：电源进入什么故障模式、保险丝是否真的得到足够 I²t、所谓“总断路”究竟断的是负载还是只断栅极，以及 API 调用是否真的改变了当前 PWM。这些都无法靠 DRC、几何检查或“函数存在且能编译”证明。
