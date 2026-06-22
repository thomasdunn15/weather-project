# P0 — Can NBM / AIFS / GEM be backfilled via Herbie? (empirical probe)

*2026-06-20 · READ-ONLY probe · branch `research/p0-backfill-probe` · gates the forecast-model project*

## Question

Can each of {NBM, AIFS-Single, AIFS-ENS, GEM/GDPS-det, GEM/GEPS-ens} be fetched via **Herbie**
deep enough to **validate on our existing ~26-month window** (VALIDATE-NOW), or is it
**FORWARD-COLLECT** only? This is the spec input for the Phase-1 ingestion agents.

## Method

Scratch scripts (`scripts/analysis/probe_backfill_depth.py`, `probe_vars.py`), run via `uv run`,
sequential, minimal-fetch, isolated `save_dir=~/data/_p0_probe` purged after each run. No DB, no
production changes.

- **Stage A — depth:** constructing `Herbie(...)` runs a *source find* (cheap HEAD/range, **no GRIB
  download**) and sets `H.grib` iff the file exists. Probed **each source separately** at init dates
  `2026-06-13, 2026-05-20, 2026-03-20, 2025-12-20, 2025-06-20, 2024-06-20` (00Z, fxx=24).
- **Stage B — variables:** `H.inventory()` (downloads only the tiny `.idx`/`.index`) to read exact
  selector strings; plus **one** real subset download + xarray + station extract for NBM.
- **GEM diagnostic:** direct HTTP HEAD on the constructed MSC URLs + current ECCC datamart listing.

## Per-model results

