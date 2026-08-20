# 2026-08-17 — Retire Chicago (KORD), Dallas (KDFW), Phoenix (KPHX)

## Decision
The three halted cities are **retired, not resumed**. `is_active: False` in
`CITY_CONFIG`, cron lines commented out in `docs/crontab.txt` (reinstalled),
halt files left in place as a third layer. Live Kalshi universe is now
**Miami (raw@0.10) + New Orleans (raw@0.15)**.

## Why — no config rescues them
Each city was swept across four raw thresholds plus blend-only and the union
rule, forward-test rows only (real-time logged `paper_trades`, 2026-06→08),
scored at 500 contracts with the 7% taker fee.

**Chicago (KORD) — every single config loses:**

| Config | n | Win% | Net | Sharpe |
|--------|---|------|-----|--------|
| raw@0.10 | 144 | 33.3% | −$1,620 | −1.50 |
| raw@0.15 | 93 | 31.2% | −$1,865 | −2.43 |
| raw@0.20 | 57 | 24.6% | −$2,605 | −4.64 |
| raw@0.25 | 40 | 27.5% | −$1,295 | −3.05 |
| blend@0.10 | 36 | 22.2% | −$2,300 | −6.79 |
| union (live rule) | 58 | 25.9% | −$2,365 | −4.11 |

**Dallas (KDFW)** — loose thresholds are breakeven-noise (raw@0.10 +$315 /
Sharpe 0.28; raw@0.15 +$275 / 0.27; raw@0.20 +$245 / 0.37), everything tighter
or blended is negative (raw@0.25 −$885, blend −$1,680, union −$1,935). The
least-bad config reverses hard across halves: raw@0.15 first half +$1,910
(41.2% win) → second half **−$1,635** (25.5%).

**Phoenix (KPHX)** — blend looks strong in aggregate (n=29, 72.4% win,
+$2,685, Sharpe 6.51) and rescues the union to +$1,355, but the union
split-half shows it is entirely a first-half artifact: +$3,055 (66.7% win)
→ **−$1,700** (25.9%). Raw is negative at every threshold.

## Interpretation
This is not a threshold-tuning problem — it is a regime break. Chicago's
full-history backtest was the single best city on record (+$14,865 at 500
contracts, Sharpe 3.59) and is now negative on every configuration; that
gap is the in-sample/forward gap, and it is consistent with the edge-decay
finding already on file (2026-07-29: Chicago Sharpe 1.70 → 0.27, second half
negative). Dallas and Phoenix show the same "looked fine, then reversed"
shape in their least-bad configs.

Contrast with the two cities kept live the same day: Miami raw@0.10 is
stable-to-improving across halves (51.8% → 63.8% win), New Orleans raw@0.15
declines but stays positive in both halves. Those are the only two of the
twelve Kalshi cities that survive a split-half check.

## What changed mechanically
- `scripts/live_trade.py`: `is_active: False` on KORD/KDFW/KPHX. (Display +
  paper-signal suppression only — the halt files and the removed crons are
  what actually stop trading.)
- `docs/crontab.txt`: the three `live_trade.py --city …` lines commented with
  a pointer to this doc; `crontab docs/crontab.txt` reinstalled. Active live
  crons are now KMIA 15:30 UTC and KMSY 14:58 UTC only.
- `halt/KORD`, `halt/KDFW`, `halt/KPHX` left in place deliberately — belt and
  braces if a cron line is ever restored without re-reading this doc.
- Aggregate limits (unchanged by this doc, set by the KMSY go-live):
  daily $650, cumulative $2,125.

## Reversal conditions
Do not resume on a threshold tweak — that is what this analysis already
ruled out. A resume needs a *new* reason: a materially different signal
(different model mix, different decision time, a market-blend refit on
post-decay data), validated forward, with a fresh decision doc. The paper
logger keeps running for all three, so the data to justify that will exist
if the regime turns.
