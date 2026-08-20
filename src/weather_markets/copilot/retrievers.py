"""Ops-copilot Retriever backend for the B0 reasoning engine.

Pure chunk builders — each takes an already-fetched metrics object (see
metrics.py for the impure DB/API calls) and returns tagged `Chunk`s, exactly
mirroring the fetch/render split in `weather_markets.expansion.retrievers`.
Tags key into `docs/matrices/ops_digest.json`'s point/sub-point ids.
Scope filtering + keyword ranking is `MockRetriever`'s existing machinery —
these functions supply real data, not a new retrieval algorithm.
"""
from __future__ import annotations

from typing import Sequence

from weather_markets.reasoning import Chunk, MockRetriever, Retriever

from weather_markets.copilot.metrics import (
    WINDOW_DAYS,
    CalibrationMetrics,
    ConfigDriftMetrics,
    DataHealthMetrics,
    ExecutionMetrics,
    RegimeMetrics,
)

_MAX_EVIDENCE = 60  # generous: one daily digest run, not a per-request budget


def calibration_chunks(metrics: Sequence[CalibrationMetrics]) -> list[Chunk]:
    out = []
    for m in metrics:
        if m.n_recent < 5 and m.n_prior < 5:
            continue  # too little settled history to say anything
        out.append(
            Chunk(
                id=f"calib:{m.station_id}",
                text=(
                    f"{m.station_id} calibration (Brier score, lower=better): last {WINDOW_DAYS}d "
                    f"{m.brier_recent if m.brier_recent is not None else 'n/a'} (n={m.n_recent}) vs "
                    f"prior {WINDOW_DAYS}d {m.brier_prior if m.brier_prior is not None else 'n/a'} "
                    f"(n={m.n_prior}). Computed from live_trades.model_prob_yes vs settlement outcome."
                ),
                source="live_trades",
                ref=f"live_trades station={m.station_id}",
                tags=["calibration_drift", "calibration_drift.brier"],
            )
        )
    return out


def regime_chunks(metrics: Sequence[RegimeMetrics]) -> list[Chunk]:
    out = []
    for m in metrics:
        if m.n_error_recent >= 3:
            out.append(
                Chunk(
                    id=f"regime:{m.station_id}:error",
                    text=(
                        f"{m.station_id} forecast error (mean |ensemble_mean - actual high|, degF): "
                        f"last {WINDOW_DAYS}d {m.forecast_error_recent} (n={m.n_error_recent}) vs "
                        f"prior {WINDOW_DAYS}d {m.forecast_error_prior}."
                    ),
                    source="paper_trades+observations",
                    ref=f"paper_trades/observations station={m.station_id}",
                    tags=["regime_detection", "regime_detection.forecast_error"],
                )
            )
        if m.n_edge_recent >= 3:
            out.append(
                Chunk(
                    id=f"regime:{m.station_id}:edge",
                    text=(
                        f"{m.station_id} mean |edge|: last {WINDOW_DAYS}d {m.abs_edge_recent} "
                        f"(n={m.n_edge_recent}) vs prior {WINDOW_DAYS}d {m.abs_edge_prior}. A falling "
                        "trend suggests edge decay; a rising trend suggests a regime shift worth checking."
                    ),
                    source="paper_trades",
                    ref=f"paper_trades station={m.station_id}",
                    tags=["regime_detection", "regime_detection.edge"],
                )
            )
    return out


def execution_chunks(metrics: Sequence[ExecutionMetrics]) -> list[Chunk]:
    out = []
    for m in metrics:
        if m.n_recent < 3:
            continue
        out.append(
            Chunk(
                id=f"exec:{m.station_id}:fill",
                text=(
                    f"{m.station_id} fill rate (filled+partial / resolved orders): last {WINDOW_DAYS}d "
                    f"{m.fill_rate_recent} (n={m.n_recent}) vs prior {WINDOW_DAYS}d {m.fill_rate_prior}. "
                    f"Rejected/expired in the last {WINDOW_DAYS}d: {m.n_rejected_or_expired_recent}."
                ),
                source="live_trades",
                ref=f"live_trades station={m.station_id}",
                tags=["execution_anomalies", "execution_anomalies.fill_rate"],
            )
        )
        if m.n_crossed_recent >= 3:
            out.append(
                Chunk(
                    id=f"exec:{m.station_id}:cross",
                    text=(
                        f"{m.station_id}: {m.n_crossed_recent} orders crossed the book in the last "
                        f"{WINDOW_DAYS}d; avg (cross_price - limit_price) = "
                        f"{m.avg_cross_over_limit_cents_recent}c. A rising gap suggests adverse "
                        "selection or a widening spread regime."
                    ),
                    source="live_trades",
                    ref=f"live_trades station={m.station_id}",
                    tags=["execution_anomalies", "execution_anomalies.adverse_selection"],
                )
            )
    return out


