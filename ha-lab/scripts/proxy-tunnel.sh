#!/bin/bash
# 把 Mac 上的 Clash 代理接进虚拟机，用来加速拉镜像。
#
#   ./scripts/proxy-tunnel.sh up     开隧道 + 配好 dockerd 走代理
#   ./scripts/proxy-tunnel.sh down   关隧道 + 撤掉 dockerd 的代理配置
#   ./scripts/proxy-tunnel.sh test   测一下现在通不通、多快
#
# 为什么要隧道：虚拟机是**桥接**的，包直接走路由器出去，不经过 Mac 的 TUN，
# 所以 Mac 上的梯子对它等于不存在。而 Clash 默认只监听 127.0.0.1，
# 虚拟机也连不到 192.168.1.25:10898（除非在 Clash 里开 Allow LAN）。
# 用 lima 自带的 SSH 通道做反向端口转发，就绕开了这两点，不用改 Clash 任何设置。
#
# 这套东西只服务于 Mac 试验台。T630 上没有这一层，直接 down 掉即可。
set -euo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMACTL="/opt/homebrew/bin/limactl"
VM="ha-lab"
PROXY_PORT="${PROXY_PORT:-10898}"
SSH_CONFIG="${HOME}/.lima/${VM}/ssh.config"
DROPIN_DIR="/etc/systemd/system/docker.service.d"

usage() { echo "用法: $0 {up|down|test}" >&2; exit 1; }
[[ $# -eq 1 ]] || usage

case "$1" in
up)
  if [[ ! -f "${SSH_CONFIG}" ]]; then
    echo "❌ 找不到 ${SSH_CONFIG}，虚拟机没起来？" >&2
    exit 1
  fi
  if ! nc -z -G 2 127.0.0.1 "${PROXY_PORT}" 2>/dev/null; then
    echo "❌ Mac 本机 127.0.0.1:${PROXY_PORT} 没在监听 —— Clash 没开？" >&2
    exit 1
  fi

  echo "==> 开反向隧道 VM:127.0.0.1:${PROXY_PORT} → Mac:127.0.0.1:${PROXY_PORT}"
  # ControlMaster 是常驻的，转发挂在它上面，所以这条 ssh 建完就退出，隧道仍在。
  ssh -F "${SSH_CONFIG}" -N -f -R "${PROXY_PORT}:127.0.0.1:${PROXY_PORT}" "lima-${VM}"

  echo "==> 配置 dockerd 走代理"
  "${LIMACTL}" shell "${VM}" -- sudo install -d "${DROPIN_DIR}"
  "${LIMACTL}" shell "${VM}" -- sudo cp \
    /mnt/ha-lab/lima/docker-http-proxy.conf "${DROPIN_DIR}/http-proxy.conf"
  "${LIMACTL}" shell "${VM}" -- sudo systemctl daemon-reload
  "${LIMACTL}" shell "${VM}" -- sudo systemctl restart docker

  exec "$0" test
  ;;

down)
  echo "==> 撤掉 dockerd 的代理配置"
  "${LIMACTL}" shell "${VM}" -- sudo rm -f "${DROPIN_DIR}/http-proxy.conf"
  "${LIMACTL}" shell "${VM}" -- sudo systemctl daemon-reload
  "${LIMACTL}" shell "${VM}" -- sudo systemctl restart docker
  echo "==> 关隧道"
  # 只杀带这个转发参数的 ssh，别误伤 lima 自己的 SSH 连接。
  pkill -f "ssh .*-R ${PROXY_PORT}:127.0.0.1:${PROXY_PORT} lima-${VM}" || true
  echo "✅ 已恢复直连"
  ;;

test)
  echo "==> 隧道连通性"
  "${LIMACTL}" shell "${VM}" -- curl -s -o /dev/null --max-time 8 \
    -x "http://127.0.0.1:${PROXY_PORT}" \
    -w "   ghcr.io 握手 HTTP %{http_code}（401 = 正常，说明通了）\n" https://ghcr.io/v2/
  echo "==> 经代理的下载速度（8 秒采样）"
  "${LIMACTL}" shell "${VM}" -- curl -sL -o /dev/null --max-time 8 \
    -x "http://127.0.0.1:${PROXY_PORT}" \
    -w "   %{speed_download} B/s\n" \
    https://github.com/containerd/nerdctl/releases/download/v2.3.5/nerdctl-full-2.3.5-linux-arm64.tar.gz || true
  echo "==> dockerd 是否已带上代理环境变量"
  "${LIMACTL}" shell "${VM}" -- sudo systemctl show docker --property=Environment \
    | tr ' ' '\n' | grep -i proxy | sed 's/^/   /' || echo "   （dockerd 未配置代理）"
  ;;

*) usage ;;
esac
