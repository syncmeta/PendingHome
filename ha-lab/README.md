# ha-lab —— Home Assistant 试验台

在 Mac 上用 [Lima](https://lima-vm.io/) 起一台 **Debian 12 虚拟机**，桥接到家里的
局域网拿一个独立的 `192.168.1.x`，里面用 Docker 跑 Home Assistant。

目的是**模拟一台常开的 Linux 裸机**：在真机到位前，先把 HA、米家设备接入、
以及"无线鼠标当灯开关"这套玩法验通。验通之后配置可以基本平移到实体机。

> **三个目录的关系**（别搞混）
> - **本目录 `ha-lab/`** —— Mac 上的试验台，就是这份文档讲的东西。
> - **`../ha-home/`** —— 这套试验台要平移到的目标：**现在住的这个家**里那台
>   奔腾 G2030 台式机（8G 内存 + 固态，原来跑黑群晖）。装机和数据迁移方案都在那边。
> - **`../ha-t630/`** —— **另一个房子**里那台**惠普 t630 瘦客户机**的方案
>   （早期文档误写成「Dell T630」，实际是惠普）。它和上面两个**并存、互不取代**，
>   各管一处房子。别往那个目录里搬东西。

## 为什么非得桥接

Home Assistant 找小米/米家设备靠 mDNS(zeroconf) 和 SSDP，都是**局域网广播**。
虚拟机躲在 NAT 后面的话收不到这些广播，设备发现直接废掉。所以：

- 虚拟机走 `socket_vmnet` 的 **bridged** 模式，直接挂在物理网段上向路由器要 DHCP；
- HA 容器走 `network_mode: host`，和虚拟机共享网络栈。

代价是 socket_vmnet 需要一次性的 root 配置（见下面第 2 步）。

## 目录结构

```
ha-lab/
├── README.md
├── lima/
│   ├── networks.yaml            # Lima 全局网络配置（装到 ~/.lima/_config/）
│   ├── ha-lab.yaml              # 虚拟机定义：Debian 12 + 桥接 + 自动装 Docker
│   └── docker-http-proxy.conf   # 让 dockerd 走代理拉镜像（仅 Mac 试验台需要）
├── homeassistant/
│   ├── docker-compose.yml  # HA 容器定义（network_mode: host）
│   ├── docker-compose.lab-proxy.yml # Mac 试验台专用：HA 出站复用代理隧道
│   └── config/             # 空目录，仅作占位/备份用，不是运行时数据，见「数据在哪」
└── scripts/
    ├── 01-prepare.sh       # 装 networks.yaml            （不用 sudo）
    ├── 02-sudo-setup.sh    # 配 socket_vmnet + sudoers   （★ 要 sudo，人自己跑）
    ├── 03-vm-up.sh         # 建/启动虚拟机                （不用 sudo）
    ├── 04-ha-up.sh         # 部署并启动 Home Assistant    （不用 sudo）
    ├── proxy-tunnel.sh     # 拉镜像太慢时用：up/down/test （不用 sudo）
    ├── vm-ip.sh            # 打印虚拟机的局域网 IP
    └── status.sh           # 体检：前置条件/虚拟机/IP/容器/8123
```

## 从零搭起来

```bash
cd ~/Untitled/PendingHome/ha-lab

./scripts/01-prepare.sh                  # 1. 装网络配置
sudo bash ./scripts/02-sudo-setup.sh     # 2. 一次性 root 配置（只需做一次）
./scripts/03-vm-up.sh                    # 3. 建虚拟机（首次几分钟：下镜像 + 装 Docker）
./scripts/proxy-tunnel.sh up             #    （国内网络必需，见下节）
./scripts/04-ha-up.sh                    # 4. 起 Home Assistant
```

跑完第 4 步会打印 `http://192.168.1.x:8123`，Mac 浏览器打开就是 HA 的初始化页面。
随时 `./scripts/status.sh` 体检。

### 第 2 步到底动了系统什么

只碰三个路径，可重复执行：

| 路径 | 干嘛的 |
|---|---|
| `/opt/socket_vmnet/bin/socket_vmnet` | 从 Homebrew 那份复制过来，改成 root 所有。Lima 拒绝通过 sudo 执行普通用户可写的程序，所以不能直接用 `/opt/homebrew` 下那份。 |
| `/private/var/run/lima/` | socket_vmnet 放 pid 文件的地方，同样要求 root 所有。 |
| `/etc/sudoers.d/lima` | `limactl sudoers` 生成的免密规则，让 `limactl start` 能自动拉起 socket_vmnet。安装前脚本会 `visudo -c` 验语法并把内容打出来给你看。 |

卸载就是把这三个删掉。

## 拉镜像太慢 —— 代理隧道

HA 的镜像在 ghcr.io，实际文件由 GitHub 的 CDN 分发，这条线在国内基本被卡死
（实测 ~100 KB/s，576 MB 的镜像要一个多小时）。

**Mac 上挂了梯子也不管用** —— 虚拟机是桥接的，包直接走路由器出去，不经过 Mac 的 TUN。
而 Clash 默认只监听 `127.0.0.1`，虚拟机连 `192.168.1.25:10898` 也不通。

解法是用 lima 自带的 SSH 通道做反向端口转发，把 Mac 的 `127.0.0.1:10898` 映射进虚拟机，
**不需要改 Clash 任何设置**（不用开 Allow LAN）：

```bash
./scripts/proxy-tunnel.sh up     # 开隧道 + 让 dockerd 走它    实测 13 MB/s
./scripts/proxy-tunnel.sh test   # 看现在通不通、多快
./scripts/proxy-tunnel.sh down   # 撤掉，恢复直连
```

代理端口默认 10898，不一样就 `PROXY_PORT=xxxx ./scripts/proxy-tunnel.sh up`。

Dockerd 拉镜像和 HA 进程访问外网都走代理；局域网地址通过 `NO_PROXY` 直连，
所以米家设备发现和本地控制仍走局域网广播/单播。隧道断了不影响 HA 页面和本地设备，
但小米集成刷新云端信息、首次下载 MIOT 规格会失败。

HA 的代理放在单独的 `docker-compose.lab-proxy.yml` 覆盖层里。基础
`docker-compose.yml` 不含 Mac 专属代理，搬到实体机时只带基础文件即可。

### 实体机上怎么办（那边没有 Mac，也就没这条隧道）

实体机（`../ha-home/` 那台，或者另一个房子的 t630）如果同样拉不动 ghcr.io，
用国内镜像源，但**必须按 digest 拉，不要按 tag**：

```bash
# 从官方 ghcr.io 取权威 digest
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:home-assistant/home-assistant:pull&service=ghcr.io" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  https://ghcr.io/v2/home-assistant/home-assistant/manifests/stable
# 拿到对应架构的 digest 后，去镜像源按 digest 拉
docker pull <镜像站>/home-assistant/home-assistant@sha256:<digest>
```

按 digest 拉时 Docker 会校验内容哈希，镜像站换了内容会直接失败 —— 第三方源的供应链
风险被内容寻址堵住了。按 tag 拉没有这个保证，别图省事。

> 注意 `registry-mirrors` 那套只对 Docker Hub 生效，对 ghcr.io 无效；
> 而 `registry-1.docker.io` 在这台机器上完全连不上，所以走 Docker Hub 也不通。

## 日常操作

```bash
limactl stop ha-lab        # 关机
limactl start ha-lab       # 开机
limactl shell ha-lab       # 进虚拟机
limactl delete ha-lab      # 删掉重来（HA 数据一起没，先看下面备份）

# HA 日志
limactl shell ha-lab -- sudo docker logs -f homeassistant
# 重启 HA
limactl shell ha-lab -- sudo docker restart homeassistant
```

## 数据在哪

**HA 的运行时数据在虚拟机内的 `/opt/ha/config`，不在 Mac 上。**

之所以不用共享目录直接挂 Mac 的 `homeassistant/config/`：HA 的 recorder 用 SQLite，
跨 virtiofs/sshfs 的文件锁不可靠，容易把数据库写坏。

备份到 Mac：

```bash
limactl shell ha-lab -- sudo tar -czf - -C /opt/ha config \
  > ha-config-$(date +%Y%m%d).tar.gz
```

Mac 上的 `ha-lab/` 目录是**只读**挂进虚拟机的 `/mnt/ha-lab`，改这边的
`docker-compose.yml` 之后重跑 `./scripts/04-ha-up.sh` 就会同步进去并生效。

## 排障笔记（都是这台机器上真踩过的）

### 大文件下载卡死 / 极慢 —— MTU

这条网络的实际路径 MTU 是 **1480**，不是以太网默认的 1500。按 1500 发包时大包被上游
丢掉，而 ICMP「需要分片」的通知又回不来，形成黑洞：TCP 建连正常、小请求正常，
**只有批量下载会卡住**，特别像"网断了"但 ping 又通。

实测同一个文件：MTU 1500 → 266 KB/s，MTU 1480 → 887 KB/s。

已经写进 `lima/ha-lab.yaml` 的 networkd 配置里。**换网络环境要重新量**：

```bash
limactl shell ha-lab -- bash -c '
for s in 1452 1456 1460 1464 1472; do
  ping -c1 -M do -s $s 223.5.5.5 >/dev/null 2>&1 && echo "$s 通" || echo "$s 不通"
done'
```

最大那个「通」的数 + 28 就是该填的 `MTUBytes`。

### 量下载速度别忘了 `curl -L`

`cloud.debian.org/.../latest/` 和 GitHub release 链接都是 302 跳转。
不加 `-L` 量到的是跳转响应体那几百字节，会得出"到处都慢"的假结论。

### 找镜像下到哪了 —— 不在 /var/lib/docker

Docker 29 默认启用 containerd 镜像存储，镜像内容在 **`/var/lib/containerd`**。
盯 `/var/lib/docker` 会看到它一直不涨，误以为下载卡死：

```bash
limactl shell ha-lab -- sudo du -sh /var/lib/containerd
```

### `.local` 名字为什么解析不到

`homeassistant.local` 那个域名是 **Home Assistant OS 整机版**自带的服务广播出来的。
这台是「Debian 虚拟机 + Docker 跑 HA」，主机名叫 `lima-ha-lab`，而且一开始没装
负责广播 `.local` 的 avahi —— 所以全网没有任何机器认领那个名字，查不到是正常的。

**2026-08-11 已在这台虚拟机上补装了 `avahi-daemon`**，现在可以用
**http://lima-ha-lab.local:8123** 访问，不用记 IP 了（IP 会随 DHCP 变，名字不会）。
装的时候顺带把广播限制在桥接网卡上（`/etc/avahi/avahi-daemon.conf` 的
`allow-interfaces=lima0`）—— 否则 avahi 会把 docker0 的 `172.17.0.1` 也播出去，
局域网里的 Mac 拿到那个地址根本连不上。

实体机上叫什么、怎么配，见 `../ha-home/`：那台的主机名就是 `homeassistant`，
所以 `homeassistant.local` 会真正生效。

### 桥接的虚拟机用不上 Mac 的梯子

虚拟机桥接后，包直接从物理网口走路由器出去，**完全不经过 Mac 的 TUN**。
Mac 上挂着梯子、`curl` 飞快，虚拟机里却一动不动，就是这个原因。
解法见上面的「拉镜像太慢 —— 代理隧道」。

## 和实体机的差别

| | 试验台 | 实体机（`../ha-home/` 那台）|
|---|---|---|
| 架构 | arm64（Apple 芯片） | x86_64（奔腾 G2030）|
| 形态 | Lima 虚拟机 | 裸机 |
| 网络 | socket_vmnet 桥接 | 物理网口 |
| `.local` 名字 | 没有（主机名 `lima-ha-lab`，后来补装了 avahi）| `homeassistant.local`，装机时就配好 |

Docker 镜像是多架构的，`docker-compose.yml` 可以直接拿去实体机用；
`lima/` 下的东西是 Mac 专属的，搬不过去。

具体怎么搬、数据怎么带过去（不用重新登录米家），见 **`../ha-home/`**。

## 阶段二（进行中）

鼠标桥接程序在 `mouse-bridge/`：两只鼠标已识别为 `2717:003b` 和
`2717:501f`，控灯行为的 18 项逻辑测试已通过。等待 Xiaomi Home 登录完成、
两盏灯生成实体后，把真实 `light.*` 实体 ID 写入 `mouse-bridge/config.json`
并做最终联调；不要在实体出现前填写占位值。
