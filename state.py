from typing import Any

_flows: dict[int, dict] = {}


def get_flow(telegram_id: int) -> dict:
    return _flows.get(telegram_id, {"kind": "idle"})


def set_flow(telegram_id: int, flow: dict):
    _flows[telegram_id] = flow


def clear_flow(telegram_id: int):
    _flows.pop(telegram_id, None)
