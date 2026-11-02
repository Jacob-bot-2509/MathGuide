"""图解告警出口:可选 webhook,只发聚合指标,不发问题/回答/用户身份。

配置:
- MG_DIAGRAM_ALERT_WEBHOOK:接收 POST JSON 的地址;为空则关闭。
- MG_DIAGRAM_ALERT_COOLDOWN:同类告警最小间隔秒数,默认 300。
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import diagram_metrics

_lock = threading.Lock()
_last_sent = 0.0


def _cooldown() -> float:
    try:
        return max(30.0, float(os.getenv("MG_DIAGRAM_ALERT_COOLDOWN", "300")))
    except ValueError:
        return 300.0


def build_payload(reason: str) -> dict:
    """只放事件名与聚合快照;调用方不得加入正文。"""
    return {
        "service": "mathguide",
        "event": "diagram_alert",
        "reason": reason[:80] or "unknown",
        "snapshot": diagram_metrics.snapshot(),
        "ts": int(time.time()),
    }


def reset_for_tests() -> None:
    global _last_sent
    with _lock:
        _last_sent = 0.0


async def notify(reason: str) -> bool:
    url = os.getenv("MG_DIAGRAM_ALERT_WEBHOOK", "").strip()
    if not url:
        return False
    now = time.monotonic()
    with _lock:
        global _last_sent
        if now - _last_sent < _cooldown():
            return False
        _last_sent = now
    ok = False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(url, json=build_payload(reason))
            ok = 200 <= response.status_code < 300
    except Exception:  # noqa: BLE001 告警失败不能影响业务
        ok = False
    # 只记结果,不打印 webhook 地址或载荷。
    print(f"[diagram] alert reason={reason[:80]} ok={int(ok)}")
    return ok


def schedule(reason: str) -> None:
    """在事件循环内发后即忘;没有配置或没有循环时静默跳过。"""
    if not os.getenv("MG_DIAGRAM_ALERT_WEBHOOK", "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(notify(reason))
