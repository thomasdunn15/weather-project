# Operator Digest (EVIDENCE-ONLY SAMPLE) - 2026-07-22 19:03Z

_No ANTHROPIC_API_KEY is configured in this environment, so this sample shows the
retrieved evidence exactly as the specialists would see it, WITHOUT the LLM synthesis
(no decision text, no debate, no ranked suggestions). Set anthropic_api_key in .env
(or ANTHROPIC_API_KEY) and re-run:
  uv run python scripts/ops_digest.py --out docs/digests/YYYY-MM-DD-ops-digest.md
for the real reasoned digest. Analytics only, not financial advice._

## Calibration drift

_Is model_prob_yes still well-calibrated against realized settlement outcomes, per city, vs the rolling 45-day baseline?_

- `[calib:KDFW]` KDFW calibration (Brier score, lower=better): last 45d 0.2033 (n=22) vs prior 45d n/a (n=0). Computed from live_trades.model_prob_yes vs settlement outcome.
- `[calib:KMIA]` KMIA calibration (Brier score, lower=better): last 45d 0.2242 (n=18) vs prior 45d n/a (n=0). Computed from live_trades.model_prob_yes vs settlement outcome.
- `[calib:KORD]` KORD calibration (Brier score, lower=better): last 45d 0.2657 (n=38) vs prior 45d n/a (n=0). Computed from live_trades.model_prob_yes vs settlement outcome.
- `[calib:KPHX]` KPHX calibration (Brier score, lower=better): last 45d 0.4045 (n=15) vs prior 45d n/a (n=0). Computed from live_trades.model_prob_yes vs settlement outcome.

## Regime detection

_Has forecast error or trading edge shifted meaningfully per city, recent window vs prior?_

