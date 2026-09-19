"""Ранжирование предложений: нормализация осей, веса, штрафы, жёсткие ограничения.

Расчёт намеренно живёт в коде, а не в промпте: модель задаёт веса,
а порядок выдачи получается детерминированным и воспроизводимым.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import airports

# Оси оценки. Сумма весов нормализуется, так что задавать их можно в любом масштабе.
AXES = ("price", "duration", "stops", "convenience", "reliability")

DEFAULT_WEIGHTS: dict[str, float] = {
    "price": 0.35,
    "duration": 0.20,
    "stops": 0.20,
    "convenience": 0.15,
    "reliability": 0.10,
}

# Минимальное время стыковки, минуты.
MCT_SAME_COUNTRY = 45
MCT_INTERNATIONAL = 60
MCT_AIRPORT_CHANGE = 180
MCT_SELF_TRANSFER_EXTRA = 60

# Сверх этого стыковка превращается в потерянный день.
LONG_LAYOVER_MIN = 300


def effective_price(offer: dict) -> float | None:
    """Цена, по которой честно сравнивать: с учётом багажа, если он посчитан."""
    total = offer.get("total_price")
    return total if total is not None else offer.get("price")


def departure_of(offer: dict) -> str | None:
    """Время вылета: из готового поля либо из первого сегмента."""
    if offer.get("departure"):
        return offer["departure"]
    segments = offer.get("segments") or []
    return segments[0].get("departure") if segments else None


def arrival_of(offer: dict) -> str | None:
    """Время прилёта: из готового поля либо из последнего сегмента.

    У маршрута туда-обратно ориентируемся на прилёт в пункт назначения:
    удобство прилёта домой через неделю волнует куда меньше.
    """
    if offer.get("arrival"):
        return offer["arrival"]
    segments = offer.get("segments") or []
    return segments[-1].get("arrival") if segments else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_weights(weights: dict | None) -> dict[str, float]:
    """Приводит веса к сумме 1, отбрасывая неизвестные оси и отрицательные значения.

    Если веса заданы хотя бы частично, неупомянутые оси получают 0: указать
    только price и duration означает «ранжируй по ним», а не «добавь их к умолчаниям».
    """
    source = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    cleaned = {axis: max(0.0, float(source.get(axis, 0.0) or 0.0)) for axis in AXES}
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {axis: value / total for axis, value in cleaned.items()}


def required_mct(offer: dict, layover: dict) -> int:
    """Минимальное безопасное время стыковки для конкретной пересадки."""
    if layover.get("change_of_airport"):
        base = MCT_AIRPORT_CHANGE
    else:
        base = MCT_INTERNATIONAL if _is_international(offer) else MCT_SAME_COUNTRY
    if offer.get("self_transfer"):
        base += MCT_SELF_TRANSFER_EXTRA
    return base


def _is_international(offer: dict) -> bool:
    segments = offer.get("segments") or []
    countries = set()
    for segment in segments:
        for code in (segment.get("origin"), segment.get("destination")):
            record = airports.get(code) if code else None
            if record:
                countries.add(record.country)
    return len(countries) > 1


def _all_layovers(offer: dict) -> list[dict]:
    return list(offer.get("layovers") or []) + list(offer.get("return_layovers") or [])


def _reliability(offer: dict) -> tuple[float, list[str]]:
    """1.0 — стыковок нет или все с запасом; ниже — по мере накопления рисков."""
    notes: list[str] = []
    score = 1.0

    if offer.get("self_transfer"):
        score -= 0.35
        notes.append("разные брони: при опоздании пересадка не защищена")

    for layover in _all_layovers(offer):
        duration = int(layover.get("duration_min") or 0)
        minimum = required_mct(offer, layover)
        airport = layover.get("airport") or "?"

        if duration < minimum:
            score -= 0.30
            notes.append(f"{airport}: {duration} мин на пересадку при минимуме {minimum}")
        elif duration < minimum + 30:
            score -= 0.12
            notes.append(f"{airport}: запас на пересадку меньше 30 мин")

        if layover.get("change_of_airport"):
            score -= 0.20
            notes.append(f"{airport}: смена аэропорта на пересадке")
        if layover.get("overnight"):
            score -= 0.10
            notes.append(f"{airport}: пересадка через ночь")

    return max(0.0, score), notes


def _convenience(offer: dict) -> tuple[float, list[str]]:
    """Удобство времени вылета и прилёта."""
    notes: list[str] = []
    score = 1.0

    departure = _parse(departure_of(offer))
    arrival = _parse(arrival_of(offer))

    if departure:
        hour = departure.hour
        if hour < 5:
            score -= 0.30
            notes.append(f"вылет ночью в {departure:%H:%M}")
        elif hour < 7:
            score -= 0.15
            notes.append(f"ранний вылет в {departure:%H:%M}")
        elif hour >= 23:
            score -= 0.15
            notes.append(f"поздний вылет в {departure:%H:%M}")

    if arrival:
        hour = arrival.hour
        if hour < 6:
            score -= 0.25
            notes.append(f"прилёт ночью в {arrival:%H:%M}")
        elif hour >= 23:
            score -= 0.15
            notes.append(f"поздний прилёт в {arrival:%H:%M}")

    for layover in _all_layovers(offer):
        if int(layover.get("duration_min") or 0) > LONG_LAYOVER_MIN:
            score -= 0.15
            notes.append(f"{layover.get('airport')}: стыковка дольше 5 часов")
            break

    return max(0.0, score), notes


def _min_max(values: list[float]) -> tuple[float, float]:
    return (min(values), max(values)) if values else (0.0, 0.0)


def _normalized_lower_is_better(
    value: float | None, low: float, high: float, min_spread: float = 0.0
) -> float:
    """1.0 — лучшее значение в выборке, 0.0 — худшее. None считаем худшим.

    min_spread гасит ложную точность: когда весь разброс — пять минут или
    пара евро, растягивать его на полный балл бессмысленно, все варианты
    по этой оси равны.
    """
    if value is None:
        return 0.0
    if high - low <= max(0.0, min_spread):
        return 1.0
    return max(0.0, min(1.0, (high - value) / (high - low)))


def check_constraints(offer: dict, constraints: dict) -> list[str]:
    """Возвращает список нарушенных жёстких ограничений (пустой — всё в порядке)."""
    violations: list[str] = []
    if not constraints:
        return violations

    price = effective_price(offer)
    max_price = constraints.get("max_price")
    if max_price is not None and price is not None and price > float(max_price):
        violations.append(f"цена {price:.0f} выше лимита {float(max_price):.0f}")

    max_stops = constraints.get("max_stops")
    if max_stops is not None and int(offer.get("stops") or 0) > int(max_stops):
        violations.append(f"пересадок {offer.get('stops')} больше разрешённых {max_stops}")

    max_duration = constraints.get("max_duration_min")
    duration = offer.get("duration_min")
    if max_duration is not None and duration is not None and duration > int(max_duration):
        violations.append(f"в пути {duration} мин при лимите {max_duration}")

    arrive_before = _parse(constraints.get("arrive_before"))
    arrival = _parse(arrival_of(offer))
    if arrive_before and arrival and arrival > arrive_before:
        violations.append(f"прилёт {arrival:%d.%m %H:%M} позже требуемого {arrive_before:%d.%m %H:%M}")

    depart_after = _parse(constraints.get("depart_after"))
    departure = _parse(departure_of(offer))
    if depart_after and departure and departure < depart_after:
        violations.append(f"вылет {departure:%d.%m %H:%M} раньше допустимого {depart_after:%d.%m %H:%M}")

    if constraints.get("require_baggage") and not offer.get("price_includes_baggage"):
        violations.append("цена без сдаваемого багажа")

    excluded = {code.upper() for code in constraints.get("exclude_airlines", [])}
    if excluded:
        offer_airlines = {code.upper() for code in offer.get("airlines") or []}
        overlap = offer_airlines & excluded
        if overlap:
            violations.append(f"исключённые авиакомпании: {', '.join(sorted(overlap))}")

    if constraints.get("exclude_self_transfer") and offer.get("self_transfer"):
        violations.append("маршрут собран из разных броней")

    return violations


def rank(offers: list[dict], weights: dict | None = None, constraints: dict | None = None) -> dict:
    """Считает баллы и сортирует предложения.

    Нарушители жёстких ограничений не выбрасываются, а выносятся в отдельный
    список с причиной: иногда единственный вариант нарушает лимит на 10 евро,
    и пользователь должен это увидеть, а не гадать, почему выдача пуста.
    """
    weights = normalize_weights(weights)
    constraints = constraints or {}

    accepted: list[dict] = []
    rejected: list[dict] = []
    for offer in offers:
        violations = check_constraints(offer, constraints)
        (rejected if violations else accepted).append({"offer": offer, "violations": violations})

    pool = accepted or rejected  # если прошедших нет, ранжируем хотя бы отклонённых
    prices = [p for p in (effective_price(o["offer"]) for o in pool) if p is not None]
    durations = [o["offer"]["duration_min"] for o in pool if o["offer"].get("duration_min")]
    stop_counts = [int(o["offer"].get("stops") or 0) for o in pool] or [0]

    price_low, price_high = _min_max(prices)
    duration_low, duration_high = _min_max(durations)
    # Разница меньше этой не считается различием: 5 единиц валюты и 20 минут.
    price_spread = max(5.0, price_low * 0.03) if prices else 0.0
    duration_spread = 20.0
    stops_high = max(max(stop_counts), 1)

    def score_one(entry: dict) -> dict:
        offer = entry["offer"]
        reliability, reliability_notes = _reliability(offer)
        convenience, convenience_notes = _convenience(offer)

        axis_scores = {
            "price": _normalized_lower_is_better(
                effective_price(offer), price_low, price_high, price_spread
            ),
            "duration": _normalized_lower_is_better(
                offer.get("duration_min"), duration_low, duration_high, duration_spread
            ),
            "stops": 1.0 - min(1.0, int(offer.get("stops") or 0) / stops_high),
            "convenience": convenience,
            "reliability": reliability,
        }
        total = sum(axis_scores[axis] * weights[axis] for axis in AXES)

        result = dict(offer)
        result["score"] = round(total * 100, 1)
        result["score_breakdown"] = {
            axis: {"score": round(axis_scores[axis], 3), "weight": round(weights[axis], 3)}
            for axis in AXES
        }
        result["risk_notes"] = reliability_notes
        result["comfort_notes"] = convenience_notes
        if entry["violations"]:
            result["violations"] = entry["violations"]
        return result

    ranked = sorted((score_one(e) for e in accepted), key=lambda o: o["score"], reverse=True)
    excluded = sorted((score_one(e) for e in rejected), key=lambda o: o["score"], reverse=True)

    return {
        "weights": weights,
        "ranked": ranked,
        "excluded": excluded,
        "summary": {
            "total": len(offers),
            "ranked": len(ranked),
            "excluded": len(excluded),
            "cheapest_price": price_low if prices else None,
            "shortest_duration_min": duration_low if durations else None,
        },
    }
