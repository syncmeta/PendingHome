"""跟 Home Assistant 说话的那一层。只用标准库，不装任何依赖。

认证用「长期访问令牌」（Long-Lived Access Token），在 HA 里
  头像 → 安全 → 长期访问令牌 → 创建令牌
生成。令牌从环境变量读，不写进配置文件、不进版本库。
"""

import json
import urllib.error
import urllib.request
from typing import Optional

MODE_BRIGHTNESS = "brightness"
MODE_COLOR_TEMP = "color_temp"


class HAError(RuntimeError):
    pass


class HAClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---------- 底层 ----------

    def _request(self, method: str, path: str, payload: Optional[dict] = None):
        url = "%s%s" % (self.base_url, path)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer %s" % self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise HAError("令牌无效或已过期（HTTP 401）") from e
            raise HAError("HA 返回 HTTP %s: %s" % (e.code, e.read().decode()[:200])) from e
        except urllib.error.URLError as e:
            raise HAError("连不上 HA（%s）：%s" % (self.base_url, e.reason)) from e

    # ---------- 查询 ----------

    def ping(self) -> str:
        """确认地址和令牌都对。返回 HA 的欢迎信息。"""
        resp = self._request("GET", "/api/")
        return (resp or {}).get("message", "")

    def get_state(self, entity_id: str) -> dict:
        return self._request("GET", "/api/states/%s" % entity_id)

    def supports_color_temp(self, entity_id: str) -> bool:
        """这盏灯能不能调色温 —— 决定中键有没有用。

        看 supported_color_modes 里有没有 color_temp。灯是关着的时候这个属性
        依然在（HA 把能力和当前状态分开存），所以开机时查一次就够。
        """
        state = self.get_state(entity_id)
        modes = (state.get("attributes") or {}).get("supported_color_modes") or []
        return MODE_COLOR_TEMP in modes

    def describe(self, entity_id: str) -> str:
        state = self.get_state(entity_id)
        attrs = state.get("attributes") or {}
        return "%s（%s，当前 %s）" % (
            attrs.get("friendly_name", entity_id), entity_id, state.get("state"))

    # ---------- 动作 ----------

    def _call(self, service: str, payload: dict):
        return self._request("POST", "/api/services/light/%s" % service, payload)

    def toggle(self, entity_id: str):
        self._call("toggle", {"entity_id": entity_id})

    def step_brightness(self, entity_id: str, pct: int):
        """相对调节亮度。HA 自己会夹在 0~100，灯是关的会顺带点亮。"""
        self._call("turn_on", {"entity_id": entity_id, "brightness_step_pct": pct})

    def step_color_temp(self, entity_id: str, delta_kelvin: int):
        """相对调节色温。

        HA 没有色温的相对调节服务，只能先读当前值再写绝对值。
        灯关着或还没上报色温时，从可用区间的中点起步，避免跳到极端值。
        """
        state = self.get_state(entity_id)
        attrs = state.get("attributes") or {}
        lo = attrs.get("min_color_temp_kelvin")
        hi = attrs.get("max_color_temp_kelvin")
        if lo is None or hi is None:
            raise HAError("%s 没有色温区间，可能并不支持色温" % entity_id)

        current = attrs.get("color_temp_kelvin")
        if current is None:
            current = (lo + hi) // 2

        target = max(lo, min(hi, current + delta_kelvin))
        if target == current:
            return  # 已经顶到头了，不用白跑一趟
        self._call("turn_on", {"entity_id": entity_id, "color_temp_kelvin": target})
