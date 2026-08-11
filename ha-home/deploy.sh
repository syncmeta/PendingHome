#!/usr/bin/env bash
# 【在 Mac 上跑】把这套东西推到实体机，包括鼠标桥的代码。
#
#   ./deploy.sh hey@homeassistant.local
#   ./deploy.sh hey@192.168.1.50 --with-token
#
# 走 tar over ssh，不用 rsync/scp —— 刚装好的 Debian 只有最小工具集，
# 这样对面只要有 ssh 和 tar（base 系统自带）就够，不用先去装东西。
#
# 鼠标桥的代码不在本目录里 —— 它的唯一一份源码在 ../ha-lab/mouse-bridge/，
# 这个脚本负责把它一起推进 ~/ha-home/mouse-bridge/，避免两份代码各自漂移。
#
# --with-token：顺手把 ../ha-lab/.env 里的 HA_TOKEN 灌进新机器的
#   /etc/ha-home/mouse-bridge.env（0600，root 独占）。令牌全程只经过管道，
#   不落临时文件、不打印、不出现在命令行参数里（ps 看不到）。
#   迁移过 .storage 之后，旧令牌在新机器上依然有效，不用重新签发。
set -euo pipefail

TARGET="${1:-}"
[[ -n "${TARGET}" ]] || { echo "用法：$0 <用户名>@<主机> [--with-token]" >&2; exit 2; }
shift
WITH_TOKEN=0
[[ "${1:-}" == "--with-token" ]] && WITH_TOKEN=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB="$(cd "${HERE}/../ha-lab" && pwd)"

echo "==> 推 ha-home → ${TARGET}:~/ha-home/"
# COPYFILE_DISABLE=1：macOS 的 tar 默认会把扩展属性打包成 ._xxx 伴生文件，
#   解到 Linux 上就是一堆垃圾（还会盖住同名文件的权限判断），关掉。
# --exclude '*.tgz'：备份包里有凭据，单独手动传，别混在例行部署里。
# --exclude './image'：装机镜像 1.6G，是用来写盘的、不是给机器自己的，别随手推过去。
COPYFILE_DISABLE=1 tar -czf - -C "${HERE}" \
    --exclude '*.tgz' --exclude '.DS_Store' --exclude './image' \
    . | ssh "${TARGET}" 'mkdir -p ~/ha-home && tar -xzf - -C ~/ha-home'

echo "==> 推鼠标桥源码 ${LAB}/mouse-bridge → ${TARGET}:~/ha-home/mouse-bridge/"
# 只带平台无关的那几个文件 + Linux 事件源 + 配置。macos/ 那份 Swift 用不上。
COPYFILE_DISABLE=1 tar -czf - -C "${LAB}/mouse-bridge" \
    bridge.py logic.py ha_client.py test_logic.py test_color_temp_range.py \
    config.json config.example.json linux \
    | ssh "${TARGET}" 'tar -xzf - -C ~/ha-home/mouse-bridge'

ssh "${TARGET}" 'chmod +x ~/ha-home/*.sh ~/ha-home/migrate/*.sh ~/ha-home/mouse-bridge/*.sh ~/ha-home/mouse-bridge/linux/*.py 2>/dev/null; ls ~/ha-home'

if [[ "${WITH_TOKEN}" -eq 1 ]]; then
  echo
  echo "==> 传令牌到 ${TARGET}:/etc/ha-home/mouse-bridge.env"
  [[ -f "${LAB}/.env" ]] || { echo "❌ 找不到 ${LAB}/.env" >&2; exit 1; }
  grep -E '^HA_TOKEN=' "${LAB}/.env" \
    | ssh "${TARGET}" 'sudo install -d -m 0700 /etc/ha-home && sudo tee /etc/ha-home/mouse-bridge.env >/dev/null && sudo chmod 600 /etc/ha-home/mouse-bridge.env'
  ssh "${TARGET}" 'sudo ls -l /etc/ha-home/mouse-bridge.env'
  echo "    （只回显了文件权限，内容没有打印）"
fi

echo
echo "✅ 推完了。到新机器上继续："
echo "   ssh ${TARGET}"
echo "   cd ~/ha-home && ./bootstrap.sh"
