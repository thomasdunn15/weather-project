"""Backfill historical paper trades by simulating what the cron would have
logged on each day in the given range. Configuration is fully CLI-driven so
the same script can backfill any (model, init_hour, decision_time, threshold,
model_source) combination.

Examples:

  # ECMWF 00Z @ 14:45 (current production)
  uv run python scripts/backfill_paper_trades.py \\
      --start-date 2025-05-27 --end-date 2026-05-26 \\
      --model ifs --init-hour 0 \\
      --decision-hour 14 --decision-minute 45 \\
      --model-source "EMOS ECMWF 00Z (rolling 45d)"

  # Combined 12Z @ 18:45 (the abandoned late-trading regime)
  uv run python scripts/backfill_paper_trades.py \\
      --start-date 2025-05-27 --end-date 2026-05-26 \\
      --model combined --init-hour 12 \\
      --decision-hour 18 --decision-minute 45 \\
      --model-source "EMOS combined (rolling 45d)"

Days with missing forecast, no contracts, or insufficient training data are
skipped silently. Idempotent via the paper_trades PK
(target_date, ticker, model_source).
"""
import argparse
import math
import statistics
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs


STATION_ID = "KNYC"

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
    """Run paper-trade logic for one date. Returns (n_trades_logged, status)."""
    snapshot_cutoff = datetime.combine(
        target_date, dtime(cfg.decision_hour, cfg.decision_minute), tzinfo=timezone.utc,
    )
    init_time = datetime(target_date.year, target_date.month, target_date.day,
                         cfg.init_hour, 0, tzinfo=timezone.utc)
    notes = f"as-of-recovery={snapshot_cutoff.isoformat()}"

    # Translate --model into (models_list_for_ensemble, model_for_emos)
    if cfg.model == "combined":
        models_list = ["gefs", "ifs"]
    else:
        models_list = [cfg.model]

    # 1. At least one of the underlying model forecasts must be present.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecasts WHERE station_id = %s AND model = ANY(%s) AND init_time = %s LIMIT 1",
            (STATION_ID, models_list, init_time),
        )
        if cur.fetchone() is None:
            return 0, "no_forecast"

    # 2. Ensemble
    try:
        ensemble_values = compute_combined_daily_highs(
            init_time, target_date, conn, station_id=STATION_ID, models=models_list,
        )
    except Exception:
        return 0, "no_forecast"
    n_members = len(ensemble_values)
    if n_members < 2:
        return 0, "no_forecast"
    ensemble_mean = statistics.mean(ensemble_values)
    ensemble_std = statistics.stdev(ensemble_values)
    notes += f"; ensemble_members={n_members}"

    # 3. Rolling EMOS
    emos = fit_emos_rolling(
        target_date, conn,
        window_days=cfg.window_days, station_id=STATION_ID,
        model=cfg.model, init_hour=cfg.init_hour,
    )
    if emos is None:
        return 0, "emos_none"
    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        return 0, "emos_none"
    emos_sigma = math.sqrt(emos_var)

    # 4. Contracts
    contracts = fetch_contracts_for_date(target_date, conn, station_id=STATION_ID)
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

    # 6. Model probs
    model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    # 7. Evaluate + insert
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
    parser.add_argument("--model", choices=["combined", "gefs", "ifs"], default="ifs",
                        help="Ensemble source for EMOS fit and ensemble computation.")
    parser.add_argument("--init-hour", type=int, choices=[0, 12], default=0,
                        help="Forecast init hour UTC (must match available forecast data).")
    parser.add_argument("--decision-hour", type=int, default=14,
                        help="UTC hour the simulated trade decision is made (price snapshot cutoff).")
    parser.add_argument("--decision-minute", type=int, default=45,
                        help="UTC minute of the simulated trade decision.")
    parser.add_argument("--window-days", type=int, default=45,
                        help="Rolling EMOS training window length.")
    parser.add_argument("--edge-threshold", type=float, default=0.10,
                        help="Minimum |edge| to log a paper trade.")
    parser.add_argument("--model-source", required=True,
                        help="Label written to paper_trades.model_source (PK component). "
                             "Different configs MUST use different labels — never pool configs.")
    args = parser.parse_args()

    print(f"Backfilling paper trades for {args.start_date} → {args.end_date}")
    print(f"  model:        {args.model}")
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
