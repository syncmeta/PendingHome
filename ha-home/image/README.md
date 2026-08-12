# 写盘即用的系统镜像

一个 **x86_64 的磁盘镜像**：写进那块 120G 固态、把盘装回台式机、插网线、开机，
它自己就配好了 —— 不用插 U 盘、不用接显示器、不用跑安装程序、不用手动敲一条命令。

开机之后直接打开 **http://homeassistant.local:8123**，里面是现在这套 Home Assistant
的原样搬迁：米家不用重登、262 个实体都在、那两盏灯的实体 ID 没变。

> 为什么走这条路而不是做 U 盘装系统：你的 Mac 是 ARM 芯片，那台奔腾是 Intel，
> 没法在 Mac 上跑 Intel 的安装程序。但**造一个镜像**可以 —— 镜像是数据，
> 组装它跟 CPU 架构无关。装机指南（`../README.md`）留着当 B 计划。

---

**镜像文件**：`ha-home-20260811.img.gz`（1.6GB，解开是 6GB）
`sha256 = b3faa962e38ccc4f9c5dbaf36f63df92f8d0ce0593e5a7141c58f30e39c8bbac`

> ⚠️ 这个文件里带着米家的登录凭据和 HA 的访问令牌 —— **别外传、别丢网盘**。

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

### 验证记录（2026-08-11）

**没有停在「结构看起来对」——把这个镜像在 x86 模拟器里真的开机跑了。**
（Lima 虚拟机里 `qemu-system-x86_64` 全系统模拟；试启动都走 qcow2 覆盖层，
原镜像全程只读，一个字节都没被改。）

| 验的东西 | 怎么验的 | 结果 |
|---|---|---|
| 传统 BIOS 能不能引导 | SeaBIOS + `-machine pc` | ✅ 38 秒到登录提示 |
| UEFI 能不能引导 | OVMF 固件 + `-machine q35` | ✅ 同样正常起来 |
| 主机名 | 串口登录提示 | ✅ `homeassistant login:` |
| cloud-init 首启配置 | 看串口日志 + 事后挂载客机磁盘 | ✅ 用户 `hey` 建好、SSH 公钥装好、时区 Asia/Shanghai |
| 有没有服务启动失败 | 抓串口里的 FAILED | ✅ 一个都没有 |
| 预置镜像装载 | 首启日志 | ✅ `docker load` 成功，压缩包自动删除回收空间 |
| **Home Assistant 真的跑起来** | 首启日志 + 端口转发出来 curl | ✅ **HTTP 200，页面标题 `Home Assistant`，API 返回 401（要令牌，说明活着）** |
| 鼠标桥的判断逻辑 | 模拟器里只有一只 PS/2 鼠标 | ✅ 正确识别为「配置里那两只都没插」，设成自启但不启动 |
| **断电重启能不能自己回来** | 关掉再开一次 | ✅ 29 秒起来，首启脚本没重复跑，HA 自动回来 |

**仍然没验、也没法在这儿验的**：那块 2013 年主板到底认不认这块盘、它的网卡驱动够不够。
这两条只有真机上电才知道。

### 真机上电结果（2026-08-11 13:04，奔腾 G2030）

上面那两条「只有真机才知道」的，真机给了答案：**主板认盘、板载网卡 `enp2s0` 驱动自带，一次点亮。**

| 项目 | 结果 |
|---|---|
| 引导 | ✅ 一次成功，没进 BIOS 调过任何东西 |
| 磁盘自动扩容 | ✅ 6GB 镜像自己撑满整盘（`/` = 110G，用了 4.9G） |
| 网络 | ✅ `enp2s0` DHCP 拿到 192.168.1.29 |
| `homeassistant.local` | ✅ Mac 上直接解析并 ping 通，avahi 正常 |
| HA | ✅ HTTP 200，262 个实体、米家集成、两盏灯的绑定全都在，**没有重新登录** |
| 失败的服务 | ✅ 一个都没有 |

### ⚠️ 迁移完必须停掉老虚拟机（否则米家全线掉线）

真机起来后出现过一次「HA 能开，但 262 个实体里 245 个 unavailable」。
**根因不是新机器有问题，是新旧两台在互相踢。**

米家集成的云端 MQTT 客户端 ID 是跟着凭据走的，迁移把凭据整套复制过去，
两台就有了**完全相同的客户端 ID**（实测两边都是 `ha.fe0000c4af0e58ee428e97226ad77776`）。
MQTT broker 遇到同 ID 会把先连的踢掉，于是两台无限互踢，谁都稳不住 ——
日志表现是 `mips disconnect` / `mips try reconnect after 10s` 每 10 秒一次。

**处理**：把老虚拟机上的 HA 停掉即可（`limactl shell ha-lab -- sudo docker stop homeassistant`）。
实测停掉后新机马上接上 broker，unavailable 从 245 掉到 8（剩的 8 个是电饭煲/热水器
这类本来就没通电的设备，外加一个已知的 `humidity-range` 上游 bug 实体），90 秒内零断开。

> 结论：**这套凭据同一时刻只能有一台 HA 在用。** 想回退到虚拟机，就得反过来先停真机。

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
