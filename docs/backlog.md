# Strategy backlog — evaluate at config re-evaluation (next: 2026-07-10)

Ideas land here instead of in the live code during a freeze. Each entry:
date, idea, evidence that prompted it. Nothing here is a commitment.

## Open

- **2026-06-12 · KMDW-trained model for Chicago.** KXHIGHCHI settles on
  Midway's climo report; model is trained end-to-end on KORD. 1-2°F
  divergence on lake-breeze days. KMDW GEFS backfill in progress; fit EMOS +
  blend on KMDW during the freeze, deploy only at re-eval if validation
  passes. HIGHEST PRIORITY backlog item.
- **2026-06-12 · Walk-the-book sizing.** Orderbook depth snapshots
  accumulating since 2026-06-10. By ~July 1 run the real-depth walk-book
  backtest: how many contracts can each signal absorb before marginal edge
  goes negative? Answer feeds any sizing-up decision.
- **2026-06-12 · IBKR ForecastEx as second venue.** Genuinely separate
  order book (unlike Robinhood, which routes to Kalshi's book). Same KORD
  model applies but contracts are T+1/T+2 (no same-day) → expect ~0.4-0.6×
  same-day Sharpe. Build only if walk-book shows Kalshi depth caps us.
- **2026-06-12 · Secondary paper cron at ~17:00 UTC.** Time-of-day analysis
  (scripts/analysis/best_time_of_day.py) showed apparent late-day P&L
  improvement for KORD, but it's probably fill-rate artifact. A 17:00 UTC
  paper-only cron would measure it honestly without touching live trades.
- **2026-06-12 · HRRR weighting / model-disagreement penalty.** On
  2026-06-10, HRRR alone nailed the high (90.5°F) while GEFS/IFS ran cold;
  flat member-weighting diluted it 1/81. Equal-model weighting or a
  disagreement-widens-sigma term might help. Needs a real backtest, not a
  one-day anecdote.
- **2026-06-09 · Cross-platform arb (Kalshi vs Polymarket US).** Needs KMDW
  price history from the forward snapshots; revisit once a few weeks have
  accumulated.

## Evaluated and rejected

- **2026-06-10 · Anti-stacking (max signals/day) + edge-cap sizing.**
  Shipped on one bad day's evidence, reverted same day: both reduce Sharpe
  and total return across the full sample. Remain available as dashboard
  what-if toggles.
- **2026-06-09 · Multi-bracket, Kelly, EMOS feature additions.** All null
  results vs single-bracket + blend baseline (see memory/project notes).
  Don't re-test on similar data.
