"""两个一模一样的接收器怎么分辨 —— 设备标识选择器的用例。

    python3 -m unittest discover -s ha-lab/mouse-bridge

背景：家里那两只小米鼠标的接收器在系统里长得**完全一样**：同样的 2717:003b、
同样的名字、USB 描述符里连序列号都没有。只靠「厂商:型号」分不出谁是谁，
只能靠插在哪个 USB 口上。于是设备标识多了一种写法：`2717:003b@1-1.5`。

这里不碰 /sys —— 把读硬件的那两个函数换成假的，纯测匹配规则。
"""

import importlib.util
import os
import unittest

# 文件名带连字符，不能直接 import，走 importlib。
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux", "evdev-source.py")
_spec = importlib.util.spec_from_file_location("evdev_source", _SRC)
evdev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evdev)


# 假的硬件：两个一模一样的接收器插在不同口，外加一只别的鼠标。
FAKE = {
    "/dev/input/event10": ("2717:003b", "1-1.5"),
    "/dev/input/event15": ("2717:003b", "1-1.6"),
    "/dev/input/event20": ("046d:c534", "1-1.2"),
    "/dev/input/event30": ("1234:5678", ""),      # 认不出插口（不是 USB）
}


class SelectorTestCase(unittest.TestCase):

    def setUp(self):
        self._real = (evdev.device_id, evdev.usb_port)
        evdev.device_id = lambda p: FAKE[p][0]
        evdev.usb_port = lambda p: FAKE[p][1]

    def tearDown(self):
        evdev.device_id, evdev.usb_port = self._real


class TestSelectorsFor(SelectorTestCase):

    def test_同时给出宽写法和带插口的窄写法(self):
        self.assertEqual(evdev.selectors_for("/dev/input/event10"),
                         ["2717:003b", "2717:003b@1-1.5"])

    def test_认不出插口时只有宽写法(self):
        self.assertEqual(evdev.selectors_for("/dev/input/event30"), ["1234:5678"])


class TestMatch(SelectorTestCase):

    def test_只写型号时两个同款接收器都被选中(self):
        # 只有一只的时候这样最省心，换 USB 口也照样认。
        wanted = {"2717:003b"}
        self.assertEqual(evdev.match("/dev/input/event10", wanted), "2717:003b")
        self.assertEqual(evdev.match("/dev/input/event15", wanted), "2717:003b")

    def test_带插口时两个同款接收器被分开(self):
        wanted = {"2717:003b@1-1.5", "2717:003b@1-1.6"}
        self.assertEqual(evdev.match("/dev/input/event10", wanted), "2717:003b@1-1.5")
        self.assertEqual(evdev.match("/dev/input/event15", wanted), "2717:003b@1-1.6")

    def test_只要其中一个口时另一个不被选中(self):
        wanted = {"2717:003b@1-1.5"}
        self.assertEqual(evdev.match("/dev/input/event10", wanted), "2717:003b@1-1.5")
        self.assertIsNone(evdev.match("/dev/input/event15", wanted))

    def test_窄写法优先于宽写法(self):
        # 两种都配了：1-1.5 上那只算窄的，别的口上的才算宽的。
        # 否则两只鼠标会同时匹配到同一个 key，一起去控同一盏灯。
        wanted = {"2717:003b", "2717:003b@1-1.5"}
        self.assertEqual(evdev.match("/dev/input/event10", wanted), "2717:003b@1-1.5")
        self.assertEqual(evdev.match("/dev/input/event15", wanted), "2717:003b")

    def test_没配的鼠标不被选中(self):
        # 平时用的那只鼠标不能把灯点了。
        self.assertIsNone(evdev.match("/dev/input/event20", {"2717:003b"}))

    def test_返回的写法跟配置里的一字不差(self):
        # 这个字段会原样进事件的 device 字段，下游拿它查 config.json 的 key，
        # 对不上就整只鼠标失灵 —— 所以必须返回配置里那个写法本身。
        for wanted in ({"2717:003b"}, {"2717:003b@1-1.5"}):
            got = evdev.match("/dev/input/event10", wanted)
            self.assertIn(got, wanted)


class TestUsbPortParsing(unittest.TestCase):
    """usb_port 从 sysfs 真实路径里挑出 USB 设备名那一段。"""

    def parse(self, realpath):
        # 只验挑段的规则，不碰文件系统。
        import re
        for part in reversed(realpath.split(os.sep)):
            if re.fullmatch(r"\d+-\d+(\.\d+)*", part):
                return part
        return ""

    def test_从真实路径里挑出插口(self):
        self.assertEqual(self.parse(
            "/sys/devices/pci0000:00/0000:00:1a.0/usb1/1-1/1-1.5/1-1.5:1.1/"
            "0003:2717:003B.0002/input/input10"), "1-1.5")

    def test_多级hub也认(self):
        self.assertEqual(self.parse("/sys/devices/pci0000:00/usb1/1-1/1-1.4/1-1.4.2/x"),
                         "1-1.4.2")

    def test_接口号那段不会被误认(self):
        # "1-1.5:1.1" 带冒号，不该被当成 USB 设备名。
        self.assertEqual(self.parse("/sys/devices/usb1/1-1/1-1.5/1-1.5:1.1"), "1-1.5")

    def test_不是USB设备时返回空(self):
        self.assertEqual(self.parse("/sys/devices/platform/i8042/serio1/input/input3"), "")


if __name__ == "__main__":
    unittest.main()
