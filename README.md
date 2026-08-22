<p align="center">
  <img src="docs/app-icon.png" width="128" alt="PendingHome 图标" />
</p>
<h1 align="center">PendingHome</h1>

<p align="center">
  一个人给自己家做的智能家居，从装机到排障的完整档案
  <br />
  <em>不是能拿去直接用的通用方案，是「这套具体的硬件、在这个具体的网络里，怎么一步步装起来、又怎么修好的」</em>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue" /></a>
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-Docker-41BDF5?logo=homeassistant&logoColor=white" />
  <img alt="ESPHome" src="https://img.shields.io/badge/ESPHome-ESP32--C3-000000?logo=espressif&logoColor=white" />
  <img alt="Zigbee" src="https://img.shields.io/badge/Zigbee-ZHA-EB0443" />
</p>

一套自建智能家居的工程文件：Home Assistant 的装机与部署方案、自己写的 ESPHome
传感器节点固件、Zigbee 接入的排障记录，以及配套的设计文档。

<!-- 截图/照片位：这里适合放两张 —— 一张 HA 仪表盘、一张传感器节点实物。
     图片只能人工补，文件放 docs/img/ 下。 -->

> **这是一个人的实验项目，不是产品。**
>
> 整套东西**不能 clone 下来直接用** —— 里面是具体的机器、具体的设备、具体的局域网。
> 下面的「做到哪儿了」一节写清了哪几处真的在跑、哪几处连静态校验都没跑过。
>
> 文档是中文的。
>
> *(A personal experiment, not a product. Chinese-language docs.
> These are one person's home-lab files, not a reusable recipe.)*

## 快速开始

**没有「装一下就能用」这条路。** 这是一份档案，不是发行版。按你的目的挑一处开始读：

| 你想干什么 | 从这儿读 |
|---|---|
| 照着装一套 HA | [`ha-home/README.md`](ha-home/README.md) —— 台式机 + Debian + Docker 的完整装机流程 |
| 看 Zigbee 到底怎么排障 | [`ha-home/zigbee/README.md`](ha-home/zigbee/README.md) —— 一份真实的排障记录，比设计文档有用 |
| 抄传感器节点的固件 | [`sensor-nodes/firmware/`](sensor-nodes/firmware/) —— ESPHome 配置，注意还没上过真机 |
| 把摄像头接进 HomeKit | [`ha-t630/README.md`](ha-t630/README.md) —— 瘦客户机 + Scrypted + 大华摄像头（含 HKSV） |

## 里面有什么

| 目录 | 是什么 |
|---|---|
| [`ha-home/`](ha-home/) | 主力 HA 部署：台式机跑 Debian + Docker，含一套能造出**开机自配置**系统镜像的脚本，以及 Zigbee 接入的现场排障记录 |
| [`ha-t630/`](ha-t630/) | 另一处房子的方案：惠普 t630 瘦客户机，HA + Scrypted 把大华摄像头接进 HomeKit（含 HKSV） |
| [`ha-lab/`](ha-lab/) | Mac 上的 Lima 虚拟机试验台。`ha-home` 就是从它平移过来的，现已退役 |
| [`sensor-nodes/`](sensor-nodes/) | ESP32-C3 传感器节点的 ESPHome 固件（CO₂、光谱、门窗磁），含选购清单 |
| [`docs/`](docs/) | 跨项目的设计文档 |
| `cct-driver/` | 6 路 CCT 灯驱动板（KiCad + ESPHome）—— **独立仓库**，见下 |

顶层的 `t630-*.sh` 是给 t630 那台机器做裸机引导（USB 直连 / PXE）的 Mac 侧脚本。

## 状态：做到哪儿了

如实写，免得看着像"全都跑起来了"：

- **`ha-home` 在跑。** HA + Docker + 米家集成 + Zigbee（ZHA，网络型协调器走 TCP）。
  "Zigbee 开关按一下 → 餐厅灯翻转"这条链路有完整的实测记录，连续按也成立。
  遗留问题在 [`ha-home/zigbee/README.md`](ha-home/zigbee/README.md) 末尾列着。
- **`ha-t630` 装机流程写完了，摄像头参数实测过**，但它是另一处房子的机器，
  和 `ha-home` 各管一处、并行存在。
- **`sensor-nodes` 的固件还没上过真机** —— 硬件没到货，这是"到货直接刷"的模板，
  连 `esphome config` 静态校验都没跑过（本机没装 esphome）。
  固件目录的 README 里自己标注了哪些部分没能验证。
- **`ha-lab` 已退役**，留着是因为 `ha-home` 的不少决定能在它的记录里找到出处。
- 没有测试，也没有 CI。这类东西的验证方式就是装到机器上看它跑不跑。

## 外人能从这儿拿走什么

整套东西不能直接用，但有几块可以单独抄：

- [`sensor-nodes/firmware/`](sensor-nodes/firmware/) 的 ESPHome 配置用 `packages:`
  做复用，三个节点共享一套 `common/`，只靠"引入了哪几个包"来区分。
  其中 AS7341 八通道光谱 → 色温的换算是自己推的，写在文件头。
- [`ha-home/image/`](ha-home/image/) 造的是**开机自配置**的 Debian 镜像：
  插上就自己联网、装好 Docker、拉起 HA，不用坐在机器前敲。
- [`ha-home/zigbee/README.md`](ha-home/zigbee/README.md) 是一份真实的排障记录 ——
  从"按键信号在发但 HA 看不见"一路查到"协调器 IP 漂了"、"一次按压有两个边沿"，
  最后靠一个自定义 ZHA quirk 收尾。想看这类问题实际怎么定位，这份比设计文档有用。

## 关于文档里的局域网地址

文档里有具体的内网地址（`192.168.1.x`）、设备 MAC 和协调器序列号。这些是
**RFC1918 私网地址，外网够不着**。留着是因为排障记录一旦换成占位符就读不懂了 ——
"协调器从 `.28` 漂到 `.32`、ARP 表里能看到、于是在路由器上按 MAC 绑死"这段话，
把数字抹掉就只剩废话。装机说明里那些一次性的地址已经写成"假设 `192.168.1.50`"。

如果你是照着这套东西做自己的：这些数字对你没有意义，全部换成你自己的。

## cct-driver 为什么单独一个库

那块板子有自己的完整提交历史（KiCad 工程、Gerber、DFM 复验记录），
所以留在自己的仓库里：<https://github.com/syncmeta/cct-driver>

本地它就在 `cct-driver/` 子目录下，本库通过 `.gitignore` 跳过它。要拿全套：

```sh
git clone git@github.com:syncmeta/PendingHome.git
cd PendingHome && git clone git@github.com:syncmeta/cct-driver.git
```

## 不进版本库的东西

凭据和大文件一律不入库，`.gitignore` 挡掉了这些：

- **凭据** —— `.env`（HA 长期访问令牌）、`secrets.yaml`（WiFi/OTA 密码）、
  `mouse-bridge/config.json`。各处都留了 `*.example` 模板，照着复制一份填自己的
- **迁移备份包** `*.tgz` —— 里面有米家证书私钥和 HA 账号
- **磁盘镜像** `*.img.gz` —— 1.5GB，且含上面那些凭据。
  用 `ha-home/image/build-image.sh` 重新造
- **构建产物** —— `.esphome/`、Swift 编译出来的 `mouse-source`

## 参与

这是个人给自己家做的东西，issue 和 PR 都欢迎，但作者不保证响应速度，也不承诺路线。
里面很多决定只对这一套具体硬件成立，照抄前先看清楚是不是你的场景。

## 许可

MIT，见 [LICENSE](LICENSE)。

---

<sub>本 README 全文由 Claude 撰写。「做到哪儿了」一节的结论来自仓库里的实测记录与目录核对
（哪几处有实测记录、哪几处连静态校验都没跑过），不是从旧文档转抄。</sub>
