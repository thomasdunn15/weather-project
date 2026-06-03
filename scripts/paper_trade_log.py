"""
Paper-trade log: once-daily prospective record of what the rolling-EMOS model
would trade in each registered city, captured BEFORE peak heating so the
market hasn't already converged on the observed high.

Runs at 14:45 UTC via cron (~45 min after Kalshi contracts open at 14:00,
~15 min after the discovery cron at 14:30, ~3 hours before peak heating).
Uses today's 00Z combined (GEFS + ECMWF) run as the forecast basis.

For each station in weather_markets.stations:
  1. Reads today's 00Z combined forecast.
  2. Fits rolling-window EMOS on the prior 45 days of (combined, observation) pairs.
  3. Compares model probability to current Kalshi market mid.
  4. INSERTs one row per contract where |edge| >= 0.10.

Per-station filter behavior:
  - KNYC keeps the pre-registered live filter (entry >= 60c) so the live
    cron's mirror remains intact for forward validation. Existing historical
    data was logged under this filter; keeping it preserves continuity.
  - All other stations are in RESEARCH MODE — no entry-price filter at logging.
    Entry filters can be applied post-hoc in analysis. This matches the
    backfill behavior and gives us unbiased data to evaluate cross-city.

Append-only — PK enforces one entry per (target_date, ticker, model_source);
re-runs are no-ops via ON CONFLICT DO NOTHING.

Skips a station with no row written when: today's 00Z forecast isn't in the
DB for that station, no contracts exist for today, rolling EMOS can't fit
(insufficient training data), or no contract has prices on both sides. One
station's skip never aborts the run for other stations.

Run with: uv run python scripts/paper_trade_log.py

If recovering from a missed cron run, use --as-of to set the price-snapshot
cutoff to when the cron *should* have fired. This faithfully reconstructs
the trade: same forecast, same contracts, same market state. Example:

    uv run python scripts/paper_trade_log.py --as-of 2026-05-27T14:45:00+00:00

Without --as-of, uses current time as the snapshot cutoff (normal cron behavior).
"""
import argparse
import math
import statistics
from datetime import datetime, timezone

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.stations import all_stations, Station


EDGE_THRESHOLD = 0.10
WINDOW_DAYS = 45
INIT_HOUR = 0          # use 00Z runs — published before market open
MODEL = "combined"     # GEFS + IFS at 00Z


def model_source_for(station: Station) -> str:
    """The model_source string for this station, matching the backfill naming."""
    if station.station_id == "KNYC":
        # NYC was the original, so its source string has no city tag.
        return "EMOS combined 00Z (rolling 45d)"
    return f"EMOS combined 00Z {station.city} (rolling 45d)"


def min_entry_price_for(station: Station) -> int:
    """The entry-price floor for this station's paper-trade logging.

    KNYC: pre-registered production filter (entry >= 60c). Backtest discovery
    on 2026-05-28 found this filter captures "agree with market direction,
    more confidently" trades and discards contrarian-bet failures.

    Other stations: research mode (entry >= 0). The cross-city study is
    ongoing; filter at analysis time, not log time, so all candidate trades
    are preserved for post-hoc evaluation."""
    return 60 if station.station_id == "KNYC" else 0


INSERT_SQL = """
    INSERT INTO paper_trades (
        logged_at, target_date, ticker, model_source,
        forecast_init_time, ensemble_mean, ensemble_std,
        emos_mu, emos_sigma, model_prob_yes,
        market_yes_bid, market_yes_ask, market_mid_prob, market_snapshot_at,
        edge, edge_threshold, position, entry_price_cents, notes
    ) VALUES (
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s
    )
    ON CONFLICT (target_date, ticker, model_source) DO NOTHING
"""


