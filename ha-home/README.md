# ha-home —— 家里那台台式机的 Home Assistant 装机方案

把现在跑在 Mac 虚拟机里的那套 Home Assistant **原样搬到一台常开的实体机**上，
搬完不用重新登录米家、不用重配集成，两只无线鼠标继续当灯的开关。

| | |
|---|---|
| 机器 | 台式机，Intel 奔腾 G2030（Ivy Bridge 双核 3.0GHz，x86_64），8GB 内存，固态硬盘 |
| 位置 | 现在住的这个家 |
| 原来跑什么 | 黑群晖（**装系统会整盘擦除；2026-08-11 已确认盘上没有要保留的数据**） |
| 装什么 | Debian 12 + Docker + Home Assistant 容器（`network_mode: host`） |
| 访问地址 | `http://homeassistant.local:8123` |

> ## 🚀 先看这个：现在有更快的一条路
>
> 那块固态已经拆下来接到 Mac 上了，所以不用再做 U 盘、跑安装程序 ——
> 我们直接**造了一个写进去就能开机自己配好的系统镜像**。
>
> **走这条：[image/README.md](image/README.md)**（写盘 → 装回机器 → 插网线 → 开机 → 完事）
>
> 下面这份分阶段装机指南**留着当 B 计划**：镜像那条路万一走不通（比如主板认不出这块盘），
> 就回来照这份从 U 盘装。两条路殊途同归，最终跑起来的是同一套东西。

> **和另外两个目录的关系**
> - `../ha-lab/` 是 Mac 上的试验台（Lima 虚拟机），本方案就是把它平移过来。搬完可以退役。
> - `../ha-t630/` 是**另一个房子**那台惠普 t630 瘦客户机的方案，跟这台各管一处、并存，
>   互不取代。**不要动那个目录。**

## 为什么不用 Home Assistant 官方整机版（HA OS）

因为鼠标控灯。鼠标接收器要插在这台机器上，读 `/dev/input/event*` 得在宿主系统里
跑一个自己的常驻进程。HA OS 是个封闭的一体化系统，往里塞这种东西很别扭。
用 Debian 就什么都能放，而且现在虚拟机里跑的就是这套，搬过去几乎零改动。

## 这个目录里有什么

```
ha-home/
├── README.md                 ← 你在看的这份，照阶段走
├── MIGRATION.md              数据迁移方案（阶段 5 展开讲）
├── deploy.sh                 【Mac 上跑】把整套东西推到实体机
├── bootstrap.sh              【机器上跑】Docker + avahi + 主机名 + 日志上限
├── docker-compose.yml        HA 容器定义（从 ha-lab 平移，去掉 Mac 专用代理层）
├── ha-up.sh                  【机器上跑】起 / 更新 Home Assistant
├── status.sh                 【机器上跑】体检，出问题先跑这个
├── backup.sh                 【机器上跑】每日备份，装进 cron
├── migrate/
│   ├── 01-backup-from-lab.sh 【Mac 上跑】从虚拟机导出数据包
│   └── 02-restore.sh         【机器上跑】恢复到新机器
└── mouse-bridge/
    ├── README.md             Linux 上怎么接鼠标（权限 / 自启 / 排查）
    ├── install.sh            装成 systemd 服务
    ├── run.sh                启动包装
    └── mouse-bridge.service  systemd 单元
```

**验证情况先说清楚**：这台机器还没到手，所以**装系统那几个阶段（0–3）全部未在硬件上
验证**，是照 `../ha-t630/README.md` 的成熟流程按这台机器的实际情况改写的。
往后的阶段有哪些是真验过的、怎么验的，见文末「哪些验过、哪些没验」。

---

# 安装流程（照阶段走，每个 ✋ 处停下把输出贴给我）

## 阶段 0 · 准备

- 一个 **≥2GB 的 U 盘**（会被清空）
- 台式机接上**显示器 + 键盘**（装系统时要用；装完就可以拔了，之后都从 Mac 远程操作）
- 一根网线，接到路由器（**别用 Wi-Fi**：HA 靠局域网广播发现米家设备，有线最省事最稳）
- Debian 12 netinst 镜像：<https://www.debian.org/download> —— 选 **amd64 的 netinst**（约 700MB）

