"""控灯逻辑 —— 平台无关的那一层。

这里只做「鼠标事件 → 想干什么」的翻译，不碰网络、不碰操作系统、不看时钟。
好处是能用合成事件把全部行为验一遍（见 test_logic.py），
将来从 Mac 搬到 T630 时这个文件一行都不用改。

需求（人类原话整理）：
  - 左键 = 开/关（切换）；右键 = 开/关（切换）；左右键功能完全相同
  - 滚轮滚动 = 调节（亮度 或 色温）
  - 中键（滚轮按下）= 在「调亮度」和「调色温」之间切换
  - 若那盏灯不支持色温，则滚轮只调亮度，中键不做切换（无模式可切）
  - 两个鼠标各控一盏灯
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

MODE_BRIGHTNESS = "brightness"
MODE_COLOR_TEMP = "color_temp"

# 左右键功能完全相同，都是切换开关 —— 这是需求里明确要求的，不是偷懒。
TOGGLE_BUTTONS = ("left", "right")
MODE_BUTTON = "middle"


@dataclass
class Toggle:
    """把这盏灯开/关切换一下。"""
    entity_id: str


@dataclass
class Adjust:
    """按当前模式调节这盏灯。ticks 为正=调高，为负=调低。"""
    entity_id: str
    mode: str
    ticks: int


@dataclass
class ModeChanged:
    """模式切换了。给日志/提示用，执行层不必产生实际动作。"""
    entity_id: str
    mode: str


@dataclass
class Ignored:
    """事件被有意忽略。带上原因，方便排查"按了没反应"。"""
    reason: str


Intent = object  # 上面四种之一


@dataclass
class Binding:
    """一个鼠标 ↔ 一盏灯的绑定关系，外加这盏灯当前的调节模式。"""

    device_id: str
    entity_id: str
    label: str
    # 这盏灯支不支持色温。开机时从 HA 查一次，决定中键有没有用。
    supports_color_temp: bool = False
    mode: str = MODE_BRIGHTNESS

    def __post_init__(self):
        # 不支持色温的灯不可能停在色温模式，兜一下底。
        if not self.supports_color_temp:
            self.mode = MODE_BRIGHTNESS


class Controller:
    """把事件流翻译成意图。纯函数式的那种"纯"——没有副作用。"""

    def __init__(self, bindings: Dict[str, Binding]):
        # key 是设备标识（厂商编号:型号编号，如 "046d:c534"）。
        # 两个鼠标型号不同，所以这个 key 天然唯一、且插哪个 USB 口都不变。
        self.bindings = bindings

    def handle(self, event: dict) -> List[Intent]:
        device_id = event.get("device")
        binding = self.bindings.get(device_id)
        if binding is None:
            # 别的鼠标（比如你平时用的那只）不该误触发灯。
            return [Ignored("设备 %s 未绑定任何灯" % device_id)]

        etype = event.get("type")
        if etype == "button":
            return self._handle_button(binding, event)
        if etype == "wheel":
            return self._handle_wheel(binding, event)
        return [Ignored("未知事件类型 %r" % etype)]

    def _handle_button(self, binding: Binding, event: dict) -> List[Intent]:
        # 只在按下时动作。松开也响应的话，一次点击会触发两次。
        if event.get("action") != "down":
            return [Ignored("忽略抬起事件")]

        button = event.get("button")

        if button in TOGGLE_BUTTONS:
            return [Toggle(binding.entity_id)]

        if button == MODE_BUTTON:
            if not binding.supports_color_temp:
                # 需求明确：不支持色温的灯，中键不做切换（没有第二个模式可切）。
                return [Ignored("%s 不支持色温，中键无模式可切" % binding.label)]
            binding.mode = (
                MODE_COLOR_TEMP if binding.mode == MODE_BRIGHTNESS else MODE_BRIGHTNESS
            )
            return [ModeChanged(binding.entity_id, binding.mode)]

        return [Ignored("未绑定的按键 %r" % button)]

    def _handle_wheel(self, binding: Binding, event: dict) -> List[Intent]:
        ticks = int(event.get("delta", 0))
        if ticks == 0:
            return [Ignored("空滚动")]
        return [Adjust(binding.entity_id, binding.mode, ticks)]


class Coalescer:
    """把连续滚动合并成一次调用。

    滚轮转一下能出十几个事件，逐个调 HA 会又慢又抖。这里按 (灯, 模式) 累加，
    攒够一个时间窗再吐出来。时钟从外面传进来，所以测试里不用真的 sleep。
    """

    def __init__(self, window_ms: int = 80):
        self.window_ms = window_ms
        # key -> [累计 ticks, 首次累加时刻]
        self._pending: Dict[tuple, List[int]] = {}

    def add(self, adjust: Adjust, now_ms: int) -> None:
        key = (adjust.entity_id, adjust.mode)
        if key in self._pending:
            self._pending[key][0] += adjust.ticks
        else:
            self._pending[key] = [adjust.ticks, now_ms]

    def flush_due(self, now_ms: int) -> List[Adjust]:
        """吐出已经攒够时间窗的调节。"""
        out = []
        for key in list(self._pending):
            ticks, started = self._pending[key]
            if now_ms - started >= self.window_ms:
                del self._pending[key]
                if ticks:  # 一上一下正好抵消就不用发了
                    out.append(Adjust(key[0], key[1], ticks))
        return out

    def flush_entity(self, entity_id: str) -> List[Adjust]:
        """立刻吐出某盏灯所有待发的调节。

        切换模式时要用：不然刚才攒的亮度调节会被当成色温发出去。
        """
        out = []
        for key in list(self._pending):
            if key[0] == entity_id:
                ticks, _ = self._pending.pop(key)
                if ticks:
                    out.append(Adjust(key[0], key[1], ticks))
        return out

    def flush_all(self) -> List[Adjust]:
        out = []
        for key, (ticks, _) in self._pending.items():
            if ticks:
                out.append(Adjust(key[0], key[1], ticks))
        self._pending.clear()
        return out
