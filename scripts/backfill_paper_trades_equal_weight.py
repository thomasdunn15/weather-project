"""Backfill paper trades using EQUAL-MODEL weighting (vs current member-flat).

The production backfill_paper_trades.py flattens 31 GEFS + 50 IFS members into
a single list, giving each model weight proportional to its member count. Adding
HRRR as a third deterministic model gives it 1/82 = 1.2% weight, which is why
the prior HRRR experiment (+3.07¢ → +3.19¢) showed no improvement.

This script tests an alternative: give each MODEL equal weight (1/3 each for
GEFS, IFS, HRRR). HRRR's signal then contributes 33%, not 1%. EMOS structure
and all filter logic are unchanged.

Example:
  uv run python scripts/backfill_paper_trades_equal_weight.py \\
      --start-date 2025-05-27 --end-date 2026-05-26 \\
      --init-hour 0 --decision-hour 14 --decision-minute 45 \\
      --model-source "EMOS combined-equal-weight 00Z (rolling 45d)"

Idempotent on (target_date, ticker, model_source). Distinct model_source label
keeps this experiment's rows separate from the production backfill's.
"""
import argparse
import math
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs_stats,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling_equal_weight, gaussian_to_bracket_probs


STATION_ID = "KNYC"
MODELS = ["gefs", "ifs", "hrrr"]  # all three for the equal-weight experiment

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
    snapshot_cutoff = datetime.combine(
        target_date, dtime(cfg.decision_hour, cfg.decision_minute), tzinfo=timezone.utc,
    )
    init_time = datetime(target_date.year, target_date.month, target_date.day,
                         cfg.init_hour, 0, tzinfo=timezone.utc)
    notes = f"equal-weight; as-of={snapshot_cutoff.isoformat()}"

    # 1. At least one model must have forecast data for this init.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecasts WHERE station_id = %s AND model = ANY(%s) AND init_time = %s LIMIT 1",
            (STATION_ID, MODELS, init_time),
        )
        if cur.fetchone() is None:
            return 0, "no_forecast"

    # 2. Combined ensemble stats under equal-model weighting.
    try:
        ensemble_mean, ensemble_std, n_members = compute_combined_daily_highs_stats(
            init_time, target_date, conn,
            station_id=STATION_ID, models=MODELS, weighting="equal_model",
        )
    except Exception:
        return 0, "no_forecast"
    if n_members < 2 or ensemble_std <= 0:
        return 0, "no_forecast"
    notes += f"; n_members={n_members}"

    # 3. Rolling EMOS fit on equal-weight training pairs.
    emos = fit_emos_rolling_equal_weight(
        target_date, conn,
        window_days=cfg.window_days, station_id=STATION_ID,
        models=MODELS, init_hour=cfg.init_hour,
    )
    if emos is None:
        return 0, "emos_none"
    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        return 0, "emos_none"
    emos_sigma = math.sqrt(emos_var)

    # 4. Contracts for the target date (KXHIGHNY only)
    contracts = fetch_contracts_for_date(target_date, conn, station_id=STATION_ID)
    contracts = [c for c in contracts if c["ticker"].startswith("KXHIGHNY")]
    if not contracts:
        return 0, "no_contracts"

    # 5. Prices at snapshot cutoff.
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

    # 6. Model probabilities.
    model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    # 7. Evaluate + insert.
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
    parser.add_argument("--init-hour", type=int, choices=[0, 12], default=0)
    parser.add_argument("--decision-hour", type=int, default=14)
    parser.add_argument("--decision-minute", type=int, default=45)
    parser.add_argument("--window-days", type=int, default=45)
    parser.add_argument("--edge-threshold", type=float, default=0.10)
    parser.add_argument("--model-source", required=True,
                        help="Distinct label, e.g. 'EMOS combined-equal-weight 00Z (rolling 45d)'.")
    args = parser.parse_args()

    print(f"Backfilling EQUAL-WEIGHT paper trades for {args.start_date} → {args.end_date}")
    print(f"  models:       {MODELS} (each gets equal weight in mean)")
    print(f"  init_hour:    {args.init_hour:02d}Z")
    print(f"  decision:     {args.decision_hour:02d}:{args.decision_minute:02d} UTC")
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
