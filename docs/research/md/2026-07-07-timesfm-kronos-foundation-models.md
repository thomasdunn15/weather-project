# Should we add a time-series foundation model (TimesFM or Kronos) to the temperature-trading stack?

*2026-07-07 · status: final*

## Question

Two frontier time-series foundation models — **TimesFM** (Google) and **Kronos** (Tsinghua) — are attracting attention. Should either be implemented into our Kalshi daily-high-temperature strategy (stack: GEFS+IFS+HRRR → EMOS → Benter market-blend)? A foundation model could in principle play one of two roles, and they are completely different problems:

- **Role A — forecast the *weather*** (predict the daily high better than our NWP→EMOS pipeline), or
- **Role B — forecast the *price*** (predict Kalshi contract price moves for a trading/execution edge).

This paper answers both with primary-source numbers, and frames the answer against (i) the *real* ML-weather frontier (GraphCast/GenCast/AIFS) and (ii) our current priority (venue/breadth expansion).

## TL;DR / Verdict

**Skip both. Confidence: HIGH.**

- **Role A (weather):** Generic univariate TS foundation models **lose to physics NWP + post-processing at short-range station temperature.** The one benchmark that tests this class head-to-head against operational NWP (WEATHER-5K, NeurIPS 2024) shows **ECMWF-HRES beats all 16 data-driven models on temperature**, the pretrained "large time model" (Timer, the closest TimesFM/Kronos analog) is **~29% worse at 24 h and worst at the extremes** the brackets are priced on. TimesFM/Kronos are structurally **blind to the atmospheric state** that carries 1–3-day skill — the exact information our GEFS+IFS+HRRR→EMOS stack already uses. They would be a downgrade, not an upgrade.
- **Role B (price):** Kronos reads the *candlestick tape*, but a weather bracket's value is a martingale estimate of an **exogenous physical outcome** — the informative signal (a better forecast) is *not in the price tape at all*. Binary-event price movement is empirically **near-random to ML** (no model beat a 0.539 coin-flip baseline), and six frontier models trading **live Kalshi lost money (avg −13.8%)**. This is the "market out-predicts us / skill ≠ edge" wall this project has hit repeatedly, in a more expensive form.
- **The frontier-worthy ML-weather move** is not hosting a TS-FM at all — it is **consuming an ML-NWP open-data product (AIFS, already in our ingest; GenCast) as another ensemble input.** That is data plumbing, not model hosting, and even then it is skill-not-edge and lower priority than venues.

**Biggest caveat:** there is no published head-to-head of *TimesFM/Chronos/Moirai by name* vs NWP+EMOS on station *daily-high* temperature — WEATHER-5K's foundation representative is Timer. Absence isn't proof, but the burden of evidence sits entirely on the "it works" side and is unmet.

## Methods & Data

**Internal (read-only).** Confirmed the live model set and pipeline from source: `grep` of `scripts/live_trade.py` CITY_CONFIG (`models`, `emos_model`) and `scripts/paper_trade_log.py`; read `src/weather_markets/emos.py` and `src/weather_markets/blend.py`; cross-referenced prior research docs (`docs/research/md/2026-06-20-forecast-model-selection.md`) and project findings (market-blend, no-edge-ECMWF-00Z, per-city capacity, intraday fair-value gate + latency probe).

**External.** Three parallel research agents, each instructed to verify every claim against its primary source (arXiv, HuggingFace model cards, official repos/blogs, benchmark papers) and cite the URL: (1) TimesFM + generic TS-FMs + the weather-benchmark question; (2) Kronos + financial benchmarks + fit to binary event contracts; (3) the ML-NWP frontier + prior art (weather and prediction markets) + compute/infra reality. Sources listed at the end.

## Internal Findings

**Our current stack already does the thing a foundation model would be brought in to do — with the right tool.**

| Component | What we run | Source |
|---|---|---|
| Forecast (Chicago/KORD) | EMOS `combined_hrrr` = GEFS+IFS+HRRR, 00Z | `live_trade.py:90-91` |
| Forecast (Miami/KMIA, Dallas/KDFW) | EMOS `combined` = GEFS+IFS, 00Z | `live_trade.py:130-131,177-178` |
| Calibration | EMOS rolling-window (μ=a+b·mean, σ²=c+d·std²) | `src/weather_markets/emos.py` |
| Market blend | Benter logit: `logit(P_blend)=α+β_model·logit(P_model)+β_market·logit(P_market)` | `src/weather_markets/blend.py` |
| Ingest | GEFS, ECMWF/IFS, HRRR | `src/weather_markets/ingest/` |