| Model | Herbie call | Backfillable via Herbie? | Earliest hit / depth | Daily-Tmax variable(s) | Members / percentiles | Grid / res | Station-extract gotcha | **Verdict** |
|---|---|---|---|---|---|---|---|---|
| **NBM-core** | `model="nbm", product="co", fxx≥1` (src **aws**; nomads shallow) | **Yes** | **≤2024-06-20** (all 6 hit) → full window | `:TMAX:2 m above ground:12-24 hour max fcst:` (native calibrated max) + `:TMP:2 m above ground:NN hour fcst:`; each also `ens std dev` | deterministic blend **mean + ens std dev** (Gaussian moments) | **2.5 km Lambert CONUS** (1597×2345; template's "13-km" label is stale) | projected grid → **nearest-neighbor like HRRR `_nearest_yx`, NOT `.sel`**; TMAX windows are fxx-referenced, not local-day → pick window(s) covering local day D; K→°F | **VALIDATE-NOW (full window)** |
| **NBM-qmd** | `model="nbmqmd", product="co"` (src **aws**) | **Yes** | **≤2024-06-20** → full window | percentile ladder `:TMP:2 m above ground:NN hour fcst:PP% level:` and `:TMAX:…:PP% level:` (PP=0,5,…,100) + prob-threshold fields | **21 percentiles** = full calibrated predictive distribution | 2.5 km CONUS (same) | same nearest-neighbor; QMD is **already calibrated** → may overlap our EMOS layer (use as feature, not raw member) | **VALIDATE-NOW (full window)** |
| **AIFS-Single** | `model="aifs", product="oper", fxx∈6h steps` (src **google/aws/azure**; ecmwf live shallow) | **Yes** | **≤2024-06-20** (all 6 hit) → full window | `:2t:sfc:` (instantaneous); **no native max field** | **1 deterministic** member | 0.25° global lat/lon | `.sel(method="nearest")` (lon 0–360 norm), like GEFS/IFS; **only 6-hourly instantaneous 2t** → daily-max from 6h samples is coarse/low-biased vs IFS `mx2t3`; **experimental→operational version change 2025-02-25** | **VALIDATE-NOW (full window; experimental-period caveat)** |
| **AIFS-ENS** | `model="aifs", product="enfo"` (`get_control=True` for cf) | **Yes** | **between 2025-06-20 (miss) and 2025-12-20 (hit)**; AIFS-ENS operational ~Jul-2025 → **~11–12 mo** | `:2t:sfc:<N>:…:pf:enfo:`, member `N` in `number` col; no native max | **50 perturbed (pf) + 1 control (cf)** = 51, all in one file | 0.25° global lat/lon | `.sel`; 6-hourly instantaneous (coarse max); **recent sub-window only, not full 26 mo** | **VALIDATE-NOW (recent ~12-mo sub-window only)** |
| **GEM / GDPS** (det) | `model="gdps", variable="TMP", level="TGL_2"` | **No — stock template broken** | **none** (all dates incl. *today* 404) | TMP @ TGL_2 (single-var files); TMAX separate | 1 deterministic | 0.15° (15 km) global | Herbie MSC path is **stale → 404 even for today**; current datamart is **date-stamped** `/{YYYYMMDD}/WXO-DD/model_gem_global/…`; ~24–48 h retention | **FORWARD-COLLECT** (needs template fix/custom fetch + daily cron) |
| **GEM / GEPS** (ens) | **no Herbie template exists** (`geps.py` absent) | **No** | **none** (~24–48 h retention) | `CMC_geps-raw_TMP_TGL_2_latlon0p5x0p5_<init>_P<fff>_allmbrs.grib2` (current datamart dir returns **200**) | ~**20 pf + 1 control** = 21, `_allmbrs` single file | 0.5° global | custom MSC fetch (`/{YYYYMMDD}/WXO-DD/ensemble/geps/grib2/raw/{HH}/{fff}/`); no Herbie support | **FORWARD-COLLECT** (custom ingest + daily cron) |

**End-to-end proof (NBM-core, 2026-06-13 via aws):** subset `:TMP:2 m above ground:` → xarray
`t2m`, grid 1597×2345, KORD nearest cell = **300.50 K ≈ 81 °F** at lat 41.998 / lon −87.931 (≈ exact
KORD). Station extraction works.

**Forward-collect timing (GDPS/GEPS):** retention is ~24–48 h, so collection is *future-only* and
cannot touch the existing window. To reach a rolling-45-day eval: **~7 weeks** to the first 45-valid-day
window, **~13 weeks (≈3 months)** for a stable eval. Start the cron now if GEM diversity is wanted later.

## Recommendation (scope for Phase-1)

**Validate now on the existing window with NBM + AIFS-Single; add AIFS-ENS on its recent sub-window;
defer GEM to a parallel forward-collect cron — do not let it gate Phase-1.**

- **NBM (core + QMD)** and **AIFS-Single** both backfill to **≤2024-06**, covering the full ~26-month
  window, are Herbie-native, and station extraction is proven. These are the immediate VALIDATE-NOW
  set — exactly the top-2 of the model-selection paper (NBM for hard coastal/terrain stations via its
  2.5 km calibrated Tmax+percentiles; AIFS for decorrelated AI skill at the same ingest cost as IFS).
- **AIFS-ENS** is backfillable but only since ~mid-2025 (~12 mo). Include it, but score it on the
  matched recent sub-window — it cannot join the full-window comparison.
- **GEM (GDPS + GEPS)** is **not Herbie-backfillable**: the GDPS template URL is stale (404 even for
  today) and GEPS has no template, and ECCC datamart retains only ~24–48 h regardless. GEM is the most
  *independent* core, so it's worth standing up a **daily MSC-datamart forward-collect cron now**
  (current date-stamped paths confirmed live) and revisiting in ~3 months — but it must not block the
  NBM+AIFS validation that can start immediately.

**Net:** Phase-1 = **NBM + AIFS** (Single full-window, ENS recent sub-window). GEM = forward-collect
side-track, custom ECCC ingest, ~7–13 weeks to a usable eval window.

## Caveats

- Skill ≠ edge (the load-bearing caveat from the model-selection paper): backfillability lets us *test*
  these models; it does not promise P&L. Validate per-station CRPS / bracket-edge Brier first.
- AIFS daily-max is built from **6-hourly instantaneous 2t** (no native max field) — coarser than the
  IFS `mx2t3` path; expect a low bias in the daily max that EMOS must absorb. AIFS-Single also spans an
  experimental→operational version change (2025-02-25) within the window.
- NBM-QMD ships an *already-calibrated* distribution that may double-count with our EMOS layer — use it
  as a covariate/feature, not a raw member.
- Mirror retention can change without notice (the `ecmwf` live source is already shallow); the AWS/GCS
  buckets are the durable ones for NBM and AIFS.

*Probe artifacts (uncommitted, this branch): `scripts/analysis/probe_backfill_depth.py`,
`scripts/analysis/probe_vars.py`, `probe.log`, `probe_vars.log`.*
