"""Источник Google Flights.

Транспорт: публичная страница /travel/flights с параметром tfs (строится
библиотекой fast-flights). Внутренний RPC GetShoppingResults с августа 2026
требует заголовок x-goog-batchexecute-bgr, который подписывает JavaScript
страницы, поэтому прямые вызовы к нему отвечают пустым payload — публичная
страница такой защиты не имеет.

Разбор: декодер из библиотеки fli. Он достаёт из строк ответа то, чего нет
в HTML-парсерах: длительность пересадок, смену аэропорта, ночные перелёты,
признак self-transfer и номера рейсов.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html
from fli.search._decoders import parse_flight_row

from models import LayoverInfo, Offer, Segment

SOURCE = "google_flights"

CABINS = {
    "economy": "economy",
    "premium_economy": "premium-economy",
    "premium-economy": "premium-economy",
    "business": "business",
    "first": "first",
}

# Блок с результатами на странице: AF_initDataCallback с ключом ds:1.
_DATA_BLOCK = re.compile(r"AF_initDataCallback\(\{key:\s*'ds:1'.*?data:(.*?), sideChannel:", re.DOTALL)


class SourceError(RuntimeError):
    """Источник недоступен или ответил не тем, что мы умеем разбирать."""


def _cabin(value: str | None) -> str:
    return CABINS.get((value or "economy").lower(), "economy")


def _passengers(passengers: dict | None) -> Passengers:
    data = passengers or {}
    return Passengers(
        adults=int(data.get("adults", 1) or 1),
        children=int(data.get("children", 0) or 0),
        infants_in_seat=int(data.get("infants_in_seat", 0) or 0),
        infants_on_lap=int(data.get("infants_on_lap", 0) or 0),
    )


def _fetch_rows(query) -> list:
    """Забирает страницу и достаёт из неё строки рейсов."""
    try:
        html = fetch_flights_html(query)
    except Exception as exc:
        raise SourceError(f"Google Flights недоступен: {exc}") from exc

    match = _DATA_BLOCK.search(html)
    if not match:
        raise SourceError("Google Flights изменил разметку страницы: блок с результатами не найден")

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceError(f"Google Flights вернул неразборчивые данные: {exc}") from exc

    rows: list = []
    for index in (2, 3):
        block = data[index] if index < len(data) else None
        if isinstance(block, list) and block and isinstance(block[0], list):
            rows.extend(block[0])
    return rows


def _offer_id(result, prefix: str = "gf") -> str:
    raw = "|".join(
        f"{leg.airline.name}{leg.flight_number}{leg.departure_datetime.isoformat()}"
        for leg in result.legs
    )
    return f"{prefix}-{hashlib.sha1(f'{raw}{result.price}'.encode()).hexdigest()[:10]}"


def _code(value) -> str:
    return value.name.removeprefix("_")


def _segments(result) -> list[Segment]:
    return [
        Segment(
            origin=_code(leg.departure_airport),
            destination=_code(leg.arrival_airport),
            departure=leg.departure_datetime.isoformat(),
            arrival=leg.arrival_datetime.isoformat(),
            duration_min=leg.duration,
            airline_code=_code(leg.airline),
            airline_name=getattr(leg.airline, "value", None),
            flight_number=leg.flight_number,
            operating_airline_code=_code(leg.operating_airline) if leg.operating_airline else None,
            aircraft=leg.aircraft,
            overnight=bool(leg.overnight),
        )
        for leg in result.legs
    ]


def _layovers(result) -> list[LayoverInfo]:
    if result.layovers:
        return [
            LayoverInfo(
                airport=_code(layover.airport),
                duration_min=layover.duration,
                change_of_airport=bool(layover.change_of_airport),
                overnight=bool(layover.overnight),
            )
            for layover in result.layovers
        ]

    # Ответ без блока пересадок: восстанавливаем их по стыкам между сегментами.
    restored: list[LayoverInfo] = []
    for previous, following in zip(result.legs, result.legs[1:]):
        gap = int((following.departure_datetime - previous.arrival_datetime).total_seconds() // 60)
        restored.append(
            LayoverInfo(
                airport=_code(previous.arrival_airport),
                duration_min=max(0, gap),
                change_of_airport=previous.arrival_airport != following.departure_airport,
                overnight=previous.arrival_datetime.date() != following.departure_datetime.date(),
            )
        )
    return restored


def _to_offer(result, currency: str, round_trip: bool) -> Offer:
    offer = Offer(
        id=_offer_id(result),
        source=SOURCE,
        price=result.price,
        currency=result.currency or currency,
        duration_min=result.duration,
        stops=result.stops,
        segments=_segments(result),
        layovers=_layovers(result),
        self_transfer=bool(result.self_transfer),
        booking_token=result.booking_token,
    )
    if result.price is None:
        offer.warnings.append("Google Flights не показал цену для этого варианта")
    if round_trip:
        offer.warnings.append(
            "цена за перелёт туда-обратно; обратный рейс Google подбирает на следующем шаге"
        )
    return offer


def search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    passengers: dict | None = None,
    cabin: str = "economy",
    max_stops: int | None = None,
    currency: str = "EUR",
    language: str = "ru",
    limit: int = 10,
    **_ignored,
) -> list[Offer]:
    """Ищет рейсы и приводит их к общей модели."""
    legs = [FlightQuery(date=departure_date, from_airport=origin.upper(), to_airport=destination.upper())]
    if return_date:
        legs.append(FlightQuery(date=return_date, from_airport=destination.upper(), to_airport=origin.upper()))

    query = create_query(
        flights=legs,
        trip="round-trip" if return_date else "one-way",
        seat=_cabin(cabin),
        passengers=_passengers(passengers),
        currency=currency,
        language=language if language in ("ru", "en-US", "es") else "",
        max_stops=max_stops,
    )

    offers: list[Offer] = []
    for row in _fetch_rows(query):
        try:
            result = parse_flight_row(row)
        except (AttributeError, KeyError, ValueError, TypeError):
            continue  # одна нечитаемая строка не повод терять остальные
        offers.append(_to_offer(result, currency, bool(return_date)))
        if len(offers) >= limit:
            break
    return offers


def cheapest_dates(
    origin: str,
    destination: str,
    from_date: str,
    to_date: str,
    passengers: dict | None = None,
    cabin: str = "economy",
    currency: str = "EUR",
    language: str = "ru",
    max_days: int = 14,
    **_ignored,
) -> list[dict]:
    """Минимальная цена по каждому дню окна.

    Календарный RPC Google закрыт тем же заголовком, что и поиск, поэтому
    каждый день опрашивается отдельно. Дни идут параллельно, а их число
    ограничено max_days, чтобы не превратить поиск в сотню запросов.
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    if end < start:
        start, end = end, start

    days: list[date] = []
    cursor = start
    while cursor <= end and len(days) < max_days:
        days.append(cursor)
        cursor += timedelta(days=1)

    def one_day(day: date) -> dict | None:
        try:
            offers = search(
                origin,
                destination,
                day.strftime("%Y-%m-%d"),
                passengers=passengers,
                cabin=cabin,
                currency=currency,
                language=language,
                limit=5,
            )
        except SourceError:
            return None
        priced = [o for o in offers if o.price is not None]
        if not priced:
            return None
        best = min(priced, key=lambda o: o.price)
        return {
            "date": day.strftime("%Y-%m-%d"),
            "price": best.price,
            "currency": best.currency,
            "duration_min": best.duration_min,
            "stops": best.stops,
            "airlines": best.airlines,
            "source": SOURCE,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one_day, days))

    return [r for r in results if r]
