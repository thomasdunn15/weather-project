# Phase-1: NBM as a forecast source — build + cheap skill/edge first read

*2026-06-21 · branch `research/p1-nbm` (unmerged) · additive only (new `forecasts` rows); no EMOS/blend/trading code touched*

## What was built

`src/weather_markets/nbm.py` — ingest of NOAA NBM **core** calibrated daily-Tmax for a station,
matching the existing gefs/ecmwf/hrrr module pattern (no base class). Pure helpers are unit-tested
(`tests/test_nbm.py`, 8 tests; full suite **122 passed**).

**Storage encoding (additive to `forecasts`; no schema change).** The table has no std column, so NBM's
calibrated distribution is encoded as pseudo-members in `tmax_f`, namespaced by `model`, which the
daily-high MAX path and the skill harness pool exactly like real members:

- `model='nbm'` — **3 Gaussian pseudo-members** per window: `member_id 0=μ, 1=μ+σ, 2=μ−σ`, where μ =
  NBM's calibrated windowed-TMAX mean and σ = its `ens std dev`. The set `{μ−σ, μ, μ+σ}` has sample
  mean μ and sample stdev σ exactly, so the harness's mean/stdev EMOS reads NBM's calibrated location
  **and** spread back. (member_id 0 is the mean.)
- `model='nbm_qmd'` — 21 percentile pseudo-members (opt-in; **descoped from the backfill** — see below).

**Windowing (the P0-A gotcha).** NBM core publishes the same-day windowed TMAX as a single
`:TMAX:2 m above ground:12-24 hour max fcst:` message at **fxx=24** (fxx 12/18/30 carry none —
confirmed empirically). Its 12–24Z period contains every US station's local afternoon peak and its end
time (valid 00Z day-D+1) lands on local day D for all US tz, so **fxx=24 alone is the day-D high** and
the existing local-day-MAX path needs no NBM-specific logic. Stored `valid_time = init+fxx`. NBM is a
projected 2.5 km Lambert grid → nearest-neighbour extraction (like HRRR), not `.sel()`.

**QMD finding / descope.** NBM-QMD ships only *instantaneous* 2 m **TMP** percentiles
(`:TMP:…:NN% level:`), **not** windowed-max-Tmax percentiles, and cfgrib silently collapses the 21
messages into one (no percentile dim → needs per-percentile extraction, 21 downloads/window). It is the
wrong shape for a clean daily-max CDF and only feeds the deferred covariate test, so it is **off by
default in the backfill** (function provided, smoke-validated once). Core's native calibrated
windowed-TMAX mean+std is the correct daily-Tmax representation and drives the scored config.

## Backfill coverage

`scripts/backfill_nbm.py` (tmux, line-buffered, sequential, RAM-guarded, `remove_grib=True` →
auto-deletes each GRIB, periodic idx purge; resumable via `ON CONFLICT DO NOTHING`). Throughput
~3.6 s/station-day; **disk footprint negligible** (idx only — gribs removed at load; peak RSS ~460 MB).

| Station | window | days | status |
|---|---|---|---|
| KORD (edge, live) | 2024-06-01 → 2026-06-19 | 749 | ✅ done (2247 rows) |
| KMIA (edge, live) | 2024-06-01 → 2026-06-19 | 749 | ✅ done (2244 rows) |
| KSEA (edge) | 2025-01-01 → 2026-06-19 | 535 | ✅ done (1605 rows) |
| KMDW (edge, no Kalshi mkt) | 2025-01-01 → 2026-06-19 | 535 | ✅ done (1605 rows) |
| KLAS, KLAX, KPHX (hard) | 2025-01-01 → 2026-06-19 | 535 ea | ✅ done (1605 rows ea) |
| KSFO (hard, obs from 2026-01) | 2026-01-01 → 2026-06-19 | 170 | ✅ done (510 rows) |

All 8 staged stations backfilled (~13.7k `nbm` rows, ~4340 station-days, 149 min).

`scripts/ingest_nbm_daily.py` + `docs/crontab.txt` line added for daily forward ingest (09:00 UTC + 14:00
retry; research-only, not in the trading path; activates when the branch merges).

## First read — `combined` vs `combined_nbm` at the EDGE cities (matched samples)

The harness scores `combined_nbm` only on days where gefs+ifs+nbm are all present; on the edge cities
that is the *same* set of days/brackets as `combined`, so this is apples-to-apples.

