#!/usr/bin/env python3
"""读 Linux 上的鼠标事件，按行吐 JSON 到标准输出。喂给 ../bridge.py。

这是 T630 上最终要用的那个适配器 —— 跟 macos/mouse-source.swift 输出**完全一样**
的事件格式，所以控灯逻辑（logic.py）搬过来一行都不用改。

    ./evdev-source.py --list                     列出所有鼠标及其设备标识
    ./evdev-source.py --device 046d:c534 ...     只上报这些鼠标
    ./evdev-source.py --device 2717:003b@1-1.5   两个接收器型号一样时，连插口一起指定
    ./evdev-source.py --device ... --grab        独占鼠标（不再移动光标）

不依赖任何第三方库 —— 直接读 /dev/input/event* 的原始结构。T630 上装个系统就能跑，
不用 pip install 任何东西。

权限：读 /dev/input/event* 需要 root，或者把用户加进 input 组：
    sudo usermod -aG input $USER     （重新登录生效）
"""

import argparse
import fcntl
import glob
import json
import os
import re
import select
import struct
import sys

# linux/input.h 里的常量
EV_KEY = 0x01
EV_REL = 0x02
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
REL_WHEEL = 0x08

BUTTON_NAMES = {BTN_LEFT: "left", BTN_RIGHT: "right", BTN_MIDDLE: "middle"}

# struct input_event {struct timeval time; __u16 type; __u16 code; __s32 value;}
# 64 位系统上 timeval 是两个 long = 16 字节，总共 24 字节。
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

# EVIOCGRAB = _IOW('E', 0x90, int) —— 独占这个设备，事件不再流给桌面。
EVIOCGRAB = 0x40044590


def device_id(event_path: str) -> str:
    """读出 "厂商编号:型号编号"，格式跟 macOS 那版完全一致，配置可以通用。"""
    name = os.path.basename(event_path)
    base = "/sys/class/input/%s/device/id" % name
    try:
        with open(os.path.join(base, "vendor")) as f:
            vendor = f.read().strip()
        with open(os.path.join(base, "product")) as f:
            product = f.read().strip()
    except OSError:
        return "0000:0000"
    return "%s:%s" % (vendor.lower(), product.lower())


def device_name(event_path: str) -> str:
    name = os.path.basename(event_path)
    try:
        with open("/sys/class/input/%s/device/name" % name) as f:
            return f.read().strip()
    except OSError:
        return "(无名)"


def usb_port(event_path: str) -> str:
    """这个设备插在哪个 USB 口上，形如 "1-1.5"（跟 /sys/bus/usb/devices 下的名字一致）。

    为什么需要它：两只小米鼠标的接收器**在系统里长得一模一样** —— 同样的
    2717:003b、同样的名字、而且都没有序列号（USB 描述符里一个可区分的字段都没有）。
    只靠"厂商:型号"分不出谁是谁，插口是唯一能区分的东西。

    代价说清楚：这个标识跟的是**插口**不是鼠标。把接收器换个 USB 口插，
    绑定就跟着换了。所以插好之后别乱动，或者在机箱上贴个标。

    认不出来（比如不是 USB 设备）时返回空串。
    """
    name = os.path.basename(event_path)
    real = os.path.realpath("/sys/class/input/%s/device" % name)
    # 路径形如 .../usb1/1-1/1-1.5/1-1.5:1.1/0003:2717:003B.0002/input/input15
    # 从右往左找第一个「数字-数字[.数字...]」的段，那就是 USB 设备本身。
    for part in reversed(real.split(os.sep)):
        if re.fullmatch(r"\d+-\d+(\.\d+)*", part):
            return part
    return ""


def selectors_for(event_path: str):
    """这个节点能被哪些写法选中，从宽到窄。

    "2717:003b"          —— 只认型号，插哪个口都算（只有一只时最省心）
    "2717:003b@1-1.5"    —— 连插口一起认（有两只一样的接收器时必须用这个）
    """
    dev = device_id(event_path)
    port = usb_port(event_path)
    return [dev] + (["%s@%s" % (dev, port)] if port else [])


def is_mouse(event_path: str) -> bool:
    """有鼠标左键 + 滚轮的才算鼠标，避开键盘和一堆虚拟设备。

    看 /sys 里的能力位图：EV_KEY 里有 BTN_LEFT，EV_REL 里有 REL_WHEEL。
    """
    name = os.path.basename(event_path)
    caps = "/sys/class/input/%s/device/capabilities" % name

    def has_bit(fname, bit):
        try:
            with open(os.path.join(caps, fname)) as f:
                # 内容是空格分隔的十六进制块，低位在最右边
                words = f.read().strip().split()
            value = int("".join(w.zfill(16) for w in words), 16)
            return bool(value >> bit & 1)
        except (OSError, ValueError):
            return False

    return has_bit("key", BTN_LEFT) and has_bit("rel", REL_WHEEL)