- `[regime:KDFW:error]` KDFW forecast error (mean |ensemble_mean - actual high|, degF): last 45d 1.6688 (n=200) vs prior 45d 2.956.
- `[regime:KDFW:edge]` KDFW mean |edge|: last 45d 0.2129 (n=204) vs prior 45d 0.225. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KLAX:error]` KLAX forecast error (mean |ensemble_mean - actual high|, degF): last 45d 3.1055 (n=120) vs prior 45d 3.5417.
- `[regime:KLAX:edge]` KLAX mean |edge|: last 45d 0.2393 (n=123) vs prior 45d 0.199. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KMIA:error]` KMIA forecast error (mean |ensemble_mean - actual high|, degF): last 45d 3.4726 (n=55) vs prior 45d 3.317.
- `[regime:KMIA:edge]` KMIA mean |edge|: last 45d 0.1971 (n=78) vs prior 45d 0.1918. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KNYC:error]` KNYC forecast error (mean |ensemble_mean - actual high|, degF): last 45d 3.1063 (n=22) vs prior 45d 4.5987.
- `[regime:KNYC:edge]` KNYC mean |edge|: last 45d 0.1853 (n=23) vs prior 45d 0.244. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KORD:error]` KORD forecast error (mean |ensemble_mean - actual high|, degF): last 45d 2.2679 (n=252) vs prior 45d 2.1561.
- `[regime:KORD:edge]` KORD mean |edge|: last 45d 0.2172 (n=258) vs prior 45d 0.2235. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KPHX:error]` KPHX forecast error (mean |ensemble_mean - actual high|, degF): last 45d 2.1329 (n=100) vs prior 45d 2.9376.
- `[regime:KPHX:edge]` KPHX mean |edge|: last 45d 0.2224 (n=103) vs prior 45d 0.1804. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.
- `[regime:KSEA:error]` KSEA forecast error (mean |ensemble_mean - actual high|, degF): last 45d 2.5721 (n=150) vs prior 45d 2.8067.
- `[regime:KSEA:edge]` KSEA mean |edge|: last 45d 0.2168 (n=153) vs prior 45d 0.2329. A falling trend suggests edge decay; a rising trend suggests a regime shift worth checking.

## Execution anomalies

_Fill rate vs expectation, spread/cross regime, signs of adverse selection._

- `[exec:KDFW:fill]` KDFW fill rate (filled+partial / resolved orders): last 45d 0.875 (n=32) vs prior 45d None. Rejected/expired in the last 45d: 0.
- `[exec:KDFW:cross]` KDFW: 32 orders crossed the book in the last 45d; avg (cross_price - limit_price) = 1.8125c. A rising gap suggests adverse selection or a widening spread regime.
- `[exec:KMIA:fill]` KMIA fill rate (filled+partial / resolved orders): last 45d 0.68 (n=25) vs prior 45d 0.7143. Rejected/expired in the last 45d: 0.
- `[exec:KMIA:cross]` KMIA: 25 orders crossed the book in the last 45d; avg (cross_price - limit_price) = 0.04c. A rising gap suggests adverse selection or a widening spread regime.
- `[exec:KORD:fill]` KORD fill rate (filled+partial / resolved orders): last 45d 0.8974 (n=39) vs prior 45d 1.0. Rejected/expired in the last 45d: 2.
- `[exec:KORD:cross]` KORD: 39 orders crossed the book in the last 45d; avg (cross_price - limit_price) = 0.7692c. A rising gap suggests adverse selection or a widening spread regime.
- `[exec:KPHX:fill]` KPHX fill rate (filled+partial / resolved orders): last 45d 0.8333 (n=18) vs prior 45d None. Rejected/expired in the last 45d: 0.
- `[exec:KPHX:cross]` KPHX: 18 orders crossed the book in the last 45d; avg (cross_price - limit_price) = 0.8889c. A rising gap suggests adverse selection or a widening spread regime.

## Config drift

_Is a live city's realized performance diverging from the profile committed in its decision doc?_

- `[config:KDFW:pnl]` KDFW live daily realized P&L, last 45d (15 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = 0.025. Series: [-40.0, -297.05, 295.0, 285.0, -165.09, -200.0, -270.28, 294.43, -230.0, -160.0, 84.4, 250.0, 234.98, -211.92, 219.92]
- `[config:KDFW:rationale]` Committed rationale/config for KDFW:
[docs/decisions/2026-06-22-dallas-live-override.md]
# Dallas (KDFW) goes LIVE — operator override of the deploy bar, 2026-06-22

> **REVISION 2026-06-22 (same day, after the section below was written).** The operator
> made two further calls that change the risk profile materially:
> 1. **Scaled Dallas from the initial MINIMAL 50 contracts to FULL 500** (KORD/KMIA parity:
>    daily-loss $150, cumulative-kill $500, max-open 5000; aggregate → **$450 daily /
>    $1,500 cumulative**). The "wrong call is cheap" framing below **no longer holds** — this
>    is now a **full-size live bet on a config with no proven OOS edge**, taken on the
>    operator's explicit instruction. This also pre-empts the doc's own "promote to full size
>    only after forward OOS clears 2.5" gate — that gate was overridden too.
> 2. **Moved the decision time 16:02 → 17:32 UTC** per the time-of-day study
>    (`scripts/analysis/best_time_of_day.py --city KDFW`): the ~17:00–17:30 window had the
>    highest in-sample P&L (17:30 total +$512 / t=2.59 vs 16:00 +$101 / t=0.54 over n=101).
>    **Caveat:** that study assumes the order **fills** at the mid at every candidate time
>    (fill rate not modeled) and 17:30 is the best of 14 times tested — so the move is a
>    **forward experiment** to test whether the late-day effect is real or a fill mirage, not
>    a proven optimum. `:32` offset (not `:30`) avoids the on-the-minute monitor_fills/`*/5`
>    pile-up on the no-swap box.
>
> The original minimal-size rationale is preserved below for the record; the config block,
> aggregate, cron, and graduation sections have been updated to the current full-size values.

**Decision:** Take **Dallas (KDFW)** LIVE on Kalshi under the KORD-style **UNION-25%**
rule — initially at **minimal size** (see revision above for the same-day scale-up to full
size) — as a deliberate **OPERATOR OVERRIDE** of the standing
**"out-of-sample walk-forward Sharpe > 2.5"** deploy bar. Dallas does **not** clear that
bar on trustworthy evidence (see below). It goes live anyway —
- `[config:KLAX:pnl]` KLAX live daily realized P&L, last 45d (1 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = n/a (too few days). Series: [363.64]
- `[config:KMIA:pnl]` KMIA live daily realized P&L, last 45d (9 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = 0.254. Series: [-272.58, 587.65, 103.98, 205.0, 195.0, -220.0, -490.02, 505.0, 201.52]
- `[config:KMIA:rationale]` Committed rationale/config for KMIA:
[docs/decisions/precommits/miami-resume-2026-06-10.md]
# Miami live trading — Resume pre-commitment (2026-06-10)

## Status change
- 2026-06-04: HALTED based on raw-strategy 90d t-stat = −0.49 (no edge in raw)
- 2026-06-10: **RESUMED** with BLEND-only strategy at 10% edge filter

## Statistical basis for resume

Rolling 90-day windows of BLEND-only strategy at 10% edge cutoff (walk-forward
fitted; coefficients refit on prior 60+ days every roll):

| Window | Fires | Total $ | Avg/trade | Win % | t-stat |
|---|---|---|---|---|---|
| Aug 25 → Nov 23, 2025 | 68 | +$32.22 | +$0.47 | 78% | **+8.31** |
| Sep 24 → Dec 23, 2025 | 77 | +$35.64 | +$0.46 | 77% | **+8.09** |
| Oct 24 → Jan 22, 2026 | 91 | +$41.94 | +$0.46 | 78% | **+9.21** |
| Nov 23 → Feb 21, 2026 | 94 | +$41.22 | +$0.44 | 74% | **+8.61** |
| Dec 23 → Mar 23, 2026 | 75 | +$34.08 | +$0.45 | 75% | **+8.58** |
| Jan 22 → Apr 22, 2026 | 73 | +$23.85 | +$0.33 | 62% | **+5.44** |
| **Feb 21 → May 22, 2026** | **61** | **+$16.53** | **+$0.27** | **61%** | **+4.10** |

Every rolling window passes Bonferroni correction at α=0.05/6 cities = 0.008
(critical t ≈ 2.6 one-tailed; all observed t > 4.10). Most recent window also
passes.

Raw-strategy comparison on the same test set: t=+0.64 at 25% edge filter
(confirms the halt rationale for the raw strategy was correct).

## Configuration — matches KORD framework

| Parameter | Value | Rationale |
|---|---|---|
| edge_threshold (raw) | 1.00 | Effectively disabled (raw has no edge) |
| blend_edge_threshold | 0.10 | Backtest-validated cutoff |
| sizing_mode | **unit** | Matches KORD's validated framework |
| unit_contracts | **500** | Matches KORD — comparable per-trade edge |
| max_contracts_per_trade | 500 | Depth cap |
| daily_loss_limit | $150 | Matches KORD |
| cumulative_kill | $500 | Matches KORD |
| max_open_contracts | 5000 | Matches KORD |

### Sizing history (logged 2026-06-10)

**Initial draft**: Amount $15/trade. Rationale: "conservative — half KORD's $."
**Revised**: unit=500. User feedback: under-deploys given Miami
- `[config:KORD:pnl]` KORD live daily realized P&L, last 45d (19 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = -0.058. Series: [-98.31, -67.38, -255.0, 657.34, 264.79, -274.22, 548.64, -323.48, -196.75, 174.84, -74.21, -205.62, -175.3, -47.54, 199.44, -15.0, -40.41, -205.8, -163.92]
- `[config:KORD:rationale]` Committed rationale/config for KORD:
[docs/decisions/precommits/chicago-resume-2026-06-07.md]
# Chicago resume — conservative parameters pre-commitment

**Status:** ACTIVE as of 2026-06-07 (REVISED same day before first cron fire)
**Replaces:** docs/decisions/halt-2026-06-06.md (Chicago portion)
**Duration:** 30 days minimum — no parameter changes until 2026-07-07.
**Miami:** REMAINS HALTED. halt/KMIA file in place.

**REVISION 2026-06-07 evening (before first KORD cron fire 2026-06-08 14:46 UTC):**
Switched model from `combined` (GEFS+IFS) to `combined_hrrr` (GEFS+IFS+HRRR).
Backtest analysis on Dec 13 2025 – Jun 5 2026 showed:
- edge≥25% Amount $25 mean: $26.13 → **$37.25** (+$11.12, +43%)
- Statistical significance: p=0.013 → **p=0.003**
- Per-contract edge≥25%: +6.98¢ → **+9.61¢**
HRRR is now ingested daily for all 6 cities via new cron (03:30 UTC + 13:45 UTC
retry). The revision keeps every other parameter unchanged.

**REVISION 2026-06-08 (before first KORD cron fire today 14:46 UTC):**
After full Jun 2025 → Jun 2026 backfill confirmed combined_hrrr at edge≥25%
delivers Sharpe 4.86, mean $36.90/trade (vs combined $36.90, HRRR +$5.05/trade),
sized up to Amount $50/trade with cumulative_kill $500.
- amount_dollars: $25 → **$50** (2x; expected daily mean +$60-90, 30-day +$1,300-1,800)
- daily_loss_limit_dollars: $75 → **$150**
- cumulative_kill_dollars: $200 → **$500**
- aggregate caps mirror (= Chicago since Miami halted)
Rationale: backtest mean per-trade is $36-41 with lifetime data; at $25 sizing
that's ~$10/trade realized which is below the noise floor of the kill switch.
$50 gives clearer signal-to-noise per day while still being 1/3 of the lifetime
backtest peak DD. Pre-commit window unchanged: still 30 days, ends 2026-07-08.

This doc locks in **every parameter** for the next 30 days. Once signed, **no
modifications** to filter, sizing, execution, or risk envelope.

---

## Why resume

After yesterday's halt + extensive analysis, three findings justify a
small-scale resume:

### 1. Chicago's lifetime edge passes the strictest Bonferroni correction

[docs/decisions/precommits/chicago-miami-live.md]
# Chicago + Miami live trading pre-commitment (DRAFT)

**Status:** DRAFT — not active until you review, edit, and sign off.
**Date drafted:** 2026-06-04
**Replaces:** Phase 8 NYC live trading (halted 2026-06-04 after pre-committed cross-city test showed NYC FAIL).

This doc locks in **every parameter** that drives real-money decisions on
KXHIGHCHI (Chicago) and KXHIGHMIA (Miami) for the next 30 days. Once signed,
**no modifications** to filter, sizing, or risk envelope. The discipline of
pre-commitment is the only thing that protects you from p-hacking yourself
into broke.

If during the 30-day window you want to change something: **stop trading
first, write a new pre-commit doc, then change.** Never change while live.

---

## Why this exists

The pre-committed cross-city test (docs/decisions/precommits/cross-city.md, 2026-06-04
verdict) produced:

| City | Verdict | Mean (limit) | t-stat | n |
|------|---------|--------------|--------|---|
| Chicago | **PASS** | +3.83¢ | +2.72 | 868 |
| Miami   | **effective PASS** | +7.49¢ | +4.11 | 521 |
| NYC     | FAIL    | −0.55¢ | −0.44 | 897 |
| Austin  | MIXED   | +0.52¢ | +0.33 | 634 |

Filter-cell overlap analysis: 20 of 23 filter cells (87%) are positive on
**both** Chicago and Miami under limit execution; 0 cells where Chicago wins
but Miami loses. Monotone increase in mean as edge threshold tightens on
both cities. Robust to filter choice.

User decision (2026-06-04): pivot live trading focus from NYC to
Chicago + Miami. **Skipping the 30-day forward paper-trade window** that
the original cross-city pre-commit recommended — this is the aggressive
choice and is documented as such for transparency.

---

## The pre-committed strategy

### Filter (identical to the passing backtest cell)

```
edge threshold:  |edge| ≥ 10%
entry-price:     no floor (entry ≥ 0¢)
execution:       limit-100% (post 1¢ inside the spread, hold to expiry)
forecast init:   00 UTC same day
model source:    EMOS combined 00Z {city} (rolling 45d)
```
- `[config:KPHX:pnl]` KPHX live daily realized P&L, last 45d (9 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = -0.332. Series: [-195.02, 157.5, 169.98, -95.02, -31.04, -75.01, -85.49, -55.0, -175.13]
- `[config:KPHX:rationale]` Committed rationale/config for KPHX:
[docs/decisions/2026-07-10-phoenix-live-override.md]
# 2026-07-10 — Phoenix (KPHX) live, operator override (MINIMAL size)

**Decision:** Take Phoenix (KPHX, series `KXHIGHTPHX`) **live with real money at minimal 50-unit
size**, as an operator override of the OOS-Sharpe > 2.5 deploy bar. Fourth live city
(Chicago + Miami + Dallas + Phoenix). Seattle explicitly stays paper-only.

## Why (the honest evidence)
- Phoenix does **NOT** clear the deploy bar. The case for it: the paper series
  `EMOS combined 00Z Phoenix (rolling 45d)` shows a **concentrated, high-conviction edge** — raw
  |edge| ≥ 0.20 → **+11.7¢/contract net** of the 7% taker fee, and **both halves of the recent
  6-month window are positive** (H1 +4.8, H2 +2.6). The edge *concentrates* at high conviction
  (0.15 → +5.2¢, 0.20 → +11.7¢), the signature of a real signal (same shape as Miami/Dallas),
  not broad noise. Plausible mechanism: desert climate is low-variance / predictable.
- The case against (why it's an override, not a graduation): the sample is **young and thin** —
  Kalshi listed `KXHIGHTPHX` ~2026-02, so ~5 months, n ≈ 63 at 0.20. +11.7¢ over 63 trades could
  be a hot start. Book **depth is UNMEASURED** (no walk-book study). And the dry-run shows the
  signal firing on **extreme brackets with very large edges** (e.g. B113.5 YES +58%), which may be
  model over-confidence at the tails (WEATHER-5K: models weakest at extremes).

## Config (`scripts/live_trade.py` CITY_CONFIG["KPHX"])
- **Signal: RAW-only @ 0.20** (`use_union=False`, `use_blend=False`, `edge_threshold=0.20`).
  Blend is disabled because Phoenix blend paper is n=13 — too thin to fit/trust.
- Model: EMOS `combined` (GEFS+IFS) 00Z, rolling 45d — the exact signal paper_trade_log logs daily.
- Execution: **POST-ONLY** (`smart_cross_edge_threshold=1.00` — never crosses). Set after the capacity
  study showed the lone crossing signal LOST in-sample (overconfident tail bets) while maker fills 100%
  at 250. Re-enable crossing (→0.40) once Phoenix proves out live.
- **Size: `unit_contracts=
- `[config:KSEA:pnl]` KSEA live daily realized P&L, last 45d (1 trading days): naive Sharpe (mean/std of daily $, NOT the walk-forward backtest metric) = n/a (too few days). Series: [-162.31]

## Data health

_Is ingestion current (forecasts, observations, price snapshots) and does the account-equity reconciliation tie out?_

- `[health:forecasts]` Most recent forecast init_time per model (any live station): aifs=2026-06-18T00:00:00+00:00, aifs_ens=2026-06-18T00:00:00+00:00, gefs=2026-07-22T12:00:00+00:00, hrrr=2026-07-22T00:00:00+00:00, ifs=2026-07-22T00:00:00+00:00, nbm=2026-06-19T00:00:00+00:00, nbm_qmd=2026-06-13T00:00:00+00:00
- `[health:observations]` Days behind today for latest observation, per live station: KDFW=1, KLAX=1, KMIA=16, KNYC=1, KORD=1, KPHX=1, KSEA=1
- `[health:prices]` Latest Kalshi price snapshot is 3.2 minutes old (every-5-min cron; anything over ~30 min suggests the snapshot cron stalled).
- `[health:equity]` Latest account_equity_snapshots row: 2026-07-22 (0d old). Reconciliation identity gap (account_value - (deposits+credit-withdrawals+pnl)) = $0.0. Should be ~$0; a large gap means the snapshot or the underlying Kalshi pull is wrong.