⚠️ **这块固态会被整盘擦除**，上面的黑群晖和数据全部消失。（2026-08-11 已确认没有要留的东西，
这里只是陈述事实，不需要你再确认一次。）

⚠️ **如果机器上还插着黑群晖的引导 U 盘 / SD 卡，现在把它拔掉。** 不拔的话开机可能
还是从它启动，你会以为「装完系统没生效」。

## 阶段 1 · 在 Mac 上做启动盘

推荐 **balenaEtcher**（<https://etcher.balena.io>，图形界面，不会选错盘）：
选 ISO → 选 U 盘 → Flash。

> 命令行党用 dd：`diskutil list` 找到 U 盘的 `diskN` →
> `diskutil unmountDisk /dev/diskN` →
> `sudo dd if=~/Downloads/debian-*.iso of=/dev/rdiskN bs=4m && sync`
> （**认准 diskN，写错盘就把 Mac 的盘毁了**）

## 阶段 2 · 在台式机上装 Debian

1. 插 U 盘和网线，开机后**立刻连续点按引导菜单键**。
   这台不是品牌整机，主板牌子不确定，**按顺序试**：`F12` → `F11` → `F8` → `Esc`。
   都不行就按 `Del`（少数是 `F2`）进 BIOS，在 Boot 里把 U 盘调到第一位。
   > 认不出 U 盘的话，去 BIOS 里把 **CSM / Legacy Support 打开**（2013 年的主板很多
   > 只认传统引导）。UEFI 还是传统都行，**关键是装完之后别再改这个设置** ——
   > 改了会变成「装好了却引导不起来」。

2. 选 **Install**（文字安装就行），语言/键盘随意，一路默认到「配置软件包管理器」。
   镜像站**选中国的**（`mirrors.tuna.tsinghua.edu.cn` 或 `mirrors.aliyun.com`），
   不然后面 apt 慢到怀疑人生。

3. **主机名填 `homeassistant`**（这一步直接决定后面 `homeassistant.local` 能不能用）。
   域名留空。建一个普通用户，**记住用户名和密码**。

4. **分区：选「使用整个磁盘」→ 认准那块固态 →「将所有文件放在同一个分区中」→ 完成并写入。**
   > 🩹 **从黑群晖来的盘有个坑**：群晖是用 Linux 软 RAID（mdadm）分区的，
   > Debian 安装器可能会把它自动组装成 `/dev/md0` 之类，然后**拒绝对这块盘分区**
   > （提示设备正忙）。遇到就：`Ctrl+Alt+F2` 切到安装器的 shell，执行
   > ```
   > mdadm --stop /dev/md*      # 拆掉自动组装的阵列
   > wipefs -a /dev/sda         # 抹掉旧分区签名（认准是那块固态！lsblk 先看一眼）
   > ```
   > 再 `Ctrl+Alt+F1` 回去重新分区。

5. 软件选择（tasksel）：**只勾 `SSH server` 和 `standard system utilities`**，
   桌面环境（GNOME 等）**全部取消**。服务器不要桌面，8GB 内存留给 HA。

6. GRUB 装到那块固态。装完**拔掉 U 盘**重启。

7. 顺手进一次 BIOS，把 **「Restore on AC Power Loss」/「AC 上电后开机」设成 Power On**。
   停电恢复后机器能自己起来，不用你跑去按电源键。

✋ **检查点 A** —— 在台式机上登录，运行下面几条，把输出贴给我：
```bash
ip -4 addr show | grep inet     # 局域网 IP，记下来
lsblk                           # 确认系统装在那块固态上
hostnamectl --static            # 应该是 homeassistant
free -h && nproc                # 确认 8G / 2 核都认到了
```

## 阶段 3 · 从 Mac 远程接管

拿到 IP（下面假设 `192.168.1.50`）后，回 Mac：

```bash
ssh <你的用户名>@192.168.1.50        # 首次问指纹，输 yes
```
通了就可以把显示器键盘拔了，之后全在 Mac 上操作。

把整套东西推过去（这一步会连鼠标桥的代码一起推）：

```bash
cd ~/Untitled/PendingHome/ha-home
./deploy.sh <你的用户名>@192.168.1.50
```

