"""
Paper-trade log: once-daily prospective record of what the rolling-EMOS model
would trade, captured BEFORE NYC peak heating so the market hasn't already
converged on the observed high.

Runs at 14:45 UTC via cron (~45 min after Kalshi NYC contracts open at 14:00,
~15 min after the discovery cron at 14:30, ~3 hours before peak heating).
Uses today's 00Z ECMWF run (ingested by the 07 UTC ECMWF cron) as the forecast
basis — gives ~14 hours of lead time to the daily high, well within ensemble
skill for daily max forecasting.

For today's UTC date:
  1. Reads today's 00Z ECMWF forecast.
  2. Fits rolling-window EMOS on the prior 45 days of (00Z ECMWF, observation)
     pairs (model="ifs", init_hour=0).
  3. Compares model probability to current Kalshi market mid.
  4. INSERTs one row per contract where |edge| >= 0.10.

Append-only — PK enforces one entry per (target_date, ticker, model_source);
re-runs are no-ops via ON CONFLICT DO NOTHING.

Skips with no row written when: today's 00Z ECMWF forecast isn't in the DB,
no contracts exist for today, rolling EMOS can't fit (insufficient training
data), or no contract has prices on both sides.

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


EDGE_THRESHOLD = 0.10
MIN_ENTRY_PRICE_CENTS = 60  # Pre-registered 2026-05-28 after backtest discovery:
                            # filter to entry ≥ 60¢ produces positive net P&L across
                            # all 4 configs (combined 00Z: +3.07¢/trade, t=+1.01, n=189).
                            # The filter captures "agree with market direction, more
                            # confidently" trades — model's contrarian bets (low entry
                            # prices) lose. Forward validation pending.
STATION_ID = "KNYC"
WINDOW_DAYS = 45
INIT_HOUR = 0          # use 00Z runs — published before market open
MODEL = "combined"     # GEFS + IFS at 00Z (GEFS 00Z backfill completed 2026-05-28)
MODEL_SOURCE = "EMOS combined 00Z (rolling 45d)"


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
    today = snapshot_cutoff.date()  # use cutoff date so --as-of targets the right trade_date
    init_time = datetime(today.year, today.month, today.day, INIT_HOUR, 0, tzinfo=timezone.utc)

    print(f"Paper-trade log for {today} (logged_at={logged_at.isoformat()})")
    if args.as_of is not None:
        print(f"  as-of recovery: prices and trade-decision moment set to {snapshot_cutoff.isoformat()}")

    with get_connection() as conn:
        # 1. Today's 00Z ECMWF init must have forecast data.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM forecasts WHERE station_id = %s AND init_time = %s AND model = %s LIMIT 1",
                (STATION_ID, init_time, MODEL),
            )
            if cur.fetchone() is None:
                print(f"  no {MODEL} forecast for init {init_time.isoformat()}. Skipping.")
                return

        # 2. Today's ECMWF-only ensemble.
        ensemble_values = compute_combined_daily_highs(
            init_time, today, conn, station_id=STATION_ID, models=[MODEL],
        )
        n_members = len(ensemble_values)
        ensemble_mean = statistics.mean(ensemble_values)
        ensemble_std = statistics.stdev(ensemble_values) if n_members > 1 else 0.0

        # 3. Rolling EMOS fit on prior days' (00Z ECMWF, observation) pairs.
        emos = fit_emos_rolling(
            today, conn,
            window_days=WINDOW_DAYS, station_id=STATION_ID,
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

        # 4. Active contracts for today.
        contracts = fetch_contracts_for_date(today, conn, station_id=STATION_ID)
        if not contracts:
            print(f"  no contracts found for {today}. Skipping.")
            return

        # 5. Latest price snapshot per contract, as of the cutoff time.
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

        # 6. Model probabilities under the EMOS Gaussian.
        model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

        notes = f"ensemble_members={n_members}"
        if args.as_of is not None:
            notes += f"; as-of-recovery={snapshot_cutoff.isoformat()}"

        print(f"  forecast init: {init_time.isoformat()}")
        print(f"  model_source:  {MODEL_SOURCE}")
        print(f"  ensemble:      n={n_members}  mean={ensemble_mean:.2f}°F  std={ensemble_std:.2f}°F")
        print(f"  EMOS μ/σ:      {emos_mu:.2f}° / {emos_sigma:.2f}°")
        print(f"  EMOS train:    {emos['train_start']} → {emos['train_end']} ({emos['n_train_days_used']} days)")

        # 7. Evaluate each contract; INSERT rows where |edge| >= threshold.
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

                # Pre-registered filter (2026-05-28): only log trades where we'd be
                # "agreeing with market direction, more confidently" (entry >= 60¢).
                # Backtest showed model's contrarian bets (low entry) systematically lose.
                if entry_price < MIN_ENTRY_PRICE_CENTS:
                    continue

                cur.execute(
                    INSERT_SQL,
                    (
                        logged_at, today, ticker, MODEL_SOURCE,
                        init_time, ensemble_mean, ensemble_std,
                        emos_mu, emos_sigma, model_p,
                        bid, ask, market_mid, snap,
                        edge, EDGE_THRESHOLD, position, entry_price, notes,
                    ),
                )
                trades_logged.append((ticker, position, edge, entry_price, model_p, market_mid))

        # 8. Summary.
        print(f"  contracts with prices: {n_checked}")
        print(f"  trades logged: {len(trades_logged)}")
        for ticker, pos, e, entry, mp, mm in trades_logged:
            print(f"    {ticker:30s} {pos:8s}  model={mp:.3f}  market={mm:.3f}  edge={e:+.3f}  entry={entry}¢")


if __name__ == "__main__":
    main()
