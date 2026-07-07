# Intraday fair-value GATE — does our fair beat the market intraday, and for how long?

**Date:** 2026-07-07 · **Branch:** `research/intraday-fair-value` · **Status:** GATE ANSWERED — **NO-GO (all 3 live cities)**
**Script:** `scripts/analysis/intraday_fair_value.py` · **Analysis only** (no orders, no config, no trading rules)

## Gate question
The operator wants to (a) update fair value through the day and (b) buy when price < fair / cash out
when the edge is gone. That only has value if our **intraday, no-look-ahead fair value is more accurate
than the market's own price at that moment**. This study measures forecast accuracy (Brier + log-loss,
per bracket, vs the 0/1 settlement outcome) for three predictors at each hour of the day, per live city:

1. **static 00Z fair** — rolling-45d EMOS on the 00Z combined (GEFS+IFS) ensemble; exactly what
   `live_trade.py` / `paper_trade_log.py` compute today. Constant through the day.
2. **intraday fair** — the only backtestable intraday model refresh: the 12Z combined ensemble.
3. **market mid** — `(yes_bid+yes_ask)/2` from `prices` top-of-book, sampled by UTC hour.

## Verdict (up front)
**NO-GO for KORD, KMIA, KDFW.** The market is already at least as accurate as our fair value by the time
we trade, and gets strictly better through the afternoon as the high develops. Updating the fair intraday
(12Z) *does* beat our own static fair — but it does **not** beat the market, because the market improves
faster. There is no window at or after the decision times where our fair beats the market. **Do not build
Phase 2.**

## Data inventory — which intraday levers the history actually supports
The two highest-signal levers the operator envisioned **do not exist in stored history:**

| Lever | Available? | Detail |
|---|---|---|
| **Hourly / sub-daily observed temps** (max-so-far floor on the daily high) | **NO** | `observations` stores only the daily settlement `high_temp_f`/`low_temp_f`. No METAR/ASOS/hourly table exists anywhere in the DB. |
| **Intraday HRRR runs** (fresh HRRR as a proxy for observed temps) | **NO** | HRRR is stored at **00Z only**, 1 run/day. No 06/12/18Z HRRR history. |
| **GEFS/IFS intraday runs (06/12/18Z)** | **~33 days only** | For the **live cities** every intraday run starts **2026-06-02/03**. Global 12Z history (back to 2025-05) is for *other* stations. A no-look-ahead **rolling-45d 12Z EMOS re-fit is INFEASIBLE** for these cities (needs ≥30 prior 12Z days). |
| **Market mid (`prices` top-of-book)** | **YES, well-powered** | Dense, all-24-hours, since ~2025-06 (KORD/KMIA, ~400 days) and 2026-02 (KDFW, ~140 days). |
| Orderbook depth (`orderbook_snapshots`) | 28 days | Not needed here; top-of-book mid is the higher-powered mid source. |

**Consequence:** the *market-vs-static-fair* accuracy curve (the backbone result) is well-powered
(~400 / ~140 days). The *intraday-model-refresh* probe is **directional only** (~33/28 days, June 2026),
and its 12Z fair reuses the 00Z-fitted EMOS affine map applied to the fresh 12Z ensemble statistics
(a flagged approximation — a proper 12Z recalibration cannot be built with <45 days of 12Z history).

## Results — accuracy vs time of day (Brier; market scored on the same bracket-obs sample as static)

Static-00Z Brier is **flat** all day (it never updates). "Crossover" = first hour the market's Brier ≤ static.

| City | Static Brier (full) | Market Brier @ decision hr | Decision hr | Crossover (market ≥ static) | Market beats static at decision? |
|---|---|---|---|---|---|
| **KORD** | 0.1282 | **0.1111** @14Z | 14Z | **08Z** | **YES** (market ahead every hr 8–21Z) |
| **KMIA** | 0.0947 | **0.0888** @15Z | 15Z | **13Z** | **YES** (static marginally ahead only 8–12Z, Δ≈0.001–0.002) |
| **KDFW** | 0.1304 | **0.0961** @17Z | 17Z | **08Z** | **YES** (market ahead every hr 8–23Z) |

- The market's Brier **collapses toward 0** through the afternoon/evening as the daily high is realized
  (KMIA: 0.089→0.014→0.0007 by 22Z; KDFW: 0.096→0.055→0.006). Our static fair stays flat.
  So the accuracy gap *widens in the market's favor* as the day goes on — the opposite of an exploitable
  hold-to-settlement window.