## 阶段 4 · 装 Docker + 让 `homeassistant.local` 能用

在 ssh 里：

```bash
cd ~/ha-home
./bootstrap.sh
```

跑完按提示 **退出 ssh 再重连**（让 docker / input 用户组生效）。

这一步顺带解决了你之前问过的那个问题 —— **为什么 `homeassistant.local` 解析不到**：
虚拟机上压根没人认领那个名字（主机名是 `lima-ha-lab`，而且没装广播服务）。
这台机器上主机名就叫 `homeassistant`，再装上 `avahi-daemon` 去局域网里广播，
名字才真正存在。

✋ **检查点 B** —— 重连后在机器上跑：
```bash
docker --version && docker compose version
groups | tr ' ' '\n' | grep -E 'docker|input'    # 两个都要有
hostnamectl --static                              # homeassistant
systemctl is-active avahi-daemon                  # active
```
**然后回 Mac 上验名字**（这条是关键）：
```bash
ping -c2 homeassistant.local
dscacheutil -q host -a name homeassistant.local   # 应该只返回 192.168.1.x
```
把两边输出都贴给我。

> `dscacheutil` 如果除了 `192.168.1.x` 还返回 `172.17.0.1`，说明 avahi 把 Docker
> 的内部网卡也播出去了 —— `bootstrap.sh` 已经处理（只在局域网口广播），
> 万一没生效，检查 `/etc/avahi/avahi-daemon.conf` 里的 `allow-interfaces=`。

## 阶段 5 · 把虚拟机里的数据搬过来

**这一步是整件事里最有价值的部分**：搬完之后米家不用重新登录、258 个实体的
名字和历史都在、鼠标桥用的那个令牌也继续有效。

详细说明和取舍见 **[MIGRATION.md](MIGRATION.md)**，操作只有三条：

```bash
# 1) 在 Mac 上，从虚拟机导出（会短暂停一下虚拟机里的 HA，约 30 秒）
cd ~/Untitled/PendingHome/ha-home
./migrate/01-backup-from-lab.sh

# 2) 传到新机器（备份包里有凭据，不要外传）
scp migrate/ha-config-*.tgz <你的用户名>@homeassistant.local:~/

# 3) 在新机器上恢复
ssh <你的用户名>@homeassistant.local
./ha-home/migrate/02-restore.sh ~/ha-config-*.tgz
```

✋ **检查点 C** —— 把 `02-restore.sh` 的完整输出贴给我。
重点看「实体数量」应该是 **258**，「集成条目」里应该有 **xiaomi_home**。

## 阶段 6 · 起 Home Assistant

第一次起**必须指定和源机器一样的版本**（`02-restore.sh` 结尾会把命令打出来）：

```bash
HA_IMAGE=ghcr.io/home-assistant/home-assistant:2026.8.1 ~/ha-home/ha-up.sh
```

> 为什么不直接用 `stable`：HA 的配置格式只能往前迁移、不能回退。用比源更旧的
> 版本去开这份数据会把 `.storage` 写坏。先用同版本起来验证没问题，之后再升级。
> 升级就是去掉 `HA_IMAGE=` 再跑一次 `ha-up.sh`。

拉镜像卡住的话看下面「镜像拉不动怎么办」。

✋ **检查点 D** —— 浏览器打开 **http://homeassistant.local:8123**：
- [ ] 直接是**已登录**的状态（或用原来的账号密码能登进去），不是「创建账户」的引导页
- [ ] 设置 → 设备与服务 里 **Xiaomi Home 还在**，**没有**要求重新登录
- [ ] 开发者工具 → 状态，能搜到 `light.yeelink_cn_476282703_ceiling23_s_2_light`（吸顶灯）
      和 `light.yeelink_cn_56292508_mono1_s_2_light`（餐厅灯），状态不是 `unavailable`
- [ ] 在界面上点一下吸顶灯，**真灯有反应**

四条都对就说一声，我们进最后一步。有任何一条不对**先别继续**，把
`sudo docker logs --tail 100 homeassistant` 贴给我。

## 阶段 7 · 把鼠标接上

把两个鼠标接收器插到这台机器的 USB 口上，然后：

