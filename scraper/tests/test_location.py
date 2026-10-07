import pytest

from scraper.models import Location
from scraper.normalize.location import parse_location


@pytest.mark.parametrize(
    ("raw", "country", "locs"),
    [
        ("Toronto, ON", "CA", [("Toronto", "ON", "CA")]),
        ("New York, NY", "US", [("New York", "NY", "US")]),
        ("London, ON", "CA", [("London", "ON", "CA")]),
        ("Toronto, ON; New York, NY", "BOTH", [("Toronto", "ON", "CA"), ("New York", "NY", "US")]),
        (
            "San Francisco, CA | Toronto, ON",
            "BOTH",
            [("San Francisco", "CA", "US"), ("Toronto", "ON", "CA")],
        ),
        ("Waterloo, Ontario, Canada", "CA", [("Waterloo", "ON", "CA")]),
        ("Seattle", "US", [("Seattle", "WA", "US")]),
        ("Hybrid - Vancouver, BC", "CA", [("Vancouver", "BC", "CA")]),
        ("Remote - Canada", "CA", [(None, None, "CA")]),
        ("Remote (US)", "US", [(None, None, "US")]),
        ("Remote, United States", "US", [(None, None, "US")]),
        ("Canada or United States", "BOTH", [(None, None, "CA"), (None, None, "US")]),
        (
            "New York, San Francisco, Seattle",
            "US",
            [("New York", "NY", "US"), ("San Francisco", "CA", "US"), ("Seattle", "WA", "US")],
        ),
        ("London, UK; Toronto, ON", "CA", [("Toronto", "ON", "CA")]),
    ],
)
def test_parse_known_locations(raw, country, locs):
    parsed = parse_location(raw)
    assert parsed.country == country
    assert parsed.locations == [Location(city=c, region=r, country=k) for c, r, k in locs]
    assert not parsed.foreign_only and not parsed.location_unclear


@pytest.mark.parametrize("raw", ["London, UK", "Bangalore, India", "Berlin, DE", "London"])
def test_foreign_only_locations_flagged(raw):
    parsed = parse_location(raw)
    assert parsed.foreign_only is True


def test_non_ca_us_country_hint_is_foreign():
    assert parse_location("", country_hint="GB").foreign_only is True
    assert parse_location("Remote", country_hint="OTHER").foreign_only is True


def test_bare_remote_is_unclear_without_hints():
    parsed = parse_location("Remote")
    assert parsed.country == "UNKNOWN"
    assert parsed.location_unclear is True
    assert parsed.work_mode == "remote"


def test_bare_remote_uses_country_hint_then_default():
    assert parse_location("Remote", country_hint="US").country == "US"
    assert parse_location("Remote", default_country="CA").country == "CA"


def test_work_modes():
    assert parse_location("Toronto, ON").work_mode == "onsite"
    assert parse_location("Toronto, ON (Hybrid)").work_mode == "hybrid"
    assert parse_location("Remote - US").work_mode == "remote"
    assert parse_location("Toronto, ON", work_mode_hint="remote").work_mode == "remote"
    assert parse_location("").work_mode == "unknown"


def test_unrecognised_city_is_not_given_the_company_default_country():
    parsed = parse_location("Gotham", default_country="US")
    assert parsed.country == "UNKNOWN" and parsed.location_unclear is True


@pytest.mark.parametrize("raw", ["Bucharest, Romania", "Prague", "Krakow, Poland", "Chennai"])
def test_more_foreign_cities(raw):
    assert parse_location(raw).foreign_only is True
