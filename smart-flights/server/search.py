"""Оркестрация поиска: несколько источников, соседние аэропорты, гибкие даты.

Источники опрашиваются параллельно и независимо: падение одного не отменяет
поиск, а попадает в диагностику ответа. Так пользователь видит, что выдача
неполная, вместо того чтобы считать её исчерпывающей.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import airports
import baggage
import deeplinks
import fx
from config import Profile
from sources import aviasales, google_flights


def _iata(place: str) -> tuple[str | None, list[dict]]:
    """Превращает название или код в IATA. Возвращает код и найденные варианты."""
    matches = airports.resolve(place)
    if not matches:
        return None, []
    return matches[0].iata, [m.to_dict() for m in matches]


def _to_currency(offers: list[dict], target: str) -> list[dict]:
    """Приводит все цены к одной валюте, иначе сравнение бессмысленно."""
    converted: list[dict] = []
    for offer in offers:
        source_currency = (offer.get("currency") or target).upper()
        if source_currency == target.upper() or offer.get("price") is None:
            converted.append(offer)
            continue

        price = fx.convert(offer["price"], source_currency, target)
        if price is None:
            offer = dict(offer)
            offer.setdefault("warnings", []).append(
                f"цена в {source_currency}: курс недоступен, пересчёт не выполнен"
            )
            converted.append(offer)
            continue

        offer = dict(offer)
        offer["original_price"] = offer["price"]
        offer["original_currency"] = source_currency
        offer["price"] = price
        offer["currency"] = target.upper()
        converted.append(offer)
    return converted


def _dedup_key(offer: dict) -> str:
    """Один и тот же рейс у разных источников должен схлопнуться в одну строку."""
    parts = []
    for segment in (offer.get("segments") or []) + (offer.get("return_segments") or []):
        parts.append(
            f"{segment.get('airline_code')}{segment.get('flight_number')}"
            f"@{(segment.get('departure') or '')[:16]}"
        )
    return "|".join(parts) or offer.get("id", "")


def _merge(offers: list[dict]) -> list[dict]:
    """Схлопывает дубли, оставляя вариант с меньшей ценой и памятью об источниках."""
    merged: dict[str, dict] = {}
    for offer in offers:
        key = _dedup_key(offer)
        existing = merged.get(key)
        if existing is None:
            offer = dict(offer)
            offer["sources"] = [offer["source"]]
            merged[key] = offer
            continue

        if offer["source"] not in existing["sources"]:
            existing["sources"].append(offer["source"])

        new_price, old_price = offer.get("price"), existing.get("price")
        if new_price is not None and (old_price is None or new_price < old_price):
            # Дешевле у другого источника — берём его цену, сохраняя разметку.
            sources = existing["sources"]
            existing.clear()
            existing.update(offer)
            existing["sources"] = sources
    return list(merged.values())


def _source_calls(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    profile: Profile,
    cabin: str,
    max_stops: int | None,
    limit: int,
) -> list[tuple[str, callable]]:
    calls: list[tuple[str, callable]] = []

    if profile.sources.get("google_flights", True):
        calls.append((
            google_flights.SOURCE,
            lambda: google_flights.search(
                origin, destination, departure_date, return_date,
                passengers=profile.passengers, cabin=cabin, max_stops=max_stops,
                currency=profile.currency, language=profile.language, limit=limit,
            ),
        ))

    if profile.sources.get("aviasales", True) and profile.has_aviasales_token:
        calls.append((
            aviasales.SOURCE,
            lambda: aviasales.search(
                origin, destination, departure_date, return_date,
                token=profile.aviasales_token, currency=profile.currency,
                max_stops=max_stops, limit=limit,
            ),
        ))

    return calls


def search_route(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    profile: Profile | None = None,
    cabin: str = "economy",
    max_stops: int | None = None,
    limit: int = 10,
    include_nearby: bool = False,
    nearby_radius_km: int | None = None,
) -> dict:
    """Поиск по маршруту во всех доступных источниках."""
    from config import load_profile

    profile = profile or load_profile()
    origin_code, origin_matches = _iata(origin)
    destination_code, destination_matches = _iata(destination)

    if not origin_code:
        return {"error": f"Не удалось распознать пункт вылета: {origin}", "offers": []}
    if not destination_code:
        return {"error": f"Не удалось распознать пункт назначения: {destination}", "offers": []}

    routes = [(origin_code, destination_code)]
    nearby_used: list[dict] = []
    if include_nearby:
        radius = nearby_radius_km or profile.nearby_radius_km
        for record in airports.nearby(origin_code, radius, limit=2):
            routes.append((record["iata"], destination_code))
            nearby_used.append({"role": "origin", **record})
        for record in airports.nearby(destination_code, radius, limit=2):
            routes.append((origin_code, record["iata"]))
            nearby_used.append({"role": "destination", **record})

    tasks: list[tuple[str, str, str, callable]] = []
    for route_origin, route_destination in routes:
        for source_name, call in _source_calls(
            route_origin, route_destination, departure_date, return_date,
            profile, cabin, max_stops, limit,
        ):
            tasks.append((source_name, route_origin, route_destination, call))

    diagnostics: list[dict] = []
    collected: list[dict] = []

    def run(task):
        source_name, route_origin, route_destination, call = task
        try:
            return source_name, route_origin, route_destination, call(), None
        except Exception as exc:  # источник не должен ронять весь поиск
            return source_name, route_origin, route_destination, [], str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for source_name, route_origin, route_destination, offers, error in pool.map(run, tasks):
            diagnostics.append({
                "source": source_name,
                "route": f"{route_origin}-{route_destination}",
                "found": len(offers),
                "error": error,
            })
            for offer in offers:
                data = offer.to_dict() if hasattr(offer, "to_dict") else dict(offer)
                data["route"] = f"{route_origin}-{route_destination}"
                data["is_alternative_route"] = (route_origin, route_destination) != (origin_code, destination_code)
                collected.append(data)

    if not profile.has_aviasales_token and profile.sources.get("aviasales", True):
        diagnostics.append({
            "source": aviasales.SOURCE,
            "route": f"{origin_code}-{destination_code}",
            "found": 0,
            "error": "токен не настроен — источник пропущен",
        })

    offers = _merge(_to_currency(collected, profile.currency))
    offers = [baggage.apply(offer, profile.baggage, profile.currency) for offer in offers]
    for offer in offers:
        offer["booking_links"] = deeplinks.build_links(
            offer, adults=int(profile.passengers.get("adults", 1) or 1)
        )

    offers.sort(key=lambda o: (o.get("total_price") is None, o.get("total_price") or 0))

    return {
        "query": {
            "origin": origin_code,
            "destination": destination_code,
            "departure_date": departure_date,
            "return_date": return_date,
            "cabin": cabin,
            "currency": profile.currency,
            "passengers": profile.passengers,
            "baggage": profile.baggage,
        },
        "resolved": {"origin": origin_matches[:3], "destination": destination_matches[:3]},
        "nearby_airports_used": nearby_used,
        "sources": diagnostics,
        "offers": offers,
    }


def search_flexible(
    origin: str,
    destination: str,
    departure_date: str,
    flex_days: int = 3,
    return_date: str | None = None,
    trip_length_days: int | None = None,
    profile: Profile | None = None,
    cabin: str = "economy",
    limit_per_day: int = 5,
) -> dict:
    """Цены по дням в окне ±flex_days вокруг желаемой даты."""
    from config import load_profile

    profile = profile or load_profile()
    origin_code, _ = _iata(origin)
    destination_code, _ = _iata(destination)
    if not origin_code or not destination_code:
        return {"error": "Не удалось распознать маршрут", "days": []}

    target = datetime.strptime(departure_date, "%Y-%m-%d").date()
    flex_days = max(0, min(int(flex_days), 10))
    days = [
        (target + timedelta(days=shift)).strftime("%Y-%m-%d")
        for shift in range(-flex_days, flex_days + 1)
        if (target + timedelta(days=shift)) >= datetime.now().date()
    ]

    if trip_length_days and not return_date:
        pairs = [(d, (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=trip_length_days)).strftime("%Y-%m-%d")) for d in days]
    else:
        pairs = [(d, return_date) for d in days]

    def one_day(pair):
        day, back = pair
        result = search_route(
            origin_code, destination_code, day, back,
            profile=profile, cabin=cabin, limit=limit_per_day,
        )
        offers = [o for o in result.get("offers", []) if o.get("total_price") is not None]
        if not offers:
            return {"date": day, "return_date": back, "price": None, "offers": 0}
        best = min(offers, key=lambda o: o["total_price"])
        return {
            "date": day,
            "return_date": back,
            "price": best["total_price"],
            "currency": best.get("currency"),
            "duration_min": best.get("duration_min"),
            "stops": best.get("stops"),
            "airlines": best.get("airlines"),
            "offer_id": best.get("id"),
            "offers": len(offers),
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one_day, pairs))

    priced = [r for r in results if r.get("price") is not None]
    best = min(priced, key=lambda r: r["price"]) if priced else None
    target_row = next((r for r in results if r["date"] == departure_date), None)

    savings = None
    if best and target_row and target_row.get("price") is not None:
        savings = round(target_row["price"] - best["price"], 2)

    return {
        "query": {
            "origin": origin_code,
            "destination": destination_code,
            "target_date": departure_date,
            "flex_days": flex_days,
            "currency": profile.currency,
        },
        "days": results,
        "best": best,
        "savings_vs_target": savings,
    }
