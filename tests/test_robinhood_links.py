"""The Robinhood deep link is the one piece of the tab that fails SILENTLY.

Every other number on the tab comes from our own database and shows up wrong if
it breaks. A bad slug just renders a link that 404s when clicked, in the app,
mid-trade. The trap is that Robinhood formats the two date halves DIFFERENTLY:
the long half does not zero-pad the day, the short half does. Verified against
live pages 2026-08-31; the zero-padded long form returns 404.
"""
import pytest
from datetime import date

from dashboard.data_forecastex import ROBINHOOD_CITIES
from weather_markets.forecastex import RH_CITY_SLUG, rh_url

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


# --- tradeable edge -----------------------------------------------------------
# The strategy prices every signal off the last trade, and ForecastEx's own feed
# has no quotes to price it any other way. Robinhood's does, and on a wide market
# the two are far apart: UHMIA_090226_89 last-traded at 45c against a 51/59 book
# on 2026-09-02, so a +41% edge was +27% to anyone actually buying.
from weather_markets.forecastex import rh_url as _rh_url  # noqa: E402,F401
from dashboard.data_forecastex import tradeable  # noqa: E402


def test_yes_edge_is_measured_against_the_yes_ask():
    # model 86%, ask 59c -> +27%
    assert tradeable(0.86, "yes", 59) == pytest.approx(0.27)


def test_no_edge_uses_the_COMPLEMENT_of_the_model_probability():
    """Buying NO wins when the event does NOT happen; using p_model here would
    invert the sign of every NO pick."""
    assert tradeable(0.59, "no", 23) == pytest.approx(0.18)


def test_crossing_a_wide_spread_can_erase_the_edge():
    """A tape edge is not a tradeable edge. 70% model, 45c tape, 88c ask."""
    assert tradeable(0.70, "yes", 45) == pytest.approx(0.25)
    assert tradeable(0.70, "yes", 88) == pytest.approx(-0.18)


def test_no_book_is_none_not_zero():
    """None must not be mistaken for a zero edge — one is unknown, the other is
    a claim that the trade is exactly fair."""
    assert tradeable(0.86, "yes", None) is None
