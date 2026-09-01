"""The entry log is a write endpoint reached from a browser, so the body is
untrusted input — and it is the ONLY record that a Robinhood position exists,
since Robinhood publishes no API for event contracts to check it against.

Two properties matter: bad input is rejected before it can touch anything, and
nothing numeric is taken from the body at all. The number that actually gets
written is re-derived server-side — a stale page recorded 66 contracts for a
pick the card showed as 50 when the size cap was not in that derivation path.
"""
import inspect

import pytest

from dashboard import data_forecastex as df


def test_bad_side_is_rejected_before_the_connection_is_touched():
    """conn=None proves nothing was queried: it would raise AttributeError."""
    with pytest.raises(ValueError, match="side must be yes|no"):
        df.record_entry(None, {"ticker": "UHLAX_090126_77", "side": "maybe"})
    with pytest.raises(ValueError, match="side must be yes|no"):
        df.record_entry(None, {"ticker": "UHLAX_090126_77"})


def test_no_number_is_read_out_of_the_request_body():
    """Only `ticker`, `side` and the free-text `note` may come from the client."""
    src = inspect.getsource(df.record_entry)
    reads = {ln.split('payload.get(')[1].split(')')[0].strip('"\' ')
             for ln in src.splitlines() if "payload.get(" in ln}
    assert reads <= {"ticker", "side", "note"}, f"body is trusted for {reads}"


def test_the_write_uses_the_server_derived_pick_not_the_body():
    src = inspect.getsource(df.record_entry)
    insert = src[src.index("INSERT INTO rh_entries"):]
    for field in ("pick[\"contracts\"]", "pick[\"limit\"]", "pick[\"lastPx\"]",
                  "pick[\"pModel\"]", "pick[\"edge\"]"):
        assert field in insert, f"{field} not sourced from the re-derived pick"


def test_capacity_reaches_the_derivation():
    """The recorded size must be the size the card showed; _trading() only caps
    it when the capacity table is passed in."""
    src = inspect.getsource(df.record_entry)
    assert "_capacity(_backtest())" in src, "picks re-derived without capacity"