| Edge city | rolling-EMOS CRPS (°F) combined → +nbm | bracket-edge Brier combined → +nbm | mean-MAE (°F) combined → +nbm |
|---|---|---|---|
| **KORD** | 1.579 → 1.570 (−0.6%) | 0.1294 → 0.1291 | 2.62 → 2.59 |
| **KMIA** | 0.771 → 0.769 (−0.3%) | 0.0953 → 0.0951 | 3.06 → 2.99 |
| **KSEA** | 1.194 → 1.185 (−0.75%) | 0.1197 → 0.1195 | 1.88 → 1.86 |
| **Pooled (KORD+KMIA+KSEA, n=4968 brackets each)** | — | **0.1137 → 0.1135 (−0.18%)** | — |

(`combined_nbm` is the best-Brier config overall; `combined_hrrr` edge-Brier is 0.1187 — HRRR *hurts*
edge cities, consistent with prior findings.)

Context — standalone `nbm` pooled skill (all 8 staged stations, n=4340): bias −0.37, **MAE 1.76**,
RMSE 2.46, ensCRPS 0.977 — far better-*looking* than gefs/ifs (MAE 2.9–3.1) **because NBM is already
calibrated**; this is not a raw-ensemble number.

### Hard stations — the model-selection paper's core thesis (NBM helps coastal/terrain)

NBM's 2.5 km statistical downscaling is supposed to fix the stations a 0.25–0.4° global grid can't
resolve. It does — for **accuracy** (ensemble-mean MAE), combined → combined_nbm:

| Hard station | mean-MAE | rolling-EMOS CRPS | bracket Brier |
|---|---|---|---|
| **KLAS** (desert) | 4.39 → **4.20** (−4.3%) | 0.948 → 0.941 | 0.0908 → 0.0903 |
| **KPHX** (desert) | 2.95 → **2.86** (−3.1%) | 0.819 → 0.814 | 0.0985 → 0.0984 |
| **KSFO** (marine) | 3.87 → **3.79** (−2.1%) | n/a (170 d obs) | no Kalshi mkt |
| **KLAX** (marine) | 2.94 → 2.92 (−0.7%) | 1.524 → 1.515 | 0.1233 → 0.1229 |

NBM cuts mean-MAE **2–4×** more at the hard desert/coastal stations than at the edge cities (~1%) —
the thesis holds for accuracy. But the CRPS/Brier gains stay ~0.5% even here, for the same reason: the
flat 84-member pool dilutes NBM to ~3.6% and rolling-EMOS double-calibrates, so the calibrated-accuracy
gain doesn't survive into the blended distribution. (KSFO has no rolling-EMOS/Brier — only 170 obs-days
since 2026-01, short of the 45-day-train + eval need; its raw-MAE gain is the only read there.)

## Kill-criterion verdict

**Not a clean STOP, but not a green light either — route to the proper test, do not start production EMOS work.**

- `combined_nbm` **does** improve edge-Brier at all three edge cities and pooled (0.1137 → 0.1135), and
  every edge-city CRPS/MAE moves the right way — so it does not trip the literal STOP.
- **But the improvement is negligible** (~0.2% Brier, 0.3–0.75% CRPS, ~1% MAE) — well within noise and
  far from a tradeable signal.
- **Why, and why this is the wrong test:** in the flat 84-member pool NBM's 3 pseudo-members carry only
  **~3.6%** weight, and the rolling-EMOS refit re-absorbs the rest — i.e. pooling an *already-calibrated*
  product then re-calibrating **double-calibrates** and dilutes it. The standalone-NBM MAE (1.65 vs
  2.75) and the consistent per-edge-city mean-MAE gains show NBM carries **real** accuracy that the
  diluted blend can't express. And per the model-selection paper, edge cities (KORD/KMIA/KSEA) are
  **not** NBM's target — its 2.5 km calibration is meant to help the hard coastal/terrain stations
  (KLAS/KSFO/KLAX/KPHX), where we don't currently trade.

**Recommendation:** Do **not** begin production EMOS integration on the strength of this pooled read.
The evidence is consistent: NBM is genuinely the most accurate single source (standalone MAE 1.76 vs
2.75; biggest mean-MAE gains at the hard stations, confirming the paper's thesis), but the flat-member
pool can't express that — NBM needs a **fitted weight**, not a 3/84 dilution. So proceed to the
**deferred EMOS-covariate bake-off** (NBM's calibrated μ as an EMOS covariate / regressor), which is
the test NBM was always meant to face. The data (all 8 staged stations backfilled) and the harness hook
(`combined_nbm`) are in place. Note the standing constraint: even a covariate win must then clear the
*edge* bar at a tradeable city, and NBM's accuracy gains are concentrated at the hard stations where we
don't currently trade — so temper P&L expectations.
