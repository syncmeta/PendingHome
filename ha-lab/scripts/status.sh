#!/bin/bash
# 一眼看清整个试验台的状态：前置条件、虚拟机、IP、容器、8123 是否可达。
# 排查问题先跑这个。
set -uo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMACTL="/opt/homebrew/bin/limactl"
VM="ha-lab"

ok()   { echo "  ✅ $*"; }
bad()  { echo "  ❌ $*"; }

echo "== 前置条件 =="
[[ -x /opt/socket_vmnet/bin/socket_vmnet ]] && ok "/opt/socket_vmnet/bin/socket_vmnet" || bad "socket_vmnet 未安装 → scripts/02-sudo-setup.sh"
[[ -f /etc/sudoers.d/lima ]] && ok "/etc/sudoers.d/lima" || bad "sudoers 未安装 → scripts/02-sudo-setup.sh"
[[ -f "${HOME}/.lima/_config/networks.yaml" ]] && ok "~/.lima/_config/networks.yaml" || bad "networks.yaml 未安装 → scripts/01-prepare.sh"

echo
echo "== 虚拟机 =="
"${LIMACTL}" list 2>&1 | sed 's/^/  /'

echo
echo "== 局域网 IP =="
IP="$("${LAB_DIR}/scripts/vm-ip.sh" 2>/dev/null)"
if [[ -n "${IP}" ]]; then
  ok "lima0 = ${IP}"
else
  bad "lima0 还没有 IP"
fi

echo
echo "== 容器 =="
"${LIMACTL}" shell "${VM}" -- sudo docker ps --format '  {{.Names}}\t{{.Status}}\t{{.Image}}' 2>&1 | sed 's/^/  /'

echo
echo "== Home Assistant =="
if [[ -n "${IP}" ]]; then
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${IP}:8123" || true)"
  if [[ "${CODE}" == "200" || "${CODE}" == "302" ]]; then
    ok "http://${IP}:8123  (HTTP ${CODE})"
  else
    bad "http://${IP}:8123 不可达 (HTTP ${CODE:-无响应})"
  fi
fi
