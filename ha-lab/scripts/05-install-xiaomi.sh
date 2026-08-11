#!/bin/bash
# 把小米官方的 Home Assistant 集成（Xiaomi Home）装进虚拟机里的 HA。
#
#   ./scripts/05-install-xiaomi.sh            装最新版
#   ./scripts/05-install-xiaomi.sh v0.4.7     装指定版本
#
# 装完还要人在浏览器里登录米家账号，脚本不碰账号（见 README「接入米家设备」）。
#
# 说明：集成是安装时从 GitHub 下载的，不把第三方代码塞进这个仓库 ——
# 升级只要重跑一次脚本，也省得我们替上游维护一份拷贝。
# 下载走 dockerd 那条代理隧道（GitHub 直连拉不动），所以要先 proxy-tunnel.sh up。
set -euo pipefail

LIMACTL="/opt/homebrew/bin/limactl"
VM="ha-lab"
REPO="XiaoMi/ha_xiaomi_home"
PROXY="http://127.0.0.1:${PROXY_PORT:-10898}"
DEST="/opt/ha/config/custom_components"

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  echo "==> 查最新版本"
  VERSION="$(curl -s --max-time 15 "https://api.github.com/repos/${REPO}/releases/latest" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["tag_name"])')"
fi
echo "    版本 ${VERSION}"

URL="https://github.com/${REPO}/releases/download/${VERSION}/xiaomi_home.zip"

echo "==> 在虚拟机里下载并安装到 ${DEST}/<domain>"
# 注意：这个发布包解压出来是「一堆文件直接在根目录」，外面没有套目录。
# 所以必须先解到临时目录，读出 manifest 里的 domain，再整个搬成
# custom_components/<domain>/ —— HA 强制要求目录名等于 domain。
# 直接 unzip 到 custom_components 会把文件散一地，HA 根本认不出来。
"${LIMACTL}" shell "${VM}" -- sudo bash -c "
set -euo pipefail
command -v unzip >/dev/null || { apt-get update -qq && apt-get install -y -qq unzip; }
tmp=\$(mktemp -d)
trap 'rm -rf \"\$tmp\"' EXIT

# GitHub 直连拉不动，走代理隧道；隧道没开就直接失败，别装出个半截。
curl -fsSL --max-time 120 -x '${PROXY}' -o \"\$tmp/x.zip\" '${URL}'
unzip -q \"\$tmp/x.zip\" -d \"\$tmp/x\"

manifest=\$(find \"\$tmp/x\" -maxdepth 2 -name manifest.json | head -1)
[ -n \"\$manifest\" ] || { echo '发布包里找不到 manifest.json' >&2; exit 1; }
domain=\$(python3 -c \"import json,sys;print(json.load(open(sys.argv[1]))['domain'])\" \"\$manifest\")

mkdir -p '${DEST}'
rm -rf \"${DEST}/\$domain\"
mv \"\$(dirname \"\$manifest\")\" \"${DEST}/\$domain\"
chown -R root:root \"${DEST}/\$domain\"
echo \"    安装到 ${DEST}/\$domain\"
"

echo "==> 装好的版本"
"${LIMACTL}" shell "${VM}" -- sudo python3 -c "
import json
m = json.load(open('${DEST}/xiaomi_home/manifest.json'))
print('    %s  version=%s  ha>=%s' % (m['domain'], m.get('version'), m.get('homeassistant','?')))
"

echo "==> 重启 Home Assistant 让它认到新集成"
"${LIMACTL}" shell "${VM}" -- sudo docker restart homeassistant >/dev/null

IP="$("$(dirname "${BASH_SOURCE[0]}")/vm-ip.sh")"
echo "==> 等 HA 起来"
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://${IP}:8123" || true)"
  [[ "${code}" == "200" || "${code}" == "302" ]] && break
  sleep 5
done

echo
echo "✅ 集成已装好。接下来要人在浏览器里操作（我们不碰你的米家账号）："
echo "   http://${IP}:8123 → 设置 → 设备与服务 → 右下角「添加集成」→ 搜 Xiaomi Home"
echo "   → 服务器地区选「中国大陆」→ 扫码或输账号密码登录 → 勾选那两盏灯"
