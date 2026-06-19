# Strategy

> How edge is computed, blended, sized, and risk-gated. Audience: agents. Last verified: 2026-06-19.

## TL;DR
- **Edge = model_P − market_mid** per bracket. Trade when |edge| ≥ a per-city threshold.
- Model_P comes from **EMOS** (rolling 45-day calibration of the ensemble) integrated over each Kalshi bracket.
- A **Benter-style logistic blend** of model_P and market_P beats the raw model; backtests fit it **walk-forward** (no lookahead).
- Sizing: unit / amount / kelly / scaling. Execution: market / post_inside_spread (~75% fill) / market_plus_*. Risk: edge threshold, daily-loss + cumulative kill, anti-stacking, edge cap.
- **CONFIG IS FROZEN 2026-06-12 → 2026-07-10** — change only for safety/correctness; new ideas go to [../backlog.md](../backlog.md). See [../decisions/](../decisions/).

## Calibration → probabilities
1. `aggregation.compute_combined_daily_highs(init, date, conn, station, models)` → ensemble member daily highs (`combined`=GEFS+IFS; `combined_hrrr`=+HRRR).
2. `emos.fit_emos_rolling(date, conn, window_days=45, station, model, init_hour=0)` → affine mean/variance correction: `μ = a + b·ens_mean`, `σ² = c + d·ens_spread²`. Corrects ensemble under-dispersion (raw ensembles are over-confident).
3. `emos.gaussian_to_bracket_probs(μ, σ, contracts)` → model_P per bracket (integrate the Gaussian over `[strike_low, strike_high]` per `bracket_type`).

## Edge & the Benter blend (`src/weather_markets/blend.py`)
- `edge = model_P − market_mid`, where `market_mid = (yes_bid + yes_ask) / 200`.
- Blend: `logit(P_blend) = α + β_model·logit(P_model) + β_market·logit(P_market)`, fit per city on settled `paper_trades` via logistic regression (`fit_blend` / cached `get_blend`).
- **Backtests MUST use `walkforward_blends(...)`** — one fit per date trained only on strictly-earlier settled data (weekly refit). Fitting on the full history and scoring it there inflated blend/union results ~30–50%.
- Empirical: blend beats raw model 11–43% test Brier across cities; market carries most of the weight; **β_model is negative for KAUS/KLAX** (model anti-informative there). See memory `project_market_blend_finding`.

## Sizing modes (`dashboard/sim_python.py`, mirrored in `static/app.js` jsComputeSim)
| mode | stake |
|---|---|
| `unit` | fixed N contracts/trade (ignores bankroll) |
| `amount` | fixed $ /trade → contracts = $ / (entry/100) |
| `kelly` | bankroll × kelly_fraction × Kelly-optimal f (capped); compounds |
| `scaling` | bankroll × fixed % (capped); compounds |

## Execution modes
| mode | behavior |
|---|---|
| `market` | cross the spread, 100% fill (realistic default) |
| `post_inside_spread` | post 1¢ inside spread; **~75% fill** (deterministic hash); saves $ when it fills |
| `market_plus_1` / `market_plus_2` | pay ask + 1¢/2¢ (aggressive, ensures fill) |

Fees: `kalshi_fee_cents(entry) = ceil(0.07 · p · (1−p) · 100)`, min 1¢, p = entry/100 — charged on entry only. Net P&L is fee-adjusted.

## Risk controls
- Per-city **edge_threshold** (raw); UNION cities also have **blend_edge_threshold**.
- **daily_loss_limit_dollars** (halt for the day) and **cumulative_kill_dollars** (kill switch).
- **Anti-stacking (`maxSignals`)**: keep only top-N |edge| signals per day (live KORD=2, KMIA=1). *(Note: dashboard what-if toggle; reverted from live earlier — see memory.)*
- **edge cap**: size edges above the cap as if they equaled it (sizing only; doesn't change which trades fire).
- **Spread-regime / data-completeness halts** + filesystem kill files (`halt/KORD|KMIA|ALL`).

## Per-city config — `scripts/live_trade.py CITY_CONFIG`
Each city dict carries (KORD shown): `city_name`, `models`, `emos_model` (`combined`/`combined_hrrr`), `model_source`, `paper_model_source`, `live_model_source_tag`, `decision_hour`/`decision_minute` (UTC), `use_union`, `use_blend`, `edge_threshold`, `blend_edge_threshold`, `smart_cross_edge_threshold`, `sizing_mode`, `unit_contracts`, `amount_dollars`, `max_contracts_per_trade`, `daily_loss_limit_dollars`, `cumulative_kill_dollars`, `is_active`.
- **KORD (Chicago, LIVE):** combined_hrrr, **UNION** (raw ≥25% OR blend ≥10%), unit 500, decision 14:46Z.
- **KMIA (Miami, LIVE):** **blend-only** ≥10%, unit 500, decision 15:30Z.
- **Paper/backtest cities:** KNYC (halted), KAUS, KDEN, KLAX, KPHX, KLAS, KSEA, KDFW, KMSY (T-series western/central). See `src/weather_markets/stations.py` for the series mapping.

## Key findings (don't re-test on similar data)
Market-blend wins; ECMWF-00Z config = no edge after fees (n=1002); rolling-EMOS window doesn't move annual CRPS; multibracket/Kelly/EMOS-features = null. Cross-platform arb is the next high-EV idea. *(Sources: memory `project_*_finding`; [../decisions/](../decisions/) precommits.)*

## Sources
- [src/weather_markets/emos.py](../../src/weather_markets/emos.py), [blend.py](../../src/weather_markets/blend.py), [evaluation.py](../../src/weather_markets/evaluation.py)
- [scripts/live_trade.py](../../scripts/live_trade.py) (`CITY_CONFIG`), [dashboard/sim_python.py](../../dashboard/sim_python.py)

## See also
[architecture.md](architecture.md) · [data-model.md](data-model.md) · [dashboard.md](dashboard.md) · [../decisions/](../decisions/) · [glossary.md](glossary.md)
