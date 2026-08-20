"""Breadth scout CLI: find where to grow (cities, venues, categories).

Scout + factory, never a live trader. Subcommands:

  sync       Pull Kalshi series/markets catalog into expansion_* tables.
  rank       Deterministic scorecard ranking of all candidates (no LLM cost).
  assess     Full B0 reasoning-engine run for one candidate (needs
             anthropic_api_key in .env; --no-llm falls back to scorecard).
  bootstrap  Scaffold a paper-only vertical for a chosen candidate.

Usage (long syncs in tmux, per repo convention):
  uv run python scripts/expansion_scout.py sync
  uv run python scripts/expansion_scout.py rank --discover --out docs/research/md/$(date -u +%F)-expansion-scout-rank.md
  uv run python scripts/expansion_scout.py assess forecastex-miami
  uv run python scripts/expansion_scout.py bootstrap forecastex-miami
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.expansion import (
    Candidate,
    Scorecard,
    build_retriever,
    collect_metrics,
    discover_kalshi_candidates,
    load_candidates,
    score,
    sync_kalshi_catalog,
)
from weather_markets.expansion.bootstrap import bootstrap
from weather_markets.expansion.candidates import REPO_ROOT
from weather_markets.reasoning import Matrix

MATRIX_PATH = REPO_ROOT / "docs" / "matrices" / "breadth_expansion.json"


# ----- rendering --------------------------------------------------------------

def render_rank(cards: list[Scorecard]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    lines = [
        f"# Breadth-expansion ranked opportunity report — {now}",
        "",
        "Deterministic scorecard (no LLM). Verdicts: GO is always paper-first;",
        "nothing goes live without the walk-forward OOS Sharpe > 2.5 bar or an",
        "explicit operator override. Ceiling estimates are heuristic — run the",
        "walk-book capacity tools before sizing anything.",
        "",
        "| # | candidate | verdict | score | est. ceiling | fee/edge | deploy-bar status |",
        "|---|-----------|---------|-------|--------------|----------|-------------------|",
    ]
    for i, sc in enumerate(cards, 1):
        ceil = f"~{sc.ceiling_contracts}" if sc.ceiling_contracts else "unknown"
        lines.append(
            f"| {i} | {sc.candidate.id} | {sc.verdict} | {sc.total}/{sc.max_total} "
            f"| {ceil} | {sc.fee_note} | {sc.bar_note} |"
        )
    lines.append("")
    if len(cards) > 20:
        lines += [f"_Detail sections below cover the top 20 of {len(cards)} candidates; "
                  "the table above is complete._", ""]
    for sc in cards[:20]:
        lines += [f"## {sc.candidate.id}", ""]
        if sc.candidate.notes:
            lines += [sc.candidate.notes, ""]
        for fp, (s, reason) in sc.points.items():
            lines.append(f"- **{fp}** {s}/2 — {reason}")
        lines.append("")
    return "\n".join(lines)


def render_assess(sc: Scorecard, result) -> str:
    lines = [
        f"# Assessment: {sc.candidate.id}",
        "",
        f"**Engine decision** (debate rounds: {result.debate_rounds}):",
        "",
        result.decision.text,
        "",
        "## Grounded claims",
        "",
    ]
    for cl in result.decision.grounded:
        lines.append(f"- {cl.text} `[{', '.join(cl.chunk_ids)}]`")
    if result.decision.ungrounded:
        lines += ["", "## FLAGGED (ungrounded — not asserted)", ""]
        for cl in result.decision.ungrounded:
            lines.append(f"- {cl.text}")
    lines += ["", "## Specialist findings", ""]
    for r in result.reports:
        lines += [f"### {r.point_name}", "", r.summary, ""]
    lines += ["", "## Deterministic scorecard appendix", "", render_scorecard(sc)]
    return "\n".join(lines)


def render_scorecard(sc: Scorecard) -> str:
    lines = [f"Verdict: **{sc.verdict}** ({sc.total}/{sc.max_total})", ""]
    for fp, (s, reason) in sc.points.items():
        lines.append(f"- {fp} {s}/2 — {reason}")
    lines += ["", f"Liquidity ceiling est.: {sc.ceiling_contracts or 'unknown'} contracts",
              f"Fees vs edge: {sc.fee_note}", f"Deploy bar: {sc.bar_note}"]
    return "\n".join(lines)


# ----- commands ---------------------------------------------------------------

def all_candidates(conn, discover: bool) -> list[Candidate]:
    cands = load_candidates()
    if discover:
        cands += discover_kalshi_candidates(conn, cands)
    return cands


def cmd_sync(args) -> int:
    conn = get_connection()
    try:
        stats = sync_kalshi_catalog(
            conn, args.category, settled_pages=args.settled_pages, series_like=args.series
        )
    finally:
        conn.close()
    print(f"synced: {stats}")
    return 0


def cmd_rank(args) -> int:
    conn = get_connection()
    try:
        cands = all_candidates(conn, args.discover)
        cards = sorted((score(collect_metrics(conn, c)) for c in cands),
                       key=lambda s: s.total, reverse=True)
    finally:
        conn.close()
    text = render_rank(cards)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"\n[written to {args.out}]", file=sys.stderr)
    return 0


def _find(conn, candidate_id: str, discover: bool = True) -> Candidate:
    for c in all_candidates(conn, discover):
        if c.id == candidate_id:
            return c
    raise SystemExit(f"unknown candidate {candidate_id!r} — see `rank --discover`")


def cmd_assess(args) -> int:
    conn = get_connection()
    try:
        cand = _find(conn, args.candidate)
        metrics = collect_metrics(conn, cand)
    finally:
        conn.close()
    sc = score(metrics)
    if args.no_llm:
        text = f"# Assessment (scorecard-only): {cand.id}\n\n" + render_scorecard(sc)
    else:
        from weather_markets.reasoning import ReasoningEngine, completer_for

        matrix = Matrix.load(MATRIX_PATH)
        # B1 defaults to the subscription CLI backend; REASONING_BACKEND=api overrides
        engine = ReasoningEngine(build_retriever(metrics), completer_for("expansion"))
        question = (
            f"Should we expand into candidate '{cand.id}' (venue {cand.venue}, kind "
            f"{cand.kind}, underlying {metrics.underlying})? Decide go/no-go for a "
            "PAPER-FIRST vertical. Address: specific data sources needed, expected "
            "edge vs fees, the liquidity ceiling, and whether it could plausibly "
            "clear the walk-forward OOS Sharpe > 2.5 deploy bar or needs a paper-only "
            "period first. The market is efficient — do not propose smarter/bigger/"
            "faster model angles."
        )
        result = engine.run(question, matrix)
        text = render_assess(sc, result)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"\n[written to {args.out}]", file=sys.stderr)
    return 0


def cmd_bootstrap(args) -> int:
    conn = get_connection()
    try:
        cand = _find(conn, args.candidate)
    finally:
        conn.close()
    dest = bootstrap(cand)
    print(f"scaffolded {dest} (paper-only; see its README for the validation path)")
    return 0


# ----- strategy assessment (strategy x market, adversarial) -------------------

def render_strategy_assess(strat, cand, result) -> str:
    lines = [
        f"# Strategy assessment: {strat.id} on {cand.id}",
        "",
        f"**{strat.title}** — market {cand.id}, venue {cand.venue}",
        "",
        f"**Engine decision** (debate rounds: {result.debate_rounds}):",
        "",
        result.decision.text,
        "",
        "## Grounded claims",
        "",
    ]
    for cl in result.decision.grounded:
        lines.append(f"- {cl.text} `[{', '.join(cl.chunk_ids)}]`")
    if result.decision.ungrounded:
        lines += ["", "## FLAGGED (ungrounded — not asserted)", ""]
        for cl in result.decision.ungrounded:
            lines.append(f"- {cl.text}")
    lines += ["", "## Specialist findings", ""]
    for r in result.reports:
        lines += [f"### {r.point_name}", "", r.summary, ""]
    return "\n".join(lines)


def cmd_strategy_rank(args) -> int:
    from fnmatch import fnmatch

    from weather_markets.expansion.scorecard import scaling_summary
    from weather_markets.expansion.strategy_retrievers import load_strategies

    conn = get_connection()
    try:
        cands = all_candidates(conn, discover=True)
        strategies = load_strategies()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        out_lines = [
            f"# Strategy x market scalability triage — {now}",
            "",
            "Deterministic (no LLM). Compare markets on realistic scale before spending an",
            "assess run. Ceilings are proxies off realized volume — run walk_book_capacity.py",
            "to measure. `strategy-assess <strategy> <market>` for the adversarial verdict.",
            "",
        ]
        for st in strategies:
            markets = [c for c in cands if any(fnmatch(c.id, g) for g in st.applies_to)]
            rows = []
            for c in markets:
                m = collect_metrics(conn, c)
                ceiling, path, _ = scaling_summary(m)
                rows.append((m.avg_volume or 0.0, c.id, c.venue, m.avg_volume, ceiling, path))
            rows.sort(reverse=True)  # deepest market first
            out_lines += [
                f"## {st.id} — {st.title}",
                "",
                f"_Preconditions: {st.preconditions.strip()}_",
                "",
                "| market | venue | avg volume | scale ceiling | scaling path |",
                "|--------|-------|-----------|---------------|--------------|",
            ]
            for _, cid, venue, vol, ceiling, path in rows:
                volstr = f"{vol:,.0f}" if vol else "unknown"
                out_lines.append(f"| {cid} | {venue} | {volstr} | {ceiling} | {path} |")
            out_lines.append("")
    finally:
        conn.close()
    text = "\n".join(out_lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"\n[written to {args.out}]", file=sys.stderr)
    return 0


def cmd_strategy_assess(args) -> int:
    from weather_markets.expansion.strategy_retrievers import (
        STRATEGY_MATRIX,
        build_strategy_retriever,
        load_strategies,
    )
    from weather_markets.reasoning import ReasoningEngine, completer_for

    strat = next((s for s in load_strategies() if s.id == args.strategy), None)
    if strat is None:
        raise SystemExit(f"unknown strategy {args.strategy!r} — see docs/strategies/strategies.yaml")

    conn = get_connection()
    try:
        cand = _find(conn, args.market)
        metrics = collect_metrics(conn, cand)
    finally:
        conn.close()

    try:
        retriever = build_strategy_retriever(metrics)  # lints corpus, raises on bad tags
    except ValueError as e:
        raise SystemExit(str(e))

    matrix = Matrix.load(STRATEGY_MATRIX)
    # subscription CLI backend by default (REASONING_BACKEND=api overrides)
    engine = ReasoningEngine(retriever, completer_for("expansion"))
    question = strat.question_frame.format(
        market=cand.id,
        venue=metrics.venue.name,
        avg_volume=f"{metrics.avg_volume:,.0f}" if metrics.avg_volume else "unknown",
    )
    result = engine.run(question, matrix)
    text = render_strategy_assess(strat, cand, result)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"\n[written to {args.out}]", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="pull Kalshi catalog into expansion_* tables")
    s.add_argument("--category", action="append", default=None,
                   help="Kalshi category (repeatable; default: Climate and Weather)")
    s.add_argument("--settled-pages", type=int, default=3,
                   help="settled-history depth per series, 200 markets/page (default 3)")
    s.add_argument("--series", default=None, help="substring filter on series ticker")
    s.set_defaults(fn=cmd_sync)

    r = sub.add_parser("rank", help="rank all candidates (deterministic, no LLM)")
    r.add_argument("--discover", action="store_true", help="add auto-discovered catalog series")
    r.add_argument("--out", default=None, help="also write the markdown report here")
    r.set_defaults(fn=cmd_rank)

    a = sub.add_parser("assess", help="full reasoning-engine assessment of one candidate")
    a.add_argument("candidate")
    a.add_argument("--no-llm", action="store_true", help="scorecard only, no API calls")
    a.add_argument("--out", default=None)
    a.set_defaults(fn=cmd_assess)

    b = sub.add_parser("bootstrap", help="scaffold a paper-only vertical for a candidate")
    b.add_argument("candidate")
    b.set_defaults(fn=cmd_bootstrap)

    sr = sub.add_parser("strategy-rank",
                        help="deterministic strategy x market scalability triage (no LLM)")
    sr.add_argument("--out", default=None, help="also write the markdown report here")
    sr.set_defaults(fn=cmd_strategy_rank)

    sa = sub.add_parser("strategy-assess",
                        help="reasoning-engine assessment of a strategy on a market")
    sa.add_argument("strategy", help="strategy id from docs/strategies/strategies.yaml")
    sa.add_argument("market", help="candidate id (the market/venue) — see `rank --discover`")
    sa.add_argument("--out", default=None)
    sa.set_defaults(fn=cmd_strategy_assess)

    args = p.parse_args()
    if args.cmd == "sync" and not args.category:
        args.category = ["Climate and Weather"]
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
