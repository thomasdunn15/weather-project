# Glossary

> Domain terms a new agent will otherwise get wrong. Audience: agents. Last verified: 2026-06-19.

## Forecasting / stats
- **GEFS / IFS (ECMWF) / HRRR** — the three ensemble models. GEFS ~31 members, IFS ~50, HRRR 1 (single deterministic). 00Z = the 00:00 UTC model run used for trading.
- **combined / combined_hrrr** — ensemble blends: GEFS+IFS, vs GEFS+IFS+HRRR. Set per city via `emos_model`.
- **EMOS** (Ensemble Model Output Statistics) — affine calibration of the ensemble mean/spread to a Gaussian (`μ=a+b·mean`, `σ²=c+d·spread²`), rolling 45-day fit. Corrects ensemble under-dispersion.
- **CRPS** — Continuous Ranked Probability Score; the proper score used to judge the probabilistic forecast.
- **Brier score** — mean squared error of probability vs binary outcome; lower is better. Used to compare model vs blend.

## Markets / trading
- **Bracket / contract** — a Kalshi YES/NO market on whether the daily high falls in a range. `bracket_type`: `greater_than` (> strike_low), `less_than` (< strike_high), `between` (strike_low–strike_high inclusive). Resolution: `evaluation.contract_resolved_yes`.
- **Series ticker** — `KXHIGH<city>` (e.g. `KXHIGHCHI`); per-city in `stations.py`.
- **Ticker format** — `KXHIGH<city>-<DDMMMYY>-<bracket>`, e.g. `KXHIGHCHI-26JUN15-B71.5`.
- **T-series** — western/central cities use a `KXHIGHT…` series (TPHX/TLV/TSEA/TDAL/TNOLA). Their Kalshi `occurrence_datetime` is the **settle day (event+1 in UTC)** → contracts were once stored a day late; fixed by parsing the date from the **ticker** (`kalshi.ticker_event_date`).
- **edge** — `model_P − market_mid` (market_mid = (yes_bid+yes_ask)/200). Positive → buy YES, negative → buy NO.
- **Benter blend** — logistic blend of model and market probabilities (`logit P_blend = α + β_model·logit P_model + β_market·logit P_market`); named after Bill Benter's horse-racing model.
- **walk-forward** — fitting a model using only data strictly before each evaluated date (no lookahead); required for honest blend backtests.
- **Sizing modes** — unit (fixed contracts), amount (fixed $), kelly (Kelly-fraction of bankroll), scaling (fixed % of bankroll).
- **Execution modes** — market (cross spread, 100% fill), post_inside_spread (1¢ inside, ~75% fill), market_plus_1/2 (ask+1/2¢).
- **UNION strategy** — fire if raw_edge ≥ raw threshold OR blend_edge ≥ blend threshold (live KORD: 25% / 10%).
- **Kill switch / halt** — filesystem flags `halt/KORD|KMIA|ALL` that stop a city (or all) trading; plus daily-loss and cumulative-kill dollar limits in `CITY_CONFIG`.
- **paper vs live vs backtest city** — *paper*: signals logged to `paper_trades`, no money; *live*: real Kalshi orders (KORD, KMIA); *backtest-only*: has data but no live cron.

## Data / infra
- **hypertable** — a TimescaleDB time-partitioned table (forecasts, observations, prices, orderbook_snapshots). `pg_stat_user_tables` shows 0 rows on the parent — real rows are in chunks.
- **CF6** — the NWS Climate Report; the authoritative observed daily high (not raw ASOS) → the resolution source.
- **`*_fp` / `*_dollars`** — Kalshi API encodings: fixed-point contract counts / dollar strings. DB stores normalized integer **cents**.

## See also
[strategy.md](strategy.md) · [data-model.md](data-model.md) · [architecture.md](architecture.md)
