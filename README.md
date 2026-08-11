# PendingHome

家里这套智能家居的全部工程文件：Home Assistant 部署、自制传感器节点固件、以及一块自己画的灯驱动板。

## 目录

| 目录 | 是什么 |
|---|---|
| [`ha-home/`](ha-home/) | 现在住这个家的 HA 装机方案 —— 台式机跑 Debian + Docker，含开机自配置的系统镜像 |
| [`ha-lab/`](ha-lab/) | Mac 上的试验台（Lima 虚拟机），`ha-home` 就是把它平移过来的。搬完可退役 |
| [`ha-t630/`](ha-t630/) | **另一个房子**那台惠普 t630 瘦客户机的方案，跟 `ha-home` 各管一处、并存 |
| [`sensor-nodes/`](sensor-nodes/) | ESPHome 传感器节点固件（CO₂、光谱、门窗磁），含选购清单 |
| [`docs/`](docs/) | 跨项目的设计文档 |
| `cct-driver/` | 6 路 CCT 灯驱动板（KiCad + ESPHome）—— **独立仓库**，不在本库里，见下 |

`t630-*.sh` 是 t630 那台机器的裸机引导脚本。

## cct-driver 为什么单独一个库

那块板子有自己的完整提交历史（KiCad 工程、Gerber、DFM 复验记录），并且由独立的一组人/会话在推进，
所以留在自己的私有仓库里：<https://github.com/syncmeta/cct-driver>

本地它就在 `cct-driver/` 子目录下，本库通过 `.gitignore` 跳过它。要拿全套：

```sh
git clone git@github.com:syncmeta/PendingHome.git
cd PendingHome && git clone git@github.com:syncmeta/cct-driver.git
```

## 不进版本库的东西

私有仓库也一样不放凭据和大文件，`.gitignore` 挡掉了这些：

- **凭据** —— `.env`（HA 长期访问令牌）、`secrets.yaml`（WiFi/OTA 密码）、`mouse-bridge/config.json`
  （各仓库都留了 `*.example` 模板，照着复制一份填自己的）
- **迁移备份包** `*.tgz` —— 里面有米家证书私钥和 HA 账号
- **磁盘镜像** `*.img.gz` —— 1.5GB，且含上面那些凭据。用 `ha-home/image/build-image.sh` 重新造
- **构建产物** —— `.esphome/`、Swift 编译出来的 `mouse-source`
