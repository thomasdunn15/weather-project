"""Backfill paper trades for KXLOWTNYC (NYC daily-low contracts) with day-ahead
decision architecture.

Different from backfill_paper_trades.py (highs) in three ways:
  1. Decision time is the PRIOR DAY at decision_hour UTC. We "decide" tomorrow's
     low using today's 00Z forecast.
  2. Init time for the forecast is (target_date - 1) at 00Z. Forecast hours
     [30, 33, 36] correspond to early-morning hours on target_date.
  3. Aggregator is compute_combined_daily_lows (MIN of instantaneous temps at
     morning forecast hours) instead of compute_combined_daily_highs.

The market for KXLOWTNYC-{target_date} opens at 14:00 UTC on (target_date - 1).
A decision at 14:45 UTC same day-prior is comparable to the highs strategy's
14:45 UTC day-of decision in that both fire 45 minutes after market open.

Example (default config — combined GEFS+IFS):
  uv run python scripts/backfill_paper_trades_lows.py \\
      --start-date 2025-12-15 --end-date 2026-05-28 \\
      --model combined \\
      --decision-hour 14 --decision-minute 45 \\
      --model-source "EMOS combined day-ahead lows (rolling 45d)"

Days with missing forecast, no contracts, no priced contracts, or insufficient
training data are skipped silently. Idempotent on
(target_date, ticker, model_source).
"""
import argparse
import math
import statistics
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_lows,
    fetch_contracts_for_date,
    DEFAULT_LOW_FORECAST_HOURS,
)
from weather_markets.emos import fit_emos_rolling_for_lows, gaussian_to_bracket_probs
from weather_markets.stations import get as get_station

INSERT_SQL = """
    INSERT INTO paper_trades (
        logged_at, target_date, ticker, model_source,
        forecast_init_time, ensemble_mean, ensemble_std,
        emos_mu, emos_sigma, model_prob_yes,
        market_yes_bid, market_yes_ask, market_mid_prob, market_snapshot_at,
        edge, edge_threshold, position, entry_price_cents, notes
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (target_date, ticker, model_source) DO NOTHING
"""


