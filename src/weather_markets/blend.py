"""Market-blend logistic regression module (Benter-style).

Fits `logit(P_blend) = α + β_model · logit(P_model) + β_market · logit(P_market)`
on historical settled paper_trades per city, and applies it to fresh predictions.

The blend captures information present in the Kalshi market price that our
EMOS model alone misses (consensus from other traders, microstructure, listing
biases). Empirically validated 2026-06-09: blend beats raw model on test-set
Brier by 11-43% across all 6 active cities; market carries 56-95% of weight
depending on city.

Usage:
    from weather_markets.blend import get_blend, apply_blend

    fit = get_blend("KORD", "Chicago")      # cached; fits once per process
    p_final = apply_blend(fit, p_model=0.42, p_market=0.27)

The fit is process-cached via lru_cache so paper_trade_log / live_trade /
dashboard each pay the cost once. Pass `max_target_date` to fit on data up
to a specific date (useful for backtest, to avoid lookahead bias).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes


# Probability clipping for logit numerical stability
EPS = 1e-3
MIN_N_FIT = 100   # require at least this many settled paper_trades to fit


# ---------- math primitives ----------
def _clip(p):
    return np.clip(p, EPS, 1.0 - EPS)

def _logit(p):
    p = _clip(p)
    return np.log(p / (1.0 - p))

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


@dataclass(frozen=True)
class BlendFit:
    """A fitted logistic blend for one city.

    Apply with `apply_blend(fit, p_model, p_market) -> p_blend` or directly
    via `fit.predict(p_model, p_market)`.
    """
    city_code: str
    alpha: float
    beta_model: float
    beta_market: float
    n_train: int
    fit_through_date: Optional[str] = None    # last paper_trade target_date included

    def predict(self, p_model, p_market):
        """Returns blended P(YES). Inputs may be scalars or numpy arrays."""
        p_model = np.asarray(p_model, dtype=float)
        p_market = np.asarray(p_market, dtype=float)
        z = self.alpha + self.beta_model * _logit(p_model) + self.beta_market * _logit(p_market)
        out = _sigmoid(z)
        # If both inputs were scalars, return scalar
        return float(out) if out.ndim == 0 else out

    def market_share(self) -> float:
        """Rough fraction of the blend weight given to market vs model."""
        denom = abs(self.beta_model) + abs(self.beta_market) + 1e-9
        return abs(self.beta_market) / denom


def apply_blend(fit: BlendFit, p_model, p_market):
    """Convenience function — same as fit.predict(p_model, p_market)."""
    return fit.predict(p_model, p_market)


# ---------- fitting ----------
def _fit_logistic(p_model: np.ndarray, p_market: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Minimizes BCE log-loss for logit(P) = α + β1·logit(p_model) + β2·logit(p_market).

    Returns (α, β_model, β_market). Uses scipy.optimize L-BFGS-B with analytic
    gradient — converges in <100 iterations even for n>10k.
    """
    X = np.column_stack([np.ones_like(p_model), _logit(p_model), _logit(p_market)])

    def nll(theta):
        z = X @ theta
        # log(1 + exp(z)) — log1p version is numerically stable for large |z|
        return -float(np.mean(y * z - np.logaddexp(0.0, z)))

    def grad(theta):
        z = X @ theta
        p = _sigmoid(z)
        return -X.T @ (y - p) / len(y)

    res = minimize(nll, np.zeros(3), jac=grad, method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1]), float(res.x[2])


def _city_model_source(city_code: str, city_name: str) -> str:
    """The default paper_trades model_source string for this city.

    Defaults to combined (GEFS+IFS); pass paper_model_source= to fit_blend()
    to override (e.g., 'EMOS combined_hrrr 00Z Chicago (rolling 45d)' for KORD
    live which uses HRRR-augmented EMOS).
    """
    if city_code == "KNYC":
        # NYC is legacy: no city tag in the source string.
        return "EMOS combined 00Z (rolling 45d)"
    return f"EMOS combined 00Z {city_name} (rolling 45d)"


