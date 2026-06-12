"""Parity tests between the dashboard's JS sim and the Python sim.

The backtest panel's jsComputeSim (scripts/assets/backtest_component/
index.html) is a hand-maintained port of dashboard.py's simulate_pnl. The
two have already drifted by design (the JS grew union/blend strategies and
the maxSignals/edgeCap what-if toggles), which creates a real risk: a config
evaluated in the dashboard may not behave the way live code does.

Two layers of protection:

1. PARITY on the shared core — raw strategy, cross execution, unit and
   amount sizing, Kalshi fees. The JS and Python sims must produce the same
   final balance on identical fixture trades. If this fails, one port
   changed without the other.

2. GOLDEN tests for JS-only features (union, maxSignals, edgeCap) — pinned
   to hand-computed expectations so accidental edits to the JS are caught
   even though Python has no counterpart to compare against.

The JS runs in a real engine (mini-racer/V8). The Python simulate_pnl is
extracted from dashboard.py via AST so we don't import streamlit (top-level
streamlit app code must not execute in tests).

Run: uv run pytest tests/test_sim_parity.py
"""
import ast
import math
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

py_mini_racer = pytest.importorskip("py_mini_racer")

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "scripts" / "assets" / "backtest_component" / "index.html"
DASHBOARD_PY = ROOT / "scripts" / "dashboard.py"


# ---------------------------------------------------------------------------
# harness: load both sims
# ---------------------------------------------------------------------------

def _load_js_sim():
    """Extract kalshiFeeCents..jsComputeSim from index.html into a V8 context."""
    src = INDEX_HTML.read_text()
    start = src.index("function kalshiFeeCents")
    end = src.index("function BTMetric")
    ctx = py_mini_racer.MiniRacer()
    ctx.eval(src[start:end])
    return ctx


def _load_py_sim():
    """Extract simulate_pnl + its helpers from dashboard.py without importing
    streamlit. Executes only the four function defs in a clean namespace."""
    src = DASHBOARD_PY.read_text()
    tree = ast.parse(src)
    wanted = {"simulate_pnl", "kalshi_fee_cents", "_apply_stake_cap", "_kelly_fraction"}
    ns = {"pd": pd, "math": math, "random": random}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module([node], type_ignores=[]), str(DASHBOARD_PY), "exec"), ns)
    missing = wanted - set(ns)
    assert not missing, f"functions not found in dashboard.py: {missing}"
    return ns


@pytest.fixture(scope="module")
def js():
    return _load_js_sim()


@pytest.fixture(scope="module")
def py():
    return _load_py_sim()


# ---------------------------------------------------------------------------
# fixtures: the same 8 trades in each sim's native shape
# ---------------------------------------------------------------------------
# (entry¢, position-won?, modelP, mktP, pos) — pos matches the sign of
# (modelP − mktP) so the JS strategy-side recomputation never flips a side.
FIXTURE = [
    (7,  True,  0.60, 0.08, "BUY_YES"),
    (27, False, 0.55, 0.30, "BUY_YES"),
    (48, True,  0.20, 0.50, "BUY_NO"),
    (63, True,  0.10, 0.35, "BUY_NO"),
    (85, False, 0.97, 0.86, "BUY_YES"),
    (15, True,  0.45, 0.16, "BUY_YES"),
    (52, False, 0.25, 0.49, "BUY_NO"),
    (33, True,  0.70, 0.34, "BUY_YES"),
]


def js_trades():
    return [
        {
            "date": f"2026-06-{10 + i % 3:02d}", "bracket": f"B{i}", "pos": pos,
            "modelP": mp, "blendP": None, "mktP": mkt, "edge": mp - mkt,
            "entry": entry, "marketYesBid": entry - 2, "marketYesAsk": entry,
            "qty": 1, "fill": "filled", "won": won, "pnl": 0,
        }
        for i, (entry, won, mp, mkt, pos) in enumerate(FIXTURE)
    ]


def py_df():
    rows = [
        {
            "target_date": f"2026-06-{10 + i % 3:02d}", "logged_at": f"2026-06-{10 + i % 3:02d}T14:46:{i:02d}",
            "ticker": f"T{i}", "entry_price_cents": entry, "won": won,
            "market_yes_bid": entry - 2, "market_yes_ask": entry,
            "bracket_type": "between", "strike_low": 80, "strike_high": 81,
            "model_prob_yes": mp, "position": pos, "edge": mp - mkt,
        }
        for i, (entry, won, mp, mkt, pos) in enumerate(FIXTURE)
    ]
    return pd.DataFrame(rows)


JS_BASE_PARAMS = {
    "sizing": "unit", "edgeFilter": 0, "minEntry": 0, "amountDollars": 500,
    "depthCap": 0, "execution": "market", "startingBankroll": 3000,
    "strategy": "raw",
}


