#!/usr/bin/env bash
# 在刚装好的 Debian 12(t630)上,以一个能 sudo 的普通用户运行:
#   chmod +x bootstrap.sh && ./bootstrap.sh
# 装 Docker + 常用工具,并给日志设上限保护 SSD。
set -euo pipefail

echo "==> 1/4 更新系统 + 基础工具"
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl gnupg git ffmpeg vainfo

echo "==> 2/4 安装 Docker(官方源)"
sudo install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"

echo "==> 3/4 限制 Docker 容器日志大小(每容器最多 3×10MB)"
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON

echo "==> 4/4 限制 systemd journal 占用(最多 200MB)"
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/size.conf >/dev/null <<'CONF'
[Journal]
SystemMaxUse=200M
CONF
sudo systemctl restart systemd-journald
sudo systemctl restart docker

echo
echo "==> 完成。现在需要【退出重新登录一次】(或 reboot),让 docker 用户组生效。"
echo "    之后:cd 到本目录,运行  docker compose up -d"
