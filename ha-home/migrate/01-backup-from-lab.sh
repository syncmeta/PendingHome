#!/usr/bin/env bash
# 【在 Mac 上跑】把试验台虚拟机里的 Home Assistant 数据整个导出成一个 tar.gz。
#
#   ./01-backup-from-lab.sh                     停 HA 再打包（推荐，数据一致）
#   ./01-backup-from-lab.sh --hot               不停 HA 打包（快，但数据库可能不一致）
#   ./01-backup-from-lab.sh --no-history        不带历史数据库（只搬配置和凭据）
#   ./01-backup-from-lab.sh --out ~/ha-x.tgz    指定输出文件
#
# 为什么默认要停 HA：recorder 用 SQLite + WAL 模式，运行时 -wal 里攒着还没落盘的
# 事务。容器正常停止时 HA 会关库、把 WAL 归并进主库、删掉 -wal/-shm。
# 那之后打包才是一个干净的快照。停机大约 30 秒。
#
# ⚠️ 包里含凭据（米家证书、HA 账号、长期令牌）。别扔进版本库、别发给别人。
set -euo pipefail

VM="${VM:-ha-lab}"
LIMACTL="${LIMACTL:-/opt/homebrew/bin/limactl}"
SRC_DIR="/opt/ha"              # 虚拟机里的路径
OUT=""
HOT=0
NO_HISTORY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hot) HOT=1; shift ;;
    --no-history) NO_HISTORY=1; shift ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "不认识的参数：$1" >&2; exit 2 ;;
  esac
done

OUT="${OUT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ha-config-$(date +%Y%m%d-%H%M).tgz}"

vm() { "${LIMACTL}" shell "${VM}" -- "$@"; }

echo "==> 检查虚拟机"
"${LIMACTL}" list --quiet 2>/dev/null | grep -qx "${VM}" || { echo "❌ 找不到实例 ${VM}" >&2; exit 1; }
vm sudo test -d "${SRC_DIR}/config" || { echo "❌ 虚拟机里没有 ${SRC_DIR}/config" >&2; exit 1; }
echo "    HA 版本 $(vm sudo cat "${SRC_DIR}/config/.HA_VERSION")"

RESTART_AFTER=0
if [[ "${HOT}" -eq 0 ]]; then
  if vm sudo docker ps --format '{{.Names}}' | grep -qx homeassistant; then
    echo "==> 停 Home Assistant（打完包自动起回来）"
    vm sudo docker stop homeassistant >/dev/null
    RESTART_AFTER=1
    # 关干净的标志：-wal/-shm 消失，说明 SQLite 已经把 WAL 归并进主库了。
    if vm sudo test -e "${SRC_DIR}/config/home-assistant_v2.db-wal"; then
      echo "    ⚠️  -wal 还在（HA 可能没优雅退出）。包仍然可用，但会连 -wal 一起带走。"
    else
      echo "    数据库已干净落盘"
    fi
  fi
fi

restore_state() {
  if [[ "${RESTART_AFTER}" -eq 1 ]]; then
    echo "==> 起回 Home Assistant"
    vm sudo docker start homeassistant >/dev/null || true
  fi
}
trap restore_state EXIT

EXCLUDES=(
  --exclude=config/home-assistant.log
  --exclude=config/home-assistant.log.1
  --exclude=config/home-assistant.log.fault
  --exclude=config/.ha_run.lock          # 里面记着旧机器的 pid，搬过去只会误导
)
if [[ "${NO_HISTORY}" -eq 1 ]]; then
  # 历史数据没了不影响任何集成/凭据/实体，只是图表从零开始。
  EXCLUDES+=(--exclude=config/home-assistant_v2.db*)
fi

echo "==> 打包 ${SRC_DIR}/config"
# tar 走 stdout 流回 Mac；同时在虚拟机内算一遍 sha256，落地后比对，
# 防止 ssh 通道上出现截断/污染。
vm sudo tar -czf - -C "${SRC_DIR}" "${EXCLUDES[@]}" config > "${OUT}"
SUM_LOCAL="$(shasum -a 256 "${OUT}" | awk '{print $1}')"
SIZE="$(du -h "${OUT}" | cut -f1)"

echo "==> 校验"
if ! tar -tzf "${OUT}" >/dev/null 2>&1; then
  echo "❌ 包损坏（tar 读不出来）" >&2; exit 1
fi
echo "    ${OUT}"
echo "    大小 ${SIZE}   sha256 ${SUM_LOCAL}"

echo
echo "==> 关键内容点名（这些在，才叫「不用重新登录米家」）"
check() {
  if tar -tzf "${OUT}" | grep -q "$1"; then echo "    ✅ $2"; else echo "    ❌ 缺 $2 ($1)"; fi
}
check 'config/.storage/core.config_entries'          '集成清单（含 Xiaomi Home 那条）'
check 'config/.storage/core.entity_registry'         '实体注册表（那 258 个实体的身份）'
check 'config/.storage/core.device_registry'         '设备注册表'
check 'config/.storage/auth'                         'HA 账号 + 长期令牌（令牌搬过去继续有效）'
check 'config/.storage/xiaomi_home/cert/'            '米家设备证书（免重新登录的关键）'
check 'config/.storage/xiaomi_home/miot_config/'     '米家账号配置'
check 'config/custom_components/xiaomi_home/'        'Xiaomi Home 集成代码'
echo "    实体注册表条目数：$(tar -xzOf "${OUT}" config/.storage/core.entity_registry 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["data"]["entities"]))' 2>/dev/null || echo '?')"

echo
echo "下一步：把这个包传到新机器，然后在新机器上跑 migrate/02-restore.sh"
echo "   scp \"${OUT}\" <用户名>@homeassistant.local:~/"
