"""Market-blend logistic regression analysis (Benter-style).

Fit: logit(P_blend) = α + β₁·logit(P_model) + β₂·logit(P_market)
on settled paper_trades, per city. Compare Brier + log-loss for:
  - Raw model alone
  - Raw market alone
  - Blended estimator

Time-series train/test split (first 70% chronologically train, last 30% test).
The TEST numbers are the honest ones — train numbers are guaranteed to look
better and don't tell us if this generalizes.

Usage:
    uv run python scripts/analysis/blend_logistic.py
    uv run python scripts/analysis/blend_logistic.py --city KORD
    uv run python scripts/analysis/blend_logistic.py --csv outputs/blend.csv

Decision rule for whether to ship the blend:
  - Test Brier_blend < Brier_model AND
  - Test log-loss_blend < log-loss_model AND
  - β₂ (market weight) statistically meaningful (rough threshold: β₂ > 0.10)
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes


# ---------- math helpers ----------
EPS = 1e-3

def clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, EPS, 1.0 - EPS)

def logit(p: np.ndarray) -> np.ndarray:
    p = clip(p)
    return np.log(p / (1.0 - p))

def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))

def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))

def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = clip(p)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


# ---------- logistic regression (NLL minimization) ----------
@dataclass
class BlendFit:
    alpha: float
    beta_model: float
    beta_market: float
    n_train: int

    def predict(self, p_model: np.ndarray, p_market: np.ndarray) -> np.ndarray:
        z = self.alpha + self.beta_model * logit(p_model) + self.beta_market * logit(p_market)
        return sigmoid(z)


def fit_blend(p_model: np.ndarray, p_market: np.ndarray, y: np.ndarray) -> BlendFit:
    X = np.column_stack([np.ones_like(p_model), logit(p_model), logit(p_market)])

    def nll(theta: np.ndarray) -> float:
        z = X @ theta
        return -np.mean(y * z - np.log1p(np.exp(z)))   # numerically stable BCE

    def grad(theta: np.ndarray) -> np.ndarray:
        z = X @ theta
        p = sigmoid(z)
        return -X.T @ (y - p) / len(y)

    res = minimize(nll, np.zeros(3), jac=grad, method="L-BFGS-B")
    return BlendFit(
        alpha=float(res.x[0]),
        beta_model=float(res.x[1]),
        beta_market=float(res.x[2]),
        n_train=len(y),
    )


# ---------- data loading ----------
def fetch_settled(city_code: str, city_name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Returns (target_dates as ordinals, p_model, p_market, y) for all settled paper trades."""
    ms = (f"EMOS combined 00Z {city_name} (rolling 45d)"
          if city_code != "KNYC" else "EMOS combined 00Z (rolling 45d)")
    rows = []
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
            rows.append((td.toordinal(), float(mp), mkt_p, 1.0 if yes_won else 0.0))
    if not rows:
        return (np.array([]),) * 4
    arr = np.array(rows)
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]


def time_split(*arrays, train_frac: float = 0.7):
    """Splits each array into (train, test) by chronological position. The
    first array (typically dates) is included in the output along with the rest."""
    n = len(arrays[0])
    cutoff = int(n * train_frac)
    return tuple((a[:cutoff], a[cutoff:]) for a in arrays)


# ---------- reporting ----------
def calibration_table(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> list[tuple]:
    """Returns [(bin_lo, bin_hi, mean_predicted, actual_rate, n), ...]"""
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi if i < n_bins - 1 else p <= hi)
        if mask.sum() == 0:
            continue
        rows.append((float(lo), float(hi), float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())))
    return rows