def list_mice():
    found = [p for p in sorted(glob.glob("/dev/input/event*")) if is_mouse(p)]
    if not found:
        print("没找到鼠标。（读 /dev/input 需要 root 或 input 组权限）")
        return

    # 型号相同的有几个 —— 决定了要不要连插口一起写。
    seen = {}
    for p in found:
        seen[device_id(p)] = seen.get(device_id(p), 0) + 1

    print("设备标识              设备节点            名称")
    for p in found:
        dev = device_id(p)
        # 只有一个的写宽的（换口也认），有重名的必须写窄的（否则分不出谁是谁）。
        pick = selectors_for(p)[-1] if seen[dev] > 1 else dev
        print("%-21s %-18s %s" % (pick, p, device_name(p)))

    dupes = [d for d, n in seen.items() if n > 1]
    if dupes:
        print("\n⚠️  %s 有不止一个 —— 它们的 USB 描述符完全相同（连序列号都没有），"
              % "、".join(dupes))
        print("    只能靠插口区分。上面已经给出带 @插口 的写法，照抄进 config.json。")
        print("    注意：换一个 USB 口插，标识就变了。插好别乱动。")
    print("\n把要用的那两个标识填进 config.json 的 mice 里。")


def emit(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()   # 下游是管道，不刷会攒着不发，按键像失灵


def match(event_path: str, wanted):
    """这个节点被 wanted 里的哪个写法选中了？没选中返回 None。

    返回的是**配置里的那个写法**，因为它要原样出现在事件的 device 字段里 ——
    下游 logic.py 拿它去查绑定，必须跟 config.json 的 key 一模一样。

    窄的优先：同时写了 "2717:003b" 和 "2717:003b@1-1.5" 时，插在 1-1.5 上的那只
    算后者，别的口上的才算前者。
    """
    for sel in reversed(selectors_for(event_path)):
        if sel in wanted:
            return sel
    return None


def run(wanted, grab):
    paths = [p for p in sorted(glob.glob("/dev/input/event*")) if is_mouse(p)]
    matched = {p: (match(p, wanted) if wanted else device_id(p)) for p in paths}
    paths = [p for p in paths if matched[p] is not None]
    if not paths:
        print("没有匹配的鼠标，先用 --list 看看有哪些。", file=sys.stderr)
        return 1

    files = {}
    for p in paths:
        try:
            f = open(p, "rb", buffering=0)
        except PermissionError:
            print("打不开 %s —— 需要 root 或加入 input 组" % p, file=sys.stderr)
            return 1
        if grab:
            try:
                fcntl.ioctl(f, EVIOCGRAB, 1)
            except OSError as e:
                print("独占 %s 失败：%s" % (p, e), file=sys.stderr)
        files[f.fileno()] = (f, matched[p])
        print("在读 %s (%s) %s" % (p, matched[p], device_name(p)), file=sys.stderr)

    print("Ctrl-C 退出", file=sys.stderr)
    try:
        while True:
            ready, _, _ = select.select(list(files), [], [])
            for fd in ready:
                f, dev = files[fd]
                data = f.read(EVENT_SIZE)
                if not data:
                    # 读到 EOF —— 设备节点没了（接收器被拔掉之类）。
                    # 这里必须退出：EOF 之后 select 会永远报「可读」，
                    # continue 下去就是死循环空转（实测占满一个核，79% CPU）。
                    # 退出后由 systemd 的 Restart=always 重新拉起并重新枚举设备。
                    print("设备 %s 断开，退出（等待重启后重新枚举）" % dev,
                          file=sys.stderr)
                    return 1
                if len(data) < EVENT_SIZE:
                    continue  # 半个事件，等下次读齐
                _, _, etype, code, value = struct.unpack(EVENT_FORMAT, data)

                if etype == EV_KEY and code in BUTTON_NAMES:
                    # value: 1=按下 0=抬起 2=长按重复（重复的丢掉，不然按住会连发）
                    if value in (0, 1):
                        emit({"device": dev, "type": "button",
                              "button": BUTTON_NAMES[code],
                              "action": "down" if value == 1 else "up"})
                elif etype == EV_REL and code == REL_WHEEL and value != 0:
                    emit({"device": dev, "type": "wheel", "delta": value})
    except KeyboardInterrupt:
        pass
    finally:
        for f, _ in files.values():
            if grab:
                try:
                    fcntl.ioctl(f, EVIOCGRAB, 0)
                except OSError:
                    pass
            f.close()
    return 0


def main():
    p = argparse.ArgumentParser(description="读 Linux 鼠标事件，吐 JSON")
    p.add_argument("--list", action="store_true", help="列出所有鼠标")
    p.add_argument("--device", action="append", default=[],
                   help="只上报这个设备标识（可重复）。"
                        "两种写法：厂商:型号，或 厂商:型号@USB插口")
    p.add_argument("--grab", action="store_true",
                   help="独占鼠标：不再移动光标，变成纯遥控器")
    args = p.parse_args()

    if args.list:
        list_mice()
        return 0
    return run(set(d.lower() for d in args.device), args.grab)


if __name__ == "__main__":
    sys.exit(main())
