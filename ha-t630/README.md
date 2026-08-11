# Home Assistant + Scrypted on HP t630 (Debian + Docker)

面向:惠普 t630(AMD GX SoC + 8GB,系统装 M.2 SSD),运行 Home Assistant + 大华摄像头经 Scrypted 接入 HomeKit(HKSV)。

## 摄像头现状(已实测,192.168.1.108 / IPC-X12-B-V2)

- 视频:H.264 High,主码流 1080p25 / 子码流 D1,智能编码关,I 帧 50 —— **纯直通,零转码**
- 音频:不需要 → Scrypted 里设 No Audio
- 大华后台无需改动

---

# 安装流程(照阶段走,每个 ✋ 处停下把输出贴给 Claude)

## 阶段 0 · 准备
- 一个 ≥2GB U 盘(会被清空)
- t630 接上显示器 + 键盘(装系统时用)
- Debian 12 netinst 镜像:https://www.debian.org/download (amd64 「netinst」约 700MB)

## 阶段 1 · 在 Mac 上做启动盘
推荐用 **balenaEtcher**(https://etcher.balena.io ,图形界面、不会选错盘):选 ISO → 选 U 盘 → Flash。

> 命令行党可用 dd:`diskutil list` 找到 U 盘 diskN → `diskutil unmountDisk /dev/diskN` → `sudo dd if=~/Downloads/debian-*.iso of=/dev/rdiskN bs=4m && sync`(**认准 diskN,别写错盘**)。

## 阶段 2 · 在 t630 上装 Debian
1. 插 U 盘,开机狂按 **F9**(HP 引导菜单),选 USB 启动。
2. 选 **Install**(文字安装即可),一路默认到磁盘分区。
3. **分区:选「使用整个磁盘」→ 认准那块 M.2 SSD**(通常显示为容量较大的 `/dev/sda`;别选到 t630 内置的小容量 eMMC/flash)→「将所有文件放在同一分区」→ 完成并写入。
4. 软件选择(tasksel)界面:**只勾 `SSH server` 和 `standard system utilities`**,把「GNOME/桌面环境」全部**取消**(服务器不要桌面)。
5. 设主机名建议 `ha-t630`,建一个普通用户(记住用户名/密码),装 GRUB 到那块 SSD。
6. 装完拔 U 盘重启。

✋ **检查点 A**:重启后在 t630 上登录,运行下面命令,把输出贴给我:
```bash
ip -4 addr show | grep inet          # 看 t630 的局域网 IP
lsblk                                # 确认系统在 M.2 SSD 上
```

## 阶段 3 · 从 Mac 远程接管
拿到 t630 的 IP(假设 192.168.1.50)后,回到 Mac:
```bash
ssh <你的用户名>@192.168.1.50        # 首次会问指纹,yes
```
把本项目文件夹传上去:
```bash
# 在 Mac、ha-t630 的上级目录执行
scp -r ha-t630 <你的用户名>@192.168.1.50:~/
```

## 阶段 4 · 一键装 Docker
在 t630(ssh 里):
```bash
cd ~/ha-t630
chmod +x bootstrap.sh
./bootstrap.sh
```
跑完按提示 **exit 退出 ssh 再重连**(让 docker 用户组生效)。

✋ **检查点 B**:重连后运行,贴给我:
```bash
docker --version && docker compose version
groups | tr ' ' '\n' | grep docker   # 应看到 docker
```

## 阶段 5 · 起服务
```bash
cd ~/ha-t630
docker compose up -d
docker compose ps
```
✋ **检查点 C**:把 `docker compose ps` 输出贴给我(两个容器都应 running / healthy)。
顺手验证 t630 能读到摄像头:
```bash
ffprobe -v error -rtsp_transport tcp -show_entries stream=codec_name,width,height \
  "rtsp://admin:<密码>@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0"
```

## 阶段 6 · Home Assistant 初始化(浏览器)
- 打开 `http://192.168.1.50:8123` → 创建账户、设地区/时区 → 完成引导。

## 阶段 7 · Scrypted 接摄像头 + HomeKit(浏览器)
- 打开 `https://192.168.1.50:10443`(自签证书,浏览器点「继续」),创建账户。
- 装插件:**Dahua**(或通用 RTSP)、**HomeKit**、**Rebroadcast**。
- 添加摄像头:IP `192.168.1.108`,账号 `admin`,密码=你的;主码流 `subtype=0`,子码流 `subtype=1`。
- 摄像头设置里 **音频 = No Audio / 禁用**(纯视频,最省资源)。
- 摄像头 → HomeKit → 勾 **HomeKit Secure Video**,录像流选主码流、预览/侦测用子码流。
- iPhone「家庭」App → 添加配件 → 扫 Scrypted HomeKit 桥的配对码 → 给摄像头选房间并开启「录像」。

## 阶段 8 · 备份(定时)
```bash
# 整个 config + scrypted volume 就是全部状态
crontab -e
# 加一行:每天 3:30 打包到家目录(保留最近 7 天可自行加清理)
30 3 * * * tar czf ~/ha-backup-$(date +\%F).tgz -C ~/ha-t630 homeassistant/config scrypted/volume
```

---

## 备用:硬件转码
当前零转码。将来若接入需要转码的摄像头:在 `docker-compose.yml` 取消 `/dev/dri` 那几行注释,宿主机 `sudo apt install mesa-va-drivers`,再 `docker compose up -d`。

## 负载预期
纯 H.264 直通、无音频转码,3 路 HKSV 在 8GB t630 上极宽裕。
