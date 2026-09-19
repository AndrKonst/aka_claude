#!/usr/bin/env python3
"""MCP-сервер плагина smart-flights.

Инструменты сознательно тонкие: вся логика живёт в отдельных модулях, а сервер
только раскрывает её наружу. Ошибки источников возвращаются как данные, а не
как исключения — модель должна уметь рассказать, что именно недоступно.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Транспорт Google Flights логирует каждый запрос в stderr — для MCP это шум.
for noisy in ("primp", "fast_flights", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from mcp.server.mcpserver import MCPServer  # noqa: E402

import airports  # noqa: E402
import deeplinks  # noqa: E402
import ranking  # noqa: E402
import search as search_module  # noqa: E402
from config import load_profile  # noqa: E402

mcp = MCPServer(
    name="smart-flights",
    version="0.2.0",
    instructions=(
        "Поиск и ранжирование авиабилетов по двум источникам: Google Flights и Aviasales. "
        "Цены приводятся к одной валюте, к тарифу добавляется оценка стоимости багажа. "
        "Порядок выдачи задаётся весами по осям: price, duration, stops, convenience, reliability."
    ),
)


@mcp.tool(
    description=(
        "Текущий профиль поиска: валюта, базовые аэропорты, пассажиры, багаж, "
        "какие источники включены и настроен ли токен Aviasales."
    )
)
def get_profile() -> dict:
    return load_profile().to_dict()


@mcp.tool(
    description=(
        "Превращает название города или аэропорта в IATA-код. Понимает русские названия "
        "('Севилья'), английские ('Seville') и сами коды ('SVQ'). "
        "Возвращает несколько вариантов, если у города больше одного аэропорта."
    )
)
def resolve_place(query: str, limit: int = 5) -> dict:
    matches = airports.resolve(query, limit=limit)
    return {
        "query": query,
        "matches": [m.to_dict() for m in matches],
        "ambiguous": len(matches) > 1,
    }


@mcp.tool(
    description=(
        "Аэропорты рядом с заданным, в радиусе километров. Нужен, чтобы проверить "
        "альтернативы вылета: из соседнего аэропорта часто летают дешевле."
    )
)
def nearby_airports(iata: str, radius_km: int = 150, limit: int = 5) -> dict:
    return {"origin": iata.upper(), "radius_km": radius_km, "airports": airports.nearby(iata, radius_km, limit)}


@mcp.tool(
    description=(
        "Основной поиск рейсов по маршруту и датам во всех доступных источниках. "
        "Возвращает предложения с полной ценой (тариф плюс оценка багажа), сегментами, "
        "пересадками и ссылками на покупку, плюс диагностику по каждому источнику. "
        "include_nearby добавляет варианты из соседних аэропортов."
    )
)
def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    cabin: str = "economy",
    max_stops: int | None = None,
    limit: int = 10,
    include_nearby: bool = False,
    nearby_radius_km: int | None = None,
) -> dict:
    return search_module.search_route(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        cabin=cabin,
        max_stops=max_stops,
        limit=limit,
        include_nearby=include_nearby,
        nearby_radius_km=nearby_radius_km,
    )


@mcp.tool(
    description=(
        "Цены по дням в окне вокруг желаемой даты (±flex_days). Показывает самый дешёвый "
        "день и экономию относительно исходной даты. trip_length_days задаёт длительность "
        "поездки, чтобы окно сдвигало обе даты сразу."
    )
)
def search_flexible_dates(
    origin: str,
    destination: str,
    departure_date: str,
    flex_days: int = 3,
    return_date: str | None = None,
    trip_length_days: int | None = None,
    cabin: str = "economy",
) -> dict:
    return search_module.search_flexible(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        flex_days=flex_days,
        return_date=return_date,
        trip_length_days=trip_length_days,
        cabin=cabin,
    )


@mcp.tool(
    description=(
        "Ранжирует предложения из search_flights по весам и жёстким ограничениям. "
        "Веса задаются по осям price, duration, stops, convenience, reliability — сумма "
        "нормализуется автоматически. Ограничения: max_price, max_stops, max_duration_min, "
        "arrive_before, depart_after, require_baggage, exclude_airlines, exclude_self_transfer. "
        "Нарушители ограничений не выбрасываются, а попадают в excluded с указанием причины."
    )
)
def rank_offers(offers: list[dict], weights: dict | None = None, constraints: dict | None = None) -> dict:
    return ranking.rank(offers, weights, constraints)


@mcp.tool(
    description=(
        "Ссылки на покупку для одного предложения: сайт авиакомпании по каждому сегменту "
        "плюс Aviasales и Google Flights на весь маршрут. Поле precision показывает точность: "
        "search — поиск с подставленным маршрутом, home — только главная страница перевозчика."
    )
)
def build_booking_links(offer: dict, adults: int = 1) -> dict:
    return {"links": deeplinks.build_links(offer, adults=adults)}


if __name__ == "__main__":
    mcp.run()
