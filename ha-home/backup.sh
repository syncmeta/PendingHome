#!/usr/bin/env bash
# 【在实体机上跑】把 /opt/ha/config 打包到 /var/backups/ha/，保留最近 7 份。
# 装成每天凌晨 4 点自动跑：
#     sudo crontab -e
#     0 4 * * * /home/<你的用户名>/ha-home/backup.sh >/var/log/ha-backup.log 2>&1
#
# 会短暂停一下 HA（约 30 秒）再打包 —— 理由和 migrate/01 一样：
# SQLite 的 WAL 要先归并进主库，快照才是一致的。
set -euo pipefail

DEST_DIR="${DEST_DIR:-/var/backups/ha}"
KEEP="${KEEP:-7}"
STAMP="$(date +%Y%m%d-%H%M)"
OUT="${DEST_DIR}/ha-config-${STAMP}.tgz"

install -d -m 0700 "${DEST_DIR}"

WAS_RUNNING=0
if docker ps --format '{{.Names}}' | grep -qx homeassistant; then
  WAS_RUNNING=1
  docker stop homeassistant >/dev/null
fi
trap '[[ "${WAS_RUNNING}" -eq 1 ]] && docker start homeassistant >/dev/null || true' EXIT

tar -czf "${OUT}" -C /opt/ha \
  --exclude=config/home-assistant.log \
  --exclude=config/home-assistant.log.1 \
  --exclude=config/home-assistant.log.fault \
  --exclude=config/.ha_run.lock \
  config
chmod 600 "${OUT}"

# 只删自己产的那类文件，别拿通配符扫整个目录。
ls -1t "${DEST_DIR}"/ha-config-*.tgz 2>/dev/null | tail -n "+$((KEEP+1))" | xargs -r rm -f

echo "$(date '+%F %T')  备份完成 ${OUT}  $(du -h "${OUT}" | cut -f1)"
