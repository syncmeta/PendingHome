# 写盘即用的系统镜像

一个 **x86_64 的磁盘镜像**：写进那块 120G 固态、把盘装回台式机、插网线、开机，
它自己就配好了 —— 不用插 U 盘、不用接显示器、不用跑安装程序、不用手动敲一条命令。

开机之后直接打开 **http://homeassistant.local:8123**，里面是现在这套 Home Assistant
的原样搬迁：米家不用重登、262 个实体都在、那两盏灯的实体 ID 没变。

> 为什么走这条路而不是做 U 盘装系统：你的 Mac 是 ARM 芯片，那台奔腾是 Intel，
> 没法在 Mac 上跑 Intel 的安装程序。但**造一个镜像**可以 —— 镜像是数据，
> 组装它跟 CPU 架构无关。装机指南（`../README.md`）留着当 B 计划。

---

## 一、写盘（这一步不可恢复，看清楚再动手）

⚠️ **`of=` 后面的盘号写错，就会把那块盘上的东西全毁掉。**
下面每次操作前都先 `diskutil list` 核对一遍：容量是 **120.0 GB**、名字里有 **绿联/UGREEN**
或标着 **external, physical**。

```bash
# 1. 核对盘号（下面假设是 /dev/disk10，你的可能不一样）
diskutil list

# 2. 卸载（不是弹出）
diskutil unmountDisk /dev/disk10

# 3. 写入。用 rdisk（带 r）快得多，几分钟的事
gunzip -c ha-home-<日期>.img.gz | sudo dd of=/dev/rdisk10 bs=4m

#    看进度：dd 跑起来后按 Ctrl+T，会打印已写了多少
#    （macOS 自带的 dd 没有 status=progress）

# 4. 落盘并弹出
sync
diskutil eject /dev/disk10
```

镜像是 6GB，写完盘上其余 114GB 是空的 —— **第一次开机会自动把根分区撑满整块盘**，
不用你管。

## 二、装回机器，开机

1. 把固态从硬盘盒里拆出来，装回台式机。
2. **插网线**（接路由器）。第一次开机建议别用 Wi-Fi —— 这台机器上没配无线。
3. 通电开机。**不需要接显示器和键盘**，但第一次开机接着更安心（能看见它在干什么，
   屏幕上会有 `[ha-home] ...` 的中文进度行）。
4. 如果机器不从这块盘启动，进 BIOS（开机点 `Del`，少数是 `F2`）把它调成第一启动项。
   > 这块盘上 **传统 BIOS 和 UEFI 两种引导方式都做好了**，主板是哪种都能起。

## 三、等它自己配好

首次开机它会依次做：撑满分区 → 建账号 → 起 Docker → 装载预置的 Home Assistant
容器镜像 → 起 HA → 有鼠标接收器就把鼠标桥也拉起来。

**大约 3~5 分钟。** 那台机器是 2013 年的双核，装载容器镜像那步慢一点，属正常。

然后打开：

**http://homeassistant.local:8123**

看到熟悉的界面、灯能点，就成了。

## 四、之后怎么进这台机器

```bash
ssh hey@homeassistant.local          # Mac 上的密钥已经预置好了，不用输密码
```

坐在机器前用键盘登录（SSH 进不去时的后路）：用户名 `hey`，密码 `homeassistant`。
> 这个密码**只能在机器本地的键盘上用** —— SSH 那边是纯密钥、关掉了密码登录，
> 所以它弱一点也不会变成网络上的口子。**登进去之后建议 `passwd` 改掉。**

机器上的常用命令：

```bash
~/ha-home/status.sh                       # 体检
sudo cat /var/log/ha-firstboot.log        # 首次开机都干了什么
sudo docker logs -f homeassistant         # HA 日志
sudo systemctl status mouse-bridge        # 鼠标桥
```

## 五、万一没起来

按顺序排查，把看到的告诉我：

| 现象 | 多半是 |
|---|---|
| 屏幕一直黑 / 提示找不到启动盘 | BIOS 没把这块盘设成第一启动项；或者盘没插好 |
| 能看到 Debian 启动、卡在某处 | 把屏幕上最后几行拍给我 |
| 起来了但 `homeassistant.local` 打不开 | 网线没插 / 路由器没给到地址。接键盘登录后跑 `ip -4 addr`，把 IP 告诉我，先用 `http://<IP>:8123` |
| 打得开但 HA 页面 502 / 转圈 | 还在启动，等两分钟；仍不行看 `sudo docker logs homeassistant` |

**这块盘上原来的东西已经没了，但你的 HA 数据一份没丢** —— 完整备份在
`ha-home/migrate/` 下那个包里，虚拟机里也还有一份。最坏情况重做一次镜像就是了。

---

## 这个镜像是怎么造出来的（给以后的自己看）

三个脚本，都在本目录：

| 脚本 | 在哪跑 | 干嘛 |
|---|---|---|
| `build-image.sh` | Lima 虚拟机里（root） | 组装镜像 |
| `verify-image.sh` | Lima 虚拟机里（root） | 挂起来逐项体检 |
| `firstboot.sh` | 被打进镜像，首次开机跑一次 | 只做「必须等到真机器上」的事 |

底座是 **Debian 12 官方 amd64 `generic` 云镜像**（不是 `genericcloud` —— 后者只带
虚拟机驱动，裸机会缺网卡驱动）。校验过官方 SHA512。

组装是在 arm64 的 Lima 虚拟机里做的，靠 `qemu-user-static` + binfmt 在 chroot 里
跑 amd64 的 apt/dpkg。这样 Docker、avahi、网卡固件、Intel 微码全部**在造镜像时就装好**，
目标机开机不用联网装任何东西 —— 尤其不用去 ghcr.io 拉 600MB 的 HA 镜像
（那条线在国内实测慢到没法用，已经把镜像存成 tar 打进去了）。

```bash
sudo ./build-image.sh \
  --base       /var/tmp/build/disk.raw \        # 官方镜像解包出来的
  --ha-image   /var/tmp/build/ha-image.tar.gz \ # docker save --platform linux/amd64
  --ha-config  /var/tmp/build/ha-config.tgz \   # migrate/01-backup-from-lab.sh 导出的
  --ssh-key    ~/.ssh/id_ed25519.pub \
  --token-file /var/tmp/build/token.env \       # 只含 HA_TOKEN= 那一行
  --out        /var/tmp/build/ha-home.img
sudo ./verify-image.sh /var/tmp/build/ha-home.img
```

### 踩过的坑（都写进脚本注释里了）

- 镜像里的 `/etc/resolv.conf` 是指向 systemd-resolved 的**软链**，chroot 里没有
  resolved 在跑，直接 cp 过去 DNS 全废，apt 一律「Temporary failure resolving」。
- `download.docker.com` 在这条网络上直接被重置连接，Docker 的签名密钥改从 USTC 取，
  **但校验了官方指纹**，来源不影响可信度。
- Debian 官方 apt 源实测 27 KB/s，USTC 12 MB/s，构建时换掉（最终镜像里也留着国内源）。
- `docker save` 默认会把**多架构全都存进去**（arm64 + amd64，1.2GB）。
  必须 `--platform linux/amd64`，只存要的那份，615MB。
- cloud-init 里设 `locale: zh_CN.UTF-8` 会失败（基础镜像里没这个 locale），
  连带 `cloud-config.service` 变成 FAILED。已去掉，系统语言不影响 HA 界面语言。
