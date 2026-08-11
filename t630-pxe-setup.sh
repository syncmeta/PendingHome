#!/usr/bin/env bash
#
# t630-pxe-setup.sh — 在 macOS 上架一个临时 PXE 服务(proxyDHCP + TFTP),
# 让 HP t630 瘦客户机从网络启动 netboot.xyz,进内存 Linux 后把 HAOS 写进内置 M.2。
# 不接管路由器 DHCP,不改动你家网络。
#
set -euo pipefail

NBDIR="${HOME}/t630-netboot"
CONF="${NBDIR}/dnsmasq.conf"

echo "==> 1/4 检测网络接口"
IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
if [[ -z "${IFACE:-}" ]]; then
  echo "找不到默认网络接口。请确认 Mac 已联网。"; exit 1
fi
MYIP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"
if [[ -z "${MYIP:-}" ]]; then
  echo "接口 $IFACE 没有 IPv4 地址。"; exit 1
fi
SUBNET="$(echo "$MYIP" | awk -F. '{print $1"."$2"."$3".0"}')"
echo "    接口=$IFACE  Mac IP=$MYIP  网段=$SUBNET/24"

echo "==> 2/4 安装 dnsmasq(如已装则跳过)"
if ! command -v dnsmasq >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "没装 Homebrew。先装 brew:https://brew.sh 然后重跑本脚本。"; exit 1
  fi
  brew install dnsmasq
fi

echo "==> 3/4 下载 netboot.xyz 引导文件"
mkdir -p "$NBDIR"
curl -fL -o "${NBDIR}/netboot.xyz.efi"  https://boot.netboot.xyz/ipxe/netboot.xyz.efi
curl -fL -o "${NBDIR}/netboot.xyz.kpxe" https://boot.netboot.xyz/ipxe/netboot.xyz.kpxe

echo "==> 4/4 生成 dnsmasq 配置:$CONF"
cat > "$CONF" <<EOF
# 只做 DHCP/TFTP,不做 DNS(避免和 Mac 的 mDNS 冲突)
port=0
log-dhcp

# proxyDHCP:不发 IP,只在你路由器分配 IP 之外附加"引导信息"
dhcp-range=${SUBNET},proxy
interface=${IFACE}
bind-interfaces

# 内置 TFTP,提供 iPXE 引导文件
enable-tftp
tftp-root=${NBDIR}

# 按客户端架构分发正确的引导文件
dhcp-match=set:bios,option:client-arch,0
dhcp-match=set:efibc,option:client-arch,7
dhcp-match=set:efi64,option:client-arch,9
pxe-service=tag:bios,x86PC,"netboot.xyz (BIOS)",netboot.xyz.kpxe
pxe-service=tag:efibc,BC_EFI,"netboot.xyz (UEFI)",netboot.xyz.efi
pxe-service=tag:efi64,x86-64_EFI,"netboot.xyz (UEFI)",netboot.xyz.efi
EOF

echo
echo "======================================================================"
echo " 准备就绪。现在在【你自己的终端】里运行下面这条命令启动 PXE 服务:"
echo
echo "   sudo dnsmasq -d -C \"$CONF\""
echo
echo " (-d = 前台运行 + 打日志;要停就 Ctrl-C。装完 HAOS 后停掉即可。)"
echo "======================================================================"
