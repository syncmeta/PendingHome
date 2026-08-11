#!/usr/bin/env bash
# 造一个「写进硬盘就能开机自己配好」的 x86_64 磁盘镜像。
#
# **在 Lima 虚拟机（Linux）里以 root 运行** —— loop 设备、parted、mkfs 这些
# macOS 上没有。虚拟机本身是 arm64 不要紧：镜像里的 amd64 程序靠
# qemu-user-static + binfmt 在 chroot 里跑，装包和配置都能正常做。
#
#   sudo ./build-image.sh \
#     --base       /var/tmp/build/disk.raw \
#     --ha-image   /var/tmp/build/ha-image.tar.gz \
#     --ha-config  /var/tmp/build/ha-config.tgz \
#     --ssh-key    /var/tmp/build/id_ed25519.pub \
#     --token-file /var/tmp/build/token.env \
#     --out        /var/tmp/build/ha-home.img
#
# 四样输入怎么来的见 README.md。--token-file 可省略（省了就不预置鼠标桥的令牌）。
#
# ⚠️ 这个脚本只写 --out 指定的那个**文件**，不碰任何物理磁盘。
set -euo pipefail

BASE=""; HA_IMAGE=""; HA_CONFIG=""; SSH_KEY=""; TOKEN_FILE=""; OUT=""
SIZE="${SIZE:-6G}"
HOSTNAME_WANT="homeassistant"
USERNAME="${USERNAME:-hey}"
# 只用于「人坐在机器前用键盘登录」的兜底密码。SSH 那边是纯密钥、禁用密码登录，
# 所以这个密码在网络上用不了。装好后建议 passwd 改掉。
CONSOLE_PASSWORD="${CONSOLE_PASSWORD:-homeassistant}"
HA_VERSION="${HA_VERSION:-2026.8.1}"
MIRROR="${MIRROR:-https://mirrors.ustc.edu.cn}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --ha-image) HA_IMAGE="$2"; shift 2 ;;
    --ha-config) HA_CONFIG="$2"; shift 2 ;;
    --ssh-key) SSH_KEY="$2"; shift 2 ;;
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --size) SIZE="$2"; shift 2 ;;
    *) echo "不认识的参数：$1" >&2; exit 2 ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || { echo "要 root：sudo $0 ..." >&2; exit 1; }
for v in BASE HA_IMAGE HA_CONFIG SSH_KEY OUT; do
  [[ -n "${!v}" ]] || { echo "缺参数 --${v,,}" >&2; exit 2; }
done
for f in "${BASE}" "${HA_IMAGE}" "${HA_CONFIG}" "${SSH_KEY}"; do
  [[ -f "${f}" ]] || { echo "找不到 ${f}" >&2; exit 1; }
done
# ha-home 那套脚本和 mouse-bridge 源码从这个脚本的位置往上找
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HA_HOME="$(cd "${HERE}/.." && pwd)"
MB_SRC="${MB_SRC:-${HA_HOME}/mouse-bridge}"

MNT=/mnt/ha-home-build
LOOP=""

cleanup() {
  set +e
  umount "${MNT}/dev/pts" "${MNT}/dev" "${MNT}/proc" "${MNT}/sys" 2>/dev/null
  umount "${MNT}/boot/efi" 2>/dev/null
  umount "${MNT}" 2>/dev/null
  [[ -n "${LOOP}" ]] && losetup -d "${LOOP}" 2>/dev/null
}
trap cleanup EXIT

echo "==> 1/9 从官方基础镜像复制并扩容到 ${SIZE}"
cp --sparse=always "${BASE}" "${OUT}"
truncate -s "${SIZE}" "${OUT}"
# 扩容后 GPT 的备份头还留在旧的盘尾，先挪到新盘尾，再把根分区拉满。
# （分区表是 p1=根 / p14=BIOS boot / p15=EFI，根分区在最后，所以能直接拉。）
sgdisk -e "${OUT}" >/dev/null
parted -s "${OUT}" resizepart 1 100%

