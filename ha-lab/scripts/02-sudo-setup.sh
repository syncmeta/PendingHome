#!/bin/bash
# 一次性的 sudo 配置 —— 让 Lima 能用 socket_vmnet 做桥接网络。
#
# 请人类自己执行，agent 不代跑：
#     ! sudo bash ~/Untitled/PendingHome/ha-lab/scripts/00-sudo-setup.sh
#
# 干三件事：
#   1. 把 Homebrew 装的 socket_vmnet 复制一份到 /opt/socket_vmnet（root 所有）。
#      Lima 拒绝执行普通用户可写的 setuid 路径，所以不能直接用 brew 那份。
#   2. 建 /private/var/run/lima 给 socket_vmnet 放 pid 文件。
#   3. 生成并安装 /etc/sudoers.d/lima，让 limactl 之后能免密拉起 socket_vmnet。
# 只碰这三个路径，不动系统其他配置。可重复执行。
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 sudo 跑这个脚本：sudo bash $0" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-}"
if [[ -z "${REAL_USER}" || "${REAL_USER}" == "root" ]]; then
  echo "拿不到发起 sudo 的普通用户名（SUDO_USER），请用 sudo 而不是 root shell 执行。" >&2
  exit 1
fi

LIMACTL="/opt/homebrew/bin/limactl"
BREW_SOCKET_VMNET="/opt/homebrew/opt/socket_vmnet/bin/socket_vmnet"
DEST_DIR="/opt/socket_vmnet/bin"

echo "==> 1/3 安装 socket_vmnet 到 /opt/socket_vmnet"
if [[ ! -x "${BREW_SOCKET_VMNET}" ]]; then
  echo "找不到 ${BREW_SOCKET_VMNET}，先 brew install socket_vmnet" >&2
  exit 1
fi
install -d -o root -g wheel -m 0755 /opt/socket_vmnet
install -d -o root -g wheel -m 0755 "${DEST_DIR}"
install -o root -g wheel -m 0755 "${BREW_SOCKET_VMNET}" "${DEST_DIR}/socket_vmnet"
ls -l "${DEST_DIR}/socket_vmnet"

echo "==> 2/3 建 /private/var/run/lima"
# 属主/权限有讲究，两边都卡：
#   - 属主必须是 root、且普通用户不可写 —— 这里放的是 socket_vmnet 的 pid 文件，
#     而 lima 会 sudo pkill -F 这个 pid 文件。用户能改它就等于能杀任意特权进程。
#   - 但必须对 daemon 组(gid 1)可写 —— socket_vmnet 降权到 daemon 后要写 pid 文件。
# 所以是 root:daemon 0775。install -d 对已存在的目录也会纠正属主和权限。
install -d -o root -g daemon -m 0775 /private/var/run/lima
ls -ld /private/var/run/lima

echo "==> 3/3 生成并安装 /etc/sudoers.d/lima"
# limactl 要读用户自己的 ~/.lima/_config/networks.yaml，所以降权到原用户来生成。
SUDOERS_TMP="$(mktemp)"
trap 'rm -f "${SUDOERS_TMP}"' EXIT
sudo -u "${REAL_USER}" "${LIMACTL}" sudoers >"${SUDOERS_TMP}"

echo "----- 即将安装的 sudoers 内容 -----"
cat "${SUDOERS_TMP}"
echo "----------------------------------"

# 语法先过一遍，写坏 sudoers 会让整台机器没法 sudo。
visudo -c -f "${SUDOERS_TMP}"
# 权限必须是 0644 而不是 sudoers 传统的 0440：limactl 每次启动都要**以普通用户身份
# 读回**这个文件，核对内容和当前 networks.yaml 一致，读不到就直接 fatal。
# sudo 只要求 sudoers 文件不可被 group/other 写入，0644 是合规的
# （Lima 官方文档给的 `install -o root` 甚至是 0755）。
install -o root -g wheel -m 0644 "${SUDOERS_TMP}" /etc/sudoers.d/lima

echo
echo "✅ 完成。回去让 agent 跑 scripts/01-up.sh 建虚拟机。"
