#!/usr/bin/env bash
# 在刚装好 Debian 12 的那台实体机上，用一个能 sudo 的普通用户运行：
#     cd ~/ha-home && chmod +x bootstrap.sh && ./bootstrap.sh
#
# 干六件事，都可重复执行：
#   1. 系统更新 + 基础工具
#   2. 主机名设成 homeassistant（为了 homeassistant.local）
#   3. 装 Docker（官方源）
#   4. 装 avahi-daemon 并只让它在局域网口上广播
#   5. 给容器日志和 journal 设上限，保护固态
#   6. 把当前用户加进 docker 和 input 组
#
# ⚠️ 未在目标硬件上验证 —— 这台机器还没到手。逐条的依据见 README。
set -euo pipefail

HOSTNAME_WANT="${HOSTNAME_WANT:-homeassistant}"

if [[ "${EUID}" -eq 0 ]]; then
  echo "别用 root 跑，用你装系统时建的那个普通用户（脚本内部会自己 sudo）。" >&2
  exit 1
fi

echo "==> 1/6 系统更新 + 基础工具"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
sudo DEBIAN_FRONTEND=noninteractive apt-get -y install \
  ca-certificates curl gnupg git tar rsync

echo
echo "==> 2/6 主机名 → ${HOSTNAME_WANT}"
# .local 那个名字就是「主机名 + avahi 广播」拼出来的，改名必须在装 avahi 之前
# 或之后重启 avahi，否则广播出去的还是旧名字。
CURRENT_HOST="$(hostnamectl --static)"
if [[ "${CURRENT_HOST}" != "${HOSTNAME_WANT}" ]]; then
  sudo hostnamectl set-hostname "${HOSTNAME_WANT}"
  # /etc/hosts 里那行也要跟着改，否则每条 sudo 都会卡一下去解析旧名字
  if grep -qE "^127\.0\.1\.1[[:space:]]" /etc/hosts; then
    sudo sed -i "s/^127\.0\.1\.1[[:space:]].*/127.0.1.1\t${HOSTNAME_WANT}/" /etc/hosts
  else
    echo -e "127.0.1.1\t${HOSTNAME_WANT}" | sudo tee -a /etc/hosts >/dev/null
  fi
  echo "    改好了（当前 shell 的提示符要重新登录才变）"
else
  echo "    已经是 ${HOSTNAME_WANT}"
fi

echo
echo "==> 3/6 安装 Docker（官方源）"
if command -v docker >/dev/null 2>&1; then
  echo "    已装：$(docker --version)"
else
  sudo install -m0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y install \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

echo
echo "==> 4/6 安装并配置 avahi（让 ${HOSTNAME_WANT}.local 真的能用）"
sudo DEBIAN_FRONTEND=noninteractive apt-get -y install avahi-daemon libnss-mdns

# 只在真正的局域网口上广播。
# 为什么必须限制：avahi 默认在**所有**网卡上广播地址，装了 Docker 之后就会把
# docker0 的 172.17.0.1 也当成自己的地址播出去。局域网里的 Mac/iPhone 拿到
# 这个地址根本连不上，表现成「homeassistant.local 时好时坏 / 要等很久」。
# 已在试验台虚拟机上实测：限制前播 4 个地址（含 172.17.0.1），限制后只剩局域网那个。
LAN_IF="${LAN_IF:-$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')}"
if [[ -z "${LAN_IF}" ]]; then
  echo "    ⚠️  认不出局域网网卡，跳过 allow-interfaces；请手动填 /etc/avahi/avahi-daemon.conf" >&2
else
  echo "    局域网网卡：${LAN_IF}"
  sudo cp -n /etc/avahi/avahi-daemon.conf /etc/avahi/avahi-daemon.conf.orig
  if grep -qE "^#?allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
    sudo sed -i "s|^#\?allow-interfaces=.*|allow-interfaces=${LAN_IF}|" /etc/avahi/avahi-daemon.conf
  else
    sudo sed -i "/^\[server\]/a allow-interfaces=${LAN_IF}" /etc/avahi/avahi-daemon.conf
  fi
fi
sudo systemctl enable --now avahi-daemon
sudo systemctl restart avahi-daemon

echo
echo "==> 5/6 给日志设上限（保护固态）"
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/size.conf >/dev/null <<'CONF'
[Journal]
SystemMaxUse=200M
CONF
sudo systemctl restart systemd-journald
sudo systemctl enable --now docker
sudo systemctl restart docker

echo
echo "==> 6/6 用户组"
# docker 组：免得每条 docker 命令都要 sudo
# input  组：鼠标桥要读 /dev/input/event*（服务本身用的是自己的账号，
#            这里加当前用户是为了你能手动跑 evdev-source.py --list 排查）
sudo usermod -aG docker,input "$USER"
sudo install -d -m 0755 /opt/ha /opt/ha/config

echo
echo "========================================================"
echo "✅ 装完了。现在必须【退出 ssh 重新登录一次】，让 docker/input 组生效。"
echo
echo "重连后自检："
echo "  docker --version && docker compose version"
echo "  groups | tr ' ' '\\n' | grep -E 'docker|input'"
echo "  hostnamectl --static           # 应显示 ${HOSTNAME_WANT}"
echo "  systemctl is-active avahi-daemon"
echo
echo "然后在 Mac 上验名字（这是关键的一步）："
echo "  ping -c2 ${HOSTNAME_WANT}.local"
echo "========================================================"