```bash
cd ~/ha-home/mouse-bridge
sudo ./linux/evdev-source.py --list      # 应该能看到 2717:003b 和 2717:501f
./install.sh
```

细节（权限、开机自启、排查、独占模式）见 **[mouse-bridge/README.md](mouse-bridge/README.md)**。

> Linux 上**不会弹权限框** —— macOS 那个「输入监控」授权是苹果特有的。
> 这边靠 `input` 用户组解决，`install.sh` 已经配好。

✋ **检查点 E** —— 动一动两个鼠标：左键开关、滚轮调亮度、中键切色温（只有吸顶灯有）。
不灵就贴 `sudo journalctl -u mouse-bridge -n 50`。

## 阶段 8 · 收尾

```bash
# 每天凌晨 4 点自动备份，保留 7 份（在新机器上跑）
sudo crontab -e
# 加一行（把 <用户名> 换掉）：
0 4 * * * /home/<用户名>/ha-home/backup.sh >/var/log/ha-backup.log 2>&1
```

- **建议在路由器上给这台机器绑一个固定 IP**。`homeassistant.local` 平时够用，
  但万一 mDNS 抽风，手上有个不会变的 IP 兜底会省很多事。
- 一切正常跑几天之后，Mac 上的试验台虚拟机就可以退役了：
  `limactl stop ha-lab`（先别 delete，留着当后路；确认稳了再删）。
  ⚠️ **两台不要同时开着** —— 同一个米家账号的证书被两处同时用容易互相踢掉，
  而且两台都广播 `.local` 名字会打架。

---

## 镜像拉不动怎么办

HA 的镜像在 `ghcr.io`，实际文件由 GitHub 的 CDN 发，这条线在国内经常被卡到
100 KB/s 上下（600MB 的镜像能拉一个多小时）。

试验台是靠一条从 Mac 打进虚拟机的 SSH 代理隧道解决的 —— **那套东西这里没有了**
（实体机直连路由器，旁边没有 Mac 给它当跳板），所以本目录的 `docker-compose.yml`
里已经没有代理覆盖层。

这台机器上的办法，按顺序试：

1. **先直接试**。`ha-up.sh` 会打印进度，能到几 MB/s 就别折腾了。
2. **家里有路由器级代理 / 软路由的话**，让这台机器走它，是最省事的。
3. **都不行就用国内镜像源，但必须按 digest 拉，不要按 tag：**

```bash
# 从官方 ghcr.io 取权威 digest（这一步只拉几 KB 的清单，慢线路也扛得住）
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:home-assistant/home-assistant:pull&service=ghcr.io" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  https://ghcr.io/v2/home-assistant/home-assistant/manifests/2026.8.1
# 在返回的清单里找 architecture 是 amd64 的那条 digest，然后：
docker pull <镜像站>/home-assistant/home-assistant@sha256:<digest>
docker tag  <镜像站>/home-assistant/home-assistant@sha256:<digest> \
            ghcr.io/home-assistant/home-assistant:2026.8.1
```

按 digest 拉时 Docker 会校验内容哈希，镜像站换了内容会直接失败 —— 第三方源的
供应链风险被内容寻址堵住了。**按 tag 拉没有这个保证，别图省事。**

> 注意 `registry-mirrors` 那套只对 Docker Hub 生效，对 ghcr.io 无效。

⚠️ **这台是 x86_64，试验台是 arm64**，所以要挑 **amd64** 那条 digest。
`ghcr.io/home-assistant/home-assistant:stable` 本身是多架构的，直连拉不用操心这个。

## 网络慢/卡的另一种可能：MTU

试验台上踩过：那条网络的实际路径 MTU 是 **1480** 而不是 1500，按 1500 发包时大包被
上游丢掉、ICMP 通知又回不来，表现是「ping 通、小请求正常、批量下载卡死」。

实体机是直接插路由器的物理口，**大概率没这个问题**。但如果出现「apt / docker pull
卡在某个百分比不动」，先量一下：

```bash
for s in 1452 1456 1460 1464 1472; do
  ping -c1 -M do -s $s 223.5.5.5 >/dev/null 2>&1 && echo "$s 通" || echo "$s 不通"
done
```
最大那个「通」的数 **+28** 就是实际 MTU。不是 1500 的话告诉我，我给网卡配上。