def fit_blend(
    city_code: str,
    city_name: str,
    max_target_date: Optional[date] = None,
    paper_model_source: Optional[str] = None,
) -> Optional[BlendFit]:
    """Fits a blend for one city from settled paper_trades.

    paper_model_source: overrides the default 'EMOS combined 00Z {name}'.
      Use this when live trading uses a different EMOS variant (e.g., KORD
      uses combined_hrrr — fit the blend on those paper_trades for matched
      probabilistic calibration).

    max_target_date: only train on paper_trades whose target_date is <= this.
      Used in backtests to avoid lookahead bias (fit on data up to T, evaluate
      on T+1 onward).  None = use all available data.

    Returns None if fewer than MIN_N_FIT settled trades available.
    """
    ms = paper_model_source or _city_model_source(city_code, city_name)
    rows = []
    with get_connection() as conn, conn.cursor() as cur:
        if max_target_date is not None:
            cur.execute(
                """SELECT pt.target_date, pt.model_prob_yes, pt.market_yes_bid, pt.market_yes_ask,
                          c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                   FROM paper_trades pt
                   JOIN contracts c ON c.ticker = pt.ticker
                   LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                     WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
                   WHERE pt.model_source = %s
                     AND pt.target_date <= %s
                     AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
                     AND pt.model_prob_yes IS NOT NULL
                   ORDER BY pt.target_date""",
                (ms, max_target_date),
            )
        else:
            cur.execute(
                """SELECT pt.target_date, pt.model_prob_yes, pt.market_yes_bid, pt.market_yes_ask,
                          c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                   FROM paper_trades pt
                   JOIN contracts c ON c.ticker = pt.ticker
                   LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                     WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
                   WHERE pt.model_source = %s
                     AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
                     AND pt.model_prob_yes IS NOT NULL
                   ORDER BY pt.target_date""",
                (ms,),
            )
        for td, mp, bid, ask, bt, sl, sh, high in cur.fetchall():
            if high is None:
                continue
            mkt_p = (int(bid) + int(ask)) / 200.0
            yes_won = contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
            rows.append((td, float(mp), mkt_p, 1.0 if yes_won else 0.0))
    if len(rows) < MIN_N_FIT:
        return None
    arr = np.array([(mp, mk, y) for _, mp, mk, y in rows])
    alpha, beta_model, beta_market = _fit_logistic(arr[:, 0], arr[:, 1], arr[:, 2])
    return BlendFit(
        city_code=city_code,
        alpha=alpha,
        beta_model=beta_model,
        beta_market=beta_market,
        n_train=len(rows),
        fit_through_date=str(rows[-1][0]),
    )


# Process-level cache so paper_trade_log / live_trade / dashboard each fit once.
@lru_cache(maxsize=32)
def get_blend(city_code: str, city_name: str,
              paper_model_source: Optional[str] = None) -> Optional[BlendFit]:
    """Cached version of fit_blend with no max_target_date. Use this in
    production (paper_trade_log, live_trade, dashboard). For backtests
    that need date-aware fits, call fit_blend(..., max_target_date=) directly.

    paper_model_source: pass cfg["paper_model_source"] to fit on the EMOS
    variant the live cron actually uses (e.g., combined_hrrr for KORD).
    """
    return fit_blend(city_code, city_name, paper_model_source=paper_model_source)


def walkforward_blends(
    city_code: str,
    city_name: str,
    paper_model_source: Optional[str] = None,
    refit_every_days: int = 7,
) -> dict:
    """Walk-forward blend fits — one BlendFit per settled target_date, each
    trained ONLY on settled data STRICTLY BEFORE that date (expanding window).

    This is what an honest backtest must use: fitting the blend on the full
    history and then scoring it on that same history (what get_blend/fit_blend
    do) is lookahead bias that inflates blend/union results. With this, each
    trade is scored by a blend that could only have seen earlier data.

    Returns {target_date: BlendFit | None}. Dates before MIN_N_FIT settled
    samples have accrued map to None (no blend possible yet — realistic).
    Refits every `refit_every_days` to bound cost (coefficients are stable
    week-to-week); between refits the most recent fit is reused (still strictly
    pre-`d`, so lookahead-free).

    One DB query + ~N/refit_every fits. Deliberately NOT lru_cached: the output
    is date-keyed, so a process-level cache would serve stale fits (missing the
    newest settled dates) in a long-lived dashboard. The sole caller,
    _fetch_city_payload, is already @st.cache_data(ttl=300), which bounds how
    often this recomputes while staying fresh.
    """
    from datetime import timedelta
    ms = paper_model_source or _city_model_source(city_code, city_name)
    rows: list[tuple] = []   # (target_date, p_model, p_market, y)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT pt.target_date, pt.model_prob_yes, pt.market_yes_bid, pt.market_yes_ask,
                      c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
               FROM paper_trades pt
               JOIN contracts c ON c.ticker = pt.ticker
               LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                 WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
               WHERE pt.model_source = %s
                 AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
                 AND pt.model_prob_yes IS NOT NULL
               ORDER BY pt.target_date""",
            (ms,),
        )
        for td, mp, bid, ask, bt, sl, sh, high in cur.fetchall():
            if high is None:
                continue
            mkt_p = (int(bid) + int(ask)) / 200.0
            yes_won = contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
            rows.append((td, float(mp), mkt_p, 1.0 if yes_won else 0.0))

    if not rows:
        return {}

    rows.sort(key=lambda r: r[0])
    unique_dates = sorted({r[0] for r in rows})
    out: dict = {}
    cur_fit: Optional[BlendFit] = None
    last_refit: Optional[date] = None

    for d in unique_dates:
        need_refit = (last_refit is None) or ((d - last_refit).days >= refit_every_days)
        if need_refit:
            train = [(mp, mk, y) for (td, mp, mk, y) in rows if td < d]
            if len(train) >= MIN_N_FIT:
                a = np.array(train, dtype=float)
                alpha, bm, bk = _fit_logistic(a[:, 0], a[:, 1], a[:, 2])
                cur_fit = BlendFit(
                    city_code=city_code, alpha=alpha, beta_model=bm, beta_market=bk,
                    n_train=len(train), fit_through_date=str(d - timedelta(days=1)),
                )
                last_refit = d
        out[d] = cur_fit
    return out
