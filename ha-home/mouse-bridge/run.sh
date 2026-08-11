#!/usr/bin/env bash
# 鼠标桥的启动包装：读 config.json 里配了哪几只鼠标，把事件源和桥接起来。
# 由 mouse-bridge.service 调用，也可以自己手动跑来排查。
#
#   GRAB=1 ./run.sh      独占模式：这两只鼠标不再移动光标，变成纯遥控器
#
# 设备标识只写在 config.json 一处，systemd 单元里不重复一遍 —— 换鼠标只改配置。
set -euo pipefail

DIR="${MOUSE_BRIDGE_DIR:-/opt/mouse-bridge}"
CFG="${DIR}/config.json"

[[ -f "${CFG}" ]] || { echo "找不到 ${CFG}" >&2; exit 1; }
[[ -n "${HA_TOKEN:-}" ]] || { echo "HA_TOKEN 没设 —— 检查 /etc/ha-home/mouse-bridge.env" >&2; exit 1; }

ARGS=()
while IFS= read -r dev; do ARGS+=(--device "$dev"); done < <(
  python3 -c 'import json,sys;[print(k) for k in json.load(open(sys.argv[1]))["mice"]]' "${CFG}"
)
[[ "${#ARGS[@]}" -gt 0 ]] || { echo "config.json 的 mice 是空的" >&2; exit 1; }
[[ -n "${GRAB:-}" ]] && ARGS+=(--grab)

# 上游（事件源）挂掉时下游读到 EOF 会跟着退出，整个单元由 systemd 重启。
# 接收器热插拔、开机时 USB 还没枚举完，都走这条路自愈。
exec "${DIR}/linux/evdev-source.py" "${ARGS[@]}" \
  | exec python3 "${DIR}/bridge.py" --config "${CFG}"
