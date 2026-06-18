"""Regression: contract target_date must come from the ticker, not
occurrence_datetime.

2026-06-18 bug: target_date was derived from occurrence_datetime.date() (UTC).
For the "T"-prefixed western/central series (KXHIGHTPHX/TLV/TSEA/TDAL/TNOLA)
Kalshi sets occurrence_datetime to the settle day (event+1 in UTC), so every
such contract was stored one day late — silently joining backtests to the
wrong day's prices AND outcomes. The ticker date matches Kalshi's title and is
authoritative.
"""
from datetime import date

from weather_markets.kalshi import ticker_event_date


def test_eastern_city_ticker_date():
    assert ticker_event_date("KXHIGHCHI-26JUN15-B71.5") == date(2026, 6, 15)


def test_western_t_series_ticker_date():
    # The exact tickers that were +1: the ticker date is the event date.
    assert ticker_event_date("KXHIGHTPHX-26JUN15-B106.5") == date(2026, 6, 15)
    assert ticker_event_date("KXHIGHTLV-26JUN15-B100.5") == date(2026, 6, 15)
    assert ticker_event_date("KXHIGHTSEA-26JUN14-B75.5") == date(2026, 6, 14)
    assert ticker_event_date("KXHIGHTDAL-26JUN09-T97") == date(2026, 6, 9)


def test_all_months_and_threshold_tickers():
    assert ticker_event_date("KXHIGHNY-26MAR26-T80") == date(2026, 3, 26)
    assert ticker_event_date("KXHIGHMIA-26DEC01-B70.5") == date(2026, 12, 1)
    assert ticker_event_date("KXHIGHTNOLA-27JAN31-T95") == date(2027, 1, 31)
