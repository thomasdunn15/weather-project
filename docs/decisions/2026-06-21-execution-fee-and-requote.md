# Execution accuracy: maker/taker fee model + 45-min re-quote (2026-06-21)

Source: `docs/research/md/2026-06-21-execution-policy-maker-vs-taker.md` (§Recommendation,
backlog items 1 & 2). Branch `feature/maker-taker-fees` (off main). **Proposals to validate —
not deployed.** Config freeze is lifted but "validate before live + log rationale" still applies.

## 1. Maker/taker-aware Kalshi fee model

**Change.** `kalshi_fee_cents(entry_price_cents, maker=False)` in `dashboard/sim_python.py`,
its byte-mirror `kalshiFeeCents(entry, maker)` in `dashboard/static/app.js`, and
`scripts/live_trade.py`:
- taker (marketable / cross fill): `ceil(0.07·P·(1−P)·100)`, min 1¢ — **unchanged**.
- maker (resting / post-only fill): `ceil(0.0175·P·(1−P)·100)`, min 1¢ — **¼ the rate** (Kalshi
  2026 schedule; resting orders were historically fee-exempt).

`simulate_pnl` marks a fill maker only when it rested **strictly inside** the cross
(`post_inside`/`limit_*` and `entry < cross_entry`); cross / at-ask / premium / no-room
fall-backs are takers. Mirrors `app.js` exactly.

**Why.** The old flat 7% overcharged makers ~4× — understating the maker policy in every
backtest by ~¾ of the fee (~1¢/contract at mid-price). With integer cents this collapses to
maker ≈ 1¢ vs taker 1–2¢, recovering ~1¢/ctr at mid as the research predicted.

**Parity.** `tests/test_sim_parity.py::test_fee_formula_parity` extended to assert JS == Python
on BOTH branches; suite stays 8/8. The default (1-arg) call is still the taker rate.

## 2. P4 re-run with corrected fees (KORD)

`scripts/analysis/backtest_mw.py` uses `simulate_pnl`, so the fix flows in automatically. The
maker case = `limit_70` (post_inside ~70%). OOS walk-forward Sharpe, flat-fee → maker-fee:

| KORD variant | maker (limit_70) before → after | cross (taker, unchanged) |
|---|---|---|
| **blend-flat** | **2.90 → 3.04**  (clears 2.5) | 2.10 |
| raw-flat | 1.57 → 1.73 | 0.08 |
| blend-model | 1.54 → 1.65 | 2.67 |
| raw-model | −0.28 → −0.13 | 0.19 |

The maker case improves ~+0.1–0.15 Sharpe everywhere and the best config (blend-flat 3.04)
clears 2.5. **But the DEPLOY GATE = `min(maker, cross)`**, and the cross/taker leg (2.10) is
unchanged by a maker-fee fix, so the gate still FAILs at 2.10. The fee fix improves backtest
*accuracy*; it does not create deployable edge — consistent with the research ("execution
recovers cents, does not create edge"). **No live config change.**

## 3. 45-minute re-quote for unfilled maker orders

`scripts/monitor_fills.py` adds `requote_unfilled_makers()` + a pure `_requote_decision()`:
for a **fully-unfilled** resting maker order older than **T=45m**, cancel (DELETE) and re-post
the same size as a **cross at the ask** iff `|edge| ≥ Y_city` (KORD 0.25, KMIA 0.10, Dallas
0.25); otherwise leave it to expire. GTC-only TIF ⇒ cancel + V2 create (re-post).

Guards: **double-fill** — re-checks live fill state right before AND after cancel; if any fill
appeared, records it and does NOT repost. **Runaway** — one re-quote per order via a `REQUOTE@45m`
notes marker. Unit-tested in `tests/test_requote.py` (7 cases incl. guard precedence).

**OFF by default.** Enable with `--requote` (places real orders) or `--requote-dry-run`
(log-only, safe). `EXECUTION_MODE="smart"` and the X cross thresholds are **unchanged** (research
says they're well-aligned).

## What must happen before this trades live
1. **V2 create endpoint confirmed working** — the re-post uses `place_limit_order` (V2
   `POST /portfolio/events/orders`). This branch was developed against that fix (uncommitted on
   main as of 2026-06-21, validated live only at the 14:46 KORD cron). **Do not enable `--requote`
   in the cron until V2 create is confirmed.**
2. **Paper-validate** the re-quote with `--requote-dry-run` for a window, confirming it picks the
   right orders / ask prices, before `--requote` goes in `docs/crontab.txt`.
3. The live crontab is **unchanged** here.
