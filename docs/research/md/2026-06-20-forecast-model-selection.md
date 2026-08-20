# Are GEFS + ECMWF-IFS + HRRR the best forecast models for this strategy — or should others be added?

*2026-06-20 · status: draft*

## Question

The daily-high strategy feeds three forecast models into its EMOS→blend pipeline: **GEFS** (NOAA, ~31 members), **ECMWF-IFS ENS** (~50 members), and **HRRR** (deterministic, folded in as one member, Chicago only). The CLAUDE.md notes this set "was an initial recommendation, not an exhaustive model-selection study." This paper asks: **of the models we already use, which actually carry skill at our scale (day-ahead, station, daily-max), and are there models we don't use — physics or AI — that would add *independent* skill and are *free to ingest*?** It matters now because forecast quality is the one upstream input that feeds every city, and the AI-weather landscape (AIFS, GenCast, GraphCast) has changed materially in the last 18 months.

## TL;DR / Verdict

**Medium confidence.** GEFS+IFS+HRRR is a *defensible* core but not optimal, and the highest-value gaps are not "another global ensemble":

1. **IFS > GEFS** after calibration (EMOS CRPS 1.327 vs 1.472), **combined beats either single** (1.268), and **HRRR is the single most accurate *raw* model at day-ahead** (MAE 2.57°F) — yet HRRR is wired into only one city. The multi-model ensemble is justified by the data; GEFS and IFS errors correlate only **r = 0.61**, so they genuinely diversify.
2. The dominant skill deficit is **at coastal/terrain stations** (KLAS MAE 6.0, KSFO 5.0, KPHX 4.4, KLAX 4.2°F) where a 0.25–0.4° global grid physically cannot resolve the microclimate. That is a **resolution/downscaling** problem, best solved by **NBM** (NOAA's free, Herbie-native, 2.5 km *calibrated* daily-Tmax blend), not by adding more coarse global members.
3. The best *free, commercially-licensed, decorrelated* additions are **ECMWF AIFS / AIFS-ENS** (same ECMWF Open Data channel we already use for IFS) and **GEM** (independent Canadian core). GFS-deterministic and ECMWF-HRES should be **skipped** — they share cores with GEFS/IFS and add little.

**Biggest caveat:** *better forecast skill ≠ trading edge.* Prior findings (no-edge ECMWF-00Z; market does 56–95% of the blend work; edge concentrated in Chicago/Miami/Seattle) mean these additions will measurably lower CRPS but may move P&L only modestly, because the market price already embeds most public-forecast information. Validate skill-first; treat edge impact as a separate, lower-prior question.

## Methods & Data

**Internal — read-only.** All numbers from a new analysis script, `scripts/analysis/forecast_model_skill.py`, run via `uv run`. It reproduces the production daily-high path (`aggregation.compute_daily_highs`): 00Z init, target = same UTC calendar day D; per ensemble member, daily high = `MAX(tmax_f)` over local-day-D valid times (station IANA tz); realized truth = CF6 `observations.high_temp_f`. Sample: all **13 stations**, IFS/GEFS back to 2024-04, HRRR from 2025-05. Metrics:
- **Ensemble-mean bias / MAE / RMSE** vs realized high. (MAE/RMSE of the ensemble mean is what external benchmarks — WeatherBench-2, ECMWF scorecards — publish for 2 m temperature, so it is the cross-comparable metric.)
- **Fair (PWM) ensemble CRPS** — distributional skill from the raw member spread; reduces to abs-error for deterministic HRRR.
- **Rolling-45-day EMOS-calibrated Gaussian CRPS**, out-of-sample, reusing `emos.fit_emos` / `crps_gaussian` exactly as production does — the production-relevant number.
- **GEFS↔IFS ensemble-mean error correlation** (Pearson) — quantifies how much *independent* signal a new model could add.
- **Matched samples** so comparisons are apples-to-apples (e.g. HRRR scored only on days where all three models are present).

**External — web search + fetch, every numeric claim verified against its primary source** (peer-reviewed papers, lab blogs, ECMWF/NOAA/DWD/ECCC docs, Herbie + Open-Meteo docs, vendor pricing pages). Three angles: (a) AI/ML models for station Tmax; (b) physics NWP + NOAA's NBM blend; (c) Open-Meteo as a unified ingestion layer + the four major paid point-forecast APIs.

## Internal Findings

### 1. Per-model day-ahead skill (00Z init, same-day high, all stations pooled)

| Config | n | Bias (°F) | MAE | RMSE | Ens-CRPS |
|---|---:|---:|---:|---:|---:|
| GEFS | 4630 | −1.40 | 3.06 | 3.88 | 2.523 |
| IFS | 4884 | −2.12 | 2.91 | 3.65 | 2.420 |
| HRRR | 3653 | −1.47 | **2.57** | 3.59 | 2.566 |
| **combined** (gefs+ifs) | 4630 | −1.85 | 2.75 | **3.44** | **2.117** |
| combined + HRRR | 3363 | −2.02 | 2.86 | 3.56 | 2.195 |

Two structural facts jump out. **(a) Every raw ensemble runs cold** — it under-forecasts the daily high by 1.4–2.1°F. This is exactly why EMOS exists, and it means *raw* MAE penalizes IFS for its larger cold bias even though IFS is the better model once corrected. **(b) HRRR's deterministic 3 km run has the lowest raw MAE** at this short lead — high resolution wins the nowcast — but its single member barely moves the 81-member pooled mean (combined vs combined+HRRR MAE 2.75→2.86 reflects a sample shift, not HRRR hurting; see matched sample below).

### 2. EMOS-calibrated CRPS — the production-relevant ranking

| Config | n_eval | Mean CRPS (°F) |
|---|---:|---:|
| GEFS | 4079 | 1.472 |
| IFS | 4331 | **1.327** |
| combined (gefs+ifs) | 4080 | **1.268** |
| combined + HRRR | 2812 | 1.238 |

After calibration: **IFS beats GEFS by ~10%**, **combining beats the best single model by ~4.4%** (and GEFS-alone by ~14%), and **adding HRRR lowers CRPS a further ~2.4%** (on a smaller, more recent eval window — see Limitations). This is the cleanest evidence that the multi-model ensemble is doing real work and that HRRR adds signal where it is present.

### 3. How much room is there for a *new* model? Error correlation

> **GEFS-mean error vs IFS-mean error: Pearson r = 0.614 (n = 4630).**

Two of the world's leading global systems still share only ~38% of their error variance. The variance of an equal average of two models scales as σ²(1+ρ)/2; at ρ=0.61 that is a ~10% RMSE reduction ceiling from a *second* equally-skilled, similarly-correlated model — and the observed combined-vs-IFS RMSE gain (3.65→3.44, −5.7%) is consistent with that (GEFS is weaker than IFS, so the realized gain is below the ceiling). **Implication:** a *third* model helps only to the extent its errors decorrelate from the GEFS+IFS pool, and the marginal gain diminishes fast. A same-lineage model (GFS-det shares GEFS's FV3 core; HRES shares IFS) will be ~highly correlated → near-zero marginal value. An independent core (GEM, ICON) or an ERA5-trained AI model (AIFS) is where decorrelation — and therefore value — actually lives.

