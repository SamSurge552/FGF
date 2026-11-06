"""战斗/集结耗时校准。正确结束时写入样本，用来改等待和超时。"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import config

PATH = os.path.join(config.ROOT, "calibrate.json")
KEEP = 10
_RECENT = 3
_TIMEOUT_ADD = 30.0


def _empty() -> dict[str, Any]:
    return {"goal0": [], "goal1": []}


def load() -> dict[str, Any]:
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("goal0", [])
        data.setdefault("goal1", [])
        return data
    except (OSError, json.JSONDecodeError):
        return _empty()


def save(data: dict[str, Any]) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


def reset() -> None:
    save(_empty())


def _durations(samples: list) -> tuple[list[float], list[float]]:
    durs = [float(s["duration_s"]) for s in samples if s.get("duration_s")]
    apps = [float(s["appear_s"]) for s in samples if s.get("appear_s") is not None]
    return durs, apps


def _average(durs: list[float]) -> float:
    """不满 3 次用默认。满了用最近 3 次的中位。"""
    if len(durs) < _RECENT:
        return float(config.DEFAULT_AVG_WAIT)
    recent = sorted(durs[-_RECENT:])
    return recent[len(recent) // 2]


def timeouts_goal0() -> dict[str, float]:
    durs, apps = _durations(load()["goal0"])
    appear_wait = float(config.ATK_APPEAR_WAIT)
    min_fight = float(config.ATK_MIN_FIGHT)
    gone_wait = float(config.ATK_GONE_WAIT)
    gone_confirm = float(config.ATK_GONE_CONFIRM)
    if apps:
        recent_apps = apps[-_RECENT:]
        appear_wait = min(40.0, max(8.0, max(recent_apps) * 2.2 + 1.0))
    if len(durs) >= _RECENT:
        recent = durs[-_RECENT:]
        med = sorted(recent)[len(recent) // 2]
        gone_confirm = min(2.5, max(1.0, med * 0.05))
    if durs:
        gone_wait = min(420.0, max(durs) + _TIMEOUT_ADD)
    return {
        "appear_wait": appear_wait,
        "min_fight": min_fight,
        "gone_wait": gone_wait,
        "gone_confirm": gone_confirm,
        "samples": float(len(durs)),
        "median": _average(durs),
    }


def timeouts_goal1() -> dict[str, float]:
    durs, apps = _durations(load()["goal1"])
    appear_wait = 25.0
    gone_wait = float(config.RALLY_WAIT)
    gone_confirm = 2.0
    min_rally = float(config.DEFAULT_AVG_WAIT)
    if apps:
        recent_apps = apps[-_RECENT:]
        appear_wait = min(45.0, max(10.0, max(recent_apps) * 2.2 + 1.0))
    if len(durs) >= _RECENT:
        recent = durs[-_RECENT:]
        med = sorted(recent)[len(recent) // 2]
        gone_confirm = min(3.0, max(1.2, med * 0.02))
    if durs:
        gone_wait = min(480.0, max(durs) + _TIMEOUT_ADD)
    return {
        "appear_wait": appear_wait,
        "min_rally": min_rally,
        "gone_wait": gone_wait,
        "gone_confirm": gone_confirm,
        "samples": float(len(durs)),
        "median": _average(durs),
    }


def timeouts() -> dict[str, float]:
    return timeouts_goal0()


def _record(goal: str, appear_s: float | None, duration_s: float, reason: str) -> None:
    data = load()
    value = round(float(duration_s), 2)
    data[goal].append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "appear_s": None if appear_s is None else round(float(appear_s), 2),
            "duration_s": value,
            "reason": reason,
        }
    )
    data[goal] = data[goal][-KEEP:]
    save(data)


def record_goal0(appear_s: float | None, duration_s: float, reason: str) -> dict[str, float]:
    _record("goal0", appear_s, duration_s, reason)
    return timeouts_goal0()


def record_goal1(appear_s: float | None, duration_s: float, reason: str) -> dict[str, float]:
    _record("goal1", appear_s, duration_s, reason)
    return timeouts_goal1()
