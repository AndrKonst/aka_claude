"""Пересчёт валют: Aviasales отдаёт рубли, Google Flights — евро, сравнивать надо в одной.

Курсы берутся из open.er-api.com (без ключа) и кэшируются на сутки. Если сеть
недоступна, конвертация не выполняется: лучше показать цену в исходной валюте
с пометкой, чем пересчитать по выдуманному курсу.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from config import plugin_root

CACHE_TTL_SECONDS = 24 * 3600
API_URL = "https://open.er-api.com/v6/latest/{base}"


def _cache_path(base: str) -> Path:
    cache_dir = plugin_root() / ".cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / f"fx-{base.upper()}.json"


def _read_cache(base: str) -> dict | None:
    path = _cache_path(base)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - data.get("fetched_at", 0) > CACHE_TTL_SECONDS:
        return None
    return data


def get_rates(base: str = "EUR") -> dict | None:
    """Курсы относительно базовой валюты. None, если получить их не удалось."""
    base = base.upper()
    cached = _read_cache(base)
    if cached:
        return cached

    try:
        response = httpx.get(API_URL.format(base=base), timeout=15.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if payload.get("result") != "success" or not payload.get("rates"):
        return None

    data = {
        "base": base,
        "rates": payload["rates"],
        "updated": payload.get("time_last_update_utc"),
        "fetched_at": time.time(),
    }
    try:
        _cache_path(base).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # кэш необязателен
    return data


def convert(amount: float | None, source_currency: str, target_currency: str) -> float | None:
    """Переводит сумму в целевую валюту. None, если курс недоступен."""
    if amount is None:
        return None
    source_currency = (source_currency or "").upper()
    target_currency = (target_currency or "").upper()
    if not source_currency or source_currency == target_currency:
        return amount

    rates_data = get_rates(target_currency)
    if not rates_data:
        return None
    rate = rates_data["rates"].get(source_currency)
    if not rate:
        return None
    return round(amount / rate, 2)