LOOP="$(losetup -f --show -P "${OUT}")"
e2fsck -fp "${LOOP}p1" >/dev/null 2>&1 || true
resize2fs "${LOOP}p1" >/dev/null
echo "    根分区：$(dumpe2fs -h "${LOOP}p1" 2>/dev/null | awk -F: '/Block count/{c=$2} /Block size/{s=$2} END{printf "%.1f GiB", c*s/1024/1024/1024}')"

echo
echo "==> 2/9 挂载并准备 chroot（amd64 靠 qemu-user-static 跑在 arm64 上）"
mkdir -p "${MNT}"
mount "${LOOP}p1" "${MNT}"
mount "${LOOP}p15" "${MNT}/boot/efi"
mount --bind /dev "${MNT}/dev"
mount --bind /dev/pts "${MNT}/dev/pts"
mount -t proc proc "${MNT}/proc"
mount -t sysfs sys "${MNT}/sys"
cp /usr/bin/qemu-x86_64-static "${MNT}/usr/bin/"
# chroot 里装包时别让 systemd 服务真的启动（这儿没有 init）
printf '#!/bin/sh\nexit 101\n' > "${MNT}/usr/sbin/policy-rc.d"
chmod +x "${MNT}/usr/sbin/policy-rc.d"
# 镜像里的 /etc/resolv.conf 是指向 systemd-resolved 的**软链**，而 chroot 里没有
# resolved 在跑 —— 直接 cp 过去只会写到一个悬空的目标，chroot 里 DNS 全废
# （表现是 apt 一律「Temporary failure resolving」）。先删掉软链再写真文件。
rm -f "${MNT}/etc/resolv.conf"
printf 'nameserver 223.5.5.5\nnameserver 119.29.29.29\n' > "${MNT}/etc/resolv.conf"
ARCH_IN_CHROOT="$(chroot "${MNT}" /bin/uname -m)"
[[ "${ARCH_IN_CHROOT}" == "x86_64" ]] || { echo "❌ chroot 里不是 x86_64（是 ${ARCH_IN_CHROOT}）" >&2; exit 1; }
echo "    chroot 内 uname -m = ${ARCH_IN_CHROOT}  ✅"

echo
echo "==> 3/9 换国内 apt 源 + 打开 non-free-firmware"
# 官方源在国内实测只有 ~27KB/s，换成 USTC 有 ~12MB/s。
# non-free-firmware 是为了网卡固件和 Intel 微码 —— 这是裸机，不是虚拟机。
cat > "${MNT}/etc/apt/mirrors/debian.list" <<EOF
${MIRROR}/debian/
EOF
cat > "${MNT}/etc/apt/mirrors/debian-security.list" <<EOF
${MIRROR}/debian-security/
EOF
sed -i 's/^Components: main$/Components: main contrib non-free-firmware/' \
  "${MNT}/etc/apt/sources.list.d/debian.sources"

echo
echo "==> 4/9 在镜像里装 Docker / avahi / 固件（全部装好，不留给开机现装）"
chroot "${MNT}" /bin/bash -euxo pipefail <<CHROOT
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# 裸机要的东西：网卡固件 + Ivy Bridge 的 CPU 微码
apt-get install -y -qq \
  ca-certificates curl gnupg tar rsync python3 \
  avahi-daemon libnss-mdns avahi-utils \
  firmware-realtek firmware-misc-nonfree intel-microcode

# Docker 官方源（走 USTC 的镜像，内容一样，速度差几十倍）。
# 签名密钥也从 USTC 取 —— download.docker.com 在这条网络上直接被重置连接
# （实测 curl: (35) Recv failure）。密钥指纹在下面校验，取哪儿都不影响可信度。
install -m0755 -d /etc/apt/keyrings
curl -fsSL ${MIRROR}/docker-ce/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
# 核对官方公布的指纹，防止镜像站给了别的密钥
FPR=\$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr:/{print \$10; exit}')
echo "    Docker 签名密钥指纹 \$FPR"
[ "\$FPR" = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88" ] || { echo "❌ Docker 密钥指纹不对"; exit 1; }
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] ${MIRROR}/docker-ce/linux/debian bookworm stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# 日志上限，保护固态
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/size.conf

# 鼠标桥的专用账号（读 /dev/input 靠 input 组，不用 root）
id -u mousebridge >/dev/null 2>&1 || \
  useradd --system --no-create-home --shell /usr/sbin/nologin --groups input mousebridge

