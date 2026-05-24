"""
Paper-trade log: once-daily prospective record of what the rolling-EMOS model
would trade. Runs at 17 UTC via cron.

For today's UTC date, fits rolling-window EMOS (w=45, model=combined),
compares against current Kalshi prices, and INSERTs one row per contract
where |edge| >= 0.10. Append-only — PK enforces one entry per
(target_date, ticker, model_source); re-runs are no-ops via ON CONFLICT
DO NOTHING.

Skips with no row written when: today's 12 UTC forecast isn't in the DB,
no contracts exist for today, rolling EMOS can't fit (insufficient training
data), or no contract has prices on both sides. The absence of a row is
itself informative when you later query tradeable-day counts.

Run with: uv run python scripts/paper_trade_log.py
"""
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
STATION_ID = "KNYC"
WINDOW_DAYS = 45
BASE_MODEL_SOURCE = "EMOS combined (rolling 45d)"


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
    logged_at = datetime.now(tz=timezone.utc)
    today = logged_at.date()
    init_time = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)

    print(f"Paper-trade log for {today} (logged_at={logged_at.isoformat()})")

    with get_connection() as conn:
        # 1. Today's 12 UTC init must have forecast data.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM forecasts WHERE station_id = %s AND init_time = %s LIMIT 1",
                (STATION_ID, init_time),
            )
            if cur.fetchone() is None:
                print(f"  no forecast data for init {init_time.isoformat()}. Skipping.")
                return

        # 2. Which models contributed (drives the model_source label).
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model FROM forecasts
                WHERE init_time = %s AND station_id = %s AND model IN ('gefs','ifs')
                GROUP BY model
                """,
                (init_time, STATION_ID),
            )
            models_present = {row[0] for row in cur.fetchall()}

        # 3. Today's combined ensemble (GEFS+IFS, or just whichever landed).
        combined_values = compute_combined_daily_highs(
            init_time, today, conn, station_id=STATION_ID,
        )
        n_members = len(combined_values)
        ensemble_mean = statistics.mean(combined_values)
        ensemble_std = statistics.stdev(combined_values) if n_members > 1 else 0.0

        # 4. Rolling EMOS fit.
        emos = fit_emos_rolling(
            today, conn,
            window_days=WINDOW_DAYS, station_id=STATION_ID, model="combined",
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

        # 5. Active contracts for today.
        contracts = fetch_contracts_for_date(today, conn, station_id=STATION_ID)
        if not contracts:
            print(f"  no contracts found for {today}. Skipping.")
            return

        # 6. Latest price snapshot per contract.
        tickers = [c["ticker"] for c in contracts]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                FROM prices WHERE ticker = ANY(%s)
                ORDER BY ticker, snapshot_at DESC
                """,
                (tickers,),
            )
            prices = {t: (b, a, s) for t, b, a, s in cur.fetchall()}

        # 7. Model probabilities under the EMOS Gaussian.
        model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

        # Build model_source label; flag GEFS-only when ECMWF is missing.
        model_source = BASE_MODEL_SOURCE
        if "ifs" not in models_present:
            model_source += " [GEFS-only]"
        notes = f"ensemble_members={n_members}"

        print(f"  forecast init: {init_time.isoformat()}")
        print(f"  model_source:  {model_source}")
        print(f"  ensemble:      n={n_members}  mean={ensemble_mean:.2f}°F  std={ensemble_std:.2f}°F")
        print(f"  EMOS μ/σ:      {emos_mu:.2f}° / {emos_sigma:.2f}°")
        print(f"  EMOS train:    {emos['train_start']} → {emos['train_end']} ({emos['n_train_days_used']} days)")

        # 8. Evaluate each contract; INSERT rows where |edge| >= threshold.
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
                trades_logged.append((ticker, position, edge, entry_price, model_p, market_mid))

        # 9. Summary.
        print(f"  contracts with prices: {n_checked}")
        print(f"  trades logged: {len(trades_logged)}")
        for ticker, pos, e, entry, mp, mm in trades_logged:
            print(f"    {ticker:30s} {pos:8s}  model={mp:.3f}  market={mm:.3f}  edge={e:+.3f}  entry={entry}¢")


if __name__ == "__main__":
    main()
