# 2026-08-12 — Polymarket US live probe (Miami port), 100 contracts

## Decision
Go LIVE on Polymarket US with the Miami daily-high port at **100 contracts/signal**,
ahead of the planned 2–4 week paper window. Operator decision (explicit go-live +
sizing call), made the same week the Kalshi live book went dark: KORD halted 07-24
(−$708), KPHX halted 07-21 (−$384), KDFW halted 08-07 (−$615 at halt) — Miami is the
sole surviving live city (+$2,135) and is exactly what this port trades.

## Evidence for
- Day-matched replay 06-30→08-06 (33 days): PM-native +$12.80 (40 trades, 85% win)
  vs Kalshi +$5.15 (20 trades, 70%) at the live 0.25 threshold, 1 contract/signal.
  PM's finer 1°F bins ≈ 2× the signals at similar-or-better per-trade net.
- Measured venue: Kalshi-parity spreads (1–2¢) since mid-July, taker fee 14% below
  Kalshi, ~10k contracts quoted within 10¢.
- Same station (KMIA), same NWS CLI settlement discipline as the validated Kalshi edge.

## Evidence against / accepted risks
- Replay is one in-sample summer month; forward paper had only 3 days at go-live.
- Fill behavior never observed (first real execution payload unverified at decision
  time); quoted depth could be softer than measured.
- The broader model family just kill-switched in 3 cities — Miami is the survivor,
  but the regime warning is real.
- PM settlement tail quirk: no NWS data for a week → settles at last market price.

## Rails (in scripts/live_trade_polymarket.py — change only via a new decision doc)
- 100 contracts/signal, max 2 signals/day, edge threshold 0.25, entries 5–95¢
- Orders are synchronous IOC marketable limits ONLY: fill at-or-better or cancel;
  never rest on the book; thin books ⇒ partial fills, never price-walking past bound
- $200/day spend cap; cumulative kill −$300 (30% of the $1k bankroll) auto-writes
  `halt/PMKMIA`; the halt file aborts every run (touch it to stop manually)
- Self-settling vs observations with PM fee (0.06·p·(1−p)) each run, so the kill
  switch always sees current P&L

## Scaling ladder (pre-agreed triggers, not vibes)
1. **100 (now)** — week 1 must show: executions parse correctly, settlements
   reconcile vs the app statement, P&L direction consistent with replay.
2. **→250** — after ≥2 clean weeks AND measured fill rate at 100 shows the book
   absorbs us at bound (fill ratio ≥~80%), AND bankroll raised to ≥$2.5k.
3. **→500** — September-window decision: ≥$5k bankroll, fill-rate study at 250,
   and forward P&L (paper + live agreeing) clearing the same bar we hold Kalshi to.

## Addendum 2026-08-12: +2¢ IOC slippage allowance
Ladder measurement (14:15–14:46 UTC window, 14d): top-of-book holds only ~28–55
contracts (thin days 6–7), but ~120–200 sit within 2¢. An IOC bound at the quoted
entry would partial-fill ~30–50% of a 100-lot; bound = entry+2¢ (capped 97¢) reaches
the 2¢ ladder while hard-capping worst-case slippage at 2¢ — trivial against 25¢+
edges. `limit_price_cents` now records the bound actually sent; P&L settles on the
actual fill average. Per-city near-book capacity measured same day: LAX ~175,
MDW ~150, SFO ~125, NYC ~100, MIA ~100 max/signal (thin-day 2¢ depth).

## Rollback
`touch halt/PMKMIA` stops trading immediately; remove the cron line
(docs/crontab.txt + reinstall) to decommission. Positions are IOC-filled only —
there are never resting orders to cancel.
