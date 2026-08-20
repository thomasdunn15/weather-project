"""Read-only DB fetch layer for the ops copilot.

Impure: every function here takes a live `conn` and issues SQL against the
`weather` DB. Pure chunk-building lives in `retrievers.py` — mirrors the
fetch/render split in `weather_markets.expansion.retrievers` so chunk logic
stays testable without a database (construct a metrics dataclass by hand).

Nothing here writes anything or touches trading. `live_cities()` derives the
active universe from `live_trades` itself (not a hardcoded city list) so this
module never goes stale as the live universe changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

WINDOW_DAYS = 45


def _mean(xs: list[float] | None) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _bucket(rows, now: datetime, window_days: int = WINDOW_DAYS):
    """rows: iterable of (station_id, value, ts). Splits into a recent window
    (last `window_days`) and the prior window of the same length just before
    it, keyed by station_id. Rows with a null value or timestamp are dropped."""
    recent: dict[str, list[float]] = {}
    prior: dict[str, list[float]] = {}
    recent_cut = now - timedelta(days=window_days)
    prior_cut = now - timedelta(days=2 * window_days)
    for station_id, value, ts in rows:
        if value is None or ts is None:
            continue
        bucket = recent if ts >= recent_cut else prior if ts >= prior_cut else None
        if bucket is not None:
            bucket.setdefault(station_id, []).append(float(value))
    return recent, prior


def live_cities(conn, lookback_days: int = 90) -> list[str]:
    """Station ids with at least one live_trades row in the lookback window —
    the actual active universe, not a hardcoded list."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.station_id
            FROM live_trades lt JOIN contracts c ON c.ticker = lt.ticker
            WHERE lt.placed_at >= %s
            """,
            (datetime.now(timezone.utc) - timedelta(days=lookback_days),),
        )
        return sorted(r[0] for r in cur.fetchall())


# ----- 1. calibration drift ---------------------------------------------------

@dataclass
class CalibrationMetrics:
    station_id: str
    n_recent: int
    brier_recent: float | None
    n_prior: int
    brier_prior: float | None


def collect_calibration(conn, now: datetime | None = None) -> list[CalibrationMetrics]:
    now = now or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.station_id,
                   POWER(lt.model_prob_yes - (CASE lt.settlement WHEN 'yes' THEN 1.0 ELSE 0.0 END), 2),
                   lt.settlement_time
            FROM live_trades lt JOIN contracts c ON c.ticker = lt.ticker
            WHERE lt.settlement IS NOT NULL AND lt.model_prob_yes IS NOT NULL
              AND lt.settlement_time >= %s
            """,
            (now - timedelta(days=2 * WINDOW_DAYS),),
        )
        rows = cur.fetchall()
    recent, prior = _bucket(rows, now)
    return [
        CalibrationMetrics(
            station_id=s,
            n_recent=len(recent.get(s, [])),
            brier_recent=_mean(recent.get(s)),
            n_prior=len(prior.get(s, [])),
            brier_prior=_mean(prior.get(s)),
        )
        for s in sorted(set(recent) | set(prior))
    ]


# ----- 2. regime detection -----------------------------------------------------

@dataclass
class RegimeMetrics:
    station_id: str
    n_error_recent: int
    forecast_error_recent: float | None  # mean |ensemble_mean - actual high|, degF
    forecast_error_prior: float | None
    n_edge_recent: int
    abs_edge_recent: float | None
    abs_edge_prior: float | None


