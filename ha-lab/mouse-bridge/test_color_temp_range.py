"""色温区间夹取的用例 —— 不需要 HA，把网络那一层换成假的。

    python3 -m unittest discover -s ha-lab/mouse-bridge

存在的理由：HomeKit 接进来的小米吸顶灯把色温上限报成 20000K，而灯实际只到
6100K。不夹住的话滚轮会一路滚到两万，灯早就不变了，用起来像坏了。
"""

import unittest

from bridge import color_temp_limits
from ha_client import HAClient

ENTITY = "light.ceiling"


class FakeHA(HAClient):
    """把 _request 换掉：查状态返回预设属性，动作只记下来不发出去。"""

    def __init__(self, attrs):
        super().__init__("http://fake", "token")
        self._attrs = attrs
        self.calls = []

    def _request(self, method, path, payload=None):
        if method == "GET":
            return {"state": "on", "attributes": self._attrs}
        self.calls.append((path, payload))
        return None


HOMEKIT_ATTRS = {
    # 实体自报的上限不老实：HomeKit 那份报到 20000K
    "min_color_temp_kelvin": 2500,
    "max_color_temp_kelvin": 20000,
    "color_temp_kelvin": 6000,
}

REAL_RANGE = (2600, 6100)


class TestColorTempClamp(unittest.TestCase):

    def target_of(self, ha):
        self.assertEqual(len(ha.calls), 1, "应该正好发一次 turn_on")
        return ha.calls[0][1]["color_temp_kelvin"]

    def test_不给区间时按实体自报的来(self):
        ha = FakeHA(HOMEKIT_ATTRS)
        ha.step_color_temp(ENTITY, +1000)
        self.assertEqual(self.target_of(ha), 7000)  # 自报上限 20000，没拦住

    def test_给了区间就夹在真实上限(self):
        ha = FakeHA(HOMEKIT_ATTRS)
        ha.step_color_temp(ENTITY, +1000, limits=REAL_RANGE)
        self.assertEqual(self.target_of(ha), 6100)

    def test_夹到头之后不再白发请求(self):
        ha = FakeHA(dict(HOMEKIT_ATTRS, color_temp_kelvin=6100))
        ha.step_color_temp(ENTITY, +1000, limits=REAL_RANGE)
        self.assertEqual(ha.calls, [], "已经顶到头，不该再发请求")

    def test_下限取两者中更高的那个(self):
        # 实体报 2500，配置说 2600 —— 该听 2600
        ha = FakeHA(dict(HOMEKIT_ATTRS, color_temp_kelvin=2700))
        ha.step_color_temp(ENTITY, -1000, limits=REAL_RANGE)
        self.assertEqual(self.target_of(ha), 2600)

    def test_灯没上报色温时从区间中点起步(self):
        ha = FakeHA(dict(HOMEKIT_ATTRS, color_temp_kelvin=None))
        ha.step_color_temp(ENTITY, +200, limits=REAL_RANGE)
        self.assertEqual(self.target_of(ha), (2600 + 6100) // 2 + 200)


class TestLimitsFromConfig(unittest.TestCase):

    CFG = {"mice": {
        "2717:003b": {"entity_id": ENTITY, "color_temp_kelvin_range": [2600, 6100]},
        "2717:501f": {"entity_id": "light.dining"},
    }}

    def test_按实体查到配置里写的区间(self):
        self.assertEqual(color_temp_limits(self.CFG, ENTITY), (2600, 6100))

    def test_没写区间的灯返回None(self):
        self.assertIsNone(color_temp_limits(self.CFG, "light.dining"))

    def test_配置里没有的实体返回None(self):
        self.assertIsNone(color_temp_limits(self.CFG, "light.nobody"))


if __name__ == "__main__":
    unittest.main()
