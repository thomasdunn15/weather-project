"""The Robinhood deep link is the one piece of the tab that fails SILENTLY.

Every other number on the tab comes from our own database and shows up wrong if
it breaks. A bad slug just renders a link that 404s when clicked, in the app,
mid-trade. The trap is that Robinhood formats the two date halves DIFFERENTLY:
the long half does not zero-pad the day, the short half does. Verified against
live pages 2026-08-31; the zero-padded long form returns 404.
"""
from datetime import date

from dashboard.data_forecastex import RH_CITY_SLUG, ROBINHOOD_CITIES, rh_url

BASE = "https://robinhood.com/us/en/prediction-markets/climate/events/"


def test_matches_verified_live_url():
    assert rh_url("KLAX", date(2026, 8, 31)) == (
        BASE + "los-angeles-daily-temperature-high-august-31-2026-aug-31-2026/")


def test_day_padding_is_asymmetric():
    """Long half `september-1`, short half `sep-01`. Both padded => 404."""
    url = rh_url("KLAX", date(2026, 9, 1))
    assert "-september-1-2026-" in url
    assert url.endswith("-sep-01-2026/")
    assert "september-01" not in url


def test_month_names_are_locale_independent():
    for m, long_, short in ((1, "january", "jan"), (9, "september", "sep"),
                            (12, "december", "dec")):
        url = rh_url("KMIA", date(2026, m, 15))
        assert url.endswith(f"-{long_}-15-2026-{short}-15-2026/")


def test_every_offered_city_has_a_slug():
    for station in ROBINHOOD_CITIES:
        assert RH_CITY_SLUG.get(station), station
        assert rh_url(station, date(2026, 8, 31)).startswith(BASE)


def test_unknown_station_is_none_not_a_broken_link():
    assert rh_url("KJFK", date(2026, 8, 31)) is None
