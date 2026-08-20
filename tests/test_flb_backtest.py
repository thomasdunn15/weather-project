"""FLB backtest: pure P&L logic (no network) — fees, sides, fill models."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from weather_markets.expansion.catalog import fee_cents

_spec = importlib.util.spec_from_file_location(
    "flb_backtest", Path(__file__).resolve().parents[1] / "scripts" / "analysis" / "flb_backtest.py"
)
bt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bt
_spec.loader.exec_module(bt)


def test_trade_pnl_win_loss_and_maker_beats_taker():
    assert bt.trade_pnl(80, True, False) == 20 - fee_cents(80, "kalshi", False)   # win: +20 gross - fee
    assert bt.trade_pnl(80, False, False) == -80 - fee_cents(80, "kalshi", False)  # loss: -cost - fee
    assert bt.trade_pnl(80, True, True) > bt.trade_pnl(80, True, False)            # maker fee cheaper


def test_favorite_buys_yes_at_ask_taker_bid_maker():
    strat, entry, won, _ = bt.simulate_market((78, 82), "yes", maker=False)
    assert strat == "favorite" and entry == 82 and won is True          # taker pays the ask
    _, entry_m, _, _ = bt.simulate_market((78, 82), "yes", maker=True)
    assert entry_m == 78                                                # maker rests at the bid


def test_fade_buys_no_and_loses_when_yes():
    strat, entry, won, net = bt.simulate_market((18, 22), "no", maker=False)
    assert strat == "fade" and entry == 100 - 18 and won is True and net > 0   # NO wins, taker pays 100-bid
    _, _, won2, net2 = bt.simulate_market((18, 22), "yes", maker=False)
    assert won2 is False and net2 < 0                                          # longshot hit -> fade loses


def test_midrange_is_skipped():
    assert bt.simulate_market((38, 42), "yes", maker=False) is None
