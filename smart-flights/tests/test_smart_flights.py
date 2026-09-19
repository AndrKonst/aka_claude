"""Оффлайн-тесты: логика, не требующая сети.

Запуск: .venv/bin/python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import airports  # noqa: E402
import baggage  # noqa: E402
import deeplinks  # noqa: E402
import ranking  # noqa: E402
from config import DEFAULT_CONFIG, load_profile  # noqa: E402


def offer(**kwargs):
    """Предложение с разумными умолчаниями — в тесте задаём только значимое."""
    base = {
        "id": "test",
        "source": "google_flights",
        "price": 100.0,
        "currency": "EUR",
        "duration_min": 120,
        "stops": 0,
        "segments": [{
            "origin": "SVQ", "destination": "BCN", "airline_code": "VY",
            "flight_number": "2221",
            "departure": "2026-10-14T10:00:00", "arrival": "2026-10-14T12:00:00",
        }],
        "layovers": [],
    }
    base.update(kwargs)
    return base


class TestAirports(unittest.TestCase):
    def test_resolves_russian_city_name(self):
        self.assertEqual(airports.resolve("Севилья")[0].iata, "SVQ")

    def test_resolves_iata_code_directly(self):
        self.assertEqual(airports.resolve("BCN")[0].iata, "BCN")

    def test_diacritics_are_ignored(self):
        self.assertEqual(airports.resolve("Malaga")[0].iata, "AGP")

    def test_multi_airport_city_lists_large_first(self):
        codes = [r.iata for r in airports.resolve("Москва")]
        self.assertIn("SVO", codes)
        self.assertGreater(len(codes), 1)

    def test_unknown_place_returns_nothing(self):
        self.assertEqual(airports.resolve("Ктулхуград"), [])

    def test_nearby_finds_closer_airport_first(self):
        found = airports.nearby("SVQ", 200)
        self.assertEqual(found[0]["iata"], "XRY")
        self.assertLess(found[0]["distance_km"], found[-1]["distance_km"])

    def test_nearby_respects_radius(self):
        self.assertEqual(airports.nearby("SVQ", 10), [])


class TestBaggage(unittest.TestCase):
    def test_low_cost_carry_on_costs_more_than_network(self):
        ryanair = baggage.apply(offer(price=47.0, segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "FR"}]), {"carry_on": True})
        vueling = baggage.apply(offer(price=53.0, segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY"}]), {"carry_on": True})
        self.assertGreater(ryanair["total_price"], vueling["total_price"])

    def test_no_baggage_means_no_surcharge(self):
        result = baggage.apply(offer(price=47.0), {"checked_bags": 0, "carry_on": False})
        self.assertEqual(result["baggage_fee"], 0.0)
        self.assertEqual(result["total_price"], 47.0)

    def test_return_direction_is_charged_too(self):
        one_way = baggage.apply(offer(price=100.0, segments=[{"origin": "SVQ", "destination": "BER", "airline_code": "FR"}]), {"checked_bags": 1})
        round_trip = baggage.apply(offer(
            price=100.0,
            segments=[{"origin": "SVQ", "destination": "BER", "airline_code": "FR"}],
            return_segments=[{"origin": "BER", "destination": "SVQ", "airline_code": "FR"}],
        ), {"checked_bags": 1})
        self.assertEqual(round_trip["baggage_fee"], one_way["baggage_fee"] * 2)

    def test_unknown_airline_falls_back_and_says_so(self):
        result = baggage.apply(offer(segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "ZZ"}]), {"checked_bags": 1})
        self.assertGreater(result["baggage_fee"], 0)
        self.assertIn("неизвестна", result["baggage_note"])

    def test_missing_price_leaves_total_empty(self):
        result = baggage.apply(offer(price=None), {"checked_bags": 1})
        self.assertIsNone(result["total_price"])


class TestRankingWeights(unittest.TestCase):
    def test_weights_normalize_to_one(self):
        weights = ranking.normalize_weights({"price": 3, "duration": 1})
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_unmentioned_axes_are_zeroed(self):
        self.assertEqual(ranking.normalize_weights({"price": 1})["stops"], 0.0)

    def test_empty_weights_fall_back_to_defaults(self):
        self.assertEqual(ranking.normalize_weights(None), ranking.DEFAULT_WEIGHTS)

    def test_negative_weight_is_clamped(self):
        self.assertEqual(ranking.normalize_weights({"price": 1, "duration": -5})["duration"], 0.0)


class TestRankingScore(unittest.TestCase):
    def test_cheaper_wins_when_price_dominates(self):
        result = ranking.rank(
            [offer(id="cheap", price=50.0), offer(id="pricey", price=200.0)],
            {"price": 1.0},
        )
        self.assertEqual(result["ranked"][0]["id"], "cheap")

    def test_total_price_beats_base_price(self):
        """Дешёвый тариф с дорогим багажом должен проиграть."""
        # FR: 47 + 45 за багаж = 92. VY: 50 + 35 = 85. По тарифу дешевле FR, по факту — VY.
        cheap_fare = baggage.apply(offer(id="fr", price=47.0, segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "FR"}]), {"checked_bags": 1})
        fair_fare = baggage.apply(offer(id="vy", price=50.0, segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY"}]), {"checked_bags": 1})
        self.assertLess(fair_fare["total_price"], cheap_fare["total_price"])
        result = ranking.rank([cheap_fare, fair_fare], {"price": 1.0})
        self.assertEqual(result["ranked"][0]["id"], "vy")

    def test_tiny_difference_does_not_decide(self):
        """Пять минут разницы не должны растягиваться на целый балл."""
        result = ranking.rank(
            [offer(id="a", duration_min=120), offer(id="b", duration_min=125)],
            {"duration": 1.0},
        )
        self.assertEqual(result["ranked"][0]["score"], result["ranked"][1]["score"])

    def test_night_departure_is_penalized(self):
        night = offer(id="night", segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY", "departure": "2026-10-14T03:00:00", "arrival": "2026-10-14T05:00:00"}])
        day = offer(id="day", segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY", "departure": "2026-10-14T10:00:00", "arrival": "2026-10-14T12:00:00"}])
        result = ranking.rank([night, day], {"convenience": 1.0})
        self.assertEqual(result["ranked"][0]["id"], "day")
        self.assertTrue(result["ranked"][1]["comfort_notes"])

    def test_time_is_read_from_segments_without_top_level_field(self):
        night = offer(id="n", segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY", "departure": "2026-10-14T03:00:00", "arrival": "2026-10-14T05:00:00"}])
        self.assertEqual(ranking.departure_of(night), "2026-10-14T03:00:00")


class TestRankingReliability(unittest.TestCase):
    def test_short_layover_is_penalized(self):
        tight = offer(id="tight", stops=1, layovers=[{"airport": "BCN", "duration_min": 30}])
        roomy = offer(id="roomy", stops=1, layovers=[{"airport": "BCN", "duration_min": 120}])
        result = ranking.rank([tight, roomy], {"reliability": 1.0})
        self.assertEqual(result["ranked"][0]["id"], "roomy")
        self.assertTrue(result["ranked"][1]["risk_notes"])

    def test_airport_change_raises_required_connection_time(self):
        same = ranking.required_mct(offer(), {"airport": "BCN", "duration_min": 60})
        changed = ranking.required_mct(offer(), {"airport": "BCN", "duration_min": 60, "change_of_airport": True})
        self.assertGreater(changed, same)

    def test_self_transfer_adds_margin_and_penalty(self):
        plain = ranking.required_mct(offer(), {"airport": "BCN", "duration_min": 60})
        risky = ranking.required_mct(offer(self_transfer=True), {"airport": "BCN", "duration_min": 60})
        self.assertEqual(risky, plain + ranking.MCT_SELF_TRANSFER_EXTRA)

    def test_international_connection_needs_more_time(self):
        domestic = offer(segments=[
            {"origin": "SVQ", "destination": "MAD", "airline_code": "IB"},
            {"origin": "MAD", "destination": "BCN", "airline_code": "IB"},
        ])
        international = offer(segments=[
            {"origin": "SVQ", "destination": "MAD", "airline_code": "IB"},
            {"origin": "MAD", "destination": "BER", "airline_code": "IB"},
        ])
        self.assertLess(
            ranking.required_mct(domestic, {"airport": "MAD", "duration_min": 60}),
            ranking.required_mct(international, {"airport": "MAD", "duration_min": 60}),
        )


class TestRankingConstraints(unittest.TestCase):
    def test_violator_is_excluded_with_reason(self):
        result = ranking.rank([offer(price=500.0)], {"price": 1.0}, {"max_price": 100})
        self.assertEqual(result["ranked"], [])
        self.assertIn("выше лимита", result["excluded"][0]["violations"][0])

    def test_late_arrival_is_rejected(self):
        late = offer(segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "VY", "departure": "2026-10-14T08:00:00", "arrival": "2026-10-14T12:00:00"}])
        result = ranking.rank([late], constraints={"arrive_before": "2026-10-14T09:00:00"})
        self.assertEqual(len(result["excluded"]), 1)

    def test_excluded_airline_is_filtered(self):
        result = ranking.rank(
            [offer(airlines=["FR"], segments=[{"origin": "SVQ", "destination": "BCN", "airline_code": "FR"}])],
            constraints={"exclude_airlines": ["fr"]},
        )
        self.assertEqual(len(result["excluded"]), 1)

    def test_baggage_requirement_rejects_bare_fare(self):
        result = ranking.rank([offer(price_includes_baggage=False)], constraints={"require_baggage": True})
        self.assertEqual(len(result["excluded"]), 1)

    def test_nothing_passes_so_excluded_are_still_scored(self):
        """Пустая выдача бесполезна: отклонённые всё равно должны быть отсортированы."""
        result = ranking.rank([offer(price=500.0), offer(price=300.0)], {"price": 1.0}, {"max_price": 100})
        self.assertEqual(len(result["excluded"]), 2)
        self.assertGreaterEqual(result["excluded"][0]["score"], result["excluded"][1]["score"])


class TestDeeplinks(unittest.TestCase):
    def test_known_low_cost_gets_dated_search_link(self):
        link = deeplinks.airline_link("FR", "SVQ", "BCN", "2026-10-14")
        self.assertEqual(link["precision"], "search")
        self.assertIn("2026-10-14", link["url"])

    def test_unmapped_airline_falls_back_to_homepage(self):
        link = deeplinks.airline_link("IB", "SVQ", "BCN", "2026-10-14")
        self.assertEqual(link["precision"], "home")

    def test_unknown_code_gives_no_link(self):
        self.assertIsNone(deeplinks.airline_link("ZZ", "SVQ", "BCN", "2026-10-14"))

    def test_aviasales_link_encodes_dates_as_ddmm(self):
        link = deeplinks.aviasales_link("SVQ", "BER", "2026-10-04", "2026-10-15", 1)
        self.assertIn("SVQ0410BER15101", link["url"])

    def test_route_always_gets_both_aggregators(self):
        links = deeplinks.build_links(offer())
        labels = [link["label"] for link in links]
        self.assertIn("Aviasales", labels)
        self.assertIn("Google Flights", labels)

    def test_each_airline_appears_once(self):
        two_legs = offer(segments=[
            {"origin": "SVQ", "destination": "BCN", "airline_code": "VY", "departure": "2026-10-14T10:00:00"},
            {"origin": "BCN", "destination": "BER", "airline_code": "VY", "departure": "2026-10-14T14:00:00"},
        ])
        vueling_links = [l for l in deeplinks.build_links(two_legs) if l["label"] == "Vueling"]
        self.assertEqual(len(vueling_links), 1)

    def test_repeated_build_does_not_duplicate_links(self):
        """Предложение уже несёт ссылки — повторный вызов не должен их размножать."""
        data = offer()
        first = deeplinks.build_links(data)
        data["booking_links"] = first
        second = deeplinks.build_links(data)
        self.assertEqual(len(first), len(second))
        self.assertEqual(len({l["url"] for l in second}), len(second))

    def test_offer_without_segments_yields_nothing(self):
        self.assertEqual(deeplinks.build_links({"segments": []}), [])


class TestProfile(unittest.TestCase):
    def test_defaults_match_declared_profile(self):
        profile = load_profile()
        self.assertEqual(profile.currency, DEFAULT_CONFIG["currency"])
        self.assertEqual(profile.home_airports, DEFAULT_CONFIG["home_airports"])

    def test_token_never_leaves_in_plain_text(self):
        profile = load_profile()
        profile.aviasales_token = "secret-token"
        exported = profile.to_dict()
        self.assertNotIn("secret-token", str(exported))
        self.assertTrue(exported["aviasales_token_configured"])


if __name__ == "__main__":
    unittest.main()
