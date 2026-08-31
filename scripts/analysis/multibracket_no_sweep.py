"""Does selling the REST of the distribution beat buying the bracket we like?

The idea (operator, 2026-08-28): brackets on one event are mutually exclusive and
exhaustive. So a YES view on bracket X is also a NO view on every other bracket.
Rather than buy YES on X, buy NO on all the others.

Algebraically that is the SAME BET when prices sum to 100: buying NO on the other
n-1 brackets pays (n-1)*100 if X lands and (n-2)*100 otherwise, which nets to the
same +({100-p_X}) / -(p_X) as buying YES on X. So this can only win where reality
departs from that identity:

  OVERROUND. If the book's YES prices sum to MORE than 100, selling the whole
  book is +EV by (sum - 100) regardless of outcome. That is strategy C below.
  FEES. Kalshi charges per contract with a 1c FLOOR, so an 8-leg replication
  pays >=8c where the 1-leg version pays 1-2c. This is the drag that has to be
  cleared before any of it matters.
  SPREAD. Each leg crosses its own spread; n-1 legs cross n-1 spreads.

Three strategies, priced off the real book (no_ask / yes_ask) at the decision
snapshot, charged the live taker fee:

  A  control     buy YES on the signalled bracket
  B  operator    buy NO on every OTHER bracket
  C  overround   buy NO on EVERY bracket, signal ignored

Capital differs enormously (B and C buy many near-$1 legs), so P&L is reported
per event AND per dollar deployed. Absolute P&L alone would flatter B and C.

    uv run python scripts/analysis/multibracket_no_sweep.py
    uv run python scripts/analysis/multibracket_no_sweep.py --station KMIA
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes

DECISION_HH, DECISION_MM = 14, 45


def fee_cents(price_cents: int) -> int:
    """Kalshi taker fee, mirroring dashboard/sim_python.kalshi_fee_cents."""
    if price_cents <= 0 or price_cents >= 100:
        return 0
    p = price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


def load(conn, station_filter: str | None, since: str):
    """(station, date) -> {"brackets": [...], "signal": ticker|None, "obs": high}"""
    sql = """
        WITH snap AS (
          SELECT DISTINCT ON (p.ticker)
                 p.ticker, p.yes_ask, p.no_ask, c.station_id, c.target_date,
                 c.bracket_type, c.strike_low, c.strike_high
          FROM prices p
          JOIN contracts c ON c.ticker = p.ticker
          WHERE c.platform='kalshi' AND c.bracket_type='between'
            AND c.target_date >= %s
            AND p.snapshot_at <= (c.target_date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
            AND p.snapshot_at >= (c.target_date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
                                 - interval '90 minutes'
            AND p.yes_ask IS NOT NULL AND p.no_ask IS NOT NULL
          ORDER BY p.ticker, p.snapshot_at DESC
        )
        SELECT s.station_id, s.target_date, s.ticker, s.yes_ask, s.no_ask,
               s.bracket_type, s.strike_low, s.strike_high, o.high_temp_f
        FROM snap s
        JOIN observations o ON o.station_id=s.station_id AND o.date=s.target_date
        WHERE o.high_temp_f IS NOT NULL
    """
    args = [since, DECISION_HH, DECISION_MM, DECISION_HH, DECISION_MM]
    if station_filter:
        sql += " AND s.station_id = %s"
        args.append(station_filter)
    events: dict = defaultdict(lambda: {"brackets": [], "obs": None, "signal": None})
    with conn.cursor() as cur:
        cur.execute(sql, args)
        for st, td, tk, ya, na, bt, lo, hi, obs in cur.fetchall():
            e = events[(st, td)]
            e["obs"] = int(round(obs))
            e["brackets"].append({"ticker": tk, "yes_ask": int(ya), "no_ask": int(na),
                                  "meta": {"bracket_type": bt, "strike_low": lo,
                                           "strike_high": hi}})
    # the YES signal we actually fired, if any
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.station_id, pt.target_date, pt.ticker
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            WHERE pt.model_source LIKE %s AND pt.model_source LIKE %s
              AND c.bracket_type='between' AND upper(pt.position) LIKE %s
              AND abs(pt.edge) >= 0.10 AND pt.target_date >= %s
        """, ('EMOS combined 00Z%', '%(rolling 45d)', '%YES', since))
        for st, td, tk in cur.fetchall():
            if (st, td) in events:
                events[(st, td)]["signal"] = tk
    return events


def run(events: dict) -> dict:
    """Per-strategy: list of (station, date, pnl_cents, cost_cents)."""
    out = {k: [] for k in ("A_yes_signal", "B_no_others", "C_no_all")}
    for (st, td), e in events.items():
        bs, obs, sig = e["brackets"], e["obs"], e["signal"]
        if len(bs) < 3:
            continue
        won = {b["ticker"]: contract_resolved_yes(obs, b["meta"]) for b in bs}

        def no_leg(b):
            px = b["no_ask"]
            return (((100 - px) if not won[b["ticker"]] else -px) - fee_cents(px), px)

        # C: sell the whole book, no signal needed
        legs = [no_leg(b) for b in bs]
        out["C_no_all"].append((st, td, sum(p for p, _ in legs), sum(c for _, c in legs)))

        if not sig or sig not in won:
            continue
        # A: the control — buy YES on the bracket we liked
        sb = next(b for b in bs if b["ticker"] == sig)
        px = sb["yes_ask"]
        out["A_yes_signal"].append(
            (st, td, ((100 - px) if won[sig] else -px) - fee_cents(px), px))
        # B: buy NO on every OTHER bracket
        legs = [no_leg(b) for b in bs if b["ticker"] != sig]
        out["B_no_others"].append((st, td, sum(p for p, _ in legs), sum(c for _, c in legs)))
    return out


def report(name: str, rows: list) -> None:
    if not rows:
        print(f"  {name:16} no events"); return
    pnl = sum(r[2] for r in rows)
    cost = sum(r[3] for r in rows)
    per_day: dict = defaultdict(float)
    for st, td, p, _ in rows:
        per_day[td] += p
    v = list(per_day.values())
    sd = statistics.pstdev(v) or 1e-9
    sharpe = statistics.mean(v) / sd * (len(v) ** 0.5)
    print(f"  {name:16} {len(rows):5d} events  net ${pnl/100:+9.2f}  "
          f"deployed ${cost/100:9.2f}  return {100*pnl/cost if cost else 0:+7.2f}%  "
          f"Sharpe {sharpe:+.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station")
    ap.add_argument("--since", default="2026-02-11")
    ap.add_argument("--per-city", action="store_true")
    a = ap.parse_args()

    conn = get_connection()
    try:
        events = load(conn, a.station, a.since)
    finally:
        conn.close()
    print(f"{len(events)} event-days from {a.since}"
          f"{' for ' + a.station if a.station else ''}\n")
    res = run(events)
    print("ALL CITIES")
    for k in ("A_yes_signal", "B_no_others", "C_no_all"):
        report(k, res[k])

    if a.per_city:
        cities = sorted({r[0] for rows in res.values() for r in rows})
        for st in cities:
            print(f"\n{st}")
            for k in ("A_yes_signal", "B_no_others", "C_no_all"):
                report(k, [r for r in res[k] if r[0] == st])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
