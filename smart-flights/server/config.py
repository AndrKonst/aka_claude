"""Профиль пользователя и настройки плагина smart-flights."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "currency": "EUR",
    "home_airports": ["SVQ"],
    "language": "ru",
    "country": "ES",
    "passengers": {"adults": 1, "children": 0, "infants_in_seat": 0, "infants_on_lap": 0},
    "baggage": {"checked_bags": 0, "carry_on": True},
    "nearby_radius_km": 150,
    "max_results": 10,
    "sources": {"google_flights": True, "aviasales": True},
    "aviasales_token": None,
}

CONFIG_FILENAME = "smart-flights.json"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    env_path = os.environ.get("SMART_FLIGHTS_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(Path.cwd() / ".claude" / CONFIG_FILENAME)
    paths.append(Path.home() / ".claude" / CONFIG_FILENAME)
    return paths


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class Profile:
    """Настройки поиска. Значения из файла перекрывают умолчания."""

    currency: str = "EUR"
    home_airports: list[str] = field(default_factory=lambda: ["SVQ"])
    language: str = "ru"
    country: str = "ES"
    passengers: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG["passengers"]))
    baggage: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG["baggage"]))
    nearby_radius_km: int = 150
    max_results: int = 10
    sources: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG["sources"]))
    aviasales_token: str | None = None
    config_path: str | None = None

    @property
    def has_aviasales_token(self) -> bool:
        return bool(self.aviasales_token)

    def to_dict(self) -> dict:
        data = asdict(self)
        # Токен наружу не отдаём — только факт его наличия.
        data.pop("aviasales_token", None)
        data["aviasales_token_configured"] = self.has_aviasales_token
        return data


def load_profile() -> Profile:
    """Собирает профиль: умолчания -> файл конфигурации -> переменные окружения."""
    data = dict(DEFAULT_CONFIG)
    used_path: str | None = None

    for path in _candidate_paths():
        if path.is_file():
            try:
                data = _deep_merge(data, json.loads(path.read_text(encoding="utf-8")))
                used_path = str(path)
                break
            except (json.JSONDecodeError, OSError):
                # Битый конфиг не должен ронять сервер — работаем на умолчаниях.
                continue

    token = (
        os.environ.get("AVIASALES_API_TOKEN")
        or os.environ.get("TRAVELPAYOUTS_TOKEN")
        or data.get("aviasales_token")
    )

    return Profile(
        currency=str(data.get("currency", "EUR")).upper(),
        home_airports=[str(a).upper() for a in data.get("home_airports", [])],
        language=data.get("language", "ru"),
        country=data.get("country", "ES"),
        passengers=data.get("passengers", dict(DEFAULT_CONFIG["passengers"])),
        baggage=data.get("baggage", dict(DEFAULT_CONFIG["baggage"])),
        nearby_radius_km=int(data.get("nearby_radius_km", 150)),
        max_results=int(data.get("max_results", 10)),
        sources=data.get("sources", dict(DEFAULT_CONFIG["sources"])),
        aviasales_token=token,
        config_path=used_path,
    )


def plugin_root() -> Path:
    """Корень плагина: из переменной окружения либо относительно этого файла."""
    env_root = os.environ.get("SMART_FLIGHTS_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent
