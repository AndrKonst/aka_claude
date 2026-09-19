"""Единая модель предложения, к которой приводятся все источники."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Segment:
    """Один перелёт: посадка в самолёт и высадка."""

    origin: str
    destination: str
    departure: str | None = None  # ISO 8601, местное время вылета
    arrival: str | None = None    # ISO 8601, местное время прилёта
    duration_min: int | None = None
    airline_code: str | None = None
    airline_name: str | None = None
    flight_number: str | None = None
    operating_airline_code: str | None = None
    aircraft: str | None = None
    overnight: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LayoverInfo:
    """Пересадка между двумя сегментами."""

    airport: str
    duration_min: int
    change_of_airport: bool = False
    overnight: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BookingLink:
    """Куда идти покупать."""

    label: str
    url: str
    kind: str  # airline | aggregator | segment
    price: float | None = None
    currency: str | None = None
    is_airline_direct: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Offer:
    """Вариант перелёта, приведённый к общему виду."""

    id: str
    source: str  # google_flights | aviasales
    price: float | None
    currency: str
    duration_min: int | None
    stops: int
    segments: list[Segment] = field(default_factory=list)
    layovers: list[LayoverInfo] = field(default_factory=list)
    return_segments: list[Segment] = field(default_factory=list)
    return_layovers: list[LayoverInfo] = field(default_factory=list)
    price_includes_baggage: bool = False
    self_transfer: bool = False
    baggage_note: str | None = None
    price_age_days: int | None = None  # только у кэшированных цен Aviasales
    booking_links: list[BookingLink] = field(default_factory=list)
    booking_token: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def origin(self) -> str | None:
        return self.segments[0].origin if self.segments else None

    @property
    def destination(self) -> str | None:
        return self.segments[-1].destination if self.segments else None

    @property
    def departure(self) -> str | None:
        return self.segments[0].departure if self.segments else None

    @property
    def arrival(self) -> str | None:
        return self.segments[-1].arrival if self.segments else None

    @property
    def airlines(self) -> list[str]:
        seen: list[str] = []
        for seg in self.segments + self.return_segments:
            code = seg.airline_code
            if code and code not in seen:
                seen.append(code)
        return seen

    def to_dict(self) -> dict:
        data = asdict(self)
        data["origin"] = self.origin
        data["destination"] = self.destination
        data["departure"] = self.departure
        data["arrival"] = self.arrival
        data["airlines"] = self.airlines
        return data