def collect_regime(conn, stations: list[str], now: datetime | None = None) -> list[RegimeMetrics]:
    """Forecast-error and edge trend, scoped to `stations` (the live universe —
    paper-only research cities aren't operator-actionable here)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=2 * WINDOW_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.station_id, ABS(pt.ensemble_mean - o.high_temp_f), pt.target_date
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            JOIN observations o ON o.station_id = c.station_id AND o.date = pt.target_date
            WHERE pt.target_date >= %s AND pt.ensemble_mean IS NOT NULL AND o.high_temp_f IS NOT NULL
              AND c.station_id = ANY(%s)
            """,
            (since.date(), stations),
        )
        error_rows = [(sid, val, datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc))
                      for sid, val, d in cur.fetchall()]
        cur.execute(
            """
            SELECT c.station_id, ABS(pt.edge), pt.target_date
            FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
            WHERE pt.target_date >= %s AND pt.edge IS NOT NULL AND c.station_id = ANY(%s)
            """,
            (since.date(), stations),
        )
        edge_rows = [(sid, val, datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc))
                     for sid, val, d in cur.fetchall()]
    err_recent, err_prior = _bucket(error_rows, now)
    edge_recent, edge_prior = _bucket(edge_rows, now)
    stations = sorted(set(err_recent) | set(err_prior) | set(edge_recent) | set(edge_prior))
    return [
        RegimeMetrics(
            station_id=s,
            n_error_recent=len(err_recent.get(s, [])),
            forecast_error_recent=_mean(err_recent.get(s)),
            forecast_error_prior=_mean(err_prior.get(s)),
            n_edge_recent=len(edge_recent.get(s, [])),
            abs_edge_recent=_mean(edge_recent.get(s)),
            abs_edge_prior=_mean(edge_prior.get(s)),
        )
        for s in stations
    ]


# ----- 3. execution anomalies --------------------------------------------------

@dataclass
class ExecutionMetrics:
    station_id: str
    n_recent: int
    fill_rate_recent: float | None
    fill_rate_prior: float | None
    n_crossed_recent: int
    avg_cross_over_limit_cents_recent: float | None
    n_rejected_or_expired_recent: int


def collect_execution(conn, now: datetime | None = None) -> list[ExecutionMetrics]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=2 * WINDOW_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.station_id, lt.fill_status, lt.cross_price_cents, lt.limit_price_cents, lt.placed_at
            FROM live_trades lt JOIN contracts c ON c.ticker = lt.ticker
            WHERE lt.placed_at >= %s AND lt.fill_status NOT IN ('pending')
            """,
            (since,),
        )
        rows = cur.fetchall()
    recent_cut = now - timedelta(days=WINDOW_DAYS)
    prior_cut = now - timedelta(days=2 * WINDOW_DAYS)
    by_station: dict[str, dict[str, list]] = {}
    for sid, status, cross, limit, ts in rows:
        if ts is None:
            continue
        window = "recent" if ts >= recent_cut else "prior" if ts >= prior_cut else None
        if window is None:
            continue
        bucket = by_station.setdefault(sid, {"recent": [], "prior": []})[window]
        bucket.append((status, cross, limit))

    out = []
    for sid, windows in sorted(by_station.items()):
        def fill_rate(bucket):
            if not bucket:
                return None
            filled = sum(1 for status, *_ in bucket if status in ("filled", "partial"))
            return round(filled / len(bucket), 4)

        recent = windows["recent"]
        crossed = [(cross, limit) for status, cross, limit in recent if cross is not None and limit is not None]
        out.append(
            ExecutionMetrics(
                station_id=sid,
                n_recent=len(recent),
                fill_rate_recent=fill_rate(recent),
                fill_rate_prior=fill_rate(windows["prior"]),
                n_crossed_recent=len(crossed),
                avg_cross_over_limit_cents_recent=_mean([c - l for c, l in crossed]),
                n_rejected_or_expired_recent=sum(
                    1 for status, *_ in recent if status in ("rejected", "expired")
                ),
            )
        )
    return out


# ----- 4. config drift ----------------------------------------------------------

# Source-of-truth doc(s) per live city — the actual committed rationale/config,
# read verbatim so the LLM compares live numbers against real text, not a
# number we guessed. Update when a new precommit changes a city's config.
STATION_DECISION_DOCS: dict[str, list[str]] = {
    "KORD": ["docs/decisions/precommits/chicago-resume-2026-06-07.md",
             "docs/decisions/precommits/chicago-miami-live.md"],
    "KMIA": ["docs/decisions/precommits/miami-resume-2026-06-10.md"],
    "KDFW": ["docs/decisions/2026-06-22-dallas-live-override.md"],
    "KPHX": ["docs/decisions/2026-07-10-phoenix-live-override.md"],
}
_MAX_DOC_CHARS = 2000


@dataclass
class ConfigDriftMetrics:
    station_id: str
    n_days: int
    daily_pnl_dollars: list[float]  # most recent WINDOW_DAYS, oldest first
    naive_sharpe: float | None      # mean/std of daily_pnl_dollars — a proxy, not the backtest Sharpe
    doc_text: str  # concatenated decision-doc excerpts, "" if none on file


def collect_config_drift(conn, repo_root, now: datetime | None = None) -> list[ConfigDriftMetrics]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.station_id, lt.placed_at::date, SUM(lt.realized_pnl_cents) / 100.0
            FROM live_trades lt JOIN contracts c ON c.ticker = lt.ticker
            WHERE lt.placed_at >= %s AND lt.realized_pnl_cents IS NOT NULL
            GROUP BY c.station_id, lt.placed_at::date
            ORDER BY c.station_id, lt.placed_at::date
            """,
            (since,),
        )
        rows = cur.fetchall()
    by_station: dict[str, list[float]] = {}
    for sid, _day, pnl in rows:
        by_station.setdefault(sid, []).append(float(pnl))

    out = []
    for sid, series in sorted(by_station.items()):
        n = len(series)
        sharpe = None
        if n >= 2:
            mean = sum(series) / n
            var = sum((x - mean) ** 2 for x in series) / (n - 1)
            std = var ** 0.5
            sharpe = round(mean / std, 3) if std > 0 else None
        text_parts = []
        for rel in STATION_DECISION_DOCS.get(sid, []):
            p = repo_root / rel
            if p.is_file():
                text_parts.append(f"[{rel}]\n{p.read_text(errors='replace')[:_MAX_DOC_CHARS]}")
        out.append(
            ConfigDriftMetrics(
                station_id=sid,
                n_days=n,
                daily_pnl_dollars=series,
                naive_sharpe=sharpe,
                doc_text="\n\n".join(text_parts),
            )
        )
    return out


