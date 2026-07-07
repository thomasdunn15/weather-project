# Intraday LATENCY probe — does the market lag a fresh intraday run enough to capture? (2026-07-05)

**Branch:** `research/intraday-latency-probe`  ·  **Script:** `scripts/analysis/intraday_latency_probe.py`
**Verdict: NO-GO.** No run/city clears all three bars (GROSS drift toward the run's news · news
true · survives fees) at once. Building intraday-forecast ingestion for a **speed** edge is **not
justified** on this evidence.

## Question
The forecasts are PUBLIC, so the only edge from ingesting intraday runs is **latency**: when a new
GEFS/IFS run publishes mid-day, does the market price DRIFT toward the run's news over the following
minutes/hours (a lag), is that drift toward the TRUTH, and would a react-fast trade profit net of
fees? This is the one thing the sibling gate (`research/intraday-fair-value`) could have missed: it
sampled the market once per HOUR and found the market already beats our fair on hourly averages; a
transient 15-min dislocation right after a run arrives would not show up there. This probe zooms to
the native 5-min price cadence in the post-arrival window.

## Method (rigor on arrival-time + no-look-ahead)
- **t0 (arrival).** `forecasts` has **no ingest/created timestamp column** (verified). t0 is the
  standard product-availability lag, stated + swept ±1h: GEFS 06Z ~11:00Z, GEFS 12Z ~16:30Z,
  GEFS 18Z ~22:00Z, IFS/combined-12Z ~18:40Z (gate's `IFS_12Z_AVAIL_HOUR=18`). The combined-12Z
  fair needs BOTH models, so it is usable only once IFS lands (~18:40Z).
- **NEWS = Δfair** = (this-run EMOS fair) − (prior-run fair), same EMOS composition for both
  (GEFS-only fit for GEFS runs; combined fit for combined runs), so Δfair is a pure ensemble change.
  Reuses the gate's no-look-ahead machinery verbatim (rolling-45d 00Z `fit_emos`, `emos_probs_on_stats`
  affine map, `ens_stats`, `contract_resolved_yes`).
- **Latency** = market MID drift at t0+15/30/60/120m regressed on Δfair; **up-run/down-run split**
  for identification (generic time-convergence moves both the same way; news-following moves up-runs
  up and down-runs down); plus a |run_fair − market| gap curve.
- **News true** = Brier(run_fair) vs Brier(prior_fair) + directional hit-rate.
- **Money** = react-fast TAKER trade at the first post-t0 tick (cross the spread toward the run),
  two exits — hold-to-**settlement** and **convergence** (exit when mid reaches run_fair) — reported
  GROSS and NET of the 7% Kalshi taker fee (formula mirrored, not imported; parity file untouched).
- No-look-ahead is structural (m_before reads only ts ≤ t0; responses read first tick ts ≥ t0+Δ;
  EMOS trains on [target−45, target−1]) and asserted per run — **PASS on all 9 run-blocks**.

## Data reality / sample
Intraday runs for the live cities begin only ~2026-06-02/03: **KORD/KMIA ~33 days, KDFW ~28 days.**
IFS runs 00Z & 12Z only; GEFS 00/06/12/18Z — so **12Z is the only cycle that refreshes both models.**
KDFW's GEFS-only runs produced no rows (sparse GEFS-00Z coverage → <30 training days → fit None), so
KDFW contributes only COMB-12Z. Small sample — **directional only.**

## Results (per city × run; cents/contract; edge≥3c react-fast taker)

| city | run | n | drift@60 slope | r60 | up60c | dn60c | news Brier +% | hit | SETTLE g/n | CONV g/n | ntr |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| KORD | GEFS-06Z | 198 | +4.26 | +0.087 | +0.42 | −0.50 | +5.4% | 0.548 | −1.69 / −3.16 | +0.55 / −1.89 | 137 |
| KORD | GEFS-12Z | 192 | +9.52 | +0.069 | +0.32 | −1.26 | +1.0% | 0.528 | −1.47 / −2.89 | +1.07 / −1.24 | 131 |
| KORD | GEFS-18Z | 198 | −0.98 | −0.009 | −2.24 | +0.09 | +11.9% | 0.652 | **+12.26 / +11.16** | +0.27 / −1.64 | 129 |
| KORD | COMB-12Z | 204 | +0.42 | +0.003 | +1.17 | −1.58 | +10.8% | 0.589 | −0.95 / −2.29 | +2.63 / **+0.39** | 129 |
| KMIA | GEFS-06Z | 192 | +2.13 | +0.060 | −0.77 | +0.34 | +2.4% | 0.543 | **+10.74 / +9.13** | +0.72 / −1.84 | 98 |
| KMIA | GEFS-12Z | 186 | −7.66 | −0.052 | +5.07 | −0.47 | **−23.8%** | 0.539 | +0.20 / −1.30 | +4.36 / **+1.73** | 87 |
| KMIA | GEFS-18Z | 192 | −0.11 | −0.102 | −0.04 | +0.11 | **−90.0%** | 0.391 | −1.17 / −2.17 | +0.00 / −1.52 | 72 |
| KMIA | COMB-12Z | 198 | **+18.41** | **+0.223** | +1.98 | −0.13 | +8.6% | 0.600 | +0.37 / −0.67 | +0.75 / −1.14 | 87 |
| KDFW | COMB-12Z | 174 | +1.62 | +0.009 | −1.07 | −1.83 | +6.9% | 0.589 | −0.85 / −2.25 | +1.51 / −1.21 | 124 |

