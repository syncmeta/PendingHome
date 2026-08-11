#!/bin/bash
# 打印虚拟机在局域网上的 IP（桥接网卡 lima0 拿到的那个 192.168.1.x）。
# 其他脚本靠它拼 URL，所以只往 stdout 输出一个裸 IP，提示信息走 stderr。
set -euo pipefail

LIMACTL="/opt/homebrew/bin/limactl"
VM="${1:-ha-lab}"

IP="$("${LIMACTL}" shell "${VM}" -- ip -4 -o addr show lima0 2>/dev/null \
      | awk '{print $4}' | cut -d/ -f1 | head -n1)"

if [[ -z "${IP}" ]]; then
  echo "❌ lima0 还没拿到 IP。桥接或 DHCP 没成功，排查：" >&2
  echo "   limactl shell ${VM} -- ip addr" >&2
  echo "   limactl shell ${VM} -- sudo journalctl -u systemd-networkd -n 50" >&2
  exit 1
fi

echo "${IP}"