def log_for_station(
    station: Station,
    today: datetime,
    init_time: datetime,
    logged_at: datetime,
    snapshot_cutoff: datetime,
    as_of: datetime | None,
    conn,
) -> None:
    """Run paper-trade logic for one station. Prints a per-station summary.

    Any "skip" condition (missing forecast, no contracts, EMOS fit fails) is
    logged and returns without raising — other stations continue uninterrupted."""
    model_source = model_source_for(station)
    min_entry = min_entry_price_for(station)

    print(f"\n--- {station.station_id} ({station.city}) -> {model_source!r}, entry>={min_entry}c ---")

    if MODEL == "combined":
        models_list = ["gefs", "ifs"]
    elif MODEL == "combined_hrrr":
        models_list = ["gefs", "ifs", "hrrr"]
    else:
        models_list = [MODEL]

    # At least one underlying model must be present for today's init at this station.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecasts WHERE station_id = %s AND model = ANY(%s) AND init_time = %s LIMIT 1",
            (station.station_id, models_list, init_time),
        )
        if cur.fetchone() is None:
            print(f"  no {MODEL} forecast for init {init_time.isoformat()}. Skipping.")
            return

    # Combined ensemble for this station / today.
    ensemble_values = compute_combined_daily_highs(
        init_time, today, conn, station_id=station.station_id, models=models_list,
    )
    n_members = len(ensemble_values)
    if n_members < 2:
        print(f"  combined ensemble has {n_members} members; skipping.")
        return
    ensemble_mean = statistics.mean(ensemble_values)
    ensemble_std = statistics.stdev(ensemble_values)

    # Rolling EMOS fit on prior days for this station.
    emos = fit_emos_rolling(
        today, conn,
        window_days=WINDOW_DAYS, station_id=station.station_id,
        model=MODEL, init_hour=INIT_HOUR,
    )
    if emos is None:
        print(f"  rolling EMOS returned None (< 30 training days). Skipping.")
        return

    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        print(f"  EMOS variance non-positive ({emos_var}). Skipping.")
        return
    emos_sigma = math.sqrt(emos_var)

    contracts = fetch_contracts_for_date(
        today, conn, station_id=station.station_id, series=station.kalshi_series,
    )
    if not contracts:
        print(f"  no contracts found for {today}. Skipping.")
        return

    tickers = [c["ticker"] for c in contracts]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
            FROM prices WHERE ticker = ANY(%s) AND snapshot_at <= %s
            ORDER BY ticker, snapshot_at DESC
            """,
            (tickers, snapshot_cutoff),
        )
        prices = {t: (b, a, s) for t, b, a, s in cur.fetchall()}

    model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    notes = f"ensemble_members={n_members}"
    if as_of is not None:
        notes += f"; as-of-recovery={snapshot_cutoff.isoformat()}"

    print(f"  forecast init: {init_time.isoformat()}")
    print(f"  ensemble:      n={n_members}  mean={ensemble_mean:.2f}°F  std={ensemble_std:.2f}°F")
    print(f"  EMOS μ/σ:      {emos_mu:.2f}° / {emos_sigma:.2f}°")
    print(f"  EMOS train:    {emos['train_start']} → {emos['train_end']} ({emos['n_train_days_used']} days)")

    n_checked = 0
    trades_logged = []
    with conn.cursor() as cur:
        for contract in contracts:
            ticker = contract["ticker"]
            bid_ask = prices.get(ticker)
            if bid_ask is None:
                continue
            bid, ask, snap = bid_ask
            if bid is None or ask is None:
                continue
            n_checked += 1

            market_mid = (bid + ask) / 200.0
            model_p = model_probs[ticker]
            edge = model_p - market_mid

            if abs(edge) < EDGE_THRESHOLD:
                continue

            if edge > 0:
                position = "BUY_YES"
                entry_price = ask
            else:
                position = "BUY_NO"
                entry_price = 100 - bid

            if entry_price < min_entry:
                continue

            cur.execute(
                INSERT_SQL,
                (
                    logged_at, today, ticker, model_source,
                    init_time, ensemble_mean, ensemble_std,
                    emos_mu, emos_sigma, model_p,
                    bid, ask, market_mid, snap,
                    edge, EDGE_THRESHOLD, position, entry_price, notes,
                ),
            )
            spread = ask - bid
            limit_target = entry_price - max(0, spread - 1)
            trades_logged.append((ticker, position, edge, entry_price, limit_target, model_p, market_mid))

    print(f"  contracts with prices: {n_checked}")
    print(f"  trades logged: {len(trades_logged)}")
    for ticker, pos, e, entry, lim, mp, mm in trades_logged:
        print(f"    {ticker:30s} {pos:8s}  model={mp:.3f}  market={mm:.3f}  edge={e:+.3f}  entry(cross)={entry}¢ limit(post)={lim}¢")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--as-of",
        type=lambda s: datetime.fromisoformat(s),
        default=None,
        help="ISO timestamp to use as the price-snapshot cutoff (e.g., '2026-05-27T14:45:00+00:00'). "
             "Used for recovering missed cron runs. Defaults to current time.",
    )
    args = parser.parse_args()

    logged_at = datetime.now(tz=timezone.utc)
    snapshot_cutoff = args.as_of if args.as_of is not None else logged_at
    today = snapshot_cutoff.date()
    init_time = datetime(today.year, today.month, today.day, INIT_HOUR, 0, tzinfo=timezone.utc)

    print(f"Paper-trade log for {today} (logged_at={logged_at.isoformat()})")
    if args.as_of is not None:
        print(f"  as-of recovery: prices and trade-decision moment set to {snapshot_cutoff.isoformat()}")

    with get_connection() as conn:
        for station in all_stations():
            try:
                log_for_station(
                    station, today, init_time, logged_at, snapshot_cutoff, args.as_of, conn,
                )
            except Exception as e:
                # One station's failure must not abort the others.
                print(f"  {station.station_id} raised: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