def config_drift_chunks(metrics: Sequence[ConfigDriftMetrics]) -> list[Chunk]:
    out = []
    for m in metrics:
        out.append(
            Chunk(
                id=f"config:{m.station_id}:pnl",
                text=(
                    f"{m.station_id} live daily realized P&L, last {WINDOW_DAYS}d ({m.n_days} trading "
                    f"days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = "
                    f"{m.naive_sharpe if m.naive_sharpe is not None else 'n/a (too few days)'}. "
                    f"Series: {[round(x, 2) for x in m.daily_pnl_dollars]}"
                ),
                source="live_trades",
                ref=f"live_trades station={m.station_id}",
                tags=["config_drift", "config_drift.pnl"],
            )
        )
        if m.doc_text:
            out.append(
                Chunk(
                    id=f"config:{m.station_id}:rationale",
                    text=f"Committed rationale/config for {m.station_id}:\n{m.doc_text}",
                    source="docs/decisions",
                    ref=f"decision doc for {m.station_id}",
                    tags=["config_drift", "config_drift.rationale"],
                )
            )
    return out


def data_health_chunks(m: DataHealthMetrics) -> list[Chunk]:
    from datetime import datetime, timezone

    out = [
        Chunk(
            id="health:forecasts",
            text=(
                "Most recent forecast init_time per model (any live station): "
                + ", ".join(
                    f"{model}={ts.isoformat() if ts else 'NONE INGESTED'}"
                    for model, ts in sorted(m.forecast_max_init.items())
                )
            ),
            source="forecasts",
            ref="forecasts",
            tags=["data_health", "data_health.ingest"],
        ),
        Chunk(
            id="health:observations",
            text=(
                "Days behind today for latest observation, per live station: "
                + ", ".join(
                    f"{sid}={d if d is not None else 'NO DATA'}"
                    for sid, d in sorted(m.observation_days_behind.items())
                )
            ),
            source="observations",
            ref="observations",
            tags=["data_health", "data_health.ingest"],
        ),
        Chunk(
            id="health:prices",
            text=(
                f"Latest Kalshi price snapshot is "
                + (f"{m.price_snapshot_age_minutes:.1f} minutes old" if m.price_snapshot_age_minutes is not None
                   else "MISSING — prices table empty")
                + " (every-5-min cron; anything over ~30 min suggests the snapshot cron stalled)."
            ),
            source="prices",
            ref="prices",
            tags=["data_health", "data_health.ingest"],
        ),
    ]
    if m.equity_snapshot_date is None:
        out.append(
            Chunk(
                id="health:equity",
                text="account_equity_snapshots is EMPTY — the daily equity cron has never run or is failing.",
                source="account_equity_snapshots",
                ref="account_equity_snapshots",
                tags=["data_health", "data_health.account"],
            )
        )
    else:
        out.append(
            Chunk(
                id="health:equity",
                text=(
                    f"Latest account_equity_snapshots row: {m.equity_snapshot_date} "
                    f"({m.equity_snapshot_age_days}d old). Reconciliation identity gap "
                    f"(account_value - (deposits+credit-withdrawals+pnl)) = "
                    f"${m.equity_identity_gap_dollars}. Should be ~$0; a large gap means the "
                    "snapshot or the underlying Kalshi pull is wrong."
                ),
                source="account_equity_snapshots",
                ref="account_equity_snapshots",
                tags=["data_health", "data_health.account"],
            )
        )
    return out


def settlement_chunks(kalshi, days: int = WINDOW_DAYS) -> list[Chunk]:
    """Realized P&L per city from Kalshi's own settlement ledger — the
    authoritative source. Deliberately does NOT use /portfolio/fills: its
    action/side labels are documented elsewhere in this repo as unreliable for
    older markets (see scripts/analysis/kalshi_reconcile_by_city.py)."""
    from datetime import datetime, timedelta, timezone

    from weather_markets.stations import all_stations

    series_to_city = {s.kalshi_series: s.city for s in all_stations() if s.kalshi_series}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    cursor = None
    for _ in range(40):  # hard cap: 40 pages * 200 = 8000 settlements, plenty for a 45d window
        page = kalshi.get_settlements(cursor=cursor)
        rows = page.get("settlements", [])
        for s in rows:
            if (s.get("settled_time") or "")[:10] < cutoff:
                continue
            ticker = s.get("ticker", "")
            city = next((c for series, c in series_to_city.items() if series and ticker.startswith(series)), None)
            if city is None:
                continue
            rev = float(s.get("revenue") or 0) / 100.0
            cost = float(s.get("yes_total_cost_dollars") or 0) + float(s.get("no_total_cost_dollars") or 0)
            fee = float(s.get("fee_cost") or 0)
            totals[city] = totals.get(city, 0.0) + (rev - cost - fee)
            counts[city] = counts.get(city, 0) + 1
        cursor = page.get("cursor")
        if not cursor or not rows:
            break

    return [
        Chunk(
            id=f"settle:{city}",
            text=(
                f"Kalshi-settled realized P&L for {city}, last {days}d: ${total:.2f} over {counts[city]} "
                "settled markets (source: GET /portfolio/settlements, the authoritative ledger)."
            ),
            source="kalshi_settlements",
            ref="/portfolio/settlements",
            tags=["config_drift", "config_drift.pnl", "execution_anomalies"],
        )
        for city, total in sorted(totals.items())
    ]


def build_retriever(chunks: Sequence[Chunk]) -> Retriever:
    return MockRetriever(list(chunks)[:_MAX_EVIDENCE])