def run_for_date(target_date: date, conn, logged_at: datetime, cfg) -> tuple[int, str]:
    """Run paper-trade logic for one target_date (the day whose low we're trading).

    Decision happens the PRIOR day at cfg.decision_hour:cfg.decision_minute UTC.
    """
    decision_date = target_date - timedelta(days=1)
    snapshot_cutoff = datetime.combine(
        decision_date, dtime(cfg.decision_hour, cfg.decision_minute), tzinfo=timezone.utc,
    )
    # Forecast init = decision_date's 00Z (i.e., prior day 00Z).
    init_time = datetime(decision_date.year, decision_date.month, decision_date.day,
                         0, 0, tzinfo=timezone.utc)
    notes = f"day-ahead-low; decision={snapshot_cutoff.isoformat()}"

    # Translate --model into actual model names
    if cfg.model == "combined":
        models_list = ["gefs", "ifs"]
    elif cfg.model == "combined_hrrr":
        models_list = ["gefs", "ifs", "hrrr"]
    else:
        models_list = [cfg.model]

    # 1. At least one underlying model must have data at the morning forecast hours
    forecast_hours = tuple(cfg.forecast_hours)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM forecasts
            WHERE station_id = %s AND model = ANY(%s) AND init_time = %s
              AND temperature_f IS NOT NULL
              AND EXTRACT(EPOCH FROM (valid_time - init_time))/3600 = ANY(%s)
            LIMIT 1
            """,
            (cfg.station_id, models_list, init_time, list(forecast_hours)),
        )
        if cur.fetchone() is None:
            return 0, "no_forecast"

    # 2. Ensemble of morning-low predictions
    try:
        ensemble_values = compute_combined_daily_lows(
            init_time, target_date, conn,
            station_id=cfg.station_id, models=models_list,
            forecast_hours=forecast_hours,
        )
    except Exception:
        return 0, "no_forecast"
    n_members = len(ensemble_values)
    if n_members < 2:
        return 0, "no_forecast"
    ensemble_mean = statistics.mean(ensemble_values)
    ensemble_std = statistics.stdev(ensemble_values)
    notes += f"; ensemble_members={n_members}"

    # 3. Rolling EMOS calibrated on (predicted_low, observed_low) pairs
    emos = fit_emos_rolling_for_lows(
        target_date, conn,
        window_days=cfg.window_days, station_id=cfg.station_id,
        model=cfg.model,
    )
    if emos is None:
        return 0, "emos_none"
    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        return 0, "emos_none"
    emos_sigma = math.sqrt(emos_var)

    # 4. KXLOWT* contracts for the target_date (explicit series override —
    # fetch_contracts_for_date defaults to KXHIGHNY for the production highs flow).
    station = get_station(cfg.station_id)
    contracts = fetch_contracts_for_date(target_date, conn, station_id=cfg.station_id,
                                         series=station.kalshi_series_low)
    if not contracts:
        return 0, "no_contracts"

    # 5. Prices at snapshot cutoff
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

    # 6. Model probabilities (Gaussian → bracket)
    model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    # 7. Evaluate and insert
    n_logged = 0
    n_priced = 0
    with conn.cursor() as cur:
        for contract in contracts:
            ticker = contract["ticker"]
            bid_ask = prices.get(ticker)
            if bid_ask is None:
                continue
            bid, ask, snap = bid_ask
            if bid is None or ask is None:
                continue
            n_priced += 1
            market_mid = (bid + ask) / 200.0
            model_p = model_probs[ticker]
            edge = model_p - market_mid
            if abs(edge) < cfg.edge_threshold:
                continue
            if edge > 0:
                position, entry_price = "BUY_YES", ask
            else:
                position, entry_price = "BUY_NO", 100 - bid
            cur.execute(
                INSERT_SQL,
                (
                    logged_at, target_date, ticker, cfg.model_source,
                    init_time, ensemble_mean, ensemble_std,
                    emos_mu, emos_sigma, model_p,
                    bid, ask, market_mid, snap,
                    edge, cfg.edge_threshold, position, entry_price, notes,
                ),
            )
            n_logged += 1

    if n_priced == 0:
        return 0, "no_priced"
    return n_logged, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True)
    parser.add_argument("--end-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True)
    parser.add_argument("--model", choices=["combined", "gefs", "ifs", "combined_hrrr"], default="combined",
                        help="Ensemble source for daily-low forecasts.")
    parser.add_argument("--decision-hour", type=int, default=14,
                        help="UTC hour the simulated day-ahead trade decision is made.")
    parser.add_argument("--decision-minute", type=int, default=45,
                        help="UTC minute of the simulated trade decision.")
    parser.add_argument("--window-days", type=int, default=45,
                        help="Rolling EMOS training window length.")
    parser.add_argument("--edge-threshold", type=float, default=0.10,
                        help="Minimum |edge| to log a paper trade.")
    parser.add_argument("--model-source", required=True,
                        help="Label written to paper_trades.model_source (PK component). "
                             "Use a distinct label from any KXHIGHNY backfill.")
    parser.add_argument("--station-id", default="KNYC",
                        help="Station to backfill (e.g. KORD, KMIA). Determines which "
                             "KXLOWT* series to query. Default: KNYC.")
    parser.add_argument("--forecast-hours", type=lambda s: tuple(int(x) for x in s.split(",")),
                        default=DEFAULT_LOW_FORECAST_HOURS,
                        help="Comma-separated forecast hours (from prior-day 00Z init) "
                             "used for the MIN-based daily-low ensemble. "
                             f"Default: {','.join(str(h) for h in DEFAULT_LOW_FORECAST_HOURS)}. "
                             "Try '24,27,30,33,36,39' for wider overnight window.")
    args = parser.parse_args()

    print(f"Backfilling {get_station(args.station_id).kalshi_series_low} day-ahead paper trades "
          f"for {args.start_date} → {args.end_date}")
    print(f"  model:        {args.model}")
    print(f"  decision:     prior-day {args.decision_hour:02d}:{args.decision_minute:02d} UTC")
    print(f"  window:       {args.window_days} days, edge ≥ {args.edge_threshold}")
    print(f"  model_source: {args.model_source}")

    logged_at = datetime.now(tz=timezone.utc)
    stats = {"ok": 0, "no_forecast": 0, "no_contracts": 0, "emos_none": 0, "no_priced": 0}
    total_trades = 0
    t0 = time.time()

    with get_connection() as conn:
        current = args.start_date
        i = 0
        total = (args.end_date - args.start_date).days + 1
        while current <= args.end_date:
            i += 1
            n_trades, status = run_for_date(current, conn, logged_at, args)
            stats[status] += 1
            total_trades += n_trades
            if i % 30 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (total - i) / rate
                print(
                    f"  [{i}/{total}] {current}: {status} (+{n_trades} trades) "
                    f"| total trades: {total_trades}, {elapsed:.0f}s elapsed, ETA {eta:.0f}s",
                    flush=True,
                )
            current += timedelta(days=1)

    elapsed = time.time() - t0
    print(f"\n=== Done in {elapsed/60:.1f} min ===")
    print(f"  total trades inserted: {total_trades}")
    print(f"  days with trades:      {stats['ok']}")
    print(f"  no forecast:           {stats['no_forecast']}")
    print(f"  no contracts:          {stats['no_contracts']}")
    print(f"  EMOS unfittable:       {stats['emos_none']}")
    print(f"  no priced contracts:   {stats['no_priced']}")


if __name__ == "__main__":
    main()