# ----- 5. data health -----------------------------------------------------------

@dataclass
class DataHealthMetrics:
    forecast_max_init: dict[str, datetime | None]      # model -> most recent init_time (any live station)
    observation_days_behind: dict[str, int | None]     # station_id -> days since latest obs
    price_snapshot_age_minutes: float | None
    equity_snapshot_date: str | None
    equity_snapshot_age_days: int | None
    equity_identity_gap_dollars: float | None  # account_value - (deposits+credit-withdrawals+pnl); ~0 = healthy


def collect_data_health(conn, stations: list[str], now: datetime | None = None) -> DataHealthMetrics:
    now = now or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model, MAX(init_time) FROM forecasts WHERE station_id = ANY(%s) GROUP BY model",
            (stations,),
        )
        forecast_max_init = dict(cur.fetchall())

        cur.execute(
            "SELECT station_id, MAX(date) FROM observations WHERE station_id = ANY(%s) GROUP BY station_id",
            (stations,),
        )
        obs_days_behind = {
            sid: (now.date() - latest).days if latest else None for sid, latest in cur.fetchall()
        }
        for sid in stations:
            obs_days_behind.setdefault(sid, None)

        cur.execute("SELECT MAX(snapshot_at) FROM prices")
        latest_price = cur.fetchone()[0]
        price_age = (now - latest_price).total_seconds() / 60 if latest_price else None

        cur.execute(
            """
            SELECT snapshot_date, account_value_dollars, deposits_dollars,
                   referral_credit_dollars, withdrawals_dollars, computed_pnl_dollars
            FROM account_equity_snapshots ORDER BY snapshot_date DESC LIMIT 1
            """
        )
        row = cur.fetchone()

    eq_date = eq_age = eq_gap = None
    if row:
        snap_date, acct_val, dep, credit, wd, pnl = row
        eq_date = snap_date.isoformat()
        eq_age = (now.date() - snap_date).days
        expected = float(dep or 0) + float(credit or 0) - float(wd or 0) + float(pnl or 0)
        eq_gap = round(float(acct_val or 0) - expected, 2)

    return DataHealthMetrics(
        forecast_max_init=forecast_max_init,
        observation_days_behind=obs_days_behind,
        price_snapshot_age_minutes=round(price_age, 1) if price_age is not None else None,
        equity_snapshot_date=eq_date,
        equity_snapshot_age_days=eq_age,
        equity_identity_gap_dollars=eq_gap,
    )