- KORD is the lone exception where the market's late Brier *rises* (0.117@14Z → 0.136@22Z) and log-loss
  blows up (0.36→0.70). This is a **late-book data-quality artifact** — KORD two-sided quotes thin/one-side
  out near settlement so the top-of-book mid becomes stale/degenerate — not evidence of model edge. It is
  outside any tradeable window and does not affect the gate.

## Results — 12Z intraday-refresh probe (directional, ~33/28 days, market sampled ≥18Z when 12Z lands)

| City | static-00Z Brier | intraday-12Z Brier | market Brier | Does intraday beat static? | Does intraday beat market? |
|---|---|---|---|---|---|
| KORD | 0.1179 | **0.1060** | **0.0711** | yes (−10%) | **NO** (market −33% vs intraday) |
| KMIA | 0.0816 | **0.0782** | **0.0155** | yes (−4%) | **NO** (market −80%) |
| KDFW | 0.1154 | **0.1087** | **0.0889** | yes (−6%) | **NO** (market −18%) |

**Updating the fair with the 12Z run improves our own accuracy, but the market at the same time is far
better still.** The proposed value-trading edge does not exist.

## Interpretation the gate demands
- **Does intraday fair beat STATIC?** Yes, modestly (12Z probe, −4% to −10% Brier). Updating has *some*
  standalone value.
- **Does intraday fair beat the MARKET?** **No.** Not at the decision time, not in the afternoon window
  where the 12Z run is available. The market is already at/ahead of our static fair by ~08Z (KORD/KDFW)
  or ~13Z (KMIA), and pulls further ahead through the day.
- **For how long does a market-beating edge persist?** Effectively **zero** at or after the decision
  times. The only sliver where our model is ahead is early-morning KMIA (before ~13Z) — pre-liquidity,
  margin ≈ 0.001 Brier (noise). Not tradeable.
- **Calibration (ECE, lower=better):** both predictors are well-calibrated; the **market is
  better-calibrated than our static fair at every decision hour** — KORD 0.0224 vs 0.0260, KMIA 0.0162 vs
  0.0187, KDFW 0.0299 vs 0.0559. Consistent with the accuracy result.
- This corroborates prior work: market-blend (`market_share` 56–95%, β_model small/negative for some
  cities) and the no-edge findings. The market already prices the public temperature development our
  model would try to capture.

## Rigor checks
- **No-look-ahead (model):** rolling EMOS trains strictly on days `< target_date`
  (`train_end < target`), verified PASS for sampled dates in all 3 cities.
- **No-look-ahead (market):** the hour-T mid is the last two-sided snapshot *within hour T*; proven
  invariant to hiding all post-T:59:59 data (identical value with the full table vs a T-truncated table).
- **Reproduction:** static-00Z fair uses the production functions unchanged (`fit_emos` /
  `gaussian_to_bracket_probs`, `μ=a+b·mean`, `σ²=c+d·std²`, window 45, min 30, series
  KXHIGHCHI/KXHIGHMIA/KXHIGHTDAL). Full sample Briers (0.095–0.130) are raw per-bracket over *all*
  brackets (many near 0/1), so they are not the edge-weighted Briers of other memos; every static-vs-market
  comparison uses the identical bracket-obs sample per hour.

## Caveats
- 12Z probe is **directional** (~4 weeks, June 2026) and its 12Z fair is calibrated with the 00Z EMOS
  affine map (proper 12Z recalibration needs ≥45d of 12Z history we don't have).
- Market mid requires a two-sided quote; thin/one-sided late-day books (esp. KORD 22–23Z) make the very
  late mid unreliable — irrelevant to the gate.
- We cannot *fully* rule out that a richer intraday model (fresh intraday HRRR + hourly-obs floor) could
  beat the market, because **that data has never been collected**. But (a) the best intraday fair we *can*
  build is already crushed by the market, and (b) all prior evidence agrees. To ever reopen this, the
  prerequisite is to **first collect intraday HRRR runs + hourly METAR obs for ≥45–90 days**, then re-run
  this exact harness — not to build Phase 2 now.

## Bottom line
Intraday-updated fair value does **not** beat the market for any live city, at any tradeable hour.
**NO-GO. Stop the continuous-value-trading / cash-out idea.**
