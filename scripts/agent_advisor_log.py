"""Agent-advisor PAPER burn-in logger (B3 experiment — no orders, ever).

Runs a few minutes AFTER a city's live decision time. Recomputes the exact
baseline signal set live_trade.py saw (compute_signals_for_today pins its
price cutoff to CITY_CONFIG's decision time, so running later reproduces the
same as-of inputs), then logs TWO paired arms into paper_trades:

    "<paper_model_source> [AB-BASE]"   — the baseline live-config decisions
    "<paper_model_source> [AB-AGENT]"  — the reasoning-engine-adjusted decisions

The agent arm logs one row per baseline signal INCLUDING skips (action in
notes), so the A/B stays paired. If the engine fails, the agent arm is not
logged that day (excluded from the comparison rather than silently equal to
baseline) and the script exits nonzero so cron surfaces it.

Judged by scripts/analysis/agent_ab_report.py after the burn-in — see
docs/decisions/2026-07-22-agent-advisor-experiment.md.

Kill switch: `touch halt/AGENT` disables this logger (clean exit 0).
Calls the real Claude API (bounded: ~4 specialist + 1 debate + 1 master
calls per city per day).

Usage:
    uv run python scripts/agent_advisor_log.py --city KORD
    uv run python scripts/agent_advisor_log.py --city KMIA --dry-run
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import live_trade  # noqa: E402  (defs only at import; nothing fires)
from paper_trade_log import INSERT_SQL  # noqa: E402

from weather_markets.db import get_connection  # noqa: E402
from weather_markets.reasoning import completer_for  # noqa: E402
from weather_markets.reasoning.advisor import (  # noqa: E402
    AGENT_TAG, BASE_TAG, build_chunks, flip_signal, propose,
)

HALT_FILE = Path(__file__).resolve().parent.parent / "halt" / "AGENT"


def _yes_prob(s: dict) -> float:
    """YES-side probability of the decision basis (model_p or blend_p)."""
    return s["p_win"] if s["side"] == "yes" else 1.0 - s["p_win"]


def _threshold_for(s: dict, cfg: dict) -> float:
    if s["signal_source"] in ("blend", "union_blend_only"):
        return cfg.get("blend_edge_threshold", 0.10)
    return cfg.get("edge_threshold", live_trade.EDGE_THRESHOLD)


def _insert_row(cur, s: dict, model_source: str, logged_at, today, init_time,
                cfg: dict, notes: str, position: str, entry: int) -> None:
    cur.execute(INSERT_SQL, (
        logged_at, today, s["ticker"], model_source,
        init_time, s["ensemble_mean"], s["ensemble_std"],
        s["emos_mu"], s["emos_sigma"], _yes_prob(s),
        s["yes_bid"], s["yes_ask"], s["market_mid"], s["market_snapshot_at"],
        s["edge"], _threshold_for(s, cfg), position, entry, notes,
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, choices=list(live_trade.CITY_CONFIG))
    parser.add_argument("--dry-run", action="store_true",
                        help="Print decisions without inserting paper_trades rows.")
    args = parser.parse_args()

    if HALT_FILE.exists():
        print(f"halt/AGENT present ({HALT_FILE.read_text().strip()}); advisor disabled. Exit 0.")
        return 0

    city = args.city
    cfg = live_trade.CITY_CONFIG[city]
    now = datetime.now(timezone.utc)
    today = now.date()
    init_time = datetime(today.year, today.month, today.day, live_trade.INIT_HOUR,
                         0, tzinfo=timezone.utc)
    base_source = f"{cfg['paper_model_source']} {BASE_TAG}"
    agent_source = f"{cfg['paper_model_source']} {AGENT_TAG}"
    print(f"=== Agent-advisor paper log: {city} {today} "
          f"(decision {cfg['decision_hour']:02d}:{cfg['decision_minute']:02d} UTC) ===")

    with get_connection() as conn:
        signals = live_trade.compute_signals_for_today(conn, city, today)
        print(f"  baseline signals: {len(signals)}")
        if not signals:
            print("  nothing fired; both arms empty today. Done.")
            return 0

        # Arm 1: baseline, exactly as live config would decide.
        if not args.dry_run:
            with conn.cursor() as cur:
                for s in signals:
                    position = "BUY_YES" if s["side"] == "yes" else "BUY_NO"
                    notes = (f"AB base; signal_source={s['signal_source']}; "
                             f"exec_path={s['exec_path']}; unit={cfg.get('unit_contracts', 0)}")
                    _insert_row(cur, s, base_source, now, today, init_time, cfg,
                                notes, position, int(s["cross_price"]))
        for s in signals:
            print(f"    BASE  {s['ticker']} {s['side'].upper()} @ {s['cross_price']}c "
                  f"edge={s['edge']:+.1%} [{s['signal_source']}]")

        # Arm 2: the reasoning engine's adjusted decisions.
        try:
            chunks = build_chunks(city, cfg, signals, conn, today)
            proposal = propose(city, cfg, signals, today, completer_for("advisor"), chunks)
        except Exception as e:
            print(f"  ENGINE FAILED ({type(e).__name__}: {e}); agent arm NOT logged today.",
                  file=sys.stderr)
            return 1

        with conn.cursor() as cur:
            for s in signals:
                adj = proposal.adjustments.get(s["ticker"])
                action = adj.action if adj else "keep"
                mult = adj.size_multiplier if adj else 1.0
                why = (adj.why[:200] if adj else "")
                row = s
                position = "BUY_YES" if s["side"] == "yes" else "BUY_NO"
                entry = int(s["cross_price"])
                if action == "flip":
                    row = flip_signal(s)
                    position = "BUY_YES" if row["side"] == "yes" else "BUY_NO"
                    entry = int(row["cross_price"])
                notes = (f"AB agent; action={action}; mult={mult:.2f}; "
                         f"debate_rounds={proposal.debate_rounds}; "
                         f"ungrounded={proposal.n_ungrounded}; why={why}")
                print(f"    AGENT {s['ticker']} -> {action} x{mult:.2f}"
                      f"{' (' + why[:100] + ')' if why else ''}")
                if not args.dry_run:
                    _insert_row(cur, row, agent_source, now, today, init_time, cfg,
                                notes, position, entry)

    if args.dry_run:
        print("\n  DRY-RUN — nothing inserted.")
    else:
        print(f"\n  logged {len(signals)} row(s) per arm "
              f"({base_source!r} / {agent_source!r}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
