"""Оценка доплаты за багаж и расчёт полной стоимости перелёта.

Google Flights игнорирует параметр багажа в публичной выдаче, а Aviasales
отдаёт цену базового тарифа, поэтому сравнивать голые тарифы лоукостера и
сетевого перевозчика нечестно: у первого чемодан может стоить больше билета.

Сборы берутся из data/baggage_fees.json — это оценка, а не тариф перевозчика.
Каждый расчёт помечается как оценочный, чтобы это не выдавалось за точную цену.
"""

from __future__ import annotations

import json
from functools import lru_cache

from config import plugin_root


@lru_cache(maxsize=1)
def _fees() -> dict:
    path = plugin_root() / "data" / "baggage_fees.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"default": {"network": {"carry_on": 0, "checked": 50}}, "airlines": {}}


def airline_fees(airline_code: str | None) -> dict:
    """Сборы конкретного перевозчика; для неизвестного — усреднённые сетевые."""
    data = _fees()
    defaults = data.get("default", {})
    fallback = defaults.get("network", {"carry_on": 0, "checked": 50})

    if not airline_code:
        return {"carry_on": fallback.get("carry_on", 0), "checked": fallback.get("checked", 50), "known": False}

    entry = (data.get("airlines") or {}).get(airline_code.upper())
    if not entry:
        return {"carry_on": fallback.get("carry_on", 0), "checked": fallback.get("checked", 50), "known": False}

    return {"carry_on": entry.get("carry_on", 0), "checked": entry.get("checked", 0), "known": True}


def estimate(offer: dict, baggage: dict | None) -> dict:
    """Считает доплату за багаж для предложения.

    Сбор берётся по каждому направлению (туда и обратно) и по перевозчику
    первого сегмента направления: при пересадке внутри одной брони багаж, как
    правило, оформляется сквозным по правилам первого перевозчика.
    """
    baggage = baggage or {}
    checked_bags = int(baggage.get("checked_bags") or 0)
    needs_carry_on = bool(baggage.get("carry_on"))

    if not checked_bags and not needs_carry_on:
        return {"amount": 0.0, "estimated": False, "known_rates": True, "details": []}

    directions = [offer.get("segments") or []]
    if offer.get("return_segments"):
        directions.append(offer["return_segments"])

    total = 0.0
    details: list[str] = []
    all_known = True

    for segments in directions:
        if not segments:
            continue
        airline = segments[0].get("airline_code")
        fees = airline_fees(airline)
        all_known = all_known and fees["known"]

        leg_total = fees["checked"] * checked_bags + (fees["carry_on"] if needs_carry_on else 0)
        total += leg_total
        if leg_total:
            route = f"{segments[0].get('origin')}→{segments[-1].get('destination')}"
            details.append(f"{route} ({airline or '?'}): {leg_total:.0f}")

    return {
        "amount": round(total, 2),
        "estimated": True,
        "known_rates": all_known,
        "details": details,
    }


def apply(offer: dict, baggage: dict | None, currency: str = "EUR") -> dict:
    """Дополняет предложение полем total_price — тариф плюс оценка багажа."""
    result = dict(offer)
    estimation = estimate(offer, baggage)
    price = offer.get("price")

    result["baggage_fee"] = estimation["amount"]
    result["baggage_estimated"] = estimation["estimated"]
    result["total_price"] = round(price + estimation["amount"], 2) if price is not None else None

    if estimation["estimated"] and estimation["amount"]:
        note = f"багаж примерно +{estimation['amount']:.0f} {currency}"
        if estimation["details"]:
            note += " (" + "; ".join(estimation["details"]) + ")"
        if not estimation["known_rates"]:
            note += "; ставка перевозчика неизвестна, взята средняя"
        result["baggage_note"] = note
    elif estimation["estimated"]:
        result["baggage_note"] = "выбранный багаж входит в тариф по нашим данным"

    return result
