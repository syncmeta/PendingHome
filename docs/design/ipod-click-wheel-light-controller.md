# iPod Click Wheel 无线灯光控制器 — 方案

日期：2026-08-08

## 目标

把一台报废的 iPod 改造成桌面灯光控制器：转动 click wheel 调亮度，按键切场景，通过 WiFi 控制现有的 ESPHome 灯带板。

## 硬件选型

| 项 | 选择 | 理由 |
|---|---|---|
| 主体机身 | **iPod 4 代全尺寸（A1059）** | 原本装 1.8 吋硬盘，掏空后内部空间宽裕，塞主控板和电池最省事 |
| 备件 | iPod mini 一代（A1051） | 同代 Synaptics 滚轮，可作替换件；铝壳内部无余量，不适合做主体 |
| 主控 | Seeed XIAO ESP32-C3（20×17mm） | 体积小、自带锂电充电电路、ESPHome 一等支持 |
| 电池 | 3.7V 锂电 500–1000mAh，带保护板 | 直接接 XIAO 的 BAT 焊盘，充放电由板载电路管 |
| 充电口 | XIAO 自带 Type-C，从原底座口位置开孔引出 | 免去额外充电模块 |
| 屏幕 | **不做** | 原灰阶屏驱动是大坑；灯带本身即反馈 |

## 软件架构

```
[click wheel] --MEP/SPI--> [ESP32-C3 跑 ESPHome] --WiFi--> [Home Assistant] --> [灯带 ESPHome 板]
```

- ESP32 上跑 ESPHome，通过一个**自定义组件**读取 click wheel。
- 组件对外暴露：
  - `sensor`：累计旋转量（或增量事件）
  - `binary_sensor` × 5：中键、菜单、播放/暂停、上一首、下一首
- Home Assistant 侧用自动化把这些绑到现有灯带实体：滚轮 → 亮度，中键 → 开关，前后键 → 切场景。
- 灯光逻辑全部留在 HA 的 YAML/自动化里，不写进固件——以后改玩法不用重新刷板。

## click wheel 接口

滚轮由 Synaptics **T1005** ASIC 驱动，走 Synaptics 的 **MEP 协议**（类 SPI 的同步串行）。默认 auto 模式下以 80Hz 主动推送 32 位数据包，高字节在前、MSB 在前、时钟前沿采样；每个包最低字节固定为 `0x1a`，用它做帧同步。

现成参考实现（已确认在 4 代/Photo 上工作）：
- 协议文档：https://github.com/Gigahawk/clickwheel_reverse_eng
- 示例固件：https://github.com/Gigahawk/clickwheel_sample_firmware

引脚定义**以实物拆开后对照上述 repo 的针脚图核对为准**，不要照抄网上其他型号的图。基本信号只有四根：3.3V、GND、CLK、DATA。

## 主要风险与对策

1. **FPC 排线焊接（唯一真正的手工难点）**
   click wheel 的排线很细，直接飞线对新手不友好。对策：买对应间距的**免焊 FPC 翻盖式插座 + 转接小板**（俗称 FPC 转直插 breakout），把排线插进去，再从转接板的 2.54mm 排针接杜邦线到 ESP32。这样全程只焊 4 根粗线。
   → 拆机第一步先量排线的针数和间距，再买对应型号的转接板。

2. **滚轮供电电压**
   T1005 是 3.3V 器件，必须接 ESP32 的 3.3V 引脚，不能接 5V。

3. **不确定滚轮是否完好**
   机器是坏的，但坏的通常是硬盘或电池，滚轮多半没事。有第二台 mini 可换。

## 分阶段实施

**阶段 1：桌面验证（不装机）**
拆下 click wheel，用转接板 + 杜邦线接到 XIAO，刷 Gigahawk 的示例固件，串口能打印出旋转量和按键 → 通路验证完成。这是第一个里程碑，在此之前不要动机身。

**阶段 2：ESPHome 组件**
把读取逻辑封装成 ESPHome external component，暴露 sensor / binary_sensor，接入 WiFi 和 Home Assistant，在 HA 里看到实体跳动。

**阶段 3：装机**
掏空 A1059，固定 ESP32 和电池，从原底座口位置开孔引出 Type-C，合壳。

**阶段 4：灯光联动**
在 HA 里写自动化，绑定现有灯带板，调手感（滚轮灵敏度、加速曲线、防抖）。

## 不做的事（YAGNI）

- 不驱动原屏
- 不保留原 iPod 固件或任何播放功能
- 不做蓝牙 / ESP-NOW 直连灯带——已有 HA，走 HA 最省事也最好改
- 不改造 mini（A1051），它只当备件