## 日常操作

```bash
ssh <用户名>@homeassistant.local

~/ha-home/status.sh                        # 体检
sudo docker logs -f homeassistant          # 看 HA 日志
sudo docker restart homeassistant          # 重启 HA
~/ha-home/ha-up.sh                         # 改完 compose 后生效 / 升级到最新版
sudo systemctl status mouse-bridge         # 鼠标桥状态
sudo journalctl -u mouse-bridge -f         # 鼠标桥日志
~/ha-home/backup.sh                        # 手动备份一次
```

---

## 哪些验过、哪些没验

老实说明，别把没验的当验过的用。

**✅ 真验过的**（在 Mac 和现有试验台虚拟机上，2026-08-11）

| 事情 | 怎么验的 | 结果 |
|---|---|---|
| avahi 能让 `.local` 名字全网可用 | 在试验台虚拟机装 `avahi-daemon`，从 Mac 解析 | `ping lima-ha-lab.local` 通，`curl http://lima-ha-lab.local:8123` 返回 200 |
| avahi 会把 docker0 的地址一起播出去 | 装完看广播记录 | 确实播了 4 个地址，含 `172.17.0.1`（局域网不可达）|
| 限制 `allow-interfaces` 能治好上面那条 | 改配置重启后再解析 | 只剩局域网地址，`bootstrap.sh` 已固化这个改法 |
| avahi 和 HA 自带的 mDNS 会不会打架 | 两个一起跑，看 5353 端口和 HA 日志 | 各自绑住 5353 共存，HA 无异常，8123 正常 |
| 迁移备份脚本 | 对着真的虚拟机跑了一遍 | 2.6MB 的包，米家证书 / 账号 / 令牌 / **258 个实体**全在 |
| 迁移恢复的解包与权限 | 把包解到临时目录，跟原件逐字节比对 | 内容一致，`.storage/auth` 的 `root:root 0600` 原样保留 |
| `docker-compose.yml` 合法性 | YAML 解析 | 通过 |
| 全部 shell 脚本语法 | `bash -n` | 通过 |
| 鼠标桥的启动包装 `run.sh` | 用假的事件源和桥实跑 | 设备参数从 `config.json` 正确读出、`GRAB=1` 生效、缺令牌时干净报错、事件能穿过管道 |
| **写盘镜像整体** | 在 x86 模拟器里真的开机跑了两遍 | 见 [image/README.md](image/README.md)；传统 BIOS 和 UEFI 两条引导路径都起来了，首启全流程跑通到 HA 可访问 |
| 鼠标桥的控灯逻辑在 Linux 上 | 在虚拟机的 Python 3.11 上跑 18 项测试 | 全绿 |
| `linux/evdev-source.py` 真能读 Linux 鼠标 | 在虚拟机里造了一个假鼠标设备（真 sysfs 结构 + 真 evdev 二进制事件），实跑 | 设备识别、按键/滚轮解析、长按重复与鼠标移动的过滤**全部正确**，输出格式和 macOS 版一模一样 |
| 顺带修掉一个真 bug | 见 mouse-bridge/README.md | 设备断开后会 79% CPU 空转，已修并回归验证 |

**❌ 没在硬件上验证的**（这台机器还没到手）

- 阶段 0–3 的**全部内容**：引导键、BIOS 设置、分区（尤其是黑群晖那块盘的 mdadm 坑）、
  Debian 安装器的每一步
- `bootstrap.sh` 在真 Debian 上的完整执行（各条命令是照 `ha-t630/bootstrap.sh` 那份
  跑通过的流程改的，avahi 那段在虚拟机上验过）
- x86_64 的 HA 镜像能不能拉下来、拉多快
- **恢复之后 HA 真的能带着米家凭据启动** —— 包的内容验过了，但「解开之后 HA 认不认」
  只能等机器到位才知道（这也是检查点 D 那四条要一条条勾的原因）
- 两只鼠标插在这台机器上被 Linux 识别成什么样（见 mouse-bridge/README.md 里
  「一只鼠标可能对应多个设备节点」那条风险）
