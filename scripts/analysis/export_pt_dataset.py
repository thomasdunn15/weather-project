"""Export paper_trades -> /tmp/pt_dataset.csv for diagnostic_city_params.py.

Rebuilds the per-trade dataset the diagnostic reads, using the project's OWN
settlement rule (evaluation.contract_resolved_yes) and fee model
(catalog.fee_cents, the parity-tested 7%·p·(1-p) taker fee) — so it matches the
original one-off `\\copy` exactly, but is reproducible. 1 contract/signal, held
to settlement.

    uv run python scripts/analysis/export_pt_dataset.py
"""
from __future__ import annotations

import csv

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket
from weather_markets.expansion.catalog import fee_cents

OUT = "/tmp/pt_dataset.csv"

_QUERY = """
    SELECT c.series, pt.target_date, pt.model_source, pt.position,
           pt.market_yes_bid, pt.market_yes_ask, pt.edge,
           c.platform, c.bracket_type, c.strike_low, c.strike_high,
           -- LOWS series settle on the daily MIN, not MAX (bug fixed 2026-08-07:
           -- lows rows were silently scored against the high)
           CASE WHEN c.series LIKE 'KXLOWT%' THEN o.low_temp_f
                ELSE o.high_temp_f END AS settle_temp_f
    FROM paper_trades pt
    JOIN contracts c ON c.ticker = pt.ticker
    JOIN observations o ON o.date = pt.target_date AND o.station_id = c.station_id
    WHERE pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
      AND (CASE WHEN c.series LIKE 'KXLOWT%' THEN o.low_temp_f
                ELSE o.high_temp_f END) IS NOT NULL
"""


def main() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_QUERY)
            rows = cur.fetchall()
    finally:
        conn.close()

    n = skipped = 0
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["series", "target_date", "model_source", "position", "entry", "edge", "net_cents", "won"])
        for series, td, ms, pos, bid, ask, edge, platform, bt, sl, sh, settle_temp in rows:
            buy_yes = pos == "BUY_YES"
            entry = int(ask) if buy_yes else 100 - int(bid)   # price paid: YES@ask, NO@(100-bid)
            if entry <= 0 or entry >= 100:
                skipped += 1
                continue
            resolved_yes = bool(contract_resolved_yes(
                int(round(settle_temp)), kalshi_equivalent_bracket(platform, bt, sl, sh)))
            won = resolved_yes if buy_yes else (not resolved_yes)
            fee = fee_cents(entry, "kalshi", maker=False)
            net = ((100 - entry) if won else -entry) - fee
            w.writerow([series, td, ms, pos, entry, edge, net, "t" if won else "f"])
            n += 1
    print(f"wrote {n} rows to {OUT} (skipped {skipped} out-of-range-price)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
