#!/usr/bin/env bash
#
# t630-direct.sh — Mac 的 USB 网口(en11)直连 HP t630 的场景:
# 让 dnsmasq 当这条直连链路上唯一的 DHCPv6 + RA + TFTP 服务器,
# t630 走 IPv6 UEFI PXE 从 Mac 加载 netboot.xyz;Mac 走 Wi-Fi 上网并对 t630 做 IPv4 NAT。
#
# 用法(需要 root):  sudo bash t630-direct.sh
#
set -euo pipefail

IF="en11"                                   # 直连 t630 的 USB 网口
WAN="en0"                                   # Wi-Fi,用来上网
DNSMASQ="/opt/homebrew/opt/dnsmasq/sbin/dnsmasq"
NBDIR="/Users/hey/t630-netboot"

if [[ $EUID -ne 0 ]]; then echo "请用 sudo 运行:sudo bash $0"; exit 1; fi

echo "==> 打开 Wi-Fi(用于上网)"
networksetup -setairportpower "$WAN" on || true

echo "==> 给直连口 $IF 配静态地址(IPv4 192.168.7.1 / IPv6 fd00::1)"
ipconfig set "$IF" MANUAL 192.168.7.1 255.255.255.0
ifconfig "$IF" inet6 fd00::1 prefixlen 64 alias 2>/dev/null || true

echo "==> 开启转发 + 对 t630 做 IPv4 NAT(经 $WAN 上网)"
sysctl -w net.inet.ip.forwarding=1 >/dev/null
cat > /tmp/t630-pf.conf <<PF
nat on $WAN from 192.168.7.0/24 to any -> ($WAN)
PF
pfctl -F all >/dev/null 2>&1 || true
pfctl -f /tmp/t630-pf.conf -e >/dev/null 2>&1 || pfctl -f /tmp/t630-pf.conf >/dev/null 2>&1 || true

echo "==> 生成 dnsmasq 配置"
cat > "$NBDIR/dnsmasq.conf" <<EOF
log-dhcp
interface=$IF
bind-interfaces
enable-tftp
tftp-root=$NBDIR

# ---------- IPv6:本链路唯一的 RA + 有状态 DHCPv6,直接发地址和引导地址 ----------
enable-ra
dhcp-range=fd00::10,fd00::ff,64,1h
dhcp-option=option6:dns-server,[fd00::1]
dhcp-option=option6:bootfile-url,tftp://[fd00::1]/netboot.xyz.efi

# ---------- IPv4:给 netboot.xyz 的 iPXE 二段用(拿 IP + 网关 + DNS 走 NAT 上网) ----------
dhcp-range=192.168.7.50,192.168.7.150,255.255.255.0,1h
dhcp-option=option:router,192.168.7.1
dhcp-option=option:dns-server,192.168.7.1
dhcp-match=set:efi64,option:client-arch,9
dhcp-match=set:efibc,option:client-arch,7
dhcp-boot=tag:efi64,netboot.xyz.efi
dhcp-boot=tag:efibc,netboot.xyz.efi
dhcp-boot=netboot.xyz.kpxe
EOF

echo "==> 启动 dnsmasq(前台,Ctrl-C 停止)"
echo "    看到 DHCP6 / RTR-ADVERT / 'sent ... netboot.xyz.efi' 就说明 t630 在拉引导文件"
echo "-----------------------------------------------------------------------"
exec "$DNSMASQ" -d -C "$NBDIR/dnsmasq.conf"
