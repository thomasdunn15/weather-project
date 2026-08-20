"""Deterministic opportunity scoring: SQL metrics + venue facts -> scorecard.

`rank` uses this alone (no LLM cost); `assess` feeds the same metrics into the
B0 reasoning engine as evidence. Scores are 0/1/2 per matrix focus point with
a reason string each — heuristic by design, tuned to this operation's reality
(≈500-700 contract depth ceilings, 2.5 OOS-Sharpe deploy bar, fee-sized edges).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from weather_markets.expansion.candidates import Candidate
from weather_markets.expansion.catalog import VENUES, VenueFacts, fee_cents
from weather_markets.stations import STATIONS

# focus-point weights (matrix ids in docs/matrices/breadth_expansion.json)
WEIGHTS = {
    "data": 2, "tract": 2, "resolution": 2, "market": 3,
    "fees": 1, "durability": 2, "capital": 1, "regulatory": 2,
}
HARD_GATES = ("data", "resolution", "regulatory")  # a 0 here = NO-GO

# Underlyings with a known NWP-grade public data source. Everything else
# defaults to "no identified source" and gates data=0 until proven otherwise.
KNOWN_UNDERLYINGS = {
    "daily_high_temp": ("GEFS/IFS/HRRR TMAX (already ingested)", 2),
    "daily_temp": ("GEFS/IFS/HRRR TMAX/TMIN (already ingested)", 2),
    "daily_low_temp": ("GEFS/IFS/HRRR TMIN (same ingest, lows backfill exists)", 2),
    "precipitation": ("NWP QPF ensembles + NWS CLI precip obs (new ingest work)", 1),
    "snowfall": ("NWP snow fields + NWS CLI obs (new ingest work)", 1),
}
_TITLE_HINTS = (("rain", "precipitation"), ("precip", "precipitation"), ("snow", "snowfall"),
                ("highest temperature", "daily_high_temp"), ("high temp", "daily_high_temp"),
                ("lowest temperature", "daily_low_temp"), ("low temp", "daily_low_temp"),
                ("temperature", "daily_temp"))

_CONUS = (21.0, 53.0, -134.0, -60.0)  # HRRR coverage box (lat, lat, lon, lon)


@dataclass
class CandidateMetrics:
    candidate: Candidate
    venue: VenueFacts
    series_ticker: str | None
    series_title: str | None
    settlement_sources: list[str]
    n_open: int
    n_settled: int
    avg_volume: float | None          # settled markets: realized daily volume
    med_spread_cents: float | None    # open markets, both sides quoted
    avg_open_interest: float | None
    underlying: str
    station_known: bool
    hrrr_ok: bool
    paper_n: int
    paper_mean_abs_edge: float | None
    paper_span_days: int
    flb_regime: dict | None = None   # stored favorite-longshot metric (flb_regime table)


def _infer_underlying(candidate: Candidate, title: str | None) -> str:
    if candidate.underlying != "unknown":
        return candidate.underlying
    for hint, name in _TITLE_HINTS:
        if title and hint in title.lower():
            return name
    return "unknown"


def collect_metrics(conn, candidate: Candidate) -> CandidateMetrics:
    venue = VENUES[candidate.venue]
    series = candidate.resolved_series()
    title = None
    settlement_sources: list[str] = []
    n_open = n_settled = 0
    avg_volume = med_spread = avg_oi = None

    if series is not None:
        with conn.cursor() as cur:
            # ForecastEx ports have no catalog rows yet; score them against the
            # Kalshi catalog for the same series as the best available proxy.
            cur.execute(
                "SELECT title, payload FROM expansion_series "
                "WHERE venue = 'kalshi' AND series_ticker = %s",
                (series,),
            )
            row = cur.fetchone()
            if row:
                title = row[0]
                for src in (row[1] or {}).get("settlement_sources") or []:
                    settlement_sources.append(src.get("name") or src.get("url") or "?")
            cur.execute(
                """
                SELECT DISTINCT ON (market_ticker)
                       status, yes_bid, yes_ask, volume, open_interest
                FROM expansion_market_snapshots
                WHERE venue = 'kalshi' AND series_ticker = %s
                ORDER BY market_ticker, snapshot_at DESC
                """,
                (series,),
            )
            latest = cur.fetchall()
        open_rows = [r for r in latest if r[0] in ("open", "active")]
        settled_rows = [r for r in latest if r[0] == "settled"]
        n_open, n_settled = len(open_rows), len(settled_rows)
        spreads = [r[2] - r[1] for r in open_rows if r[1] and r[2]]
        med_spread = statistics.median(spreads) if spreads else None
        vols = [r[3] for r in settled_rows if r[3]]
        avg_volume = statistics.mean(vols) if vols else None
        ois = [r[4] for r in open_rows if r[4]]
        avg_oi = statistics.mean(ois) if ois else None

    station = STATIONS.get(candidate.station_id) if candidate.station_id else None
    hrrr_ok = bool(
        station
        and _CONUS[0] <= station.latitude <= _CONUS[1]
        and _CONUS[2] <= station.longitude <= _CONUS[3]
    )

    paper_n, paper_edge, paper_span = 0, None, 0
    if candidate.station_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), avg(abs(pt.edge)),
                       COALESCE(max(pt.target_date) - min(pt.target_date), 0)
                FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
                WHERE c.station_id = %s
                """,
                (candidate.station_id,),
            )
            paper_n, paper_edge, paper_span = cur.fetchone()

    flb = None
    if series is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT longshot_mass, longshot_overpricing_pp, favorite_underpricing_pp, "
                "resolution_hours, verdict, n_markets FROM flb_regime WHERE series_ticker = %s",
                (series,),
            )
            row = cur.fetchone()
        if row:
            flb = {"longshot_mass": row[0], "longshot_overpricing_pp": row[1],
                   "favorite_underpricing_pp": row[2], "resolution_hours": row[3],
                   "verdict": row[4], "n_markets": row[5]}

    return CandidateMetrics(
        candidate=candidate,
        venue=venue,
        series_ticker=series,
        series_title=title,
        settlement_sources=settlement_sources,
        n_open=n_open,
        n_settled=n_settled,
        avg_volume=avg_volume,
        med_spread_cents=med_spread,
        avg_open_interest=avg_oi,
        underlying=_infer_underlying(candidate, title),
        station_known=station is not None,
        hrrr_ok=hrrr_ok,
        paper_n=paper_n or 0,
        paper_mean_abs_edge=float(paper_edge) if paper_edge is not None else None,
        paper_span_days=int(paper_span or 0),
        flb_regime=flb,
    )