systemctl enable docker containerd avahi-daemon >/dev/null 2>&1
apt-get clean
CHROOT

echo
echo "==> 5/9 放进 Home Assistant 的数据和容器镜像"
install -d -m 0755 "${MNT}/opt/ha" "${MNT}/opt/ha/images"
# HA 的全部状态（含米家凭据、262 个实体、长期令牌）—— 直接展开到位，
# 开机不用再做恢复动作。权限必须原样保留：.storage/auth 是 root:root 0600。
tar -xzpf "${HA_CONFIG}" --same-owner -C "${MNT}/opt/ha"
[[ -f "${MNT}/opt/ha/config/.HA_VERSION" ]] || { echo "❌ HA 数据没展开成功" >&2; exit 1; }
echo "    HA 数据版本 $(cat "${MNT}/opt/ha/config/.HA_VERSION")"

# compose：镜像版本钉死成预置的那个，别让它开机去拉 stable
sed "s|image: ghcr.io/home-assistant/home-assistant:stable|image: ghcr.io/home-assistant/home-assistant:${HA_VERSION}|" \
  "${HA_HOME}/docker-compose.yml" > "${MNT}/opt/ha/docker-compose.yml"
grep -q "${HA_VERSION}" "${MNT}/opt/ha/docker-compose.yml" || { echo "❌ compose 里的版本没钉上" >&2; exit 1; }

cp "${HA_IMAGE}" "${MNT}/opt/ha/images/ha-image.tar.gz"
echo "    预置容器镜像 $(du -h "${MNT}/opt/ha/images/ha-image.tar.gz" | cut -f1)"

echo
echo "==> 6/9 放进鼠标桥"
install -d -m 0755 "${MNT}/opt/mouse-bridge" "${MNT}/opt/mouse-bridge/linux"
install -m 0644 "${MB_SRC}"/bridge.py "${MB_SRC}"/logic.py "${MB_SRC}"/ha_client.py "${MNT}/opt/mouse-bridge/"
install -m 0755 "${MB_SRC}/run.sh" "${MNT}/opt/mouse-bridge/run.sh"
install -m 0755 "${MB_SRC}/linux/evdev-source.py" "${MNT}/opt/mouse-bridge/linux/evdev-source.py"
install -m 0644 "${MB_SRC}/README.md" "${MNT}/opt/mouse-bridge/README.md"
# ha_url 指到本机回环：HA 就跑在这台机器上，不依赖 mDNS 或 DHCP 给的地址
python3 - "${MB_SRC}/config.json" "${MNT}/opt/mouse-bridge/config.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
cfg["ha_url"] = "http://127.0.0.1:8123"
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("    绑定：", ", ".join("%s→%s" % (d, s.get("label", "?")) for d, s in cfg["mice"].items()))
PY
chmod 0644 "${MNT}/opt/mouse-bridge/config.json"
install -m 0644 "${MB_SRC}/mouse-bridge.service" "${MNT}/etc/systemd/system/mouse-bridge.service"

if [[ -n "${TOKEN_FILE}" && -f "${TOKEN_FILE}" ]]; then
  install -d -m 0700 "${MNT}/etc/ha-home"
  install -m 0600 "${TOKEN_FILE}" "${MNT}/etc/ha-home/mouse-bridge.env"
  echo "    令牌已预置（0600，内容不打印）"
else
  echo "    没给令牌，鼠标桥装好但不会自启（之后手工放令牌即可）"
fi

# 把整个 ha-home 也带进去，之后在机器上要用 status.sh / backup.sh 很方便
install -d -m 0755 "${MNT}/root/ha-home"
tar -cf - -C "${HA_HOME}" --exclude '*.tgz' --exclude '*.img' --exclude '.DS_Store' . \
  | tar -xf - -C "${MNT}/root/ha-home"
