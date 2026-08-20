# 2026-08-17 — Miami-only book; New Orleans offboarded

## Decision
The live Kalshi universe is **Miami alone** (raw@0.10, 500 units, 15:30 UTC).
New Orleans (KMSY) is offboarded the same day it was added, without ever having
traded live. Aggregate risk limits tightened from $650/$2,125 to **$150/$500**
(= Miami's own limits) so a future re-activation cannot silently inherit a
four-city risk envelope.

## The decisive evidence — realized money, not backtests
Per-city realized P&L from `live_trades` (2026-05-31 → 2026-08-06):

| City | Trades | Win% | Realized |
|---|---|---|---|
| **Miami** | 30 | 60% | **+$2,135** |
| other/manual | 6 | 50% | +$191 |
| Phoenix | 15 | 33% | −$384 |
| Dallas | 38 | 26% | −$735 |
| Chicago | 43 | 26% | −$956 |
| **Net** | 132 | | **+$251** |

Miami earned +$2,135; the other three cities lost −$2,075 and cancelled it.
A Miami-only book would have returned ~8x the actual net over the identical
period on a third of the trades. The "diversification" from extra cities was
negative-EV — this is the same conclusion the forward-only analysis reached
(full-history backtest +$13,010 vs forward-only −$810), now confirmed in cash.

## Why New Orleans specifically
It was the weakest evidence we kept even at go-live (raw@0.15 declining across
halves: H1 +$2,895 → H2 +$1,585; no capacity study; blend unusable at n=1).
Decisively, it is **untradeable on ForecastEx** — only 12 of 99 days show ANY
flow — so it cannot join the two-venue structure that makes the Miami book
work (below). A city that can only ever trade on one venue adds concentrated
single-venue risk for a declining edge.

## Why concentration is not reckless here: the venues decorrelate
Settlement sources, VERIFIED from contract specs (not assumed):
- Kalshi KMIA → NWS Climatological Report (Daily)
- Polymarket KMIA → NWS Climatological Report (Daily) — **same as Kalshi**
- ForecastEx UHMIA → **Weather Underground** — a genuinely different number

Because Kalshi and ForecastEx settle on different sources (~0.7 F apart,
differing on 59% of days), the same forecast can win on one and lose on the
other. Measured daily P&L correlation is only **r = +0.29** (same direction
just 71% of days), over 56 overlapping days at 500 contracts each:

| Approach | Total | Sharpe | Worst day | Max DD |
|---|---|---|---|---|
| Kalshi 500 | $7,455 | 5.79 | −$760 | −$1,030 |
| ForecastEx 500 | $7,425 | 6.79 | −$570 | −$1,100 |
| **Both, 500 each** | **$14,880** | **7.77** | **−$820** | **−$1,680** |
| Kalshi alone @1000 | $14,910 | 5.79 | −$1,520 | −$2,060 |

Splitting the same exposure across two venues returns the same dollars with
~half the worst-day risk and 34% better Sharpe — and keeps each venue inside
its measured ~500–700 capacity ceiling instead of overloading one book.

## Polymarket's role (different from ForecastEx)
Polymarket settles on the SAME NWS CLI as Kalshi, so it is **capacity, not
diversification** — its outcomes are identical to Kalshi's for an equivalent
bracket. Its genuine advantages are finer 1 F bins (≈2x signal count) and a
lower taker fee (6·p·(1−p) vs Kalshi's 7%). Its correlation is unmeasurable
today (6 trades, 2 overlapping days) and the account has never funded.

## Mechanics
- `scripts/live_trade.py`: KMSY `is_active: False` (config retained for a
  future re-test); aggregate limits → $150/$500.
- `docs/crontab.txt`: KMSY line commented, `crontab docs/crontab.txt` installed.
  The only live cron remaining is KMIA at 15:30 UTC.
- Dashboard restarted; KMSY renders halted, aggregate dials read 150/500.
- Tests: 204 pass (1 pre-existing KORD dry-run failure, expected — retired).

## Concentration risks accepted
1. **The live config is unproven.** The +$2,135 was earned under BLEND-only;
   we switched to raw@0.10 today on paper evidence. Same paper→live gap that
   killed Chicago.
2. **Single operational point of failure.** The KMIA observation outage
   (2026-07-07 → 08-09) ran the model on stale data for a month unnoticed. On
   a one-city book that is the whole business — the staleness alert is now a
   requirement, not a nice-to-have.
3. **No fallback if the edge dies.** Chicago went best-in-project to negative
   in a quarter. Mitigated only by the fact that no other city was profitable
   anyway.

## Revisit
KMSY (and the retired cities) keep paper-logging. Re-entry requires a fresh
decision doc with forward evidence, not a threshold tweak.
