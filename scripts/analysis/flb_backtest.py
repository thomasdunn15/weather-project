"""Net-of-fee backtest of the FLB harvest on settled Kalshi markets.

Turns the measured +Npp longshot overpricing (flb_regime.py) into a real
per-contract net P&L: does it survive Kalshi's fee once you pay a realistic fill
price? For each settled market we take the (yes_bid, yes_ask) at `entry_frac` of
its life, classify by mid, and simulate holding to settlement:

  FAVORITE  (mid >= 50c): buy YES   — tests favorite UNDER-pricing
  FADE      (mid <  30c): buy NO    — tests longshot OVER-pricing (buy NO = 100 - yes)

Two fill models bracket reality:
  TAKER (realistic floor):  pay the ask (YES @ yes_ask, NO @ 100-yes_bid), taker fee
  MAKER (optimistic ceil):  capture the spread (YES @ yes_bid, NO @ 100-yes_ask), maker fee

    uv run python scripts/analysis/flb_backtest.py KXSILVERD KXCOPPERD KXGOLDD KXNATGASD
    uv run python scripts/analysis/flb_backtest.py KXSILVERD --entry-frac 0.4 --limit 60
"""
from __future__ import annotations

import argparse
import statistics
import time

from weather_markets.db import get_connection
from weather_markets.expansion.candlesticks import entry_quote, settled_markets
from weather_markets.expansion.catalog import fee_cents


def trade_pnl(entry_cents: int, won: bool, maker: bool) -> float:
    """Net cents from buying one contract at entry_cents that pays 100 if won."""
    fee = fee_cents(int(round(entry_cents)), "kalshi", maker=maker)
    gross = (100 - entry_cents) if won else (-entry_cents)
    return gross - fee


def simulate_market(quote: tuple[int, int], result: str, maker: bool):
    """Return (strategy, entry_cents, won, net_cents) or None if the mid is 30-50c."""
    bid, ask = quote
    mid = (bid + ask) / 2
    if mid >= 50:                       # favorite -> buy YES
        entry = bid if maker else ask
        won = result == "yes"
        return "favorite", entry, won, trade_pnl(entry, won, maker)
    if mid < 30:                        # longshot -> fade (buy NO)
        entry = (100 - ask) if maker else (100 - bid)
        won = result == "no"
        return "fade", entry, won, trade_pnl(entry, won, maker)
    return None                         # 30-50c: no clear side


def run_backtest(conn, series: str, limit: int, entry_frac: float, throttle: float = 0.15):
    """agg[(strategy, maker)] = list of (entry_cents, net_cents, won); + n_attempted."""
    rows = settled_markets(conn, series, limit)
    agg: dict[tuple[str, bool], list[tuple[int, float, bool]]] = {}
    n_priced = 0
    for ticker, open_ts, close_ts, result in rows:
        time.sleep(throttle)
        try:
            q = entry_quote(series, ticker, int(open_ts), int(close_ts), entry_frac)
        except Exception:
            q = None
        if not q:
            continue
        n_priced += 1
        for maker in (False, True):
            sim = simulate_market(q, result, maker)
            if sim:
                strat, entry, won, net = sim
                agg.setdefault((strat, maker), []).append((entry, net, won))
    return agg, len(rows), n_priced


def _stats(trades: list[tuple[int, float, bool]]) -> dict:
    nets = [t[1] for t in trades]
    cost = sum(t[0] for t in trades)
    return {
        "n": len(trades),
        "win_pct": 100 * sum(t[2] for t in trades) / len(trades),
        "mean_net": statistics.mean(nets),
        "total_net_dollars": sum(nets) / 100.0,
        "return_pct": 100 * sum(nets) / cost if cost else 0.0,
    }


_ROWS = [("favorite", False), ("favorite", True), ("fade", False), ("fade", True)]


def _print_block(title: str, agg: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"  {'strategy':9s} {'fill':6s} {'n':>4s} {'win%':>6s} {'net¢/ct':>8s} {'total$':>9s} {'ret%':>7s}")
    for strat, maker in _ROWS:
        trades = agg.get((strat, maker))
        if not trades:
            continue
        s = _stats(trades)
        print(f"  {strat:9s} {'maker' if maker else 'taker':6s} {s['n']:>4d} {s['win_pct']:>5.0f}% "
              f"{s['mean_net']:>+7.1f} {s['total_net_dollars']:>+8.2f} {s['return_pct']:>+6.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("series", nargs="+")
    ap.add_argument("--limit", type=int, default=120, help="most-recent settled markets per series")
    ap.add_argument("--entry-frac", type=float, default=0.6, help="fraction of life to enter at")
    args = ap.parse_args()

    combined: dict[tuple[str, bool], list] = {}
    conn = get_connection()
    try:
        for series in args.series:
            agg, n_att, n_priced = run_backtest(conn, series, args.limit, args.entry_frac)
            _print_block(f"{series} — {n_priced}/{n_att} priced (entry @ {args.entry_frac:.0%} of life)", agg)
            for k, v in agg.items():
                combined.setdefault(k, []).extend(v)
    finally:
        conn.close()
    if len(args.series) > 1:
        _print_block("COMBINED (all series pooled)", combined)
    print("\nNote: net of Kalshi fee, held to settlement. TAKER = realistic (pay the spread); "
          "MAKER = optimistic (capture the spread, assumes the resting order fills).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