chmod +x "${MNT}"/root/ha-home/*.sh "${MNT}"/root/ha-home/migrate/*.sh 2>/dev/null || true

echo
echo "==> 7/9 首启脚本 + cloud-init 配置"
install -d -m 0755 "${MNT}/opt/ha-firstboot"
install -m 0755 "${HERE}/firstboot.sh" "${MNT}/opt/ha-firstboot/firstboot.sh"

# NoCloud 数据源：种子直接放进根文件系统，不用额外造一个种子分区。
# 同时把 datasource_list 钉死，免得 cloud-init 在裸机上花一两分钟去探
# 各家云的元数据服务（那些地址在家里的网络上根本不存在）。
install -d -m 0755 "${MNT}/var/lib/cloud/seed/nocloud"
printf 'datasource_list: [ NoCloud, None ]\n' > "${MNT}/etc/cloud/cloud.cfg.d/99-ha-home.cfg"

PWHASH="$(openssl passwd -6 "${CONSOLE_PASSWORD}")"
cat > "${MNT}/var/lib/cloud/seed/nocloud/meta-data" <<EOF
instance-id: ha-home-$(date +%Y%m%d%H%M%S)
local-hostname: ${HOSTNAME_WANT}
EOF

cat > "${MNT}/var/lib/cloud/seed/nocloud/user-data" <<EOF
#cloud-config
# 这台机器的首次开机配置。由 ha-home/image/build-image.sh 生成。
hostname: ${HOSTNAME_WANT}
fqdn: ${HOSTNAME_WANT}
manage_etc_hosts: true
timezone: Asia/Shanghai
# 刻意不设 locale：基础镜像里没有 zh_CN.UTF-8，cloud-init 去设它会失败，
# 连带把 cloud-config.service 标成 FAILED（实测过，开机时屏幕上一行红字）。
# 系统语言不影响 Home Assistant —— 它的界面语言是在 HA 里按用户存的。

# 根分区自动长满整块盘 —— 镜像只有 ${SIZE}，盘是 120G
growpart:
  mode: auto
  devices: ['/']
  ignore_growroot_disabled: false
resize_rootfs: true

users:
  - name: ${USERNAME}
    groups: [sudo, docker, input]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: false
    passwd: "${PWHASH}"
    ssh_authorized_keys:
      - $(cat "${SSH_KEY}")

# SSH 只认密钥。上面那个密码只在「人坐在机器前用键盘登录」时有用，
# 网络上用不了 —— 所以它弱一点也不会变成对外的口子。
ssh_pwauth: false
disable_root: true

# 不在首次开机时联网升级：慢，而且失败了会让人以为机器坏了。
# 该装的在造镜像时就都装好了。
package_update: false
package_upgrade: false

runcmd:
  - [ /opt/ha-firstboot/firstboot.sh ]

final_message: "ha-home 首次配置完成，用了 \$UPTIME 秒。打开 http://${HOSTNAME_WANT}.local:8123"
EOF

echo
echo "==> 8/9 收尾清理"
chroot "${MNT}" /bin/bash -c 'rm -f /usr/sbin/policy-rc.d; apt-get clean; rm -rf /var/lib/apt/lists/*'
rm -f "${MNT}/usr/bin/qemu-x86_64-static"
# machine-id 留空，让每台机器首次启动自己生成（不然克隆出来的机器 DHCP 会撞车）
: > "${MNT}/etc/machine-id"
rm -f "${MNT}/var/lib/dbus/machine-id"
# 造镜像时写进去的 resolv.conf 是虚拟机的，删掉让目标机自己按 DHCP 生成
rm -f "${MNT}/etc/resolv.conf"
ln -sf /run/systemd/resolve/stub-resolv.conf "${MNT}/etc/resolv.conf" 2>/dev/null || true
# cloud-init 的运行痕迹清掉，否则它以为自己已经跑过了
rm -rf "${MNT}/var/lib/cloud/instance" "${MNT}/var/lib/cloud/instances" "${MNT}/var/lib/cloud/data"

USED="$(df -h "${MNT}" | awk 'NR==2{print $3" / "$2}')"
cleanup
trap - EXIT

echo
echo "==> 9/9 完成"
echo "    镜像文件：${OUT}"
echo "    表面大小：$(du -h --apparent-size "${OUT}" | cut -f1)   实际占用：$(du -h "${OUT}" | cut -f1)"
echo "    镜像内已用：${USED}"
echo
echo "下一步：verify-image.sh 验一遍，再压缩交付。"