Two project findings make the foundation-model question nearly moot before we start:

1. **Skill ≠ edge, already demonstrated repeatedly.** Adding models (NBM, AIFS, HRRR outside Chicago) improved forecast *skill* but did **not** improve trading *edge* (`2026-06-20-forecast-model-selection.md`; AIFS was evaluated on branch `research/p1-aifs` and left unadopted as marginal). A foundation model is the same "add a better model" hypothesis in a larger, costlier package.
2. **The market out-predicts us.** The intraday fair-value gate (2026-07-05) showed the *market price* is already better-calibrated and lower-Brier than our fair at every decision hour, and the latency probe showed no capturable lag. Our edge is a **thin margin on top of an efficient market**, captured via the blend — not an ability to out-forecast it. A price-forecasting model (Role B) has nothing to exploit in a market we have measured to be efficient.

## External Context

### What the two models actually are

| | **TimesFM** (Google) | **Kronos** (Tsinghua) |
|---|---|---|
| Aimed at | General univariate time series | **Financial** OHLCV / candlesticks |
| Architecture | Decoder-only *patched* transformer | Decoder-only; **BSQ tokenizer** over K-lines + AR transformer |
| Sizes | 1.0=200M (ctx 512); 2.0=500M (ctx 2048); 2.5=200M (ctx 16k) | mini 4.1M · small 24.7M · base 102.3M · large 499.2M (unreleased) |
| Training corpus | ~100B time-points (Google Trends + Wikipedia + synthetic; 2.0 adds LOTSA incl. ERA5/CMIP6) | >12B K-lines, 45 exchanges, 7 granularities |
| License | Apache-2.0 | MIT |
| Footprint | ~0.8 GB (200M) / ~2 GB (500M) F32; CPU backend | base ~410 MB; CPU, seconds |
| Venue | ICML 2024 (arXiv 2310.10688) | AAAI 2026 (arXiv 2508.02739) |

Peer generic TS-FMs (Chronos/Chronos-2, Moirai/Moirai-2.0) sit in the same top tier as TimesFM-2.5 on *general* TS benchmarks (GIFT-Eval) — none dramatically ahead. None of that tier ranking speaks to weather-vs-NWP.

### Role A — weather: the decisive benchmark (WEATHER-5K, NeurIPS 2024)

~5,672 global stations, hourly, TSF models vs operational **ECMWF-HRES** interpolated to stations. Temperature MAE (≈ °C):

| Model | Temp MAE @ 24 h | Full-horizon avg |
|---|---|---|
| **ECMWF-HRES (operational NWP)** | **1.76** | **1.94** |
| Pyraformer (best plain TSF) | 1.75 | 2.49 |
| iTransformer | 1.82 | 2.64 |
| **Timer (pretrained TS-FM analog)** | **2.27** | 2.97 |
| DLinear | 2.71 | 3.57 |
| PhysicsFormer (physics + station graph) | 1.55 | 2.34 |

- HRES "**outperforms all existing TSF methods across nearly all variables**"; on the full horizon it beats **every** TSF model. NWP dominance grows with lead time.
- The pretrained large-time-model **Timer (2.27 @24h) is the worst credible option** — worse than even a small purpose-trained transformer.
- The **only** model to beat HRES at short range is **PhysicsFormer** — precisely because it is *not* univariate (it adds a physics core + spatial graph). This reinforces *why* NWP wins.
- **Extremes:** HRES temperature SEDI ≈ **37.4** vs plain TSF ≈ 10–14. NWP is far better at the tails — exactly what a daily-high *bracket* is priced on.

**Mechanism:** TimesFM/Chronos forecast a station's future from its own past values, **blind to the current 3-D atmospheric state** (pressure, fronts, advection, moisture) that determines tomorrow's high. NWP integrates the physics forward from an initialized state; EMOS then debiases it against local history — capturing the *same* climatology signal a TS-FM would learn, **on top of** the physics it lacks. A univariate TS-FM can only ever recover a strict subset of what NWP+EMOS already exploits. (TS-FMs are competitive only at long-range/S2S where NWP decays to climatology, or at data-poor stations with no NWP — neither is our situation.)

### The real ML-weather frontier (a different category)

Models that genuinely **match/beat operational NWP** all train on the **full gridded atmospheric state** (ERA5), not a scalar history:

