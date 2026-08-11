#!/usr/bin/env bash
# 在实体机上跑：一眼看清整机状态。出问题先跑这个，把输出贴回来。
set -uo pipefail

ok()  { echo "  ✅ $*"; }
bad() { echo "  ❌ $*"; }

echo "== 机器 =="
echo "  主机名 $(hostnamectl --static)   内核 $(uname -r)   架构 $(uname -m)"
echo "  运行时长 $(uptime -p 2>/dev/null || uptime)"
echo "  内存 $(free -h | awk '/^Mem:/{print $3"/"$2}')   根分区 $(df -h / | awk 'NR==2{print $3"/"$2" ("$5")"}')"

echo
echo "== 网络 =="
IP="$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
IF="$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
[[ -n "${IP}" ]] && ok "局域网 ${IP} (${IF})" || bad "拿不到局域网地址"

echo
echo "== mDNS（homeassistant.local）=="
if systemctl is-active --quiet avahi-daemon; then
  ok "avahi-daemon 在跑"
  echo "     正在广播的地址："
  avahi-resolve -n "$(hostnamectl --static).local" 2>/dev/null | sed 's/^/       /' \
    || echo "       （avahi-resolve 查不到，装 avahi-utils 可看得更细）"
  grep -E "^allow-interfaces=" /etc/avahi/avahi-daemon.conf 2>/dev/null | sed 's/^/     /' \
    || echo "     ⚠️  没限制网卡 —— docker0 的地址可能被一起播出去（见 bootstrap.sh 注释）"
else
  bad "avahi-daemon 没在跑 → sudo systemctl enable --now avahi-daemon"
fi

echo
echo "== Docker =="
if command -v docker >/dev/null 2>&1; then
  ok "$(docker --version)"
  sudo docker ps --format '     {{.Names}}\t{{.Status}}\t{{.Image}}' 2>&1
else
  bad "没装 Docker → ./bootstrap.sh"
fi

echo
echo "== Home Assistant =="
if [[ -f /opt/ha/config/.HA_VERSION ]]; then
  echo "     配置目录版本 $(cat /opt/ha/config/.HA_VERSION)   占用 $(sudo du -sh /opt/ha/config | cut -f1)"
fi
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:8123" || true)"
if [[ "${CODE}" == "200" || "${CODE}" == "302" ]]; then
  ok "http://${IP}:8123  (HTTP ${CODE})"
  ok "http://$(hostnamectl --static).local:8123"
else
  bad "8123 不可达 (HTTP ${CODE:-无响应}) → sudo docker logs --tail 50 homeassistant"
fi

echo
echo "== 鼠标桥 =="
if systemctl list-unit-files 2>/dev/null | grep -q '^mouse-bridge\.service'; then
  systemctl is-active --quiet mouse-bridge && ok "mouse-bridge 在跑" || bad "mouse-bridge 没在跑 → sudo journalctl -u mouse-bridge -n 50"
  echo "     认到的鼠标："
  sudo /opt/mouse-bridge/linux/evdev-source.py --list 2>/dev/null | sed 's/^/       /' || echo "       （列不出来）"
else
  echo "  ·  还没装（见 mouse-bridge/README.md）"
fi
