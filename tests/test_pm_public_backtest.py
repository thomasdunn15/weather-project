"""Checks for the public-Polymarket backtest's three easy-to-get-wrong pieces."""
import importlib.util
import math
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "pm_public_backtest",
    Path(__file__).resolve().parents[1] / "scripts" / "analysis"
    / "polymarket_public_backtest.py")
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)


def test_band_parses_every_label_shape():
    # Markets before Mar 2026 use an EN DASH, later ones a hyphen. Getting this
    # wrong drops whole ladders silently rather than raising.
    assert pm.band("90-91°F") == (90.0, 91.0)
    assert pm.band("90–91°F") == (90.0, 91.0)
    assert pm.band("89°F or below") == (float("-inf"), 89.0)
    assert pm.band("108°F or higher") == (108.0, float("inf"))
    assert pm.band("not a bracket") is None


def test_ladder_probabilities_sum_to_one():
    """A full ladder must partition the line — no gap, no double-count."""
    ladder = [(float("-inf"), 79.0)]
    ladder += [(t, t + 1) for t in range(80, 96, 2)]
    ladder += [(96.0, float("inf"))]
    total = sum(pm.model_p(lo, hi, mu=88.0, sigma=3.0) for lo, hi in ladder)
    assert abs(total - 1.0) < 1e-9, total


def test_model_p_is_the_integer_rounded_band():
    # P(high == 90) for mu exactly 90 is the mass in [89.5, 90.5].
    p = pm.model_p(90, 90, mu=90.0, sigma=2.0)
    expected = 1 - 2 * pm.norm_sf(0.5 / 2.0)
    assert abs(p - expected) < 1e-12


def test_weather_fee_matches_published_table():
    """docs.polymarket.com/trading/fees: weather taker peaks at $1.25/100."""
    def fee_usd(p, shares=100):
        return shares * pm.WEATHER_TAKER_FEE * p * (1 - p)

    assert math.isclose(fee_usd(0.50), 1.25, abs_tol=0.005)
    assert math.isclose(fee_usd(0.10), 0.45, abs_tol=0.005)
    assert math.isclose(fee_usd(0.90), 0.45, abs_tol=0.005)   # symmetric
    assert math.isclose(fee_usd(0.25), 0.9375, abs_tol=0.005)
    # Makers are never charged; posting being free is the whole POST/CROSS gap.
    assert pm.WEATHER_MAKER_FEE == 0.0
