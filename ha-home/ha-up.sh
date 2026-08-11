#!/usr/bin/env bash
# 在实体机上跑：把 docker-compose.yml 放到 /opt/ha 并起 Home Assistant。
# 改完 docker-compose.yml 之后重跑一次就生效。
#
#   ./ha-up.sh                 用 compose 里写的镜像
#   HA_IMAGE=ghcr.io/home-assistant/home-assistant:2026.8.1 ./ha-up.sh
#                              临时指定版本（迁移恢复时用，见 MIGRATION.md）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# HA 的运行时数据固定在 /opt/ha/config —— 和试验台保持一致，
# 迁移脚本、备份脚本、README 里的路径都按这个来。
sudo install -d -m 0755 /opt/ha /opt/ha/config
sudo cp "${HERE}/docker-compose.yml" /opt/ha/docker-compose.yml

if [[ -n "${HA_IMAGE:-}" ]]; then
  echo "==> 覆盖镜像为 ${HA_IMAGE}"
  sudo tee /opt/ha/docker-compose.override.yml >/dev/null <<EOF
services:
  homeassistant:
    image: ${HA_IMAGE}
EOF
else
  sudo rm -f /opt/ha/docker-compose.override.yml
fi

echo "==> 拉镜像（首次约 600MB，国内可能很慢，见 README「镜像拉不动」）"
sudo docker compose -f /opt/ha/docker-compose.yml \
  $( [[ -f /opt/ha/docker-compose.override.yml ]] && echo "-f /opt/ha/docker-compose.override.yml" ) \
  up -d

IP="$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
URL="http://${IP:-127.0.0.1}:8123"

echo "==> 等 ${URL} 起来（首次启动要装依赖，可能两三分钟）"
for _ in $(seq 1 60); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "${URL}" || true)"
  if [[ "${CODE}" == "200" || "${CODE}" == "302" ]]; then
    echo
    echo "✅ Home Assistant 起来了："
    echo "   ${URL}"
    echo "   http://$(hostnamectl --static).local:8123"
    exit 0
  fi
  sleep 5
done

echo "❌ 等了 5 分钟 8123 还没响应，看日志：" >&2
echo "   sudo docker logs --tail 100 homeassistant" >&2
exit 1