| Model | Headline result vs NWP | Runnable on our box? |
|---|---|---|
| **GenCast** (DeepMind, diffusion ensemble) | Beats ECMWF **ENS on 97.2%** of 1,320 targets | No — ~300 GB RAM / 60 GB vRAM at 0.25° |
| **GraphCast** (DeepMind, GNN) | Beats **HRES on 90%** of 1,380 targets; 36.7M params | No — needs TPU/GPU + full global grid input |
| **AIFS** (ECMWF) | **Operational Feb 2025**, ~20% gains on TC tracks; **open data** | Not hosted — but its **outputs are open data we already ingest** |
| **Pangu-Weather** (Huawei, 256M) | First AI to beat **IFS on all vars, all ranges 1h–1wk** | No — GPU + gridded IC |

The decisive blocker for hosting these isn't just GPU — it's the **global gridded initial condition** each requires (tens of GB/cycle). **The only realistic way to touch this frontier is to consume the open-data outputs (AIFS/GenCast) as another ensemble member** — a data-plumbing task. TimesFM/Kronos are *not* in this category and do not compete with NWP.

### Role B — price: Kronos and the prediction-market evidence

- **Kronos benchmarks are real but are forecast-*accuracy*, not net P&L.** Reported: +93% RankIC vs the best TS-FM baseline, 9% lower volatility MAE, best AER/IR in an investment sim. But RankIC ≠ money; the only profit-flavored result is a **long-only Chinese-equities** top-k backtest with **no clear deduction of realistic costs**, and **nothing in the paper touches binary/event contracts.**
- **Distribution mismatch is severe.** Kronos learns endogenous microstructure (momentum, mean-reversion, volume) in liquid continuous OHLCV. A weather bracket's price is a **probability estimate of an exogenous outcome** that converges to 0/1 at settlement regardless of any candlestick pattern; its thin, gappy book is off-distribution for the tokenizer; and the *only* informative signal (a superior forecast) is not in the tape.
- **Binary-event movement is near-random to ML.** A 2025 study (arXiv 2511.15960) tested RF/LogReg/GBM/kNN/MLP/LSTM on binary-option up/down; after tuning **no model beat the 0.539 majority-class baseline** — "a fundamental failure to learn any true predictive signal."
- **Frontier models lose money on live Kalshi.** "Prediction Arena" (arXiv 2604.07355) ran six frontier models as live autonomous Kalshi traders (Jan–Mar 2026): **all six posted negative returns, averaging −13.8%** (best −4.4%, worst −26.8%).
- **The documented Kalshi/Polymarket edges are structural, not model-sourced:** a **favorite-longshot bias** (contracts priced **≥50¢ earn statistically significant positive returns**; passive market-making on them returns ~2.6% after commission — Whelan 2025), cross-venue arbitrage, and liquidity provision. No one has published durable prediction-market alpha from a foundation model; generic TS pretraining is documented *not* to transfer to finance without finance-native retraining.

## Limitations & Threats to Validity

- **No exact head-to-head.** WEATHER-5K's foundation representative is **Timer**, not TimesFM/Chronos/Moirai by name, and it uses hourly temperature, not our daily-high bracket target. No paper claims a generic TS-FM beats NWP+MOS at short range — but "absence of a win" is weaker than "a demonstrated loss." The first-principles argument (univariate blindness to atmospheric state) is the load-bearing evidence; the burden is on the "it works" side.
- **Secondary sources:** GIFT-Eval leaderboard percentages are from a web summary (not cell-verified). The oft-cited "Kalshi market-implied temp uncertainty = 1.27× realized" is **unverified** (GitHub writeups only) — use only as directional corroboration of our own market-blend result, not a citation.
- **Kronos investment-sim cost treatment** could not be confirmed to deduct realistic fees/slippage (likely not; equities not binaries regardless).
- **CPU-latency figures** for TimesFM/Kronos are inferred from model size, not officially benchmarked.
- **Analogue, not identical:** the binary-options and Prediction-Arena papers are the closest available evidence, not a candlestick-FM-on-Kalshi-weather experiment (which does not appear to exist — itself informative).

## Recommendation

**Do not implement TimesFM or Kronos as a forecaster or a price model.** (Read-only research; no config change. Backlog proposals only — see below.)