# ---------------------------------------------------------------------------
# 1. parity on the shared core
# ---------------------------------------------------------------------------

class TestParity:
    def test_unit_sizing(self, js, py):
        res_js = js.call("jsComputeSim", js_trades(), {**JS_BASE_PARAMS, "sizing": "unit", "amountDollars": 500})
        hist = py["simulate_pnl"](py_df(), 3000, "unit", contracts=500,
                                  execution_mode="cross", max_contracts_per_trade=None)
        final_py = hist[-1]["balance"] if isinstance(hist, list) else hist.iloc[-1]["balance"]
        assert res_js["n"] == len(FIXTURE)
        assert res_js["final"] == pytest.approx(final_py, abs=0.01), (
            f"unit-sizing drift: JS final {res_js['final']} vs Python {final_py}")

    def test_amount_sizing(self, js, py):
        res_js = js.call("jsComputeSim", js_trades(), {**JS_BASE_PARAMS, "sizing": "amount", "amountDollars": 50})
        hist = py["simulate_pnl"](py_df(), 3000, "amount", amount_dollars=50,
                                  execution_mode="cross", max_contracts_per_trade=None)
        final_py = hist[-1]["balance"] if isinstance(hist, list) else hist.iloc[-1]["balance"]
        assert res_js["final"] == pytest.approx(final_py, abs=0.01), (
            f"amount-sizing drift: JS final {res_js['final']} vs Python {final_py}")

    def test_fee_formula_parity(self, js, py):
        for entry in (1, 7, 27, 50, 85, 99):
            assert js.call("kalshiFeeCents", entry) == py["kalshi_fee_cents"](entry), (
                f"fee drift at {entry}¢")


# ---------------------------------------------------------------------------
# 2. golden tests for JS-only features
# ---------------------------------------------------------------------------

def _one_js_trade(entry, won, model_p, mkt_p, *, blend_p=None, date="2026-06-10", bracket="B0"):
    pos = "BUY_YES" if model_p - mkt_p > 0 else "BUY_NO"
    return {
        "date": date, "bracket": bracket, "pos": pos, "modelP": model_p,
        "blendP": blend_p, "mktP": mkt_p, "edge": model_p - mkt_p,
        "entry": entry, "marketYesBid": entry - 2, "marketYesAsk": entry,
        "qty": 1, "fill": "filled", "won": won, "pnl": 0,
    }


class TestGoldenJsOnly:
    def test_max_signals_drops_lowest_edge_per_day(self, js):
        trades = [
            _one_js_trade(20, True, 0.50, 0.20, bracket="A"),   # edge .30
            _one_js_trade(30, True, 0.55, 0.35, bracket="B"),   # edge .20
            _one_js_trade(40, True, 0.52, 0.42, bracket="C"),   # edge .10 ← dropped
        ]
        res = js.call("jsComputeSim", trades, {**JS_BASE_PARAMS, "edgeFilter": 0.05, "maxSignals": 2})
        assert res["n"] == 2
        dropped = [r for r in res["tradeRecords"] if r["fill"] == "anti-stack"]
        assert len(dropped) == 1 and dropped[0]["bracket"] == "C"

    def test_edge_cap_scales_sizing_only(self, js):
        # edge .80, cap .40 → unit count halves: floor(100 × 0.5) = 50.
        trades = [_one_js_trade(20, True, 0.90, 0.10)]
        res = js.call("jsComputeSim", trades,
                      {**JS_BASE_PARAMS, "amountDollars": 100, "edgeCap": 0.40})
        filled = [r for r in res["tradeRecords"] if r["fill"] == "filled"]
        assert len(filled) == 1 and filled[0]["computedQty"] == 50
        # And with no cap, full size.
        res2 = js.call("jsComputeSim", trades, {**JS_BASE_PARAMS, "amountDollars": 100})
        assert [r for r in res2["tradeRecords"] if r["fill"] == "filled"][0]["computedQty"] == 100

    def test_union_fires_raw_or_blend(self, js):
        trades = [
            # raw edge .30 ≥ .25 → fires on raw
            _one_js_trade(20, True, 0.50, 0.20, blend_p=0.22, bracket="RAW"),
            # raw edge .05 < .25, blend edge .15 ≥ .10 → fires on blend
            _one_js_trade(30, True, 0.40, 0.35, blend_p=0.50, bracket="BLEND"),
            # raw .05, blend .05 → neither fires
            _one_js_trade(40, True, 0.45, 0.40, blend_p=0.45, bracket="NONE"),
        ]
        res = js.call("jsComputeSim", trades,
                      {**JS_BASE_PARAMS, "strategy": "union", "edgeFilter": 0.25})
        assert res["n"] == 2
        filtered = [r for r in res["tradeRecords"] if r["fill"] == "filtered"]
        assert len(filtered) == 1 and filtered[0]["bracket"] == "NONE"
