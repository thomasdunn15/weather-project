"""A/B verdict for the agent-advisor experiment: agent arm vs baseline arm.

Reads the paired paper_trades arms written by scripts/agent_advisor_log.py
("... [AB-BASE]" / "... [AB-AGENT]"), settles them against observed highs
(contract_resolved_yes — same convention as the dashboard backtest), and
reports per city and overall:

    n trades / wins, Brier (YES prob vs YES outcome), gross and net P&L
    after taker fees, max drawdown, annualized Sharpe (daily P&L, same
    formula as diagnostic_city_params.py), and the deploy bar (Sharpe > 2.5).

Verdict per city: BEATS BASELINE / DOES NOT BEAT / INSUFFICIENT DATA.
Judgment criteria: docs/decisions/2026-07-22-agent-advisor-experiment.md
(>= 30 settled paired days, agent net > base net AND agent Sharpe > base
Sharpe out-of-sample; live still requires the Sharpe > 2.5 bar + operator
override).

Both arms are scored identically: cross entry (entry_price_cents), taker
fee, unit sizing (--unit, default 100 contracts), agent rows scaled by the
mult=X.XX recorded in notes (skip rows -> 0 contracts but still count as
paired decisions).

Usage:
    uv run python scripts/analysis/agent_ab_report.py [--unit 100]
"""
import argparse
import math
import re
from collections import defaultdict
from statistics import mean, stdev

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes

# Fee + tag conventions come from the modules that define them.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from live_trade import kalshi_fee_cents  # noqa: E402
from weather_markets.reasoning.advisor import AGENT_TAG, BASE_TAG  # noqa: E402

MULT_RE = re.compile(r"mult=([0-9.]+)")

QUERY = """
SELECT pt.model_source, pt.target_date, pt.ticker, pt.position,
       pt.entry_price_cents, pt.model_prob_yes, pt.notes,
       c.station_id, c.bracket_type, c.strike_low, c.strike_high,
       o.high_temp_f
FROM paper_trades pt
JOIN contracts c ON c.ticker = pt.ticker
LEFT JOIN observations o ON o.station_id = c.station_id AND o.date = pt.target_date
WHERE pt.model_source LIKE %s
ORDER BY pt.target_date, pt.ticker
"""


