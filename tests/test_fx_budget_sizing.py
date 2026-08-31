"""Sizing ForecastEx orders under IBKR's event-contract cap.

THE CAP COUNTS CONTRACTS, NOT DOLLARS. An event contract settles at $0 or $1,
so IBKR reserves $1.00 per contract and the limit price does not enter into it.
At $1,010 net liq the 2% allowance is 20 contracts a day, whether they cost 7c
or 85c.

This was diagnosed the expensive way. Six orders across five sessions were all
cancelled and not one ever filled: 08-23 sent 50 contracts, 08-24 sent 25,
08-25 sent 23, 08-27 sent 29 — every one above 20. The first fix read IBKR's
"mandatory cap price" prompt (limits of 65c/78c/85c reserving at 84c/96c/98c)
and sized on `min(1.0, limit * 1.35)`, which takes the SMALLER of the two bounds
where safety wanted the larger, and under-reserved every order it sized.

The decisive counter-example is 2026-08-25: 23 contracts at 65c is $14.95 of
premium, inside $20.20 on any price-based reading — inside it even at the full
1.35x headroom ($20.18) — and IBKR killed it anyway with "You have reached that
limit." Only the per-contract rule explains that, so the tests below assert on
contract COUNT and treat any price-sensitivity in sizing as the bug it was.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from live_trade_forecastex import RESERVE_PER_CONTRACT, budget_counts  # noqa: E402

CAP = 20.20  # 2% of the $1,010 probe account


def _picks(*limits):
    return [{"limit": c} for c in limits]


def _reserved(counts):
    """What IBKR actually holds against the cap: $1.00 a contract."""
    return sum(counts) * RESERVE_PER_CONTRACT


def test_every_order_ibkr_cancelled_would_now_fit():
    """Replay all four cancelled sessions against the cap that killed them."""
    for label, limits, probe_max in [
        ("08-23", (37, 7), 25),
        ("08-24", (65, 78, 85), 25),
        ("08-25", (65,), 23),
        ("08-27", (38, 85), 25),
    ]:
        counts = budget_counts(_picks(*limits), CAP, probe_max=probe_max)
        assert _reserved(counts) <= CAP, f"{label}: reserved ${_reserved(counts):.2f} > cap"
        assert all(n >= 1 for n in counts), f"{label}: sized something to zero — {counts}"


def test_the_2026_08_25_order_is_sized_down_below_twenty():
    """The case that refutes price-based sizing: $14.95 of premium, still killed.

    A price-based rule leaves 23 contracts alone. The correct rule cuts to 20.
    """
    assert budget_counts(_picks(65), CAP, probe_max=23) == [20]


def test_size_does_not_depend_on_price():
    """The old rule gave cheap contracts more size. Price is irrelevant to the
    cap, so a 7c pick and a 95c pick must be sized identically."""
    assert budget_counts(_picks(7), CAP, probe_max=1000) == \
           budget_counts(_picks(95), CAP, probe_max=1000)
    cheap, dear = budget_counts(_picks(10, 90), CAP, probe_max=1000)
    assert cheap == dear, "sizing regained a price term"


def test_total_never_exceeds_the_cap_for_any_pick_count():
    """Even split must not let the remainder push the total over."""
    for n in range(1, 9):
        counts = budget_counts(_picks(*([50] * n)), CAP, probe_max=1000)
        assert _reserved(counts) <= CAP, f"{n} picks reserved ${_reserved(counts):.2f}"


def test_a_full_price_contract_is_still_twenty_not_twentyone():
    counts = budget_counts(_picks(95), CAP, probe_max=100)
    assert counts == [20]


def test_probe_max_still_caps_a_large_budget():
    """A funded account must not silently scale past the probe size."""
    assert budget_counts(_picks(50), 10_000.0, probe_max=25) == [25]


def test_budget_is_split_evenly_not_spent_on_the_first_pick():
    """Even split is the operator's choice; the first pick must not eat it all."""
    one = budget_counts(_picks(50), CAP, probe_max=1000)[0]
    three = budget_counts(_picks(50, 50, 50), CAP, probe_max=1000)
    assert three == [one // 3] * 3


def test_a_pick_with_no_headroom_sizes_to_zero_rather_than_one():
    """Zero means "skip"; rounding up to 1 would breach the cap the caller is
    trying to respect."""
    assert budget_counts(_picks(90), 0.50, probe_max=25) == [0]


def test_no_picks_is_not_a_division_by_zero():
    assert budget_counts([], CAP, probe_max=25) == []
