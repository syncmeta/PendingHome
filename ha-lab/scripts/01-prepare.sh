#!/bin/bash
# 把 lima/networks.yaml 装到 ~/.lima/_config/networks.yaml。
# 必须在 02-sudo-setup.sh 之前跑 —— 那一步生成的 sudoers 文件内容是
# 从这份配置里的 socketVMNet / varRun 路径推出来的。
# 不需要 sudo，可重复执行。
set -euo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HOME}/.lima/_config/networks.yaml"

mkdir -p "$(dirname "${DEST}")"

if [[ -f "${DEST}" ]] && ! cmp -s "${LAB_DIR}/lima/networks.yaml" "${DEST}"; then
  BACKUP="${DEST}.bak.$(date +%Y%m%d%H%M%S)"
  cp "${DEST}" "${BACKUP}"
  echo "已备份原配置到 ${BACKUP}"
fi

cp "${LAB_DIR}/lima/networks.yaml" "${DEST}"
echo "✅ 已安装 ${DEST}"
echo
echo "桥接网卡是 en7，当前状态："
ifconfig en7 2>/dev/null | awk '/inet |status:/ {print "   " $0}' || echo "   ⚠️  找不到 en7，去 lima/networks.yaml 里改成实际网卡"
echo
echo "下一步：请人类执行  ! sudo bash ${LAB_DIR}/scripts/02-sudo-setup.sh"
