#!/bin/bash
# 把 compose 文件同步进虚拟机并起 Home Assistant，然后等 8123 起来。
# 改完 homeassistant/docker-compose.yml 之后重跑这个脚本即可生效。
set -euo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMACTL="/opt/homebrew/bin/limactl"
VM="ha-lab"

echo "==> 同步 compose 文件到虚拟机 /opt/ha/"
# /mnt/ha-lab 是 lima 只读挂进去的 ha-lab/ 目录（见 lima/ha-lab.yaml）。
# HA 的运行时数据放 /opt/ha/config —— 在虚拟机自己的磁盘上，不走共享挂载，
# 免得 SQLite 数据库踩到 virtiofs 的文件锁问题。
"${LIMACTL}" shell "${VM}" -- sudo install -d -m 0755 /opt/ha /opt/ha/config
"${LIMACTL}" shell "${VM}" -- sudo cp /mnt/ha-lab/homeassistant/docker-compose.yml /opt/ha/docker-compose.yml
"${LIMACTL}" shell "${VM}" -- sudo cp /mnt/ha-lab/homeassistant/docker-compose.lab-proxy.yml /opt/ha/docker-compose.lab-proxy.yml

echo "==> 拉镜像并启动（首次拉取要几分钟）"
"${LIMACTL}" shell "${VM}" -- sudo docker compose \
  -f /opt/ha/docker-compose.yml \
  -f /opt/ha/docker-compose.lab-proxy.yml \
  up -d

IP="$("${LAB_DIR}/scripts/vm-ip.sh")"
URL="http://${IP}:8123"

echo "==> 等 ${URL} 起来"
for i in $(seq 1 60); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "${URL}" || true)"
  if [[ "${CODE}" == "200" || "${CODE}" == "302" ]]; then
    echo
    echo "✅ Home Assistant 起来了：${URL}   (HTTP ${CODE})"
    exit 0
  fi
  sleep 5
done

echo "❌ 等了 5 分钟 8123 还没响应，看日志：" >&2
echo "   limactl shell ${VM} -- sudo docker logs --tail 100 homeassistant" >&2
exit 1
