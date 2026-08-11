#!/usr/bin/env bash
# 【在实体机上跑】把鼠标桥装成开机自启的系统服务。
#
#   cd ~/ha-home/mouse-bridge && ./install.sh
#   ./install.sh --start        装完直接启动（默认只装不启，先让你 --check 一遍）
#
# 装到哪：/opt/mouse-bridge（代码，root 所有、只读）
#         /etc/ha-home/mouse-bridge.env（令牌，root:root 0600）
#         /etc/systemd/system/mouse-bridge.service
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/opt/mouse-bridge"
ENV_FILE="/etc/ha-home/mouse-bridge.env"
START=0
[[ "${1:-}" == "--start" ]] && START=1

for f in bridge.py logic.py ha_client.py config.json run.sh linux/evdev-source.py; do
  [[ -f "${HERE}/${f}" ]] || { echo "❌ 缺 ${HERE}/${f} —— 先在 Mac 上跑 ha-home/deploy.sh" >&2; exit 1; }
done

echo "==> 1/5 建专用账号 mousebridge（加进 input 组，才能读 /dev/input/event*）"
if ! id -u mousebridge >/dev/null 2>&1; then
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin --groups input mousebridge
  echo "    已建"
else
  sudo usermod -aG input mousebridge
  echo "    已存在"
fi

echo
echo "==> 2/5 装代码到 ${DEST}"
sudo install -d -m 0755 "${DEST}" "${DEST}/linux"
sudo install -m 0644 "${HERE}"/bridge.py "${HERE}"/logic.py "${HERE}"/ha_client.py "${DEST}/"
sudo install -m 0755 "${HERE}/run.sh" "${DEST}/run.sh"
sudo install -m 0755 "${HERE}/linux/evdev-source.py" "${DEST}/linux/evdev-source.py"
[[ -f "${HERE}/README.md" ]] && sudo install -m 0644 "${HERE}/README.md" "${DEST}/README.md"

echo
echo "==> 3/5 配置"
# ha_url 改成本机回环：HA 就跑在这台机器上，走 127.0.0.1 最短、也不依赖
# 主机名解析或者 DHCP 地址。（试验台上那份指向虚拟机的局域网 IP，搬过来必须改。）
sudo python3 - "${HERE}/config.json" "${DEST}/config.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
cfg["ha_url"] = "http://127.0.0.1:8123"
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("    ha_url → http://127.0.0.1:8123")
for dev, spec in cfg["mice"].items():
    print("    %s → %s (%s)" % (dev, spec.get("label", "?"), spec["entity_id"]))
PY
sudo chmod 0644 "${DEST}/config.json"

echo
echo "==> 4/5 令牌"
if sudo test -f "${ENV_FILE}"; then
  sudo ls -l "${ENV_FILE}" | sed 's/^/    /'
else
  echo "    ❌ ${ENV_FILE} 不存在。两种办法二选一："
  echo "       · 在 Mac 上跑：ha-home/deploy.sh <目标> --with-token"
  echo "       · 或在这台机器上手敲（粘贴令牌后按 Ctrl-D）："
  echo "           sudo install -d -m 0700 /etc/ha-home"
  echo "           sudo tee ${ENV_FILE} <<< \"HA_TOKEN=<粘贴令牌>\" >/dev/null"
  echo "           sudo chmod 600 ${ENV_FILE}"
  echo "    （迁移过 .storage 之后，试验台那个令牌在这台机器上继续有效，不用重新签发。）"
fi

echo
echo "==> 5/5 装 systemd 单元"
sudo install -m 0644 "${HERE}/mouse-bridge.service" /etc/systemd/system/mouse-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable mouse-bridge >/dev/null
echo "    已设为开机自启"

echo
echo "========================================================"
echo "先干跑一遍（不动灯，只验配置和连通性）："
echo "  sudo -u mousebridge HA_TOKEN=\$(sudo sed -n 's/^HA_TOKEN=//p' ${ENV_FILE}) \\"
echo "    python3 ${DEST}/bridge.py --config ${DEST}/config.json --check"
echo
echo "看系统认到哪些鼠标（接收器要插好）："
echo "  sudo ${DEST}/linux/evdev-source.py --list"
echo
if [[ "${START}" -eq 1 ]]; then
  sudo systemctl restart mouse-bridge
  sleep 2
  sudo systemctl status mouse-bridge --no-pager | head -20
else
  echo "确认无误后启动："
  echo "  sudo systemctl start mouse-bridge"
  echo "  sudo journalctl -u mouse-bridge -f"
fi
echo "========================================================"
