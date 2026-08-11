#!/usr/bin/env bash
# 【在新的实体机上跑】把 01-backup-from-lab.sh 导出的包恢复成这台机器的 HA 数据。
#
#   ./02-restore.sh ~/ha-config-20260811-1130.tgz
#
# 恢复的是「整个 /opt/ha/config」，包含 .storage 里的凭据 —— 米家的设备证书、
# HA 的账号和长期令牌都在里面。所以恢复完不用重新登录米家、不用重配集成、
# 鼠标桥用的那个令牌也继续有效。
#
# 这个脚本只动 /opt/ha/config，不碰系统其他地方；原有内容会先挪到旁边留底。
set -euo pipefail

PKG="${1:-}"
DEST="/opt/ha"
[[ -n "${PKG}" && -f "${PKG}" ]] || { echo "用法：$0 <备份包.tgz>" >&2; exit 2; }

echo "==> 校验包"
tar -tzf "${PKG}" >/dev/null || { echo "❌ 包读不出来" >&2; exit 1; }
tar -tzf "${PKG}" | grep -q '^config/' || { echo "❌ 包里没有 config/ 顶层目录，不是本流程导出的包" >&2; exit 1; }
SRC_VER="$(tar -xzOf "${PKG}" config/.HA_VERSION 2>/dev/null | tr -d '[:space:]')"
echo "    源 HA 版本：${SRC_VER:-未知}"

# HA 的配置格式只能往前迁移，不能往回。用比源更旧的镜像去开这份数据，
# 轻则集成加载失败，重则把 .storage 写坏。所以第一次起容器请显式指定同版本：
#   HA_IMAGE=ghcr.io/home-assistant/home-assistant:${SRC_VER} ~/ha-home/ha-up.sh
echo
echo "==> 停 Home Assistant（如果在跑）"
if command -v docker >/dev/null 2>&1 && sudo docker ps -a --format '{{.Names}}' | grep -qx homeassistant; then
  sudo docker stop homeassistant >/dev/null 2>&1 || true
  echo "    已停"
else
  echo "    还没有这个容器，跳过"
fi

sudo install -d -m 0755 "${DEST}"
if sudo test -d "${DEST}/config" && [[ -n "$(sudo ls -A "${DEST}/config" 2>/dev/null)" ]]; then
  BAK="${DEST}/config.bak-$(date +%Y%m%d-%H%M%S)"
  echo "==> 原有 ${DEST}/config 非空，先挪到 ${BAK}"
  sudo mv "${DEST}/config" "${BAK}"
fi

echo "==> 解包到 ${DEST}"
# --same-owner + -p：.storage/auth 这些是 root:root 0600，权限必须原样带过来，
# 掉了权限 HA 会拒绝加载或者把凭据暴露给别的账号。
sudo tar -xzpf "${PKG}" --same-owner -C "${DEST}"
sudo test -f "${DEST}/config/.HA_VERSION" || { echo "❌ 解完没看到 .HA_VERSION" >&2; exit 1; }

echo
echo "==> 落地检查"
sudo ls -l "${DEST}/config/.storage/auth" | sed 's/^/    /'
echo "    米家证书：$(sudo ls "${DEST}/config/.storage/xiaomi_home/cert/" 2>/dev/null | tr '\n' ' ')"
echo "    实体数量：$(sudo python3 -c 'import json;print(len(json.load(open("/opt/ha/config/.storage/core.entity_registry"))["data"]["entities"]))' 2>/dev/null || echo '?')"
echo "    集成条目：$(sudo python3 -c 'import json;print(", ".join(sorted({e["domain"] for e in json.load(open("/opt/ha/config/.storage/core.config_entries"))["data"]["entries"]})))' 2>/dev/null || echo '?')"
echo "    占用：$(sudo du -sh "${DEST}/config" | cut -f1)"

echo
echo "========================================================"
echo "✅ 数据已就位。第一次启动请用**和源一样的版本**，起来验过再升级："
echo
echo "   HA_IMAGE=ghcr.io/home-assistant/home-assistant:${SRC_VER:-<源版本>} ~/ha-home/ha-up.sh"
echo
echo "验通之后要升到最新，把 HA_IMAGE 去掉再跑一次 ha-up.sh 即可（stable 只会更新）。"
echo "========================================================"