def load_arm(conn, tag: str) -> dict[str, list[dict]]:
    """Rows by station, settled + pending. Settled rows get won/net fields."""
    by_station: dict[str, list[dict]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(QUERY, (f"%{tag}",))
        for (src, td, ticker, pos, entry, p_yes, notes,
             station, bt, sl, sh, high) in cur.fetchall():
            m = MULT_RE.search(notes or "")
            mult = float(m.group(1)) if m else 1.0
            row = {"date": td, "ticker": ticker, "pos": pos, "entry": int(entry),
                   "p_yes": float(p_yes), "mult": mult, "settled": high is not None}
            if high is not None:
                yes_won = contract_resolved_yes(
                    int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
                row["yes_won"] = yes_won
                row["won"] = yes_won if pos == "BUY_YES" else not yes_won
            by_station[station].append(row)
    return by_station


def score(rows: list[dict], unit: int) -> dict | None:
    """Metrics over SETTLED rows. Net = unit*mult contracts at cross entry,
    taker fee per contract (identical treatment for both arms)."""
    settled = [r for r in rows if r["settled"]]
    if not settled:
        return None
    daily = defaultdict(float)
    net_total = 0.0
    briers, wins, traded = [], 0, 0
    for r in settled:
        contracts = unit * r["mult"]
        if contracts < 1:
            continue  # agent skip — a decision, not a trade
        # Brier over the TRADED set: measures the calibration of what this
        # arm actually chose to hold (selection is the agent's only lever
        # on calibration — it never produces its own probabilities).
        briers.append((r["p_yes"] - (1.0 if r["yes_won"] else 0.0)) ** 2)
        traded += 1
        wins += int(r["won"])
        entry = r["entry"]
        fee = kalshi_fee_cents(entry, maker=False)
        pnl = contracts * ((100 - entry if r["won"] else -entry) - fee) / 100.0
        daily[r["date"]] += pnl
        net_total += pnl
    dates = sorted(daily)
    pnls = [daily[d] for d in dates]
    eq = peak = maxdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    sharpe = None
    if len(pnls) >= 3:
        sd = stdev(pnls)
        span = (dates[-1] - dates[0]).days
        if sd > 0 and span > 0:
            ppy = len(pnls) / (span / 365.25)
            sharpe = (mean(pnls) / sd) * math.sqrt(ppy)
    return {
        "n_decisions": len(settled), "n_traded": traded, "wins": wins,
        "n_days": len(dates), "brier": mean(briers) if briers else None,
        "net": net_total, "maxdd": maxdd, "sharpe": sharpe,
    }


def fmt(m: dict | None, unit: int) -> str:
    if m is None:
        return "    (no settled rows)"
    shp = "n/a" if m["sharpe"] is None else f"{m['sharpe']:.2f}"
    win = f"{m['wins']}/{m['n_traded']}" if m["n_traded"] else "0/0"
    brier = "n/a" if m["brier"] is None else f"{m['brier']:.4f}"
    return (f"    decisions={m['n_decisions']} traded={m['n_traded']} days={m['n_days']} "
            f"wins={win}  Brier={brier}  "
            f"net=${m['net']:+,.2f} (unit {unit})  maxDD=${m['maxdd']:,.2f}  Sharpe={shp}")


def verdict(base: dict | None, agent: dict | None, min_days: int) -> str:
    if base is None or agent is None or min(base["n_days"], agent["n_days"]) < min_days:
        have = 0 if (base is None or agent is None) else min(base["n_days"], agent["n_days"])
        return f"INSUFFICIENT DATA ({have}/{min_days} settled paired days) — keep burning in."
    beats_pnl = agent["net"] > base["net"]
    beats_sharpe = (agent["sharpe"] is not None and base["sharpe"] is not None
                    and agent["sharpe"] > base["sharpe"])
    bar = (agent["sharpe"] is not None and agent["sharpe"] > 2.5)
    if beats_pnl and beats_sharpe:
        return ("AGENT BEATS BASELINE (net + Sharpe). "
                + ("Clears the Sharpe>2.5 live bar — live use still requires an "
                   "operator override at tiny size." if bar
                   else "Does NOT clear the Sharpe>2.5 live bar — stay paper."))
    return "AGENT DOES NOT BEAT BASELINE — keep paper or kill (halt/AGENT)."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unit", type=int, default=100,
                        help="Contracts per baseline trade for scoring (default 100).")
    parser.add_argument("--min-days", type=int, default=30,
                        help="Settled paired days required for a verdict (default 30).")
    args = parser.parse_args()

    with get_connection() as conn:
        base_arm = load_arm(conn, BASE_TAG)
        agent_arm = load_arm(conn, AGENT_TAG)

    stations = sorted(set(base_arm) | set(agent_arm))
    if not stations:
        print("No [AB-BASE]/[AB-AGENT] rows in paper_trades yet — has the burn-in cron run?")
        return

    print(f"=== Agent-advisor A/B report (unit={args.unit}, taker fees, cross entry) ===")
    all_base, all_agent = [], []
    for st in stations:
        b, a = base_arm.get(st, []), agent_arm.get(st, [])
        # PAIRED days only: if the engine failed one day, the agent arm has no
        # rows for it — scoring base's extra days would skew the comparison.
        paired = {r["date"] for r in b} & {r["date"] for r in a}
        b = [r for r in b if r["date"] in paired]
        a = [r for r in a if r["date"] in paired]
        all_base += b
        all_agent += a
        mb, ma = score(b, args.unit), score(a, args.unit)
        print(f"\n{st}:")
        print(f"  BASE:\n{fmt(mb, args.unit)}")
        print(f"  AGENT:\n{fmt(ma, args.unit)}")
        print(f"  VERDICT: {verdict(mb, ma, args.min_days)}")

    mb, ma = score(all_base, args.unit), score(all_agent, args.unit)
    print("\nALL CITIES:")
    print(f"  BASE:\n{fmt(mb, args.unit)}")
    print(f"  AGENT:\n{fmt(ma, args.unit)}")
    print(f"  VERDICT: {verdict(mb, ma, args.min_days)}")


if __name__ == "__main__":
    main()
