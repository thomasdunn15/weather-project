"""FLB-regime metric: pure-logic tests (no network) for price extraction,
bucketing, overpricing, and the regime verdict."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# scripts/ isn't a package; load the module by path
_spec = importlib.util.spec_from_file_location(
    "flb_regime", Path(__file__).resolve().parents[1] / "scripts" / "analysis" / "flb_regime.py"
)
flb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = flb  # dataclass decorator needs the module registered
_spec.loader.exec_module(flb)


def test_implied_p_prefers_traded_mean_then_midpoint():
    assert flb._implied_p({"price": {"mean_dollars": "0.42"}}) == 0.42
    # no trades -> bid/ask midpoint
    assert abs(flb._implied_p({"price": {}, "yes_bid": {"close_dollars": "0.10"},
                               "yes_ask": {"close_dollars": "0.20"}}) - 0.15) < 1e-9
    # only one side quoted -> that side
    assert flb._implied_p({"price": {}, "yes_ask": {"close_dollars": "0.08"}}) == 0.08
    # nothing -> None
    assert flb._implied_p({"price": {}}) is None


def test_period_interval_tiers():
    assert flb._period_interval(15 * 60) == 1          # 15-min market -> 1-min candles
    assert flb._period_interval(7 * 86400) == 60       # weekly -> hourly
    assert flb._period_interval(30 * 86400) == 1440    # monthly -> daily


def test_bucketize_and_overpricing():
    # longshots priced 20c but win 5%; favorites priced 80c win 95%
    obs = [(0.20, 0)] * 19 + [(0.20, 1)] * 1 + [(0.80, 1)] * 19 + [(0.80, 0)] * 1
    buckets = {b.label: b for b in flb.bucketize(obs)}
    ls = buckets["<30c longshot"]
    assert ls.n == 20 and abs(ls.mean_implied - 0.20) < 1e-9
    assert abs(ls.yes_rate - 0.05) < 1e-9
    assert ls.overpricing > 0.10          # overpriced: 20c implied vs 5% actual


def test_verdict_flb_present_vs_coinflip():
    # longshot-rich + overpriced -> FLB PRESENT
    flb_obs = [(0.20, 0)] * 30 + [(0.20, 1)] * 2 + [(0.70, 1)] * 20
    assert "FLB PRESENT" in flb.verdict(flb_obs)

    # near coin-flip (all ~50c, no <30c mass) -> NO LONGSHOT REGIME
    coinflip = [(0.50, 1)] * 25 + [(0.48, 0)] * 25
    assert "NO LONGSHOT REGIME" in flb.verdict(coinflip)

    # too little data -> guarded
    assert "INSUFFICIENT" in flb.verdict([(0.2, 0)] * 3)