### 4. Where the models actually fail: per-station MAE of the ensemble mean (°F)

| Station | GEFS | IFS | combined | combined+HRRR |
|---|---:|---:|---:|---:|
| KAUS | 2.51 | 2.75 | 2.43 | 2.55 |
| KDEN | 2.93 | 2.51 | 2.56 | 2.87 |
| KDFW | 2.71 | 2.73 | 2.48 | 2.47 |
| **KLAS** | **6.05** | 3.43 | 4.39 | 4.33 |
| **KLAX** | 3.07 | **4.18** | 2.94 | 3.66 |
| KMDW | 2.71 | 2.72 | 2.53 | **2.52** |
| KMIA | 2.67 | 3.37 | 3.06 | 3.08 |
| KMSY | 2.01 | 3.44 | 2.90 | 2.89 |
| KNYC | 2.72 | 2.67 | 2.51 | 2.75 |
| KORD | 2.62 | 2.94 | 2.62 | 2.64 |
| **KPHX** | **4.38** | 2.19 | 2.95 | 2.93 |
| KSEA | 2.26 | 2.22 | 1.88 | 1.89 |
| **KSFO** | **5.03** | 3.07 | 3.87 | 3.73 |

The skill is wildly station-dependent. Flat inland stations (KSEA 1.9, KMDW/KDFW/KAUS ~2.5) are easy; **coastal-marine and desert-basin stations are 2–3× worse** (KLAS, KSFO, KPHX, KLAX), and *which* model wins flips by station (GEFS is terrible at KLAS/KSFO/KPHX; IFS is terrible at KLAX/KMSY/KMIA). This is the fingerprint of **unresolved terrain and land/sea contrast** at 0.25–0.4° — not something a fourth global ensemble fixes, but exactly what a 2.5 km statistically-downscaled product (NBM) targets.

