"""Ссылки «где купить»: сайты авиакомпаний по сегментам и агрегаторы на весь маршрут.

Ни один из бесплатных источников не отдаёт ссылку в конкретную бронь, поэтому
ссылки ведут в поиск с подставленным маршрутом. Точные ссылки вендоров приходят
отдельно — из get_booking_options Google Flights, см. sources/google_flights.py.

deeplink в таблице ниже задан только там, где формат проверен. Для остальных
перевозчиков честнее открыть главную страницу, чем вести на собранный наугад URL.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

# code: (название, сайт, шаблон поиска | None)
# В шаблоне доступны {origin}, {destination}, {date}, {return_date}, {adults}.
AIRLINES: dict[str, tuple[str, str, str | None]] = {
    "FR": ("Ryanair", "https://www.ryanair.com/", "https://www.ryanair.com/es/es/trip/flights/select?adults={adults}&dateOut={date}&originIata={origin}&destinationIata={destination}"),
    "W6": ("Wizz Air", "https://wizzair.com/", "https://wizzair.com/en-gb#/booking/select-flight/{origin}/{destination}/{date}/null/{adults}/0/0/null"),
    "W4": ("Wizz Air Malta", "https://wizzair.com/", "https://wizzair.com/en-gb#/booking/select-flight/{origin}/{destination}/{date}/null/{adults}/0/0/null"),
    "U2": ("easyJet", "https://www.easyjet.com/", "https://www.easyjet.com/en/buy/flights?dep={origin}&arr={destination}&dd={date}&apax={adults}"),
    "EC": ("easyJet Europe", "https://www.easyjet.com/", "https://www.easyjet.com/en/buy/flights?dep={origin}&arr={destination}&dd={date}&apax={adults}"),
    "VY": ("Vueling", "https://www.vueling.com/", None),
    "IB": ("Iberia", "https://www.iberia.com/", None),
    "I2": ("Iberia Express", "https://www.iberiaexpress.com/", None),
    "UX": ("Air Europa", "https://www.aireuropa.com/", None),
    "NT": ("Binter Canarias", "https://www.bintercanarias.com/", None),
    "V7": ("Volotea", "https://www.volotea.com/", None),
    "TP": ("TAP Air Portugal", "https://www.flytap.com/", None),
    "LH": ("Lufthansa", "https://www.lufthansa.com/", None),
    "EW": ("Eurowings", "https://www.eurowings.com/", None),
    "AF": ("Air France", "https://www.airfrance.com/", None),
    "KL": ("KLM", "https://www.klm.com/", None),
    "BA": ("British Airways", "https://www.britishairways.com/", None),
    "AZ": ("ITA Airways", "https://www.ita-airways.com/", None),
    "SN": ("Brussels Airlines", "https://www.brusselsairlines.com/", None),
    "OS": ("Austrian Airlines", "https://www.austrian.com/", None),
    "LX": ("SWISS", "https://www.swiss.com/", None),
    "SK": ("SAS", "https://www.flysas.com/", None),
    "AY": ("Finnair", "https://www.finnair.com/", None),
    "LO": ("LOT", "https://www.lot.com/", None),
    "TK": ("Turkish Airlines", "https://www.turkishairlines.com/", None),
    "PC": ("Pegasus", "https://www.flypgs.com/", None),
    "FZ": ("flydubai", "https://www.flydubai.com/", None),
    "EK": ("Emirates", "https://www.emirates.com/", None),
    "QR": ("Qatar Airways", "https://www.qatarairways.com/", None),
    "SU": ("Аэрофлот", "https://www.aeroflot.ru/", None),
    "S7": ("S7 Airlines", "https://www.s7.ru/", None),
    "DP": ("Победа", "https://www.pobeda.aero/", None),
    "U6": ("Уральские авиалинии", "https://www.uralairlines.ru/", None),
    "UT": ("Utair", "https://www.utair.ru/", None),
    "N4": ("Северный ветер", "https://nordwindairlines.ru/", None),
    "5N": ("Smartavia", "https://flysmartavia.com/", None),
    "WZ": ("Red Wings", "https://flyredwings.com/", None),
    "KC": ("Air Astana", "https://airastana.com/", None),
    "HY": ("Uzbekistan Airways", "https://www.uzairways.com/", None),
    "B2": ("Белавиа", "https://belavia.by/", None),
}


def airline_name(code: str | None) -> str | None:
    if not code:
        return None
    entry = AIRLINES.get(code.upper())
    if entry:
        return entry[0]
    try:
        from fli.models.airline import AIRLINE_NAMES

        return AIRLINE_NAMES.get(code.upper())
    except ImportError:
        return None


def _ddmm(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%d%m")


def airline_link(
    code: str | None,
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
    adults: int = 1,
) -> dict | None:
    """Ссылка на сайт перевозчика: в поиск с датами, если формат известен, иначе на главную."""
    if not code:
        return None
    entry = AIRLINES.get(code.upper())
    if not entry:
        return None

    name, site, template = entry
    if template:
        url = template.format(
            origin=origin.upper(),
            destination=destination.upper(),
            date=date,
            return_date=return_date or "",
            adults=adults,
        )
        precision = "search"
    else:
        url = site
        precision = "home"

    return {
        "label": name,
        "url": url,
        "kind": "airline",
        "is_airline_direct": True,
        "precision": precision,
    }


def aviasales_link(
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
    adults: int = 1,
) -> dict:
    """Поиск Aviasales: /search/{ORIG}{DDMM}{DEST}[{DDMM}]{пассажиры}."""
    path = f"{origin.upper()}{_ddmm(date)}{destination.upper()}"
    if return_date:
        path += _ddmm(return_date)
    path += str(max(1, adults))
    return {
        "label": "Aviasales",
        "url": f"https://www.aviasales.ru/search/{path}",
        "kind": "aggregator",
        "is_airline_direct": False,
        "precision": "search",
    }


def google_flights_link(
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
) -> dict:
    """Поиск Google Flights текстовым запросом — формат устойчив к смене их внутренних параметров."""
    query = f"Flights from {origin.upper()} to {destination.upper()} on {date}"
    if return_date:
        query += f" through {return_date}"
    return {
        "label": "Google Flights",
        "url": f"https://www.google.com/travel/flights?q={quote(query)}",
        "kind": "aggregator",
        "is_airline_direct": False,
        "precision": "search",
    }


def build_links(offer: dict, adults: int = 1) -> list[dict]:
    """Полный набор ссылок для предложения: по сегментам плюс два агрегатора на маршрут."""
    segments = offer.get("segments") or []
    if not segments:
        return []

    origin = segments[0].get("origin")
    destination = segments[-1].get("destination")
    date = (segments[0].get("departure") or "")[:10]
    return_segments = offer.get("return_segments") or []
    return_date = (return_segments[0].get("departure") or "")[:10] if return_segments else None

    links: list[dict] = []

    # Ссылки вендоров, если они пришли из Google Flights, всегда точнее собранных нами.
    for link in offer.get("booking_links") or []:
        links.append({**link, "precision": link.get("precision", "fare")})

    seen_airlines: set[str] = set()
    for segment in segments + return_segments:
        code = (segment.get("airline_code") or "").upper()
        if not code or code in seen_airlines:
            continue
        seen_airlines.add(code)
        link = airline_link(
            code,
            segment.get("origin") or origin,
            segment.get("destination") or destination,
            (segment.get("departure") or date)[:10],
            adults=adults,
        )
        if link:
            link["segment"] = f"{segment.get('origin')}→{segment.get('destination')}"
            link["flight"] = f"{code}{segment.get('flight_number') or ''}"
            links.append(link)

    if origin and destination and date:
        links.append(aviasales_link(origin, destination, date, return_date, adults))
        links.append(google_flights_link(origin, destination, date, return_date))

    # Предложение может уже нести ссылки с прошлого вызова — не размножаем их.
    unique: list[dict] = []
    seen_urls: set[str] = set()
    for link in links:
        url = link.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(link)
    return unique
