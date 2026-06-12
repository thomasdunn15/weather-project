"""Unit tests for the pure decision logic in scripts/live_trade.py.

This module changed five times during the week of 2026-06-08 (union mode,
smart execution, ensemble guards, sizing changes) with no test coverage —
each change was verified only by eyeballing a dry run. These tests pin the
behavior that the live cron depends on.

Run: uv run pytest tests/test_live_trade_logic.py
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import live_trade  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_exec_path — the 'smart' execution branch
# ---------------------------------------------------------------------------

class TestResolveExecPath:
    def test_smart_high_edge_crosses(self):
        assert live_trade.resolve_exec_path("smart", 0.50) == "cross_at_ask"

    def test_smart_threshold_is_inclusive(self):
        # |edge| >= threshold crosses. The boundary case matters: a trade at
        # exactly 40% edge should NOT risk a missed fill.
        t = live_trade.SMART_CROSS_EDGE_THRESHOLD
        assert live_trade.resolve_exec_path("smart", t) == "cross_at_ask"

    def test_smart_below_threshold_posts_inside(self):
        t = live_trade.SMART_CROSS_EDGE_THRESHOLD
        assert live_trade.resolve_exec_path("smart", t - 0.001) == "post_inside_spread"

    def test_smart_uses_absolute_edge(self):
        # NO-side signals carry negative edge; conviction is the magnitude.
        assert live_trade.resolve_exec_path("smart", -0.60) == "cross_at_ask"
        assert live_trade.resolve_exec_path("smart", -0.10) == "post_inside_spread"

    @pytest.mark.parametrize("mode", ["post_inside_spread", "cross_at_ask", "cross_with_premium"])
    def test_non_smart_modes_pass_through(self, mode):
        assert live_trade.resolve_exec_path(mode, 0.99) == mode
        assert live_trade.resolve_exec_path(mode, 0.0) == mode


# ---------------------------------------------------------------------------
# incomplete_ensembles — the pre-trade data guard
# ---------------------------------------------------------------------------

class TestIncompleteEnsembles:
    FULL = {"gefs": 31, "ifs": 50, "hrrr": 1}

    def test_full_ensemble_passes(self):
        assert live_trade.incomplete_ensembles(self.FULL, ["gefs", "ifs", "hrrr"]) == []

    def test_missing_model_halts(self):
        present = {"ifs": 50, "hrrr": 1}  # the 2026-06-10 failure state
        assert live_trade.incomplete_ensembles(present, ["gefs", "ifs", "hrrr"]) == ["gefs=0/31"]

    def test_partial_ensemble_halts(self):
        # 15 of 31 GEFS members (DB blip mid-ingest) must NOT pass.
        present = {"gefs": 15, "ifs": 50, "hrrr": 1}
        assert live_trade.incomplete_ensembles(present, ["gefs", "ifs", "hrrr"]) == ["gefs=15/31"]

    def test_only_configured_models_checked(self):
        # KMIA uses gefs+ifs; absent HRRR must not halt it.
        present = {"gefs": 31, "ifs": 50}
        assert live_trade.incomplete_ensembles(present, ["gefs", "ifs"]) == []

    def test_multiple_shortfalls_all_reported(self):
        present = {"gefs": 30, "ifs": 49, "hrrr": 1}
        out = live_trade.incomplete_ensembles(present, ["gefs", "ifs", "hrrr"])
        assert out == ["gefs=30/31", "ifs=49/50"]

    def test_extra_members_pass(self):
        # More members than expected (e.g. NOAA adds members) should not halt.
        present = {"gefs": 32, "ifs": 51, "hrrr": 1}
        assert live_trade.incomplete_ensembles(present, ["gefs", "ifs", "hrrr"]) == []


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_cities():
    """Inject test cities into CITY_CONFIG; remove them afterwards."""
    live_trade.CITY_CONFIG["_TEST_UNIT"] = {
        "sizing_mode": "unit", "unit_contracts": 500,
    }
    live_trade.CITY_CONFIG["_TEST_AMT"] = {
        "sizing_mode": "amount", "amount_dollars": 15.0,
        "max_contracts_per_trade": 500,
    }
    yield
    del live_trade.CITY_CONFIG["_TEST_UNIT"]
    del live_trade.CITY_CONFIG["_TEST_AMT"]


class TestSizeTrade:
    def test_unit_mode_constant(self, synthetic_cities):
        for price in (5, 30, 95):
            sig = {"limit_price": price, "edge": 0.50}
            assert live_trade.size_trade("_TEST_UNIT", sig, 0) == 500

    def test_amount_mode_divides_by_price(self, synthetic_cities):
        # $15 at 30¢ = 1500¢ // 30¢ = 50 contracts
        sig = {"limit_price": 30, "edge": 0.20}
        assert live_trade.size_trade("_TEST_AMT", sig, 0) == 50

    def test_amount_mode_depth_cap(self, synthetic_cities):
        # $15 at 1¢ = 1500 contracts, capped at 500
        sig = {"limit_price": 1, "edge": 0.20}
        assert live_trade.size_trade("_TEST_AMT", sig, 0) == 500

    def test_amount_mode_zero_price_is_zero(self, synthetic_cities):
        sig = {"limit_price": 0, "edge": 0.20}
        assert live_trade.size_trade("_TEST_AMT", sig, 0) == 0

    def test_no_edge_scaling_in_frozen_config(self, synthetic_cities):
        # The edge-cap-for-sizing experiment was reverted 2026-06-10 (it cut
        # Sharpe). Sizing must NOT depend on edge magnitude. If this fails,
        # someone re-introduced edge-scaled sizing without re-validating.
        low = live_trade.size_trade("_TEST_UNIT", {"limit_price": 30, "edge": 0.11}, 0)
        high = live_trade.size_trade("_TEST_UNIT", {"limit_price": 30, "edge": 0.90}, 0)
        assert low == high == 500


class TestEvenSplitStake:
    def test_even_division(self):
        assert live_trade.even_split_stake_cents(1000, 4) == 250

    def test_integer_floor(self):
        assert live_trade.even_split_stake_cents(1000, 3) == 333

    def test_zero_signals(self):
        assert live_trade.even_split_stake_cents(1000, 0) == 0


# ---------------------------------------------------------------------------
# frozen-config invariants (docs/config_freeze_2026-06-12.md)
# ---------------------------------------------------------------------------

class TestFrozenConfig:
    """Pin the frozen live config. If one of these fails, either the freeze
    was deliberately lifted (update the test alongside the precommit doc) or
    something drifted by accident (the bad case this exists to catch)."""

    def test_kord(self):
        c = live_trade.CITY_CONFIG["KORD"]
        assert c["use_union"] is True
        assert c["edge_threshold"] == 0.25
        assert c["blend_edge_threshold"] == 0.10
        assert c["sizing_mode"] == "unit"
        assert c["unit_contracts"] == 500
        assert c["is_active"] is True

    def test_kmia(self):
        c = live_trade.CITY_CONFIG["KMIA"]
        assert c["use_union"] is False
        assert c["use_blend"] is True
        assert c["blend_edge_threshold"] == 0.10
        assert c["sizing_mode"] == "unit"
        assert c["unit_contracts"] == 500
        assert c["is_active"] is True

    def test_execution_mode(self):
        assert live_trade.EXECUTION_MODE == "smart"
        assert live_trade.SMART_CROSS_EDGE_THRESHOLD == 0.40

    def test_aggregate_limits(self):
        assert live_trade.AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS == 300.0
        assert live_trade.AGGREGATE_CUMULATIVE_KILL_DOLLARS == 1000.0


# ---------------------------------------------------------------------------
# integration smoke: the dry run must never crash
# ---------------------------------------------------------------------------

class TestDryRunSmoke:
    def test_kord_dry_run_exits_cleanly(self):
        """Run the real cron entrypoint without --live. Whatever the data
        state (full ensembles → signals, missing data → HALT), it must exit 0
        and print one of the two known outcomes — never a traceback."""
        proc = subprocess.run(
            ["uv", "run", "python", "scripts/live_trade.py", "--city", "KORD"],
            capture_output=True, text=True, timeout=300,
            cwd=str(SCRIPTS_DIR.parent),
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"dry run exited {proc.returncode}:\n{out[-2000:]}"
        assert ("forecast data check OK" in out) or ("HALT" in out), out[-2000:]
        assert "Traceback" not in out, out[-2000:]
