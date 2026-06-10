"""Find the best UTC time-of-day to fire the daily cron for each city, given
current strategy parameters.

For each historical settled day, walk through candidate decision times every
30 minutes (13:00 → 19:00 UTC). At each time:
  1. Take the model probability from paper_trades (fixed — computed from forecast)
  2. Pull the actual market_mid_price at that time from `prices` table
  3. Recompute edge under the city's current strategy
  4. Apply max_signals_per_day and edge_cap risk controls
  5. Simulate trades, compute realized P&L using known settlement outcomes

Then aggregate by candidate time, report mean P&L + t-stat for each. Best time
= highest mean P&L (or best t-stat if you prefer significance over absolute $).

Methodology notes:
- Walk-forward blend coefficients refit each day on prior 60+ days of data
  (matches production behavior — no look-ahead).
- Sizing matches production: KORD unit=500 with edge cap; KMIA amount=$15
  with edge cap.
- Reports SETTLED P&L only (assumes the limit price gets filled at cron-time
  market). Real-world fill rate isn't modeled here — that's a different
  question. This compares times under EQUAL fill assumptions.
"""
import argparse, sys, types, math, statistics
sys.path.insert(0, 'scripts')
sm = types.ModuleType('streamlit'); sm.components = types.ModuleType('streamlit.components')
sm.components.v1 = types.ModuleType('streamlit.components.v1'); sm.components.v1.html = lambda *a, **k: None
sm.cache_data = lambda *a, **k: (lambda f: f)
sys.modules['streamlit'] = sm; sys.modules['streamlit.components'] = sm.components
sys.modules['streamlit.components.v1'] = sm.components.v1
from datetime import date, datetime, time, timedelta, timezone
from collections import defaultdict
import numpy as np

from weather_markets.db import get_connection

# Per-city config — matches production live_trade.CITY_CONFIG
CITY_CONFIGS = {
    "KORD": {
        "model_source": "EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        "strategy": "union",
        "raw_edge_threshold": 0.25,
        "blend_edge_threshold": 0.10,
        "max_signals_per_day": 2,
        "sizing_mode": "unit",
        "unit_contracts": 500,
        "max_contracts": 500,
        "size_edge_cap": 0.40,
    },
    "KMIA": {
        "model_source": "EMOS combined 00Z Miami (rolling 45d)",
        "strategy": "blend",
        "raw_edge_threshold": 1.00,                # disabled
        "blend_edge_threshold": 0.10,
        "max_signals_per_day": 1,
        "sizing_mode": "amount",
        "amount_dollars": 15.0,
        "max_contracts": 500,
        "size_edge_cap": 0.40,
    },
}

def logit(p): p = max(0.001, min(0.999, p)); return math.log(p/(1-p))
def inv_logit(x): return 1/(1+math.exp(-x))

def yes_wins(bt, sl, sh, h):
    if bt == "greater_than": return h > sl
    if bt == "less_than":    return h < sh
    if bt == "between":      return sl <= h <= sh
    return False