1. **Reject Role A (TS-FM as temperature forecaster)** and **Role B (Kronos on the price tape)** outright. Both are the exhausted "smarter-forecasting" lever in a costlier form; the weather benchmark shows a *downgrade*, and the market evidence shows event-contract prices are near-random / already efficient.
2. **The one non-null, low-priority probe** (backlog, not now): a TS-FM used strictly as a **covariate-blender that ingests our NWP ensemble members** (i.e., as post-processing, *not* as the forecaster) — e.g. Chronos-2 / TimesFM-XReg. It competes with EMOS, has no published win, and per our binding-constraint principle is unlikely to move CRPS. Only worth touching if the venue path stalls.
3. **The frontier-worthy ML-weather move** is orthogonal to this question: **ingest an ML-NWP open-data product (AIFS — already partly in our stack; GenCast products) as an additional ensemble input.** Data plumbing, not model hosting. Still skill-not-edge, still below venues in priority.
4. **Unrelated but cited lead worth its own study:** the **favorite-longshot bias** (≥50¢ Kalshi contracts earning positive returns; passive MM ~2.6% after commission) is a *structural* edge independent of forecasting — a different and possibly more promising direction than any foundation model.
5. **Priority is unchanged:** breadth/venues — **ForecastEx access** (highest upside) and the maturing **Polymarket depth data** (mid-July readout).

*Infra note (moot given the above): TimesFM-200M (~0.8 GB) and Kronos-base (~410 MB) would technically run on the 7.6 GB no-swap CPU box, but only ephemerally and off the live-trading host — a resident fp32 model is a real OOM risk against prod Postgres. Feasibility was never the blocker; skill is.*

**Backlog line to append to `docs/backlog.md`:** *"TS foundation models (TimesFM/Kronos) evaluated 2026-07-07 → SKIP (lose to NWP+EMOS on short-range temp per WEATHER-5K; price-tape models don't fit exogenous-outcome binaries; skill≠edge). Only frontier ML-weather move = consume AIFS/GenCast open-data outputs as an ensemble member (data plumbing). Separate lead: favorite-longshot bias on ≥50¢ contracts."*

## Sources

**Model specs & benchmarks**
1. TimesFM — arXiv 2310.10688 (ICML 2024); model cards https://huggingface.co/google/timesfm-1.0-200m , https://huggingface.co/google/timesfm-2.0-500m-pytorch , https://huggingface.co/google/timesfm-2.5-200m-pytorch ; repo https://github.com/google-research/timesfm ; blog https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
2. Kronos — arXiv 2508.02739 (AAAI 2026); https://github.com/shiyu-coder/Kronos ; https://huggingface.co/NeoQuasar/Kronos-base
3. Chronos — arXiv 2403.07815 ; https://github.com/amazon-science/chronos-forecasting . Chronos-2 — arXiv 2510.15821. Moirai — arXiv 2402.02592 ; Moirai-2.0 — arXiv 2511.11698. GIFT-Eval — https://huggingface.co/spaces/Salesforce/GIFT-Eval

**Weather / NWP**
4. WEATHER-5K — arXiv 2406.14399 (NeurIPS 2024 D&B); tables 2/3/8 at https://arxiv.org/html/2406.14399v4
5. GraphCast — arXiv 2212.12794 ; Science 382:1416 (2023) https://www.science.org/doi/10.1126/science.adi2336 ; params https://github.com/google-deepmind/graphcast/issues/107
6. GenCast — arXiv 2312.15796 ; https://deepmind.google/discover/blog/gencast-predicts-weather-and-the-risks-of-extreme-conditions-with-sota-accuracy/
7. AIFS — arXiv 2406.01465 ; https://www.ecmwf.int/en/about/media-centre/news/2025/ecmwfs-ai-forecasts-become-operational
8. Pangu-Weather — arXiv 2211.02556 ; Nature https://www.nature.com/articles/s41586-023-06185-3 . FourCastNet — arXiv 2202.11214

**Prediction markets / prior art**
9. ML vs Randomness (binary options) — arXiv 2511.15960
10. Prediction Arena (frontier models on live Kalshi) — arXiv 2604.07355
11. Whelan 2025, "Makers and Takers: The Economics of the Kalshi Prediction Market" — https://www.karlwhelan.com/Papers/Kalshi.pdf
12. Prediction-market systematic edges synthesis — https://quantpedia.com/systematic-edges-in-prediction-markets/
13. Finance-native TS pretraining necessity — arXiv 2507.07296 ; arXiv 2511.18578

**Internal**
14. `scripts/live_trade.py` CITY_CONFIG (models/emos_model); `scripts/paper_trade_log.py`; `src/weather_markets/emos.py`, `blend.py`; `docs/research/md/2026-06-20-forecast-model-selection.md`; project findings: market-blend, no-edge-ECMWF-00Z, per-city capacity, intraday fair-value gate + latency probe.