@dataclass
class Scorecard:
    candidate: Candidate
    metrics: CandidateMetrics
    points: dict[str, tuple[int, str]]   # focus id -> (0-2 score, reason)
    total: int
    max_total: int
    verdict: str                          # NO-GO | WATCH | GO (paper-first)
    ceiling_contracts: int | None
    fee_note: str
    bar_note: str

    @property
    def pct(self) -> float:
        return self.total / self.max_total


def score(m: CandidateMetrics) -> Scorecard:
    c, v = m.candidate, m.venue
    pts: dict[str, tuple[int, str]] = {}

    src, data_score = KNOWN_UNDERLYINGS.get(m.underlying, ("no identified NWP-grade source", 0))
    if data_score == 2 and not m.station_known and c.kind != "category":
        data_score, src = 1, src + "; station not in STATIONS yet (add lat/lon + NWS obs)"
    pts["data"] = (data_score, src)

    if m.underlying in ("daily_high_temp", "daily_low_temp", "daily_temp"):
        pts["tract"] = (2, "EMOS Gaussian -> bracket integration, proven in production")
    elif m.underlying in ("precipitation", "snowfall"):
        pts["tract"] = (1, "EMOS-able but censored/skewed distribution — new calibration work")
    else:
        pts["tract"] = (0, "no calibrated-distribution mapping identified")

    if m.settlement_sources:
        pts["resolution"] = (2, "settlement sources on series: " + ", ".join(m.settlement_sources[:3]))
    elif m.underlying.startswith("daily"):
        pts["resolution"] = (2 if v.key == "kalshi" else 1,
                             "NWS CLI report standard for temp; " + v.resolution)
    else:
        pts["resolution"] = (0, "no authoritative settlement source identified")

    if v.key == "forecastex":
        proxy = (f"; Kalshi same-station proxy: avg volume {m.avg_volume:,.0f}, "
                 f"spread {m.med_spread_cents:.0f}c"
                 if m.avg_volume is not None and m.med_spread_cents is not None else "")
        mk = (1, "own depth unknown — " + v.open_questions[0] + proxy)
    elif m.avg_volume is not None and m.med_spread_cents is not None:
        if m.avg_volume >= 5000 and m.med_spread_cents <= 3:
            mk = (2, f"avg settled volume {m.avg_volume:,.0f}, median spread {m.med_spread_cents:.0f}c")
        elif m.avg_volume >= 500:
            mk = (1, f"tradeable but thin: avg volume {m.avg_volume:,.0f}, spread {m.med_spread_cents:.0f}c")
        else:
            mk = (0, f"illiquid: avg settled volume {m.avg_volume:,.0f}")
    else:
        mk = (0, "no catalog data — run sync first")
    pts["market"] = mk

    pts["fees"] = (
        (2, f"~1/2 Kalshi: taker {fee_cents(50, v.key)}c vs {fee_cents(50)}c at 50c")
        if v.taker_rate < VENUES["kalshi"].taker_rate
        else (1, f"taker {fee_cents(50, v.key)}c / maker {fee_cents(50, v.key, maker=True)}c at 50c")
    )

    if m.paper_n >= 100:
        pts["durability"] = (2, f"{m.paper_n} paper signals over {m.paper_span_days}d for this station")
    elif m.underlying.startswith("daily"):
        pts["durability"] = (1, "same signal family as proven cities; no station-specific evidence yet")
    else:
        pts["durability"] = (0, "no evidence this edge family transfers")

    pts["capital"] = (2, v.capital_cycle) if "Same-day" in v.capital_cycle else (1, v.capital_cycle)

    if v.key == "polymarket_us":
        pts["regulatory"] = (0, v.regulatory)
    elif v.open_questions:
        pts["regulatory"] = (1, v.regulatory + " OPEN: " + v.open_questions[-1])
    else:
        pts["regulatory"] = (2, v.regulatory)

    total = sum(WEIGHTS[k] * s for k, (s, _) in pts.items())
    max_total = sum(w * 2 for w in WEIGHTS.values())

    gated = [k for k in HARD_GATES if pts[k][0] == 0]
    if gated:
        verdict = f"NO-GO (gate: {', '.join(gated)})"
    elif total / max_total >= 0.65:
        verdict = "GO (paper-first)"
    else:
        verdict = "WATCH"
    if c.prior:
        verdict += f" [prior: {c.prior}]"

    # ponytail: ceiling heuristic = 10% of realized daily volume, capped at the
    # 700 found in the KORD/KDFW/KMIA capacity studies; replace with a real
    # walk-book run (scripts/analysis/walk_book_capacity.py) before sizing.
    ceiling = int(min(700, m.avg_volume * 0.10)) if m.avg_volume else None

    fee_note = (
        f"taker {fee_cents(50, v.key)}c / maker {fee_cents(50, v.key, maker=True)}c at 50c"
        + (f"; paper mean abs edge {m.paper_mean_abs_edge:.1%}" if m.paper_mean_abs_edge else "")
    )
    bar_note = (
        f"backtestable now ({m.paper_n} paper rows, {m.paper_span_days}d) — walk-forward OOS "
        "Sharpe vs the 2.5 bar can be computed"
        if m.paper_n >= 100
        else "cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first"
    )
    return Scorecard(c, m, pts, total, max_total, verdict, ceiling, fee_note, bar_note)