def report_city(city_code: str, city_name: str, csv_writer=None) -> dict | None:
    dates, p_model, p_market, y = fetch_settled(city_code, city_name)
    if len(y) < 100:
        print(f"\n{'='*64}\n{city_name} ({city_code}) — only {len(y)} settled trades; skipping (need ≥100)")
        return None

    (d_tr, d_te), (pm_tr, pm_te), (mk_tr, mk_te), (y_tr, y_te) = time_split(dates, p_model, p_market, y)

    fit = fit_blend(pm_tr, mk_tr, y_tr)
    blend_tr = fit.predict(pm_tr, mk_tr)
    blend_te = fit.predict(pm_te, mk_te)

    def metrics(p, y_):
        return brier(p, y_), log_loss(p, y_)
    b_m_tr, ll_m_tr = metrics(pm_tr, y_tr); b_m_te, ll_m_te = metrics(pm_te, y_te)
    b_k_tr, ll_k_tr = metrics(mk_tr, y_tr); b_k_te, ll_k_te = metrics(mk_te, y_te)
    b_b_tr, ll_b_tr = metrics(blend_tr, y_tr); b_b_te, ll_b_te = metrics(blend_te, y_te)

    print(f"\n{'='*64}\n{city_name} ({city_code}) — n_train={len(y_tr)}, n_test={len(y_te)}")
    print(f"  Coefficients: α={fit.alpha:+.3f}  β_model={fit.beta_model:+.3f}  β_market={fit.beta_market:+.3f}")
    print(f"  → market weight share: {abs(fit.beta_market)/(abs(fit.beta_model)+abs(fit.beta_market)+1e-9)*100:.0f}%")
    print()
    print(f"  {'METRIC':<14} {'TRAIN MODEL':>12} {'TRAIN MKT':>11} {'TRAIN BLEND':>13}   {'TEST MODEL':>11} {'TEST MKT':>10} {'TEST BLEND':>12}")
    print(f"  {'Brier ↓':<14} {b_m_tr:>12.4f} {b_k_tr:>11.4f} {b_b_tr:>13.4f}   {b_m_te:>11.4f} {b_k_te:>10.4f} {b_b_te:>12.4f}")
    print(f"  {'LogLoss ↓':<14} {ll_m_tr:>12.4f} {ll_k_tr:>11.4f} {ll_b_tr:>13.4f}   {ll_m_te:>11.4f} {ll_k_te:>10.4f} {ll_b_te:>12.4f}")

    blend_better_brier_te = b_b_te < b_m_te
    blend_better_ll_te = ll_b_te < ll_m_te
    market_meaningful = abs(fit.beta_market) > 0.10
    verdict = ("SHIP" if (blend_better_brier_te and blend_better_ll_te and market_meaningful) else
               "PROBABLY" if (blend_better_brier_te or blend_better_ll_te) and market_meaningful else
               "SKIP")
    print(f"  Verdict (test set): {verdict}")
    if not blend_better_brier_te:
        print(f"    blend Brier WORSE than raw model on test set — likely overfit on train")
    if not market_meaningful:
        print(f"    β_market too small ({fit.beta_market:+.3f}) — market not adding info above the model")

    # Calibration deciles on TEST set
    cal_model = calibration_table(pm_te, y_te)
    cal_blend = calibration_table(blend_te, y_te)
    print(f"\n  Calibration (test set deciles): predicted → actual win rate")
    print(f"  {'BIN':<10} {'MODEL pred→actual (n)':<32} {'BLEND pred→actual (n)':<32}")
    for i in range(len(cal_model)):
        m = cal_model[i]
        bl = cal_blend[i] if i < len(cal_blend) else None
        m_str = f"{m[2]:.2f} → {m[3]:.2f} (n={m[4]})"
        b_str = f"{bl[2]:.2f} → {bl[3]:.2f} (n={bl[4]})" if bl else "—"
        print(f"  [{m[0]:.1f}-{m[1]:.1f})  {m_str:<32} {b_str:<32}")

    if csv_writer is not None:
        import csv
        for i in range(len(d_te)):
            csv_writer.writerow([city_code, int(d_te[i]), pm_te[i], mk_te[i], blend_te[i], int(y_te[i])])

    return {
        "city": city_code, "n_train": len(y_tr), "n_test": len(y_te),
        "alpha": fit.alpha, "beta_model": fit.beta_model, "beta_market": fit.beta_market,
        "test_brier_model": b_m_te, "test_brier_blend": b_b_te,
        "test_logloss_model": ll_m_te, "test_logloss_blend": ll_b_te,
        "verdict": verdict,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--city", default=None, help="Limit to a single station_id")
    p.add_argument("--csv", default=None, help="Dump per-row test predictions to a CSV")
    args = p.parse_args()

    CITIES = [("KORD","Chicago"),("KMIA","Miami"),("KAUS","Austin"),
              ("KDEN","Denver"),("KLAX","Los Angeles"),("KNYC","NYC")]
    if args.city:
        CITIES = [(c, n) for c, n in CITIES if c == args.city]

    csv_writer = None
    if args.csv:
        import csv as _csv
        from pathlib import Path
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        f = open(args.csv, "w", newline="")
        csv_writer = _csv.writer(f)
        csv_writer.writerow(["city", "date_ordinal", "p_model", "p_market", "p_blend", "y"])

    results = []
    for code, name in CITIES:
        r = report_city(code, name, csv_writer=csv_writer)
        if r: results.append(r)

    if csv_writer:
        print(f"\nTest-set predictions written to {args.csv}")

    print(f"\n{'='*64}\nSUMMARY — verdicts per city")
    print(f"  {'City':<14} {'n_test':>6} {'β_model':>8} {'β_mkt':>7} {'Brier Δ':>9} {'Verdict':>10}")
    for r in results:
        b_imp = r["test_brier_model"] - r["test_brier_blend"]
        print(f"  {r['city']:<14} {r['n_test']:>6} {r['beta_model']:>+8.3f} {r['beta_market']:>+7.3f} {b_imp:>+9.4f} {r['verdict']:>10}")


if __name__ == "__main__":
    main()
