"""Справочник аэропортов: резолв названий в IATA и поиск соседних аэропортов."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from config import plugin_root


@dataclass(frozen=True)
class AirportRecord:
    iata: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    size: str  # L | M | S

    def to_dict(self) -> dict:
        return {
            "iata": self.iata,
            "name": self.name,
            "city": self.city,
            "country": self.country,
            "lat": self.lat,
            "lon": self.lon,
            "size": self.size,
        }


# Города, чьи русские/испанские написания не выводятся из латиницы автоматически.
CITY_ALIASES: dict[str, str] = {
    "севилья": "Seville",
    "мадрид": "Madrid",
    "барселона": "Barcelona",
    "малага": "Malaga",
    "валенсия": "Valencia",
    "аликанте": "Alicante",
    "бильбао": "Bilbao",
    "пальма": "Palma de Mallorca",
    "майорка": "Palma de Mallorca",
    "лиссабон": "Lisbon",
    "порту": "Porto",
    "париж": "Paris",
    "лондон": "London",
    "берлин": "Berlin",
    "мюнхен": "Munich",
    "франкфурт": "Frankfurt am Main",
    "гамбург": "Hamburg",
    "кёльн": "Cologne",
    "кельн": "Cologne",
    "дюссельдорф": "Dusseldorf",
    "вена": "Vienna",
    "цюрих": "Zurich",
    "женева": "Geneva",
    "милан": "Milan",
    "рим": "Rome",
    "венеция": "Venice",
    "неаполь": "Naples",
    "флоренция": "Florence",
    "амстердам": "Amsterdam",
    "брюссель": "Brussels",
    "прага": "Prague",
    "варшава": "Warsaw",
    "краков": "Krakow",
    "будапешт": "Budapest",
    "стамбул": "Istanbul",
    "афины": "Athens",
    "копенгаген": "Copenhagen",
    "стокгольм": "Stockholm",
    "осло": "Oslo",
    "хельсинки": "Helsinki",
    "дублин": "Dublin",
    "эдинбург": "Edinburgh",
    "москва": "Moscow",
    "санкт-петербург": "Saint Petersburg",
    "петербург": "Saint Petersburg",
    "спб": "Saint Petersburg",
    "сочи": "Sochi",
    "казань": "Kazan",
    "екатеринбург": "Yekaterinburg",
    "новосибирск": "Novosibirsk",
    "калининград": "Kaliningrad",
    "минск": "Minsk",
    "киев": "Kyiv",
    "тбилиси": "Tbilisi",
    "ереван": "Yerevan",
    "баку": "Baku",
    "алматы": "Almaty",
    "астана": "Astana",
    "ташкент": "Tashkent",
    "стамбул сабиха": "Istanbul",
    "дубай": "Dubai",
    "тель-авив": "Tel Aviv",
}


def _normalize(text: str) -> str:
    """Убирает диакритику и регистр, чтобы 'Málaga' совпало с 'malaga'."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, AirportRecord], dict[str, list[str]]]:
    """Читает data/airports.csv: индекс по IATA и индекс по нормализованным названиям."""
    path = plugin_root() / "data" / "airports.csv"
    by_iata: dict[str, AirportRecord] = {}
    by_name: dict[str, list[str]] = {}

    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = AirportRecord(
                iata=row["iata"],
                name=row["name"],
                city=row["city"],
                country=row["country"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                size=row["size"],
            )
            by_iata[record.iata] = record
            for key in filter(None, (_normalize(record.city), _normalize(record.name))):
                by_name.setdefault(key, []).append(record.iata)

    return by_iata, by_name


def get(iata: str) -> AirportRecord | None:
    by_iata, _ = _load()
    return by_iata.get(iata.strip().upper())


def _size_rank(record: AirportRecord) -> int:
    return {"L": 0, "M": 1, "S": 2}.get(record.size, 3)


def resolve(query: str, limit: int = 5) -> list[AirportRecord]:
    """Превращает 'Севилья', 'Seville' или 'SVQ' в записи аэропортов.

    Крупные аэропорты идут первыми: для города с несколькими аэропортами
    пользователь почти всегда имеет в виду главный.
    """
    by_iata, by_name = _load()
    raw = query.strip()

    if len(raw) == 3 and raw.upper() in by_iata:
        return [by_iata[raw.upper()]]

    key = _normalize(CITY_ALIASES.get(raw.lower(), raw))
    codes = list(by_name.get(key, []))

    if not codes:
        # Частичное совпадение: 'франкфурт' -> 'frankfurt am main'.
        for name_key, name_codes in by_name.items():
            if key and (name_key.startswith(key) or key in name_key.split()):
                codes.extend(name_codes)

    records = [by_iata[code] for code in dict.fromkeys(codes)]
    records.sort(key=lambda r: (_size_rank(r), r.iata))
    return records[:limit]


def distance_km(a: AirportRecord, b: AirportRecord) -> float:
    """Расстояние по большому кругу между аэропортами."""
    radius = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(h)), 1)


def nearby(iata: str, radius_km: int = 150, limit: int = 5, min_size: str = "M") -> list[dict]:
    """Аэропорты в радиусе от заданного, по возрастанию расстояния.

    min_size отсекает мелкие площадки: 'L' — только крупные, 'M' — крупные и средние.
    """
    by_iata, _ = _load()
    origin = by_iata.get(iata.strip().upper())
    if origin is None:
        return []

    allowed = {"L": {"L"}, "M": {"L", "M"}, "S": {"L", "M", "S"}}.get(min_size.upper(), {"L", "M"})
    found: list[dict] = []
    for record in by_iata.values():
        if record.iata == origin.iata or record.size not in allowed:
            continue
        dist = distance_km(origin, record)
        if dist <= radius_km:
            entry = record.to_dict()
            entry["distance_km"] = dist
            found.append(entry)

    found.sort(key=lambda r: r["distance_km"])
    return found[:limit]
