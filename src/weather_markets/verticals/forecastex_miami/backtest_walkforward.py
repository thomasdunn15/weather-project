"""Walk-forward backtest stub for forecastex-miami — enforces the deploy bar.

Hard rules baked in:
- OOS Sharpe must exceed 2.5 on realistic execution to even PROPOSE going live.
- Strict no-look-ahead: only data recorded at-or-before each day's decision
  time is eligible (enforced in SQL below, not by convention).
- This script never places orders and is never wired to --live.

Run: uv run python -m weather_markets.verticals.forecastex_miami.backtest_walkforward
"""

from __future__ import annotations

import statistics

from weather_markets.db import get_connection

DEPLOY_BAR_SHARPE = 2.5
STATION = 'KMIA'

# As-of-decision-time predicate: the paper row AND its market snapshot must
# both predate the decision timestamp logged with the signal. No look-ahead.
QUERY = """
    SELECT pt.target_date, pt.edge, pt.position, pt.entry_price_cents
    FROM paper_trades pt
    JOIN contracts c ON c.ticker = pt.ticker
    WHERE c.station_id = %s
      AND pt.logged_at <= pt.target_date::timestamptz + interval '1 day'
      AND (pt.market_snapshot_at IS NULL OR pt.market_snapshot_at <= pt.logged_at)
    ORDER BY pt.target_date
"""


def walk_forward(rows: list, train_days: int = 60, test_days: int = 30) -> list[float]:
    """TODO: per-window P&L with the production fee model (maker/taker aware)
    and realistic fills — copy the harness pattern from scripts/analysis/
    (best_time_of_day.py / backtest_with_blend.py), do not invent a new one."""
    raise NotImplementedError


def main() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY, (STATION,))
            rows = cur.fetchall()
    finally:
        conn.close()
    if len(rows) < 90:
        print(f"INSUFFICIENT DATA: {len(rows)} paper rows — accumulate a paper period first.")
        return 1
    daily_pnl = walk_forward(rows)
    sharpe = statistics.mean(daily_pnl) / (statistics.pstdev(daily_pnl) or float("inf")) * (252 ** 0.5)
    verdict = "CLEARS" if sharpe > DEPLOY_BAR_SHARPE else "FAILS"
    print(f"walk-forward OOS Sharpe = {sharpe:.2f} -> {verdict} the {DEPLOY_BAR_SHARPE} bar")
    print("Going live is a MANUAL operator decision at small size regardless of this number.")
    return 0 if sharpe > DEPLOY_BAR_SHARPE else 1


if __name__ == "__main__":
    raise SystemExit(main())