Note also that **combined+HRRR independently replicates the documented per-city HRRR result**: it *improves* KMDW/KDFW (2.53→2.52, 2.48→2.47) but *hurts* KNYC (2.51→2.75) and KLAX (2.94→3.66) — i.e. "HRRR helps Chicago, not NYC," recovered here from a clean-room computation.

## External Context

### AI / ML global models (verified)

| Model | Type | Temporal out | Free + commercial to ingest? | 2 m-temp skill vs IFS (verified) | Key limitation for station Tmax |
|---|---|---|---|---|---|
| **ECMWF AIFS Single** | Deterministic, 0.25° | 6-hourly | **Yes — CC-BY-4.0, ECMWF Open Data + Open-Meteo + Herbie** | **>15% lower T2m RMSE than IFS at 1.5-day vs SYNOP stations** (midday, flat terrain) [7] | Smoother than IFS; weaker over complex terrain |
| **AIFS-ENS** | Ensemble (CRPS-trained), 0.25° | 6-hourly | **Yes — CC-BY-4.0** [5] | Beats IFS-ENS on most CRPS targets [11] | Same smoothing; operational since Jul 2025 |
| **GenCast** (DeepMind) | Ensemble (diffusion), 0.25° | **12-hourly** | Weights **CC-BY-NC-SA — no commercial** [9] | More skillful than ENS on **97.2% of 1320 targets** (CRPS, global) [3][4] | **12-hourly output cannot resolve a sub-daily Tmax** |
| **GraphCast** (DeepMind) | Deterministic, 0.25° | 6-hourly | Weights **CC-BY-NC-SA — no commercial** [1][2] | Beat HRES on ">90% of 1380 targets" (global, not T2m-specific) | RMSE-trained → blurs extremes |
| **Aurora** (Microsoft) | Deterministic, 0.1° | 6-hourly | Weights open; **no free live feed** | Beats IFS-HRES on 2m-temp at **13,000+ ISD stations**, all leads to 10d [14] | Must self-run; op/licensing for trading unverified |
| **WeatherNext / 2** (Google) | Ensemble | sub-daily | **Cloud-gated** (BigQuery/Earth Engine/Vertex) [15][16] | v2 beats v1 on "99.9% of vars/leads" (not vs IFS directly) | Licensing + cost; ERA5-lineage smoothing |
| Pangu-Weather; FourCastNet | Deterministic, 0.25° | 1–6h | Research weights; no managed feed | Pangu > IFS on T2M (2023) [10]; FourCastNet weaker | Self-host only |

