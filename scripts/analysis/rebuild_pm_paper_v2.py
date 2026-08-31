"""Rebuild the Polymarket paper series under CORRECTED (inclusive-pair) brackets.

Writes NEW rows under a `... PM v2 ...` model_source. Never UPDATEs or DELETEs a
historical row: paper_trades is keyed (target_date, ticker, model_source), so the
old series stays exactly as generated and the two are directly diffable. See
docs/analysis-snapshots/2026-08-23-pre-bracket-fix/.

WHY IT REBUILDS FROM THE LADDER, NOT FROM THE OLD ROWS. paper_trades only ever
held contracts that PASSED the old filter. Recomputing just those would inherit
the buggy selection — contracts the old reading wrongly rejected would stay
invisible. So the ladder is re-read from `prices` and every bracket is rescored.

Deterministic from stored inputs only: emos_mu/emos_sigma as logged that day and
quotes at or before that day's logging time. No new forecast data, no hindsight.

  uv run python scripts/analysis/rebuild_pm_paper_v2.py
  uv run python scripts/analysis/rebuild_pm_paper_v2.py --apply
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict

from weather_markets.db import get_connection
from weather_markets.evaluation import kalshi_equivalent_bracket

EDGE_THRESHOLD = 0.10
V2 = " v2 (rolling 45d)"


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bracket_prob(b: dict, mu: float, sigma: float) -> float:
    """P(integer daily high satisfies this bracket) under N(mu, sigma)."""
    bt, lo, hi = b["bracket_type"], b["strike_low"], b["strike_high"]
    if bt == "between":         # inclusive lo..hi
        return max(0.0, norm_cdf((hi + 0.5 - mu) / sigma) - norm_cdf((lo - 0.5 - mu) / sigma))
    if bt == "greater_than":    # high > lo
        return 1.0 - norm_cdf((lo + 0.5 - mu) / sigma)
    if bt == "less_than":       # high < hi
        return norm_cdf((hi - 0.5 - mu) / sigma)
    raise ValueError(bt)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # the model as it stood that day, from the old rows (mu/sigma are
            # bracket-independent, so the bug never touched them)
            cur.execute("""
                SELECT DISTINCT ON (c.station_id, pt.target_date)
                       c.station_id, pt.target_date, pt.model_source,
                       pt.emos_mu, pt.emos_sigma, pt.forecast_init_time,
                       pt.ensemble_mean, pt.ensemble_std, pt.logged_at
                FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
                WHERE c.platform = 'polymarket' AND pt.model_source NOT LIKE '%% v2 %%'
                  AND pt.emos_mu IS NOT NULL
                ORDER BY c.station_id, pt.target_date, pt.logged_at""")
            days = cur.fetchall()

        rows, per_day = [], defaultdict(int)
        for (stn, td, msrc, mu, sigma, init, emean, estd, logged) in days:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (c.ticker) c.ticker, c.bracket_type,
                           c.strike_low, c.strike_high, p.yes_bid, p.yes_ask,
                           p.snapshot_at
                    FROM contracts c JOIN prices p ON p.ticker = c.ticker
                    WHERE c.platform='polymarket' AND c.station_id=%s
                      AND c.target_date=%s AND p.snapshot_at <= %s
                      AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
                    ORDER BY c.ticker, p.snapshot_at DESC""", (stn, td, logged))
                ladder = cur.fetchall()

            for tk, bt, sl, sh, bid, ask, snap in ladder:
                b = kalshi_equivalent_bracket("polymarket", bt, sl, sh)
                p_model = bracket_prob(b, float(mu), float(sigma))
                mid = (bid + ask) / 200.0
                edge = p_model - mid
                if abs(edge) < EDGE_THRESHOLD:
                    continue
                pos = "BUY_YES" if edge > 0 else "BUY_NO"
                entry = ask if edge > 0 else 100 - bid
                rows.append((logged, td, tk, msrc.replace(" (rolling 45d)", V2),
                             init, emean, estd, mu, sigma, p_model, bid, ask, mid,
                             snap, edge, EDGE_THRESHOLD, pos, entry))
                per_day[(stn, td)] += 1

        print(f"{len(days)} station-days -> {len(rows)} v2 signals "
              f"(old series had 112 rows)")
        for (stn, td), n in sorted(per_day.items())[:8]:
            print(f"  {stn} {td}: {n}")
        if len(per_day) > 8:
            print(f"  ... {len(per_day) - 8} more station-days")

        if not a.apply:
            print("\nDRY RUN — add --apply to insert. No existing row is touched either way.")
            return 0

        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO paper_trades (logged_at, target_date, ticker, model_source,
                    forecast_init_time, ensemble_mean, ensemble_std, emos_mu, emos_sigma,
                    model_prob_yes, market_yes_bid, market_yes_ask, market_mid_prob,
                    market_snapshot_at, edge, edge_threshold, position, entry_price_cents)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (target_date, ticker, model_source) DO NOTHING""", rows)
        conn.commit()
        print(f"\ninserted {len(rows)} v2 row(s); old series untouched")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
