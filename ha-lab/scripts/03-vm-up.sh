#!/bin/bash
# 建并启动 Debian 12 虚拟机（实例名 ha-lab）。
# 首次跑要下载云镜像 + apt 装 docker，几分钟起步；之后再跑就是纯启动。
# 不需要 sudo（sudo 免密规则已由 02-sudo-setup.sh 装好）。
set -euo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMACTL="/opt/homebrew/bin/limactl"
VM="ha-lab"

if [[ ! -x /opt/socket_vmnet/bin/socket_vmnet ]]; then
  echo "❌ /opt/socket_vmnet/bin/socket_vmnet 不存在 —— 先跑 02-sudo-setup.sh" >&2
  exit 1
fi
if [[ ! -f /etc/sudoers.d/lima ]]; then
  echo "❌ /etc/sudoers.d/lima 不存在 —— 先跑 02-sudo-setup.sh" >&2
  exit 1
fi

if "${LIMACTL}" list --quiet 2>/dev/null | grep -qx "${VM}"; then
  echo "==> 实例 ${VM} 已存在，直接启动"
  "${LIMACTL}" start "${VM}"
else
  echo "==> 创建实例 ${VM}"
  "${LIMACTL}" start --tty=false --name="${VM}" "${LAB_DIR}/lima/ha-lab.yaml"
fi

echo
echo "==> 虚拟机内网卡情况"
"${LIMACTL}" shell "${VM}" -- ip -4 addr show lima0 || true

echo
"${LAB_DIR}/scripts/vm-ip.sh"
