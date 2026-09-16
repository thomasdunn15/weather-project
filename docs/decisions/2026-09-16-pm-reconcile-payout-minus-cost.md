# Polymarket reconcile: realized = payout − cost, from the venue's BEFORE record

**Date:** 2026-09-16
**Status:** live on Ashburn (applied to all 16 ledger rows)
**Files:** `scripts/reconcile_pm_trades.py`, `scripts/snapshot_polymarket_prices.py`

## What was wrong

The fourth P&L misread. `collect_resolutions` read `afterPosition.realized`
for losses and `afterPosition.cost − fees` for wins. A losing LONG leaves
`after.realized` at 0 and `after.cost` at its pre-fee basis, so it was booked
as a **gain**. Two Miami longs did this:

| market | booked | true |
|---|---|---|
| 2026-09-01 gte91lt92 (long 128.9 @43.5c, resolved NO) | +$52.26 | −$56.02 |
| 2026-09-12 gte90lt91 (long 116.1 @57.5c, resolved NO) | +$63.30 | −$66.73 |

Ledger said +$420.44; venue cash said +$166.34. The kill switch (fires at
−$300 cumulative) was therefore $254 too lenient.

## What the venue states consistently

On the **before** record of every POSITION_RESOLUTION:
`cashValue` = payout at resolution (0 on a loss, |net| on a win),
`cost` = full basis including fees. `payout − cost` reproduces all 15 settled
markets and, summed with every trade in the account, ties to the balance to
the cent. The `after` fields and the resolution-level `side` label are not
consistent across long/short × win/loss and are no longer read.

Funding: the operator's credit is a **$20 `ACTIVITY_TYPE_REFERRAL_BONUS`** in
the activity feed, not a $10 promo outside it. It is now counted with
completed deposits; the promo constant is 0.

## Residual, known and accepted

Cumulative now reads +$176.03 vs cash-implied +$166.34: drift +$9.69. That is
the 2026-08-23 short that was bought back intraday at a loss before the
resting long replaced it. Positions closed before resolution never appear in
POSITION_RESOLUTION, so a resolution-based ledger cannot see them. The cash
cross-check keeps flagging it, which is correct behaviour. If intraday round
trips recur, the next step is trade-based P&L (Σ signed trade notional − fees
+ `cashValue − max(−net, 0)`), verified here to tie exactly.

## Same day: the quote feed had been dead since 09-13

Both the paper logger and the live trader exited daily with "no PM quotes
newer than 30min". `snapshot_polymarket_prices.py` polled every ladder the
venue lists as active (4,253 by 09-16, nearly all dead) with no throttle;
the gateway 429'd and the script swallowed the exception, landing ~20 quotes
a run, so today's Miami brackets were 75 min stale at the 14:46 decision.
Fixed: skip ladders older than yesterday (120 markets), pace calls at 0.3 s,
retry a 429 once, print the first failure. The 0.10-threshold change of 09-11
therefore had exactly one live day (09-12: two orders, +$63 gross booked,
true −$66.87 after this correction) before the feed went dark.
