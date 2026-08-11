"""用合成事件把控灯逻辑验一遍 —— 不需要真鼠标、不需要 HA、不需要灯。

    python3 -m unittest discover -s ha-lab/mouse-bridge

需求里每一条都对应下面至少一个用例，改逻辑前先看这里。
"""

import unittest

from logic import (
    MODE_BRIGHTNESS,
    MODE_COLOR_TEMP,
    Adjust,
    Binding,
    Coalescer,
    Controller,
    Ignored,
    ModeChanged,
    Toggle,
)

MOUSE_A = "046d:c534"   # 控「书桌灯」，支持色温
MOUSE_B = "1ea7:0064"   # 控「床头灯」，不支持色温
LIGHT_A = "light.desk"
LIGHT_B = "light.bed"


def make_controller():
    return Controller({
        MOUSE_A: Binding(MOUSE_A, LIGHT_A, "书桌灯", supports_color_temp=True),
        MOUSE_B: Binding(MOUSE_B, LIGHT_B, "床头灯", supports_color_temp=False),
    })


def press(device, button):
    return {"device": device, "type": "button", "button": button, "action": "down"}


def release(device, button):
    return {"device": device, "type": "button", "button": button, "action": "up"}


def wheel(device, delta):
    return {"device": device, "type": "wheel", "delta": delta}


class TestToggle(unittest.TestCase):
    def test_左键切换开关(self):
        c = make_controller()
        self.assertEqual(c.handle(press(MOUSE_A, "left")), [Toggle(LIGHT_A)])

    def test_右键和左键功能完全相同(self):
        c = make_controller()
        left = c.handle(press(MOUSE_A, "left"))
        right = c.handle(press(MOUSE_A, "right"))
        self.assertEqual(left, right)

    def test_只在按下时动作_抬起不重复触发(self):
        c = make_controller()
        self.assertEqual(c.handle(press(MOUSE_A, "left")), [Toggle(LIGHT_A)])
        self.assertIsInstance(c.handle(release(MOUSE_A, "left"))[0], Ignored)

    def test_两个鼠标各控各的灯(self):
        c = make_controller()
        self.assertEqual(c.handle(press(MOUSE_A, "left")), [Toggle(LIGHT_A)])
        self.assertEqual(c.handle(press(MOUSE_B, "left")), [Toggle(LIGHT_B)])

    def test_未绑定的鼠标不误触发(self):
        """平时用的那只鼠标不能把灯点了。"""
        c = make_controller()
        out = c.handle(press("dead:beef", "left"))
        self.assertIsInstance(out[0], Ignored)


class TestWheel(unittest.TestCase):
    def test_默认调亮度(self):
        c = make_controller()
        self.assertEqual(c.handle(wheel(MOUSE_A, 1)),
                         [Adjust(LIGHT_A, MODE_BRIGHTNESS, 1)])

    def test_反向滚动是负数(self):
        c = make_controller()
        self.assertEqual(c.handle(wheel(MOUSE_A, -1)),
                         [Adjust(LIGHT_A, MODE_BRIGHTNESS, -1)])

    def test_空滚动被忽略(self):
        c = make_controller()
        self.assertIsInstance(c.handle(wheel(MOUSE_A, 0))[0], Ignored)


class TestModeSwitch(unittest.TestCase):
    def test_中键在亮度和色温之间来回切(self):
        c = make_controller()
        self.assertEqual(c.handle(press(MOUSE_A, "middle")),
                         [ModeChanged(LIGHT_A, MODE_COLOR_TEMP)])
        self.assertEqual(c.handle(press(MOUSE_A, "middle")),
                         [ModeChanged(LIGHT_A, MODE_BRIGHTNESS)])

    def test_切到色温后滚轮调的是色温(self):
        c = make_controller()
        c.handle(press(MOUSE_A, "middle"))
        self.assertEqual(c.handle(wheel(MOUSE_A, 2)),
                         [Adjust(LIGHT_A, MODE_COLOR_TEMP, 2)])

    def test_不支持色温的灯_中键不做切换(self):
        """需求原话：若那盏灯不支持色温，中键不做切换（无模式可切）。"""
        c = make_controller()
        out = c.handle(press(MOUSE_B, "middle"))
        self.assertIsInstance(out[0], Ignored)

    def test_不支持色温的灯_滚轮始终只调亮度(self):
        c = make_controller()
        c.handle(press(MOUSE_B, "middle"))   # 按了也没用
        self.assertEqual(c.handle(wheel(MOUSE_B, 1)),
                         [Adjust(LIGHT_B, MODE_BRIGHTNESS, 1)])

    def test_不支持色温的灯_即使配置成色温模式也会被纠正(self):
        b = Binding(MOUSE_B, LIGHT_B, "床头灯",
                    supports_color_temp=False, mode=MODE_COLOR_TEMP)
        self.assertEqual(b.mode, MODE_BRIGHTNESS)

    def test_一个鼠标切模式不影响另一个(self):
        c = make_controller()
        c.handle(press(MOUSE_A, "middle"))
        self.assertEqual(c.handle(wheel(MOUSE_A, 1)),
                         [Adjust(LIGHT_A, MODE_COLOR_TEMP, 1)])
        self.assertEqual(c.handle(wheel(MOUSE_B, 1)),
                         [Adjust(LIGHT_B, MODE_BRIGHTNESS, 1)])


class TestCoalescer(unittest.TestCase):
    def test_时间窗内的连续滚动合并成一次(self):
        co = Coalescer(window_ms=80)
        for _ in range(10):
            co.add(Adjust(LIGHT_A, MODE_BRIGHTNESS, 1), now_ms=1000)
        self.assertEqual(co.flush_due(now_ms=1000), [])       # 还没到窗口
        self.assertEqual(co.flush_due(now_ms=1080),
                         [Adjust(LIGHT_A, MODE_BRIGHTNESS, 10)])

    def test_一上一下抵消后不发请求(self):
        co = Coalescer(window_ms=80)
        co.add(Adjust(LIGHT_A, MODE_BRIGHTNESS, 3), now_ms=0)
        co.add(Adjust(LIGHT_A, MODE_BRIGHTNESS, -3), now_ms=10)
        self.assertEqual(co.flush_due(now_ms=100), [])

    def test_不同灯不同模式各攒各的(self):
        co = Coalescer(window_ms=80)
        co.add(Adjust(LIGHT_A, MODE_BRIGHTNESS, 1), now_ms=0)
        co.add(Adjust(LIGHT_B, MODE_BRIGHTNESS, 2), now_ms=0)
        co.add(Adjust(LIGHT_A, MODE_COLOR_TEMP, 3), now_ms=0)
        out = sorted(co.flush_due(now_ms=100), key=lambda a: (a.entity_id, a.mode))
        self.assertEqual(out, [
            Adjust(LIGHT_B, MODE_BRIGHTNESS, 2),   # light.bed 字典序在前
            Adjust(LIGHT_A, MODE_BRIGHTNESS, 1),
            Adjust(LIGHT_A, MODE_COLOR_TEMP, 3),
        ])

    def test_切模式时先把攒着的旧模式调节发出去(self):
        """否则刚滚的亮度会被当成色温发出去 —— 这是个真实会踩的坑。"""
        co = Coalescer(window_ms=80)
        co.add(Adjust(LIGHT_A, MODE_BRIGHTNESS, 5), now_ms=0)
        self.assertEqual(co.flush_entity(LIGHT_A),
                         [Adjust(LIGHT_A, MODE_BRIGHTNESS, 5)])
        self.assertEqual(co.flush_due(now_ms=1000), [])


if __name__ == "__main__":
    unittest.main()
