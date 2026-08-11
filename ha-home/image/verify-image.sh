#!/usr/bin/env bash
# 把造好的镜像挂起来逐项体检。**在 Lima 虚拟机里以 root 运行。**
#
#   sudo ./verify-image.sh /var/tmp/build/ha-home.img
#
# 能在这儿验的都验（结构、装了什么、数据在不在、配置语法）。
# **引导能不能成、网卡认不认，只有真机上电才知道** —— 这个脚本不会假装验过。
set -uo pipefail

IMG="${1:-}"
[[ -f "${IMG}" ]] || { echo "用法：$0 <镜像文件>" >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo "要 root" >&2; exit 1; }

MNT=/mnt/ha-home-verify
LOOP=""
PASS=0; FAIL=0
ok()   { echo "  ✅ $*"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
note() { echo "  ·  $*"; }
check() { if [[ "$1" -eq 0 ]]; then ok "$2"; else bad "$2"; fi; }

cleanup() {
  set +e
  umount "${MNT}/dev/pts" "${MNT}/dev" "${MNT}/proc" "${MNT}/sys" "${MNT}/boot/efi" "${MNT}" 2>/dev/null
  [[ -n "${LOOP}" ]] && losetup -d "${LOOP}" 2>/dev/null
}
trap cleanup EXIT

echo "== 1. 分区结构（决定它能不能被 BIOS / UEFI 认出来）=="
sfdisk -l "${IMG}" 2>/dev/null | grep -E "^/|Disklabel" | sed 's/^/     /'
sfdisk -l "${IMG}" 2>/dev/null | grep -q "BIOS boot"
check $? "有 BIOS boot 分区（传统 BIOS 引导用）"
sfdisk -l "${IMG}" 2>/dev/null | grep -q "EFI System"
check $? "有 EFI System 分区（UEFI 引导用）"

echo
echo "== 2. 引导代码 =="
python3 - "${IMG}" <<'PY'
import sys
d = open(sys.argv[1], "rb").read(512)
mbr = d[:440]
print("  %s MBR 里有 GRUB 引导代码" % ("✅" if b"GRUB" in mbr else "❌"))
print("  %s MBR 签名 0x55AA" % ("✅" if d[510:512] == b"\x55\xaa" else "❌"))
PY

LOOP="$(losetup -f --show -P "${IMG}")"
mkdir -p "${MNT}"
mount "${LOOP}p1" "${MNT}" || { echo "根分区挂不上"; exit 1; }
mount "${LOOP}p15" "${MNT}/boot/efi"

[[ -f "${MNT}/boot/efi/EFI/BOOT/BOOTX64.EFI" ]]
check $? "EFI/BOOT/BOOTX64.EFI 在（UEFI 找不到启动项时就认这个路径）"
[[ -f "${MNT}/boot/efi/EFI/debian/grubx64.efi" ]]
check $? "EFI/debian/grubx64.efi 在"

echo
echo "== 3. 内核与根文件系统 =="
KERNEL="$(ls "${MNT}"/boot/vmlinuz-* 2>/dev/null | tail -1)"
[[ -n "${KERNEL}" ]]
check $? "内核 $(basename "${KERNEL:-无}")"
ls "${MNT}"/boot/initrd.img-* >/dev/null 2>&1
check $? "initramfs 在"
note "根分区 $(df -h "${MNT}" | awk 'NR==2{print $2, "已用", $3}')"

echo
echo "== 4. 镜像里装了什么（在 chroot 里查，amd64 靠 qemu 跑）=="
cp /usr/bin/qemu-x86_64-static "${MNT}/usr/bin/" 2>/dev/null
mount --bind /dev "${MNT}/dev"; mount --bind /dev/pts "${MNT}/dev/pts"
mount -t proc proc "${MNT}/proc"; mount -t sysfs sys "${MNT}/sys"
ARCH="$(chroot "${MNT}" /bin/uname -m 2>/dev/null)"
[[ "${ARCH}" == "x86_64" ]]
check $? "镜像是 x86_64（目标机是奔腾 G2030，对得上），实测 uname -m = ${ARCH}"
for p in docker-ce docker-compose-plugin containerd.io avahi-daemon libnss-mdns cloud-init intel-microcode firmware-realtek; do
  V="$(chroot "${MNT}" dpkg-query -W -f='${Version}' "$p" 2>/dev/null)"
  [[ -n "${V}" ]]
  check $? "$p ${V}"
done
for s in docker avahi-daemon; do
  chroot "${MNT}" systemctl is-enabled "$s" >/dev/null 2>&1
  check $? "$s 已设为开机自启"
done
chroot "${MNT}" id mousebridge >/dev/null 2>&1
check $? "鼠标桥专用账号在：$(chroot "${MNT}" id mousebridge 2>/dev/null)"

echo
echo "== 5. Home Assistant 数据（这是「不用重新登录米家」的关键）=="
[[ -f "${MNT}/opt/ha/config/.HA_VERSION" ]]
check $? "HA 数据版本 $(cat "${MNT}/opt/ha/config/.HA_VERSION" 2>/dev/null)"
PERM="$(stat -c '%U:%G %a' "${MNT}/opt/ha/config/.storage/auth" 2>/dev/null)"
[[ "${PERM}" == "root:root 600" ]]
check $? "凭据文件权限 ${PERM}（原样保留）"
[[ -d "${MNT}/opt/ha/config/.storage/xiaomi_home/cert" ]]
check $? "米家设备证书在"
python3 - "${MNT}" <<'PY'
import json, sys, os
mnt = sys.argv[1]
reg = json.load(open(os.path.join(mnt, "opt/ha/config/.storage/core.entity_registry")))
ents = reg["data"]["entities"]
print("  ·  实体注册表 %d 个实体" % len(ents))
ce = json.load(open(os.path.join(mnt, "opt/ha/config/.storage/core.config_entries")))
domains = sorted({e["domain"] for e in ce["data"]["entries"]})
print("  ·  集成：", ", ".join(domains))
print("  %s Xiaomi Home 集成配置在" % ("✅" if "xiaomi_home" in domains else "❌"))
ids = {e["entity_id"] for e in ents}
for lid in ("light.yeelink_cn_476282703_ceiling23_s_2_light",
            "light.yeelink_cn_56292508_mono1_s_2_light"):
    print("  %s %s" % ("✅" if lid in ids else "❌", lid))
PY

echo
echo "== 6. 预置的容器镜像（开机不用去 ghcr.io 拉）=="
T="${MNT}/opt/ha/images/ha-image.tar.gz"
[[ -f "${T}" ]]
check $? "预置镜像包在（$(du -h "${T}" 2>/dev/null | cut -f1)）"
if [[ -f "${T}" ]]; then
  python3 - "${T}" <<'PY'
import json, sys, tarfile
tf = tarfile.open(sys.argv[1], "r:gz")
def blob(name):
    return json.load(tf.extractfile(name))
idx = blob("index.json")
d = idx["manifests"][0]["digest"].split(":")[1]
man = blob("blobs/sha256/" + d)
cfgd = man["config"]["digest"].split(":")[1]
cfg = blob("blobs/sha256/" + cfgd)
arch = "%s/%s" % (cfg["os"], cfg["architecture"])
ver = cfg.get("config", {}).get("Labels", {}).get("io.hass.version")
print("  ·  平台 %s，Home Assistant 版本 %s" % (arch, ver))
print("  %s 预置镜像确认是 linux/amd64" % ("✅" if cfg["architecture"] == "amd64" else "❌"))
PY
fi
PINNED="$(grep -oE 'home-assistant:[0-9][0-9.]*' "${MNT}/opt/ha/docker-compose.yml" 2>/dev/null)"
[[ -n "${PINNED}" ]]
check $? "compose 里版本钉死为 ${PINNED:-未钉}（不会开机去拉 stable）"

echo
echo "== 7. 首次开机的自动配置 =="
[[ -x "${MNT}/opt/ha-firstboot/firstboot.sh" ]]
check $? "首启脚本在且可执行"
bash -n "${MNT}/opt/ha-firstboot/firstboot.sh" 2>/dev/null
check $? "首启脚本语法通过"
SEED="${MNT}/var/lib/cloud/seed/nocloud"
[[ -f "${SEED}/user-data" && -f "${SEED}/meta-data" ]]
check $? "cloud-init 种子就位（NoCloud）"
python3 - "${SEED}/user-data" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
u = d["users"][0]
print("  ·  主机名 %s | 用户 %s | 附加组 %s" % (d["hostname"], u["name"], ",".join(u["groups"])))
print("  ·  根分区自动扩容 %s | SSH 密码登录 %s | 时区 %s"
      % (d["resize_rootfs"], d["ssh_pwauth"], d["timezone"]))
good = (d["hostname"] == "homeassistant"
        and u["ssh_authorized_keys"][0].startswith("ssh-")
        and d["ssh_pwauth"] is False
        and d["resize_rootfs"] is True)
print("  %s user-data 是合法 YAML 且内容对得上" % ("✅" if good else "❌"))
PY
grep -q "NoCloud" "${MNT}/etc/cloud/cloud.cfg.d/99-ha-home.cfg" 2>/dev/null
check $? "数据源钉成 NoCloud（不去探云元数据，省一两分钟）"
[[ ! -s "${MNT}/etc/machine-id" ]]
check $? "machine-id 已清空（留给首次开机生成，避免 DHCP 撞车）"
[[ ! -e "${MNT}/usr/bin/qemu-x86_64-static.bak" ]]

echo
echo "== 8. 鼠标桥 =="
for f in run.sh bridge.py logic.py ha_client.py config.json linux/evdev-source.py; do
  [[ -f "${MNT}/opt/mouse-bridge/${f}" ]]
  check $? "opt/mouse-bridge/${f}"
done
[[ -f "${MNT}/etc/systemd/system/mouse-bridge.service" ]]
check $? "systemd 单元在"
python3 - "${MNT}/opt/mouse-bridge/config.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
print("  ·  ha_url: %s" % c["ha_url"])
for dev, spec in c["mice"].items():
    print("  ·  %s → %s  %s" % (dev, spec.get("label"), spec["entity_id"]))
print("  %s config.json 已指向本机回环" % ("✅" if c["ha_url"] == "http://127.0.0.1:8123" else "❌"))
PY
if [[ -f "${MNT}/etc/ha-home/mouse-bridge.env" ]]; then
  ok "令牌已预置 $(stat -c '%U:%G %a' "${MNT}/etc/ha-home/mouse-bridge.env" 2>/dev/null)（内容不打印）"
else
  note "没预置令牌 —— 鼠标桥要手工放令牌后才能起"
fi

echo
echo "======================================================"
echo "  通过 ${PASS} 项，失败 ${FAIL} 项（上面 python 打的 ✅/❌ 不计入这个数）"
echo
echo "  ⚠️ 以下没有也无法在这里验证，只有真机上电才知道："
echo "     · 这块主板从 BIOS 还是 UEFI 引导、认不认这块盘"
echo "     · 网卡驱动/固件够不够（已装 realtek + 常见固件 + Intel 微码）"
echo "     · 首次开机 cloud-init 是否顺利跑完"
echo "======================================================"
[[ "${FAIL}" -eq 0 ]]
