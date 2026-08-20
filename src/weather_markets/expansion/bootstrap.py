"""Vertical bootstrapper: scaffold a validated-new-vertical skeleton.

Generates src/weather_markets/verticals/<slug>/ wired to the SAME pipeline
(ingest -> emos -> blend -> evaluate -> paper) with a walk-forward backtest
stub that enforces the Sharpe>2.5 deploy bar and strict as-of-decision-time
data. Nothing generated references --live: going live stays a manual operator
decision at small size.
"""

from __future__ import annotations

from pathlib import Path

from weather_markets.expansion.candidates import REPO_ROOT, Candidate

VERTICALS_ROOT = REPO_ROOT / "src" / "weather_markets" / "verticals"


def bootstrap(candidate: Candidate, root: Path = VERTICALS_ROOT) -> Path:
    slug = candidate.id.replace("-", "_")
    dest = root / slug
    if dest.exists():
        raise FileExistsError(f"{dest} already exists — refusing to overwrite")
    if candidate.kind == "category" and candidate.underlying not in (
        "daily_high_temp", "daily_low_temp", "daily_temp"
    ) and not candidate.station_id:
        dest.mkdir(parents=True)
        (dest / "README.md").write_text(_readme(candidate, full=False))
        return dest

    dest.mkdir(parents=True)
    (root / "__init__.py").touch()
    (dest / "__init__.py").write_text(f'"""Vertical scaffold for {candidate.id} — paper-only."""\n')
    (dest / "config.py").write_text(_config(candidate, slug))
    (dest / "pipeline.py").write_text(_pipeline(candidate, slug))
    (dest / "backtest_walkforward.py").write_text(_backtest(candidate, slug))
    (dest / "README.md").write_text(_readme(candidate, full=True))
    return dest


def _config(c: Candidate, slug: str) -> str:
    return f'''"""CITY_CONFIG-style entry for the {c.id} vertical (paper-only).

Copy of the live_trade.py CITY_CONFIG shape so a validated vertical can be
promoted by pasting this dict — a manual operator decision, never automated.
"""

VERTICAL_CONFIG = {{
    "{c.station_id or slug}": {{
        "city_name": "{c.id}",
        "venue": "{c.venue}",
        "series_ticker": {c.resolved_series()!r},
        "underlying": "{c.underlying}",
        "models": ["gefs", "ifs"],            # TODO: validate model set for this vertical
        "decision_hour": 15,                   # TODO: pick via entry-timing check (UTC)
        "decision_minute": 0,
        "use_blend": True,
        "edge_threshold": 0.25,                # TODO: validate on paper data before trusting
        "blend_edge_threshold": 0.10,
        "sizing_mode": "unit",
        "unit_contracts": 50,                  # minimal size if EVER promoted (operator decision)
        "max_contracts_per_trade": 50,
        "daily_loss_limit_dollars": 25.0,
        "cumulative_kill_dollars": 100.0,
        "is_active": False,                    # paper-only; promotion is manual
    }}
}}
'''


def _pipeline(c: Candidate, slug: str) -> str:
    return f'''"""Paper pipeline for {c.id}: ingest -> EMOS -> blend -> evaluate -> paper log.

Reuses the production library end to end; the TODOs are the vertical-specific
gaps, not new architecture. Run stages via:
    uv run python -m weather_markets.verticals.{slug}.pipeline
"""

from __future__ import annotations

from datetime import date

from weather_markets.aggregation import compute_combined_daily_highs, fetch_contracts_for_date
from weather_markets.db import get_connection
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.verticals.{slug}.config import VERTICAL_CONFIG

STATION = {c.station_id!r}


def ingest() -> None:
    """TODO: ensure daily forecast + observation ingest covers this vertical.
    For temperature verticals on an existing station this is already done by
    the production crons (scripts/ingest_*); a NEW station needs a STATIONS
    entry + backfill; a new underlying needs a new ingest module."""
    raise NotImplementedError


def signal(target: date) -> dict | None:
    """EMOS -> bracket probs -> blend -> edge, exactly the production shapes.
    TODO: adapt model list / underlying field for this vertical, then mirror
    scripts/paper_trade_log.py's insert into paper_trades (that table IS the
    validation record the backtest consumes)."""
    cfg = next(iter(VERTICAL_CONFIG.values()))
    conn = get_connection()
    try:
        highs = compute_combined_daily_highs(conn, STATION, target, cfg["models"])
        mu_sigma = fit_emos_rolling(conn, STATION, target, cfg["models"])
        contracts = fetch_contracts_for_date(conn, cfg["series_ticker"], target)
        probs = gaussian_to_bracket_probs(mu_sigma, contracts)
        # TODO: market mid + Benter blend (weather_markets.blend) + edge vs threshold
        return {{"target": target, "probs": probs, "highs": highs}}
    finally:
        conn.close()


if __name__ == "__main__":
    print(signal(date.today()))
'''


def _backtest(c: Candidate, slug: str) -> str:
    return f'''"""Walk-forward backtest stub for {c.id} — enforces the deploy bar.

Hard rules baked in:
- OOS Sharpe must exceed 2.5 on realistic execution to even PROPOSE going live.
- Strict no-look-ahead: only data recorded at-or-before each day's decision
  time is eligible (enforced in SQL below, not by convention).
- This script never places orders and is never wired to --live.

Run: uv run python -m weather_markets.verticals.{slug}.backtest_walkforward
"""

from __future__ import annotations

import statistics

from weather_markets.db import get_connection

DEPLOY_BAR_SHARPE = 2.5
STATION = {c.station_id!r}

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
        print(f"INSUFFICIENT DATA: {{len(rows)}} paper rows — accumulate a paper period first.")
        return 1
    daily_pnl = walk_forward(rows)
    sharpe = statistics.mean(daily_pnl) / (statistics.pstdev(daily_pnl) or float("inf")) * (252 ** 0.5)
    verdict = "CLEARS" if sharpe > DEPLOY_BAR_SHARPE else "FAILS"
    print(f"walk-forward OOS Sharpe = {{sharpe:.2f}} -> {{verdict}} the {{DEPLOY_BAR_SHARPE}} bar")
    print("Going live is a MANUAL operator decision at small size regardless of this number.")
    return 0 if sharpe > DEPLOY_BAR_SHARPE else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _readme(c: Candidate, full: bool) -> str:
    head = f"""# Vertical: {c.id}

Scaffolded by `scripts/expansion_scout.py bootstrap {c.id}` — **paper-only**.
Venue: {c.venue} | kind: {c.kind} | station: {c.station_id or "n/a"} | underlying: {c.underlying}

{c.notes or ""}
"""
    if not full:
        return head + """
This is a category candidate without a mapped station/underlying — no pipeline
scaffold was generated. Close these gaps first: identify the predictive data
source, the settlement source, and a station/series mapping; then re-run
bootstrap.
"""
    return head + """
## Validation path (in order — do not skip)

1. `pipeline.py` TODOs: ingest coverage, blend wiring, paper logging.
2. Accumulate >= 90 days of paper_trades rows for this vertical.
3. `backtest_walkforward.py`: walk-forward OOS Sharpe on realistic execution.
   The 2.5 bar gates any promotion proposal.
4. Promotion to live = manual operator decision, minimal size, halt file wired,
   pre-commit doc in docs/decisions/precommits/. Nothing here automates it.
"""