**t0 SWEEP (drift@60 slope at t0−60m / t0 / t0+60m)** — the tell: no cell's slope is stable across
the ±1h window. KMIA COMB-12Z, the strongest drift (r+0.223), exists **only** at exactly t0+0m and
**flips negative at both ±60m** (−5.2 / +18.4 / −4.4). KORD COMB-12Z: +19.6 / +0.4 / +13.6. That is
the signature of noise pinned to the assumed minute, not a physical repricing lag.

## Read
1. **LATENCY (gross): essentially none, and not robust.** Drift slopes are tiny (|r| ≤ 0.09 except
   the one knife-edge KMIA COMB-12Z r+0.223). The up/down identification is inconsistent — correct
   sign for KORD, **wrong** for KMIA GEFS-06Z/12Z (up-runs drift down), both-negative for KDFW
   (generic downdrift, not news-following). Magnitudes are ~0.5–2c, below a 1c tick and far below the
   spread. The `|run_fair − market|` gap does **not** close after t0 — for KDFW COMB it *widens*
   (13.1c → 16.5c by +120m): the market moves **away** from our fair, toward truth. The market has
   already absorbed the public run by the first tick we can trade.
2. **NEWS TRUE: only for the too-late runs.** The 7–12% Brier gains are on 18Z (~22Z, when the day's
   high is essentially realized — not prediction, leakage) and the evening COMB-12Z. The one genuinely
   intraday, tradeable run — **GEFS-12Z** — shows +1.0% (KORD) and **−23.8%** (KMIA, anti-informative).
3. **MONEY: dead after fees.** Convergence-exit GROSS is mildly positive in most cells (there is a
   whisper of ~1–2c mid-to-mid drift), but after the 7% taker fee you must pay to react fast,
   convergence NET is negative almost everywhere; hold-to-settlement NET is negative in every genuinely
   intraday cell. The large SETTLE profits (KORD-18Z +11c, KMIA-06Z +9c) are **timing artifacts**
   (near-resolved markets / wide near-certain Miami brackets), not drift capture. The trades fire on a
   persistent ~13c gap that is *our fair being wrong vs the market*, not the market being slow — exactly
   what the gate already killed.

## Reconciliation with the gate
Confirms explanation **(a): no capturable lag** (not "a lag that closes before 18Z"). The gate's
hourly-average result was not hiding a transient exploitable dislocation; at 5-min resolution the
market already reflects the run at the first post-arrival tick and, if anything, pulls further away
from our inferior fair. Even a real lag on the 12Z would not help KORD (14:46Z) / KMIA (15:30Z) whose
decisions precede the ~16:30Z GEFS-12Z arrival; only KDFW (17:32Z) sits after it — and KDFW shows no
news-following drift.

## Caveats
~33 days (KORD/KMIA) / ~28 (KDFW), directional only. t0 assumed from availability lags (no ingest
column); the sweep shows the verdict does not hinge on the exact minute in a way that could rescue a
GO — it hinges on it in a way that exposes noise. KDFW GEFS-only runs unavailable (sparse GEFS-00Z).
Concurrent-observation confound inflates the late-run (18Z/evening) numbers. Combined-12Z fair is
only available ~18:40Z (past all decisions).

## Verify
`uv run pytest` → 121 passed (parity 8/8). Parity files (`dashboard/static/app.js`,
`dashboard/sim_python.py`, `tests/test_sim_parity.py`), `scripts/live_trade.py`,
`scripts/monitor_fills.py` untouched (empty diff vs HEAD). Read-only; no orders/config/cron. Reruns
end-to-end deterministically (EXIT=0, empty stderr). Stop before merge.
