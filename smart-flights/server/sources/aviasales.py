"""Источник Aviasales (Data API, он же Travelpayouts).

Отдаёт цены, найденные пользователями Aviasales за последние 48 часов, — это
кэш, а не живой опрос авиакомпаний. Поэтому цена может отличаться от актуальной,
и каждое предложение помечается источником.

Взамен кэш даёт то, чего нет у Google Flights: покрытие российских и
среднеазиатских перевозчиков и прямую ссылку на поиск Aviasales.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import httpx

from models import BookingLink, Offer, Segment

SOURCE = "aviasales"
API_BASE = "https://api.travelpayouts.com/aviasales/v3"
SITE = "https://www.aviasales.ru"
CACHE_WINDOW_HOURS = 48


class SourceError(RuntimeError):
    """Источник недоступен, не авторизован или ответил ошибкой."""


class MissingTokenError(SourceError):
    """Токен не настроен — источник просто пропускается."""


def _request(path: str, token: str, params: dict) -> dict:
    if not token:
        raise MissingTokenError("Токен Aviasales не настроен")
    if not token.isascii():
        raise MissingTokenError(
            "Токен Aviasales содержит недопустимые символы — скопируйте его заново из кабинета"
        )

    try:
        response = httpx.get(
            f"{API_BASE}/{path}",
            params={k: v for k, v in params.items() if v is not None},
            headers={"X-Access-Token": token},
            timeout=25.0,
        )
    except httpx.HTTPError as exc:
        raise SourceError(f"Aviasales недоступен: {exc}") from exc

    if response.status_code == 401:
        raise MissingTokenError("Aviasales отклонил токен: проверьте AVIASALES_API_TOKEN")
    if response.status_code == 429:
        raise SourceError("Aviasales: превышен лимит запросов, попробуйте позже")
    if response.status_code >= 400:
        raise SourceError(f"Aviasales вернул {response.status_code}: {response.text[:200]}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError(f"Aviasales вернул не JSON: {exc}") from exc

    if not payload.get("success", True):
        raise SourceError(f"Aviasales: {payload.get('error') or 'неизвестная ошибка'}")
    return payload


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _offer_id(item: dict) -> str:
    raw = f"{item.get('origin')}{item.get('destination')}{item.get('departure_at')}{item.get('airline')}{item.get('flight_number')}{item.get('price')}"
    return f"av-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def _to_offer(item: dict, currency: str) -> Offer:
    """Собирает предложение из плоской записи API.

    У записи нет разбивки по сегментам — известны только конечные точки,
    время вылета и число пересадок. Поэтому сегмент один, а пересадки
    остаются числом: сочинять промежуточные аэропорты нельзя.
    """
    departure = _parse_dt(item.get("departure_at"))
    duration_to = item.get("duration_to") or item.get("duration")
    arrival = departure + timedelta(minutes=int(duration_to)) if departure and duration_to else None

    origin = item.get("origin_airport") or item.get("origin") or ""
    destination = item.get("destination_airport") or item.get("destination") or ""
    transfers = int(item.get("transfers") or 0)

    segment = Segment(
        origin=origin,
        destination=destination,
        departure=departure.isoformat() if departure else None,
        arrival=arrival.isoformat() if arrival else None,
        duration_min=int(duration_to) if duration_to else None,
        airline_code=item.get("airline"),
        flight_number=str(item.get("flight_number")) if item.get("flight_number") else None,
    )

    offer = Offer(
        id=_offer_id(item),
        source=SOURCE,
        price=float(item["price"]) if item.get("price") is not None else None,
        currency=(item.get("currency") or currency).upper(),
        duration_min=int(item["duration"]) if item.get("duration") else None,
        stops=transfers,
        segments=[segment],
        price_includes_baggage=False,
        baggage_note="багаж не учтён: Aviasales отдаёт цену базового тарифа",
    )

    return_at = _parse_dt(item.get("return_at"))
    if return_at:
        duration_back = item.get("duration_back")
        back_arrival = return_at + timedelta(minutes=int(duration_back)) if duration_back else None
        offer.return_segments = [
            Segment(
                origin=destination,
                destination=origin,
                departure=return_at.isoformat(),
                arrival=back_arrival.isoformat() if back_arrival else None,
                duration_min=int(duration_back) if duration_back else None,
                airline_code=item.get("airline"),
            )
        ]

    if transfers:
        offer.warnings.append(
            f"пересадок: {transfers}; Aviasales не раскрывает аэропорты и время стыковок"
        )

    link = item.get("link")
    if link:
        offer.booking_links.append(
            BookingLink(
                label="Aviasales",
                url=link if link.startswith("http") else f"{SITE}{link}",
                kind="aggregator",
                price=offer.price,
                currency=offer.currency,
            )
        )

    return offer


def search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    token: str = "",
    currency: str = "EUR",
    max_stops: int | None = None,
    limit: int = 10,
    **_ignored,
) -> list[Offer]:
    """Цены по маршруту на конкретную дату."""
    payload = _request(
        "prices_for_dates",
        token,
        {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_at": departure_date,
            "return_at": return_date,
            "currency": currency.lower(),
            "one_way": "false" if return_date else "true",
            "direct": "true" if max_stops == 0 else None,
            "sorting": "price",
            "limit": min(int(limit), 1000),
            "market": "es",
        },
    )

    offers = [_to_offer(item, currency) for item in (payload.get("data") or [])]
    for offer in offers:
        offer.warnings.append(f"цена из кэша Aviasales (поиски за последние {CACHE_WINDOW_HOURS} ч)")
    return offers[:limit]


def cheapest_dates(
    origin: str,
    destination: str,
    from_date: str,
    to_date: str,
    token: str = "",
    currency: str = "EUR",
    max_days: int = 31,
    **_ignored,
) -> list[dict]:
    """Минимальные цены по дням окна.

    Aviasales умеет отдавать целый месяц одним запросом, поэтому окно берётся
    месяцем, а лишние дни отсекаются на нашей стороне.
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    if end < start:
        start, end = end, start

    months: list[str] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m-%d"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    best_per_day: dict[str, dict] = {}
    for month in months:
        payload = _request(
            "prices_for_dates",
            token,
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_at": month[:7],
                "currency": currency.lower(),
                "one_way": "true",
                "sorting": "price",
                "group_by": "departure_at",
                "limit": 1000,
                "market": "es",
            },
        )
        for item in payload.get("data") or []:
            departure = _parse_dt(item.get("departure_at"))
            if not departure:
                continue
            day = departure.date()
            if not (start <= day <= end):
                continue
            key = day.strftime("%Y-%m-%d")
            price = float(item["price"]) if item.get("price") is not None else None
            if price is None:
                continue
            current = best_per_day.get(key)
            if current is None or price < current["price"]:
                best_per_day[key] = {
                    "date": key,
                    "price": price,
                    "currency": (item.get("currency") or currency).upper(),
                    "duration_min": item.get("duration_to") or item.get("duration"),
                    "stops": int(item.get("transfers") or 0),
                    "airlines": [item["airline"]] if item.get("airline") else [],
                    "source": SOURCE,
                }

    return sorted(best_per_day.values(), key=lambda r: r["date"])[:max_days]
