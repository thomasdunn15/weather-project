"""reconcile_live_trades books from Kalshi's order + market records.
Fixtures are real orders; expected P&L is what /portfolio/settlements paid."""
import importlib.util
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location(
    "reconcile_live_trades", Path(__file__).parents[1] / "scripts" / "reconcile_live_trades.py")
rlt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rlt)

ORDERS = {
    # row 187: resting YES buy, canceled after 22.39 filled, YES won -> settled $11.48
    "o187": {"outcome_side": "yes", "fill_count_fp": "22.39", "initial_count_fp": "500.00",
             "maker_fill_cost_dollars": "0", "taker_fill_cost_dollars": "10.523300",
             "maker_fees_dollars": "0", "taker_fees_dollars": "0.390500"},
    # row 100: stored fill_count 300, but the order kept resting and filled 500; NO lost -> -$205
    "o100": {"outcome_side": "no", "fill_count_fp": "500.00", "initial_count_fp": "500.00",
             "maker_fill_cost_dollars": "205.000000", "taker_fill_cost_dollars": "0",
             "maker_fees_dollars": "0", "taker_fees_dollars": "0"},
    # row 169: NO price stored in the NO leg (old code booked +$399.90); NO won -> $99.90
    "o169": {"outcome_side": "no", "fill_count_fp": "500.00", "initial_count_fp": "500.00",
             "maker_fill_cost_dollars": "392.800000", "taker_fill_cost_dollars": "7.200000",
             "maker_fees_dollars": "0", "taker_fees_dollars": "0.100800"},
}
RESULTS = {"T187": "yes", "T100": "yes", "T169": "no", "OPEN": ""}


class FakeClient:
    def _request(self, method, path):
        oid = path.rsplit("/", 1)[-1]
        if oid not in ORDERS:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "http://x"),
                                        response=httpx.Response(404))
        return {"order": ORDERS[oid]}

    def get_market(self, ticker):
        return {"market": {"result": RESULTS[ticker]}}


def book(ticker, oid):
    return rlt.reconcile_one(None, FakeClient(), (1, ticker, oid), dry_run=True)


def test_books_venue_fill_cost_and_fees_to_the_cent():
    b = book("T187", "o187")
    assert (b["pnl_cents"], b["fill_count"], b["fill_status"], b["fee_cents"]) == (1148, 22, "partial", 39)
    b = book("T100", "o100")
    assert (b["pnl_cents"], b["fill_count"], b["fill_status"], b["won"]) == (-20500, 500, "filled", False)
    assert book("T169", "o169")["pnl_cents"] == 9990


def test_waits_for_finalized_market_and_skips_orders_kalshi_dropped():
    assert book("OPEN", "o187")["status"] == "not_finalized"
    assert book("T187", "gone")["status"] == "venue_unavailable"
