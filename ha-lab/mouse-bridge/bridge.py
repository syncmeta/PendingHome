#!/usr/bin/env python3
"""鼠标 → Home Assistant 的桥。

从标准输入按行读 JSON 事件，翻译成控灯动作发给 HA。
事件从哪来它不关心 —— Mac 上是 macos/mouse-source（Swift），
将来 T630 上是 linux/evdev-source.py，也可以是手敲的假事件（用来验逻辑）。

    # 真实使用（Mac）
    export HA_TOKEN=...
    ./macos/mouse-source | ./bridge.py --config config.json

    # 不碰真鼠标，手喂事件验一遍
    echo '{"device":"046d:c534","type":"button","button":"left","action":"down"}' \
      | ./bridge.py --config config.json

    # 只检查配置和 HA 连通性，不做任何动作
    ./bridge.py --config config.json --check

事件格式（每行一个 JSON）：
    {"device":"046d:c534","type":"button","button":"left","action":"down"}
    {"device":"046d:c534","type":"wheel","delta":-1}
"""

import argparse
import json
import os
import select
import sys
import time
from typing import Dict

from ha_client import HAClient, HAError
from logic import (
    MODE_BRIGHTNESS,
    Adjust,
    Binding,
    Coalescer,
    Controller,
    Ignored,
    ModeChanged,
    Toggle,
)


def log(msg: str):
    # 走 stderr，免得跟事件流搅在一起（万一有人把 bridge 的输出再接给别的程序）。
    print(msg, file=sys.stderr, flush=True)


def now_ms() -> int:
    return int(time.monotonic() * 1000)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_bindings(cfg: dict, ha: HAClient) -> Dict[str, Binding]:
    """建立鼠标↔灯的绑定，并在启动时查一次每盏灯支不支持色温。

    支持色温与否决定中键有没有用。开机查一次而不是每次按键都查，
    是因为这是设备能力，不会变。
    """
    bindings = {}
    for device_id, spec in cfg["mice"].items():
        entity_id = spec["entity_id"]
        label = spec.get("label", entity_id)
        try:
            supports_ct = ha.supports_color_temp(entity_id)
        except HAError as e:
            raise HAError("查 %s 的能力失败：%s" % (entity_id, e)) from e
        bindings[device_id] = Binding(
            device_id=device_id,
            entity_id=entity_id,
            label=label,
            supports_color_temp=supports_ct,
        )
        log("  %s → %s  %s" % (
            device_id, ha.describe(entity_id),
            "可调色温（中键切模式）" if supports_ct else "不支持色温（中键无效，滚轮只调亮度）"))
    return bindings


def execute(intent, ha: HAClient, cfg: dict):
    """把一个意图变成实际的 HA 调用。"""
    wheel_cfg = cfg.get("wheel", {})
    if isinstance(intent, Toggle):
        ha.toggle(intent.entity_id)
        log("  开关切换 %s" % intent.entity_id)
    elif isinstance(intent, Adjust):
        if intent.mode == MODE_BRIGHTNESS:
            pct = intent.ticks * int(wheel_cfg.get("brightness_step_pct", 5))
            ha.step_brightness(intent.entity_id, pct)
            log("  亮度 %+d%% %s" % (pct, intent.entity_id))
        else:
            delta = intent.ticks * int(wheel_cfg.get("color_temp_step_kelvin", 200))
            ha.step_color_temp(intent.entity_id, delta)
            log("  色温 %+dK %s" % (delta, intent.entity_id))


def run(cfg: dict, ha: HAClient, bindings: Dict[str, Binding]):
    controller = Controller(bindings)
    coalescer = Coalescer(window_ms=int(cfg.get("wheel", {}).get("coalesce_ms", 80)))

    log("开始监听事件（Ctrl-C 退出）")
    while True:
        # 有事件就处理事件；没事件也要定期醒来，把攒着的滚动发出去。
        ready, _, _ = select.select([sys.stdin], [], [], 0.02)
        if ready:
            line = sys.stdin.readline()
            if not line:
                break  # 上游关了
            line = line.strip()
            if line:
                handle_line(line, controller, coalescer, ha, cfg)

        for adjust in coalescer.flush_due(now_ms()):
            safe_execute(adjust, ha, cfg)

    for adjust in coalescer.flush_all():
        safe_execute(adjust, ha, cfg)
    log("事件流结束，退出")


def handle_line(line, controller, coalescer, ha, cfg):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        log("  跳过无法解析的一行：%.80s" % line)
        return

    for intent in controller.handle(event):
        if isinstance(intent, Ignored):
            continue
        if isinstance(intent, Adjust):
            # 连续滚动先攒起来，别一个 tick 一个请求
            coalescer.add(intent, now_ms())
        elif isinstance(intent, ModeChanged):
            # 切模式前先把旧模式攒着的调节发掉，
            # 否则刚滚的亮度会被当成色温发出去。
            for pending in coalescer.flush_entity(intent.entity_id):
                safe_execute(pending, ha, cfg)
            log("  模式 → %s  %s" % (
                "色温" if intent.mode != MODE_BRIGHTNESS else "亮度", intent.entity_id))
        else:
            safe_execute(intent, ha, cfg)


def safe_execute(intent, ha, cfg):
    """一次调用失败不该让整个桥挂掉 —— 灯离线、HA 重启都是常事。"""
    try:
        execute(intent, ha, cfg)
    except HAError as e:
        log("  ⚠️  执行失败：%s" % e)


def main():
    p = argparse.ArgumentParser(description="鼠标 → Home Assistant 的桥")
    p.add_argument("--config", required=True, help="配置文件路径")
    p.add_argument("--check", action="store_true",
                   help="只检查配置与 HA 连通性，不监听事件")
    args = p.parse_args()

    cfg = load_config(args.config)

    token = os.environ.get(cfg.get("token_env", "HA_TOKEN"))
    if not token:
        log("❌ 环境变量 %s 没设 —— 需要 HA 的长期访问令牌。" % cfg.get("token_env", "HA_TOKEN"))
        log("   在 HA 里：头像 → 安全 → 长期访问令牌 → 创建令牌")
        return 2

    ha = HAClient(cfg["ha_url"], token)

    try:
        log("连接 %s ... %s" % (cfg["ha_url"], ha.ping()))
        log("绑定关系：")
        bindings = build_bindings(cfg, ha)
    except HAError as e:
        log("❌ %s" % e)
        return 1

    if args.check:
        log("✅ 配置和连通性都没问题")
        return 0

    try:
        run(cfg, ha, bindings)
    except KeyboardInterrupt:
        log("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