def scaling_summary(m: CandidateMetrics) -> tuple[str, str, bool]:
    """Honest scalability proxy: (ceiling_range, scaling_path, is_proxy).

    No real order-book depth exists here (top-of-book + going-forward 5-min
    snapshots only), so the ceiling is a RANGE off realized volume, always
    flagged proxy — a walk_book_capacity.py run measures the true number.
    ponytail: 5-15% of avg_volume heuristic; replace with a measured walk-book.
    """
    if not m.avg_volume:
        return "unknown (no catalog volume — run sync)", "no catalog data — sync + probe first", True
    lo, hi = int(0.05 * m.avg_volume), int(0.15 * m.avg_volume)
    # paper_n>=100 means we have internal data to ASSESS, NOT that an edge exists
    # (skill != edge — NYC/Denver have paper rows and are still HOLD/NO-GO). Real
    # edge is the assess/walk-forward job, never a deterministic volume proxy.
    has_data = m.paper_n >= 100
    if has_data and m.avg_volume >= 5000:
        path = "deep book + internal data — assess edge before deepening"
    elif has_data:
        path = "internal data — assess; scale by breadth if edge holds"
    else:
        path = "no internal data — probe before sizing"
    return f"~{lo:,}-{hi:,} contracts/day (proxy)", path, True
