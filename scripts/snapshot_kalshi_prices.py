# scripts/snapshot_kalshi_prices.py
"""Snapshot current prices for every registered station's daily-high AND daily-low series.

Lows were added 2026-08-24. kalshi_series_low had been populated in stations.py
since the Polymarket commit but nothing ever read it here, so KXLOWT* price
collection died on 2026-06-07 with the NYC lows experiment and the market went
unobserved for 2.5 months. Research on the lows needs an unbroken price history,
and unlike a forecast backfill this one cannot be recovered after the fact —
Kalshi does not serve historical books.
"""
from weather_markets.kalshi import snapshot_kalshi_prices
from weather_markets.stations import all_stations


def main() -> None:
    for station in all_stations():
        # "" for stations with no market on that side (KMDW/KSFO have no Kalshi
        # high; several stations have no low series listed).
        for series in (station.kalshi_series, station.kalshi_series_low):
            if not series:
                continue
            try:
                result = snapshot_kalshi_prices(series_ticker=series)
                print(f"{station.station_id} / {series}: {result}")
            except Exception as e:
                print(f"  {station.station_id} / {series} snapshot raised: "
                      f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
