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

    def test_per_city_cross_threshold(self):
        # KMIA's low threshold (0.10) makes a 12% blend edge CROSS, where the
        # default 0.40 would post passively (the 2026-06-17 missed-fills bug).
        assert live_trade.resolve_exec_path("smart", 0.123, 0.10) == "cross_at_ask"
        assert live_trade.resolve_exec_path("smart", 0.123, 0.40) == "post_inside_spread"
        # boundary is inclusive at the per-city threshold too
        assert live_trade.resolve_exec_path("smart", 0.10, 0.10) == "cross_at_ask"


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
        assert c["smart_cross_edge_threshold"] == 0.40   # KORD execution unchanged
        assert c["sizing_mode"] == "unit"
        assert c["unit_contracts"] == 500
        assert c["is_active"] is True

    def test_kmia(self):
        c = live_trade.CITY_CONFIG["KMIA"]
        assert c["use_union"] is False
        assert c["use_blend"] is True
        assert c["blend_edge_threshold"] == 0.10         # edge filter UNCHANGED — same trades fire
        assert c["smart_cross_edge_threshold"] == 0.10   # exec fix 2026-06-17: cross instead of miss fills
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


# ---------------------------------------------------------------------------
# best_cross_price_from_book — order-book parsing for the cross fallback
# ---------------------------------------------------------------------------

# The actual KORD T74 book at 2026-06-15 14:46:16 UTC — the moment the bot's
# post_only YES @5¢ was rejected. Best NO bid was 95¢ → YES ask (cross) = 5¢.
T74_BOOK_1446 = {
    "orderbook_fp": {
        "yes_dollars": [["0.04", 80], ["0.03", 539], ["0.02", 198], ["0.01", 2006]],
        "no_dollars": [["0.95", 82], ["0.94", 1025], ["0.93", 693], ["0.92", 112],
                       ["0.06", 33], ["0.05", 200], ["0.01", 2652]],
    }
}


class TestBestCrossPriceFromBook:
    def test_today_t74_yes_cross_is_5(self):
        # Regression for 2026-06-15: YES cross = 100 − best NO bid (95) = 5¢.
        assert live_trade.best_cross_price_from_book(T74_BOOK_1446, "yes") == 5

    def test_today_t74_no_cross(self):
        # NO cross = 100 − best YES bid (4) = 96¢.
        assert live_trade.best_cross_price_from_book(T74_BOOK_1446, "no") == 96

    def test_empty_book_returns_none(self):
        assert live_trade.best_cross_price_from_book({"orderbook_fp": {}}, "yes") is None
        assert live_trade.best_cross_price_from_book({}, "no") is None

    def test_legacy_shape(self):
        legacy = {"orderbook": {"yes": [["0.40", 10]], "no": [["0.55", 10]]}}
        assert live_trade.best_cross_price_from_book(legacy, "yes") == 45   # 100-55
        assert live_trade.best_cross_price_from_book(legacy, "no") == 60    # 100-40

    def test_malformed_levels_skipped(self):
        book = {"orderbook_fp": {"no_dollars": [["bad", 1], ["0.90", 5]], "yes_dollars": []}}
        assert live_trade.best_cross_price_from_book(book, "yes") == 10   # 100-90


# ---------------------------------------------------------------------------
# place_with_guaranteed_fill — the cross-fallback placement logic
# ---------------------------------------------------------------------------

class FakeClient:
    """Records place_limit_order calls; behavior() decides success/raise."""
    def __init__(self, behavior, book=None):
        self._behavior = behavior
        self._book = book if book is not None else {}
        self.calls = []

    def place_limit_order(self, **kw):
        self.calls.append(kw)
        return self._behavior(**kw)

    def get_orderbook(self, ticker):
        if isinstance(self._book, Exception):
            raise self._book
        return self._book


def _ok(order_id="OK"):
    return {"order": {"order_id": order_id}}


class TestPlaceWithGuaranteedFill:
    BASE = dict(ticker="KXHIGHCHI-26JUN15-T74", side="yes", count=500,
                limit_price=5, cross_price=6, client_order_id="livech-KORD-x-T74-yes")

    def test_maker_success_no_fallback(self):
        client = FakeClient(lambda **kw: _ok("M1"))
        status, price, koid, coid, note = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=True, **self.BASE)
        assert status == "placed" and price == 5 and koid == "M1"
        assert coid == self.BASE["client_order_id"] and note == ""
        assert len(client.calls) == 1 and client.calls[0]["post_only"] is True

    def test_today_t74_fallback_crosses_at_live_ask(self):
        # Reproduce 2026-06-15: post_only @5¢ → 400; book shows YES ask 5¢ →
        # resubmit as taker @5¢. THIS is the trade the bot used to drop.
        def behavior(**kw):
            if kw["post_only"]:
                raise Exception("Client error '400 Bad Request' for url ...")
            return _ok("CROSS1")
        client = FakeClient(behavior, book=T74_BOOK_1446)
        status, price, koid, coid, note = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=True, **self.BASE)
        assert status == "placed"
        assert price == 5                     # live ask from the book
        assert koid == "CROSS1"
        assert coid == self.BASE["client_order_id"] + "-x"
        assert "cross-fallback" in note
        # two attempts: the rejected maker, then the taker
        assert [c["post_only"] for c in client.calls] == [True, False]

    def test_fallback_uses_signal_cross_when_book_unavailable(self):
        def behavior(**kw):
            if kw["post_only"]:
                raise Exception("400 Bad Request")
            return _ok("CROSS2")
        client = FakeClient(behavior, book=RuntimeError("orderbook down"))
        status, price, koid, coid, note = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=True, **self.BASE)
        assert status == "placed" and price == 6   # fell back to signal cross_price
        assert client.calls[1]["price_cents"] == 6

    def test_both_fail_returns_rejected(self):
        client = FakeClient(lambda **kw: (_ for _ in ()).throw(Exception("400 Bad Request")),
                            book=T74_BOOK_1446)
        status, price, koid, coid, note = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=True, **self.BASE)
        assert status == "rejected" and koid is None
        assert "cross-fallback" in note
        assert [c["post_only"] for c in client.calls] == [True, False]

    def test_taker_primary_failure_no_fallback_loop(self):
        # A non-post_only primary that fails is not a would-cross race; don't
        # spin a second order.
        client = FakeClient(lambda **kw: (_ for _ in ()).throw(Exception("400")))
        status, *_ = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=False, **self.BASE)
        assert status == "rejected"
        assert len(client.calls) == 1

    def test_429_retries_then_succeeds(self):
        state = {"n": 0}
        def behavior(**kw):
            if state["n"] < 2:
                state["n"] += 1
                raise Exception("429 Too Many Requests")
            return _ok("AFTER_RETRY")
        client = FakeClient(behavior)
        status, price, koid, *_ = live_trade.place_with_guaranteed_fill(
            client, primary_post_only=True, sleep=lambda _s: None, **self.BASE)
        assert status == "placed" and koid == "AFTER_RETRY"
        assert len(client.calls) == 3   # two 429s + success, all on the maker order