def fit_blend(records):
    """Fit logit blend on a list of {pm, pmk, won} dicts."""
    if len(records) < 30: return None
    X = np.array([[1.0, logit(r["pm"]), logit(r["pmk"])] for r in records])
    y = np.array([1 if r["won"] else 0 for r in records], dtype=float)
    beta = np.zeros(3)
    for _ in range(50):
        p = 1/(1+np.exp(-X @ beta))
        H = -X.T @ np.diag(p*(1-p)) @ X
        try: beta = beta - np.linalg.solve(H, X.T @ (y-p))
        except np.linalg.LinAlgError: return None
    return beta

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=["KORD", "KMIA", "both"], default="both")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end",   default="2026-06-09")
    args = parser.parse_args()

    cities = ["KORD", "KMIA"] if args.city == "both" else [args.city]
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d   = datetime.strptime(args.end,   "%Y-%m-%d").date()

    # Candidate decision times (UTC) — every 30 min from 13:00 → 19:00
    cand_times = [time(h, m) for h in range(13, 20) for m in (0, 30)]

    for city in cities:
        cfg = CITY_CONFIGS[city]
        print(f"\n{'='*70}\n  {city}  ({cfg['strategy']} strategy)\n{'='*70}")

        # Pull all candidate trades for this city — joined with obs to know outcome
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT pt.target_date, pt.ticker, pt.model_prob_yes, pt.position,
                       c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                FROM paper_trades pt
                JOIN contracts c ON c.ticker = pt.ticker
                JOIN observations o ON o.station_id=%s AND o.date=pt.target_date
                WHERE pt.model_source = %s
                  AND pt.target_date BETWEEN %s AND %s
                  AND o.high_temp_f IS NOT NULL
                ORDER BY pt.target_date""",
                (city, cfg["model_source"], start_d, end_d))
            paper_rows = cur.fetchall()

            if not paper_rows:
                print(f"  no paper_trades data for {city}")
                continue

            # For each (target_date, ticker), pull price snapshots throughout the day
            tickers = list({r[1] for r in paper_rows})
            cur.execute("""
                SELECT ticker, snapshot_at, yes_bid, yes_ask
                FROM prices
                WHERE ticker = ANY(%s)
                  AND snapshot_at::date BETWEEN %s AND %s
                  AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
                ORDER BY ticker, snapshot_at""", (tickers, start_d, end_d))
            price_rows = cur.fetchall()

        # Index prices by (ticker, date) -> sorted list of (snapshot_at, mid)
        price_idx = defaultdict(list)
        for ticker, snap_ts, yb, ya in price_rows:
            mid = (int(yb) + int(ya)) / 2.0   # YES mid in cents
            d = snap_ts.astimezone(timezone.utc).date()
            price_idx[(ticker, d)].append((snap_ts, mid))

        def price_at(ticker, target_date, t):
            """Get closest snapshot to UTC time `t` on target_date for this ticker."""
            key = (ticker, target_date)
            arr = price_idx.get(key, [])
            if not arr: return None
            wanted = datetime.combine(target_date, t, tzinfo=timezone.utc)
            best = min(arr, key=lambda r: abs((r[0] - wanted).total_seconds()))
            if abs((best[0] - wanted).total_seconds()) > 1800:   # >30 min off → skip
                return None
            return best[1]

        # Build (per-day) list of candidate trades enriched with outcome
        per_day = defaultdict(list)
        for td, ticker, pm, pos, bt, sl, sh, high in paper_rows:
            won = yes_wins(bt, sl, sh, int(high))
            per_day[td].append({
                "ticker": ticker, "pm": float(pm), "pos": pos,
                "bt": bt, "sl": sl, "sh": sh, "won": won, "high": int(high),
            })

        # For each candidate time, simulate the strategy across all settled days
        results_by_time = {}
        for cand_t in cand_times:
            trades_by_day = []
            # walk-forward blend re-fit each day
            for ti, target_d in enumerate(sorted(per_day.keys())):
                day_trades = per_day[target_d]
                # blend train set = all settled trades from prior 60+ days (any time-of-day, just use original cron snapshot)
                train = []
                for td2 in sorted(per_day.keys()):
                    if td2 >= target_d: break
                    if (target_d - td2).days > 365: continue
                    for tr in per_day[td2]:
                        # we don't know pmk at cand_t for past days; use mid at SAME cand_t for consistency
                        # but training is on "did we win" with any market_p — use pm only for fit purposes
                        pmk = price_at(tr["ticker"], td2, cand_t)
                        if pmk is None: continue
                        train.append({"pm": tr["pm"], "pmk": pmk/100.0, "won": tr["won"]})
                if len(train) < 30: continue
                beta = fit_blend(train)
                if beta is None: continue

                # Score TODAY's candidate trades
                day_signals = []
                for tr in day_trades:
                    pmk = price_at(tr["ticker"], target_d, cand_t)
                    if pmk is None: continue
                    pm = tr["pm"]; market_p = pmk/100.0
                    p_blend = inv_logit(beta[0] + beta[1]*logit(pm) + beta[2]*logit(market_p))
                    # Edges (raw + blend) using current side
                    raw_edge = (pm - market_p) if tr["pos"] == "BUY_YES" else ((1-pm) - (1-market_p))
                    blend_edge = (p_blend - market_p) if tr["pos"] == "BUY_YES" else ((1-p_blend) - (1-market_p))
                    fires = False
                    if cfg["strategy"] == "raw":
                        fires = raw_edge >= cfg["raw_edge_threshold"]
                        edge = raw_edge
                    elif cfg["strategy"] == "blend":
                        fires = blend_edge >= cfg["blend_edge_threshold"]
                        edge = blend_edge
                    else:  # union
                        fires = raw_edge >= cfg["raw_edge_threshold"] or blend_edge >= cfg["blend_edge_threshold"]
                        edge = max(raw_edge, blend_edge)
                    if not fires: continue
                    # entry price = current market (we'd post at mid or cross)
                    entry = int(round(pmk))   # YES-eq cents
                    if tr["pos"] == "BUY_NO": entry = 100 - entry
                    # Outcome
                    won = tr["won"] if tr["pos"] == "BUY_YES" else not tr["won"]
                    pnl_per_contract_cents = (100 - entry) if won else (-entry)
                    day_signals.append({"edge": abs(edge), "entry": entry, "pnl_c": pnl_per_contract_cents})

                # Anti-stacking
                day_signals.sort(key=lambda s: -s["edge"])
                day_signals = day_signals[:cfg["max_signals_per_day"]]

                # Sizing with edge cap
                day_pnl = 0
                for s in day_signals:
                    edge_scale = min(1.0, cfg["size_edge_cap"] / max(s["edge"], 0.01))
                    if cfg["sizing_mode"] == "unit":
                        n_contracts = int(round(cfg["unit_contracts"] * edge_scale))
                    else:
                        amount_cents = int(round(cfg["amount_dollars"] * 100 * edge_scale))
                        n_contracts = amount_cents // max(s["entry"], 1)
                    n_contracts = min(n_contracts, cfg["max_contracts"])
                    day_pnl += s["pnl_c"] * n_contracts / 100.0
                trades_by_day.append(day_pnl)

            if len(trades_by_day) < 5: continue
            n = len(trades_by_day)
            total = sum(trades_by_day)
            mean = statistics.mean(trades_by_day)
            sd   = statistics.stdev(trades_by_day) if n > 1 else 0
            tstat = mean / (sd / math.sqrt(n)) if sd > 0 else 0
            wins = sum(1 for p in trades_by_day if p > 0)
            results_by_time[cand_t] = {"n": n, "total": total, "mean": mean, "tstat": tstat,
                                       "wins": wins}

        if not results_by_time:
            print("  no results (insufficient price data?)")
            continue

        # Report sorted by total $
        print(f"\n{'time UTC':<10} {'days':>5} {'total $':>10} {'avg/day':>8} {'win-day %':>10} {'t-stat':>7}")
        print("-" * 60)
        for t in sorted(results_by_time.keys()):
            r = results_by_time[t]
            print(f"{t.strftime('%H:%M'):<10} {r['n']:>5} ${r['total']:>+9.2f} ${r['mean']:>+7.2f} "
                  f"{r['wins']/r['n']*100:>9.1f}% {r['tstat']:>+6.2f}")

        # Best by total
        best_total = max(results_by_time.items(), key=lambda kv: kv[1]["total"])
        best_tstat = max(results_by_time.items(), key=lambda kv: kv[1]["tstat"])
        print(f"\n  Best total $: {best_total[0].strftime('%H:%M')} UTC (+${best_total[1]['total']:.2f})")
        print(f"  Best t-stat:  {best_tstat[0].strftime('%H:%M')} UTC (t={best_tstat[1]['tstat']:+.2f})")

if __name__ == "__main__":
    main()
