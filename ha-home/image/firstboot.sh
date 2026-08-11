#!/usr/bin/env bash
# 首次开机时由 cloud-init 调一次（见 build-image.sh 写进去的 user-data）。
# 做的都是「必须等到真机器上、拿到真网卡才能做」的事：
#   1. 让 avahi 只在真正的局域网口上广播（装机时不知道网卡叫什么）
#   2. 把预装在镜像里的 Home Assistant 容器镜像 load 进 Docker
#   3. 起 Home Assistant
#   4. 条件满足就把鼠标桥也拉起来
#
# 全过程写日志到 /var/log/ha-firstboot.log，关键进度同时打到屏幕上（/dev/console），
# 这样人在显示器前能看见到哪一步了。跑完留个标记文件，重跑一次也不会出乱子。
set -uo pipefail

LOG=/var/log/ha-firstboot.log
MARK=/var/lib/ha-firstboot.done
exec >>"${LOG}" 2>&1

say() {
  echo "[$(date '+%F %T')] $*"
  echo "[ha-home] $*" > /dev/console 2>/dev/null || true
}

say "===== 首次开机自动配置开始 ====="

# ---------- 1. 等网络 ----------
# 没网的话 avahi 播不出去、HA 也连不上米家云。最多等 60 秒，等不到也继续
# （HA 本身能离线启动，网通了会自己恢复）。
for i in $(seq 1 30); do
  IF="$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
  [[ -n "${IF}" ]] && break
  sleep 2
done
IP="$(ip route get 223.5.5.5 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
say "网卡=${IF:-未就绪} 地址=${IP:-无}"

# ---------- 2. avahi 只在局域网口广播 ----------
# 为什么要限制：avahi 默认在所有网卡上播，装了 Docker 之后会把 docker0 的
# 172.17.0.1 也当成自己的地址播出去。局域网里的 Mac/iPhone 拿到那个地址连不上，
# 表现成「homeassistant.local 时好时坏」。这条在试验台上实测过。
if [[ -n "${IF}" ]]; then
  if grep -qE "^#?allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
    sed -i "s|^#\?allow-interfaces=.*|allow-interfaces=${IF}|" /etc/avahi/avahi-daemon.conf
  else
    sed -i "/^\[server\]/a allow-interfaces=${IF}" /etc/avahi/avahi-daemon.conf
  fi
  say "avahi 绑定到 ${IF}"
fi
systemctl restart avahi-daemon && say "avahi 已启动，homeassistant.local 应该可以解析了"

# ---------- 3. 装载预置的 HA 镜像 ----------
# 镜像是在 Mac 上就拉好塞进这个磁盘镜像里的 —— 这台机器不用去 ghcr.io 拉，
# 那条线在国内慢到没法用。
TARBALL=/opt/ha/images/ha-image.tar.gz
if [[ -f "${TARBALL}" ]]; then
  say "装载 Home Assistant 容器镜像（约 600MB，这台机器上要一两分钟）"
  if docker load -i "${TARBALL}"; then
    say "装载完成，删掉压缩包腾出空间"
    rm -f "${TARBALL}"
  else
    say "⚠️ 装载失败 —— 起服务时会尝试联网拉取，可能很慢"
  fi
else
  say "没有预置镜像包，跳过"
fi

# ---------- 4. 起 Home Assistant ----------
say "启动 Home Assistant"
docker compose -f /opt/ha/docker-compose.yml up -d && say "容器已拉起"

# 给到 10 分钟：这台是 2013 年的双核，恢复过来的库第一次打开要建索引，会慢。
# 等不到也不算失败，HA 自己会继续起完。
for _ in $(seq 1 120); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8123 || true)"
  if [[ "${CODE}" == "200" || "${CODE}" == "302" ]]; then
    say "✅ Home Assistant 已就绪：http://homeassistant.local:8123  （或 http://${IP}:8123）"
    break
  fi
  sleep 5
done

# ---------- 5. 鼠标桥 ----------
# 令牌在、代码在、鼠标接收器插着，三者齐了才启动；缺哪个都只是不启动，不报错，
# 之后人手动 systemctl start 即可。
if [[ -f /etc/ha-home/mouse-bridge.env && -x /opt/mouse-bridge/run.sh ]]; then
  # 只认 config.json 里配的那两只 —— 不能看「有没有鼠标」，因为随便一只 PS/2
  # 鼠标都会让判断为真，而桥启动后发现没有匹配设备就退出，被 systemd 反复重启。
  # （在模拟器里就踩到了：QEMU 自带一只 PS/2 鼠标，差点让它空转重启。）
  WANTED="$(python3 -c 'import json;print("|".join(json.load(open("/opt/mouse-bridge/config.json"))["mice"]))' 2>/dev/null)"
  MICE=0
  [[ -n "${WANTED}" ]] && MICE="$(/opt/mouse-bridge/linux/evdev-source.py --list 2>/dev/null | grep -cE "^(${WANTED})" || true)"
  say "配置里那两只鼠标，现在插着 ${MICE} 只"
  if [[ "${MICE}" -ge 1 ]]; then
    systemctl enable --now mouse-bridge && say "鼠标桥已启动"
  else
    systemctl enable mouse-bridge
    say "没检测到鼠标（接收器没插？）—— 已设为开机自启，插上后 systemctl start mouse-bridge"
  fi
fi

date > "${MARK}"
say "===== 首次开机自动配置结束（完整日志见 ${LOG}）====="