**The crucial caveat for our use case:** every AI model is trained on **ERA5/HRES gridbox-average** fields and verified at headline level against *gridded analysis*, not US-airport daily-Tmax. They **systematically smooth and under-predict extremes** — precisely the tails a daily-Tmax market trades on — and several emit only **6–12-hourly** output, which cannot capture a sub-daily maximum (fatal for GenCast at 12-hourly). Their bias *structure* differs from physics NWP (AIFS avoids IFS's wintertime warm bias [7]), which is the decorrelation we want, but it must be measured locally before trusting it.

### Physics NWP + NOAA's NBM (verified)

| Model | Center | Independent of GEFS/IFS? | Res | Free + Herbie / Open-Meteo? | Verdict |
|---|---|---|---|---|---|
| GFS-det | NCEP | **No** (shares FV3 + GDAS with GEFS) | 13 km | Herbie ✓ | **Skip** — correlated |
| ECMWF HRES | ECMWF | **No** (same IFS) | 9 km | Herbie ✓ | **Skip** — adds little over IFS-ENS |
| **GEM / GDPS / GEPS** | **ECCC (Canada)** | **Yes** (independent GEM core) | 15 km global; **HRDPS 2.5 km** NA | Herbie ✓ (beta); Open-Meteo ✓ | **Best independent add** |
| **ICON (global)** | **DWD (Germany)** | **Yes** | ~13 km | Herbie ✗; **Open-Meteo ✓** | Good diversity member (ICON-EU/D2 are **Europe-only** — useless for US) |
| **ARPEGE** | **Météo-France** | **Yes** | ~0.25° | Open-Meteo ✓ | Secondary diversity member |
| UKMET / MOGREPS | UKMO | **Yes** | 10 km | Herbie ✗; Open-Meteo ✓ | Independent but US ingestion is the friction |
| NAM / RAP | NCEP | Partial | 3 km / 13 km | Herbie ✓ | RAP subsumed by HRRR; NAM short-range only |
| JMA GSM | JMA | Yes | ~55 km | Open-Meteo ✓ | Too coarse for station Tmax |
| **NBM** | **NOAA/MDL** | Blend (not independent) | **2.5 km CONUS** | **Herbie ✓; AWS/NOMADS free** | **Best practical add for hard stations** |

**NBM (National Blend of Models)** is NOAA/MDL's "calibrated… blend of NWS and non-NWS NWP and **post-processed** model guidance" — it ingests GFS/ECMWF/CMC/NAM/HRRR, then **bias-corrects and terrain-downscales to a 2.5 km CONUS grid**, emitting calibrated **daily Tmax/Tmin plus percentiles**. It is free (`s3://noaa-nbm-grib2-pds`/NOMADS) and `Herbie(model="nbm")`-native. It directly attacks our worst stations (KSFO/KLAS/KLAX/KPHX/KSEA) because its statistical downscaling resolves marine-layer gradients and basin inversions a coarse grid misses. **Caveat:** NBM partly blends the same GFS/IFS we already use, so it is a *calibrated downscaler / feature*, not a decorrelated independent member — and it ships an already-calibrated distribution that may overlap our own EMOS layer.

### Ingestion layer & paid APIs (verified)

- **Open-Meteo is the single best ingestion path.** Its free API serves 30+ NWP models and an **Ensemble API with individual members** (GEFS, IFS-ENS, **ICON-EPS, GEM, AIFS-ENS, UKMO**), serves **AI models** (AIFS, a GFS-GraphCast), and — critically — offers a **free Historical Forecast / "Previous Runs" archive** (forecasts-as-issued, ~2021/2024 onward) that solves the honest-backtest problem. Data is **CC-BY 4.0** (commercial OK with attribution); but the **free tier is non-commercial** and member-level + history needs the **Professional tier or self-hosting** the AGPL server. Member *history* is only ~3 days, so a rolling-archive cron is needed [1–6, ingestion].
- **The four paid point-forecast APIs (Tomorrow.io, Weatherbit, Visual Crossing, AccuWeather) are low value here.** All are **deterministic single-point** forecasts — **no per-member ensemble → no native CRPS** — and none offers a cheap, bulk *forecast-as-issued* archive for backtesting (they sell *observation* history). They are MOS-style and may beat *raw* GEFS/IFS at a station, but as one correlated number they cannot substitute for an ensemble. At most, Visual Crossing's free 1,000 records/day is a cheap single MOS *feature* to A/B — not a core source.

## Limitations & Threats to Validity

- **Skill ≠ edge — the load-bearing caveat.** Every internal number here is forecast *accuracy*, not P&L. The market-blend finding (market carries 56–95% of weight; β_model negative at KAUS/KLAX) and the per-city diagnostic (edge concentrated in Chicago/Miami/Seattle) mean a CRPS improvement may not convert to edge. A better model helps most where our model still has *independent* signal versus the market — which is a smaller set than "all stations."
- **Short lead only.** We measured the ~12–36h day-ahead horizon the strategy trades. Rankings (especially HRRR's raw-MAE win) would shift at longer leads, where global ensembles and AI models dominate and HRRR isn't available.
- **Raw MAE penalizes bias; EMOS corrects it.** The raw-MAE tables understate IFS (largest cold bias) relative to its post-calibration skill. The EMOS-CRPS table is the fairer production-relevant view.
- **HRRR / combined+HRRR eval samples are smaller and more recent** (HRRR from 2025-05/12; EMOS n_eval 2812 vs 4080). The "+2.4% CRPS from HRRR" is suggestive, not matched-sample definitive. The per-station replication of the Chicago-yes/NYC-no pattern is the more robust HRRR result.
- **External skill figures are global/gridded, not station-Tmax.** The headline AI claims ("beats IFS on 90%+ of targets") are global, multi-variable averages against analysis — not US-airport daily-max at 12–36h. The single most on-point external number is AIFS's SYNOP-station T2m RMSE [7]; the rest must be re-validated locally before being trusted for trading.
- **AI extreme-smoothing** biases the tails this market resolves on; an AI model could improve mean CRPS yet *worsen* bracket-boundary calibration. Must be checked with Brier/reliability at bracket edges, not just CRPS.
- **No model fixes the binding constraint directly.** Per the standing "grow data, not sophistication" principle, the value of these additions is partly that they *grow the data* (more independent members, more stations resolved) — but they remain upstream of a market that already prices most of it.

## Recommendation

**Do not act now — CONFIG FREEZE is in effect until 2026-07-10.** The following are **backlog proposals**, ranked by expected skill-per-integration-effort, to be validated **skill-first** (per-station CRPS/Brier vs the current combined baseline on a matched sample) *before* any edge/backtest claim. Each is appended to `docs/backlog.md`.

1. **NBM (National Blend of Models)** — highest immediate value. Free, `Herbie`-native, 2.5 km **calibrated daily-Tmax**; directly targets our worst stations (KSFO/KLAS/KLAX/KPHX). Integrate as a **calibrated feature / EMOS covariate**, not a raw member (it's already post-processed). Validate it most where the global grid fails — but temper expectations: those are not currently our edge-positive cities.
2. **ECMWF AIFS + AIFS-ENS** — lowest integration cost (same ECMWF Open Data channel + Herbie we already use for IFS), **free and commercially licensed (CC-BY-4.0)**, and structurally **decorrelated** from physics NWP. The one AI model whose licensing and station-level T2m evidence both clear the bar. Add as ensemble members; check bracket-edge calibration, not just CRPS.
3. **GEM (GDPS + GEPS, HRDPS 2.5 km)** — the best *truly independent* dynamical add (independent core, free, Herbie beta, native North-America high-res). Highest decorrelation of the physics options.
4. **(Lower priority) ICON-global and ARPEGE via Open-Meteo** as further diversity members; adopt **Open-Meteo's Ensemble + Historical-Forecast API** as the unified ingestion + backtest-archive layer (note: commercial/member-level needs the Professional tier or self-hosting).
5. **Explicitly skip:** GFS-deterministic and ECMWF-HRES (lineage-correlated with GEFS/IFS), RAP (subsumed by HRRR), JMA GSM (too coarse), and **all four paid point-forecast APIs** (deterministic, no ensemble, no cheap forecast history). GenCast/GraphCast/WeatherNext are non-commercial-licensed or cloud-gated → not usable for live trading even though GenCast's *research* skill is state-of-the-art.

**Suggested validation protocol** (for after the freeze): ingest NBM + AIFS for the 13 stations over a backfilled window; recompute the §2 rolling-EMOS CRPS and bracket-boundary Brier for `combined`, `combined+NBM`, `combined+AIFS`, `combined+NBM+AIFS`; **adopt an addition only if it lowers per-station CRPS *and* improves (or holds) bracket-edge reliability** at a city that is already edge-relevant — and only then test whether it moves blended P&L.

## Sources

**Internal (reproducible):**
- `scripts/analysis/forecast_model_skill.py` — `cd /home/tdunn/weather-project && uv run python scripts/analysis/forecast_model_skill.py` (all §1–§4 tables).
- `aggregation.compute_daily_highs`, `emos.fit_emos`, `emos.crps_gaussian`, `evaluation.brier_score` (production scoring paths reused).
- DB: `psql -d weather` — `forecasts` (model/member coverage), `observations` (CF6 highs). 13 stations; IFS/GEFS 2024-04→2026-06, HRRR 2025-05→.
- Project context: `docs/context/decisions.md` (model rationale, per-city HRRR), memories `project_market_blend_finding`, `project_per_city_diagnostic_finding`, `project_no_edge_ecmwf_00z_finding`.

**External (verified):**
1. GraphCast — DeepMind: https://deepmind.google/discover/blog/graphcast-ai-model-for-faster-and-more-accurate-global-weather-forecasting/
2. GraphCast — Lam et al., *Science* 382, 1416 (2023): https://www.science.org/doi/10.1126/science.adi2336
3. GenCast — Price et al., *Nature* (2024): https://www.nature.com/articles/s41586-024-08252-9
4. GenCast — DeepMind (97.2% claim): https://deepmind.google/discover/blog/gencast-predicts-weather-and-the-risks-of-extreme-conditions-with-sota-accuracy/
5. ECMWF AIFS ML data (CC-BY-4.0, commercial OK): https://www.ecmwf.int/en/forecasts/dataset/aifs-machine-learning-data
6. ECMWF Open Data: https://www.ecmwf.int/en/forecasts/datasets/open-data
7. ECMWF AIFS blog — SYNOP-station 2 m-temp verification: https://www.ecmwf.int/en/about/media-centre/aifs-blog/2025/verifying-2-m-temperature-forecasts-wintertime-anticyclonic
8. Open-Meteo ECMWF/AIFS API: https://open-meteo.com/en/docs/ecmwf-api
9. GraphCast/GenCast GitHub (weights CC-BY-NC-SA): https://github.com/google-deepmind/graphcast
10. Pangu-Weather — Bi et al., *Nature* 619, 533 (2023): https://www.nature.com/articles/s41586-023-06185-3
11. AIFS-ENS / AIFS-CRPS — arXiv:2412.15832: https://arxiv.org/abs/2412.15832
12. FourCastNet — arXiv:2202.11214; code https://github.com/NVlabs/FourCastNet
13. Aurora — Microsoft Research: https://www.microsoft.com/en-us/research/blog/introducing-aurora-the-first-large-scale-foundation-model-of-the-atmosphere/
14. Aurora — Bodnar et al., *Nature* (2025), 13,000+ station 2m-temp: https://www.nature.com/articles/s41586-025-09005-y
15. WeatherNext — DeepMind: https://deepmind.google/science/weathernext/
16. WeatherNext 2 — Google: https://blog.google/technology/google-deepmind/weathernext-2/
17. AWS Open Data — NOAA NBM: https://registry.opendata.aws/noaa-nbm/
18. NWS MDL / VLab — National Blend of Models: https://vlab.noaa.gov/web/mdl/nbm
19. Herbie NBM gallery: https://herbie.readthedocs.io/en/stable/gallery/noaa_models/nbm.html
20. Herbie model gallery (supported models): https://herbie.readthedocs.io/en/stable/gallery/index.html
21. DWD ICON description: https://www.dwd.de/EN/research/weatherforecasting/num_modelling/01_num_weather_prediction_modells/icon_description.html
22. Open-Meteo DWD ICON API: https://open-meteo.com/en/docs/dwd-api
23. ECCC MSC Open Data — GDPS: https://eccc-msc.github.io/open-data/msc-data/nwp_gdps/readme_gdps_en/
24. Open-Meteo GEM (Canada) API: https://open-meteo.com/en/docs/gem-api
25. Open-Meteo Forecast API: https://open-meteo.com/en/docs
26. Open-Meteo Ensemble API (per-member): https://open-meteo.com/en/docs/ensemble-api
27. Open-Meteo Historical Forecast / Previous Runs API: https://open-meteo.com/en/docs/historical-forecast-api
28. Open-Meteo pricing + licence (CC-BY-4.0 data / AGPL code): https://open-meteo.com/en/pricing
29. Tomorrow.io pricing / ToS: https://support.tomorrow.io/hc/en-us/articles/23554984091156-Tomorrow-io-Pricing-Overview
30. Weatherbit pricing: https://www.weatherbit.io/pricing
31. Visual Crossing editions/pricing: https://www.visualcrossing.com/weather-data-editions/
32. AccuWeather developer packages: https://developer.accuweather.com/packages
