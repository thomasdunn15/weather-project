# Polymarket BUY_SHORT wire price was the NO bound, not the YES leg

**Date:** 2026-08-23
**Status:** fixed
**Files:** `src/weather_markets/polymarket.py`, `tests/test_polymarket_order_price.py`

## Symptom

2026-08-22 KMIA signal produced an order that filled **0 of 150** while the book
held ~54-98 contracts inside our limit. The order was accepted (id
`C1AXWRRMMDK0`) and appears in no execution record anywhere.

## Cause

`create_order` shipped `price_usd` verbatim. A `BUY_SHORT` is submitted as
`ORDER_SIDE_SELL` of the YES leg, so the venue reads `price` as a **YES-side
floor**, never as the NO price. The stored response is unambiguous:

```json
"side": "ORDER_SIDE_SELL", "price": {"value": "0.64"},
"quantity": 150, "cumQuantity": 0, "leavesQuantity": 150,
"tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL", "state": "ORDER_STATE_NEW"
```

"Sell YES at >= 0.64" against a 0.38-0.43 YES bid is not marketable. The IOC
cancelled untouched. Correct limit was `1 - 0.64 = 0.36`.

## Why it hid for four days

The inversion only bites when the NO bound is HIGH. A low NO bound becomes a low
YES floor that any bid clears, so the order fills and looks fine — while the
price cap silently does nothing.

| date | NO bound | sent | YES bid | filled | verdict |
|---|---|---|---|---|---|
| 08-20 | 52c | 0.52 | ~0.48 | 56.3/100 | partial, cap inactive |
| 08-21 | 38c | 0.38 | ~0.64 | 150/150 | filled by luck |
| **08-22** | **64c** | **0.64** | **0.38-0.43** | **0/150** | **missed** |
| 08-23 | 42c | 0.42 | ~0.60 | 150/150 | filled; took NO 43c vs 42c bound |

08-23 is the tell: an execution landed at NO 43c against a 42c bound. Under the
correct YES floor (0.58) that execution would have been refused.

So the bug had two faces — missed fills on expensive NO, and **no price
protection at all** on cheap NO. The second is the dangerous one: it had not
cost money yet only because the market happened to sit well through our floor.

## Fix

Convert in `create_order`, not at the call site, so every future caller inherits
it. Added a `[0,1]` guard so a cents value (64) raises instead of shipping a
nonsense limit.

## Verification

`tests/test_polymarket_order_price.py`, 7 cases, including a replay asserting the
08-22 order would have been marketable against the 0.38 bid it actually faced.
Full suite 230 passed (1 pre-existing unrelated `KORD` dry-run failure).

Not yet confirmed against a live fill — the next BUY_SHORT is the real test.
Watch that the achieved NO price lands at or under the bound.
