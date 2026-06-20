# Strategy backlog — candidate ideas to validate before live

Ideas land here to be validated (backtest/paper) before going into live code — the config freeze was lifted 2026-06-20. Each entry:
date, idea, evidence that prompted it. Nothing here is a commitment.

## Open

- **2026-06-20 · Add NBM + ECMWF-AIFS as forecast sources (validate skill-first).**
  Forecast-model-selection study (`docs/research/md/2026-06-20-forecast-model-selection.md`):
  current GEFS+IFS+HRRR is defensible but not optimal. After EMOS, IFS>GEFS (CRPS 1.327 vs
  1.472), combined beats best single (1.268), HRRR adds ~2.4%; GEFS↔IFS error r=0.61 so a NEW
  model only helps if decorrelated. Worst stations are coastal/terrain (KLAS 6.0, KSFO 5.0,
  KPHX 4.4, KLAX 4.2°F MAE) — a resolution problem. Ranked adds: (1) **NBM** (free, Herbie-native,
  2.5km calibrated daily-Tmax) as an EMOS covariate for hard stations; (2) **ECMWF AIFS/AIFS-ENS**
  (free CC-BY-4.0, same Open-Data channel as IFS, decorrelated AI member); (3) **GEM/GDPS** (best
  truly-independent core, Herbie beta). Skip GFS-det/HRES (correlated), RAP (HRRR subsumes), paid
  APIs (deterministic, no ensemble, no cheap history). GenCast/GraphCast = non-commercial licence.
  Adopt **Open-Meteo Ensemble + Historical-Forecast API** as the unified ingest/backtest archive.
  Validation bar: lower per-station CRPS AND hold/improve bracket-edge Brier on an edge-relevant
  city, on a matched sample, before any P&L claim. CAVEAT: skill≠edge — market already prices most
  forecast info; expect modest edge impact. Do NOT act during freeze.
- **2026-06-20 · Widen HRRR beyond Chicago.** Same study: HRRR has the lowest *raw* day-ahead MAE
  (2.57°F) of any single model yet is wired into one city. Per-station combined+HRRR independently
  replicates "helps KMDW/KDFW, hurts KNYC/KLAX" — so re-evaluate HRRR inclusion per-city at re-eval
  (likely add for KDFW; keep off NYC/LAX). Folds into the per-city param decision.
- **2026-06-20 · Narrow live universe to demonstrated-edge cities + adopt per-city params.**
  Per-city diagnostic (`docs/research/md/2026-06-20-per-city-strategy-diagnostic.md`):
  the 11-city baseline portfolio LOSES net of fees (−$149, Sharpe −2.62); only
  Chicago, Miami, Seattle are profitable at baseline AND in both history halves AND
  out-of-sample (walk-forward). Trading just those 3 = +$46.51, Sharpe 2.37, P/DD 3.50.
  Proposed params: Chicago = combined+HRRR, |edge|≥0.25, both, all-price; Miami = GEFS,
  |edge|≥0.15, both, 10–90¢; Seattle = combined, |edge|≥0.15, both, 10–90¢ (watchlist).
  Do NOT per-city-tune the no-edge cities (NY/DEN/AUS/NOLA/LV/PHX) — in-sample optima
  are overfit (~360 configs/city). Resolve Chicago paper(+$21)-vs-live(−$124, n=17 fills)
  contradiction before scaling Chicago. (Chicago+Miami are already the live cities → corroborates.)
- **2026-06-12 · KMDW-trained model for Chicago.** KXHIGHCHI settles on
  Midway's climo report; model is trained end-to-end on KORD. 1-2°F
  divergence on lake-breeze days. KMDW GEFS backfill in progress; fit EMOS +
  blend on KMDW during the freeze, deploy only at re-eval if validation
  passes. HIGHEST PRIORITY backlog item.
- **2026-06-12 · Walk-the-book sizing.** Orderbook depth snapshots
  accumulating since 2026-06-10. By ~July 1 run the real-depth walk-book
  backtest: how many contracts can each signal absorb before marginal edge
  goes negative? Answer feeds any sizing-up decision.
- **2026-06-12 · IBKR ForecastEx as second venue.** Genuinely separate
  order book (unlike Robinhood, which routes to Kalshi's book). Same KORD
  model applies but contracts are T+1/T+2 (no same-day) → expect ~0.4-0.6×
  same-day Sharpe. Build only if walk-book shows Kalshi depth caps us.
- **2026-06-12 · Secondary paper cron at ~17:00 UTC.** Time-of-day analysis
  (scripts/analysis/best_time_of_day.py) showed apparent late-day P&L
  improvement for KORD, but it's probably fill-rate artifact. A 17:00 UTC
  paper-only cron would measure it honestly without touching live trades.
- **2026-06-12 · HRRR weighting / model-disagreement penalty.** On
  2026-06-10, HRRR alone nailed the high (90.5°F) while GEFS/IFS ran cold;
  flat member-weighting diluted it 1/81. Equal-model weighting or a
  disagreement-widens-sigma term might help. Needs a real backtest, not a
  one-day anecdote.
- **2026-06-09 · Cross-platform arb (Kalshi vs Polymarket US).** Needs KMDW
  price history from the forward snapshots; revisit once a few weeks have
  accumulated.
- **2026-06-19 · Evaluate additional NWP models (NAM, RAP, GFS, …).** The
  GEFS+ECMWF(+HRRR) ensemble was an initial recommendation, not an exhaustive
  model-selection study (user, 2026-06-19). Test whether adding short-range /
  regional models improves daily-high forecast accuracy and EMOS calibration —
  backtest CRPS/Brier before any live use.
- **2026-06-19 · Add Polymarket as a trading venue (not just arb).** User wants
  to trade Polymarket in the future, not only run the cross-platform-arb study.
  Blockers to solve first: Polymarket Chicago = KMDW ≠ KORD (non-fungible) and
  no historical-price API (only forward snapshots accumulating).
- **2026-06-20 · IBKR ForecastEx ingest pilot (HIGH-value venue candidate).**
  Per venue-survey (docs/research/md/2026-06-20-polymarket-ibkr-venue-expansion).
  ForecastEx = CFTC DCM/DCO, ~$0.01 flat/contract (≈ half Kalshi's ~2¢ mid-range,
  directly attacks the fee = binding-constraint finding), professional API, and
  airport-station match with Kalshi on 5/6 cities (all but Chicago=Midway). Build
  read-only quote ingester (`platform='forecastex'`), then measure: (a) does the
  lower fee + blend-vs-ForecastEx-market flip any config to break-even; (b) live
  Kalshi↔ForecastEx basis/spread. NOTE: lower fee narrows loss but does NOT
  create edge — combined-00Z only moves −1.88¢→−0.83¢ (gross ≈ −0.33¢).
- **2026-06-20 · Confirm primary polymarket.us weather fee + deepen data.** Before
  any Polymarket trading: read the real US-regulated weather fee from a primary
  source (secondary reports say 0.30% taker; intl help-center says ~1.25% wx —
  unresolved), start orderbook-depth snapshots (currently 0), and accumulate
  ≥60–90 days. Crypto-rail (pUSD/Polygon) friction is a standing con vs a
  brokerage venue.
- **2026-06-20 · Fungible-pair arb scan (opportunistic, not a strategy).** Once
  ForecastEx is ingested, extend cross_platform_arb.py to the truly fungible
  pairs (NYC/LA/Miami three-way; Chicago-Midway FEx↔Poly). Flag only gaps >
  combined fees+slippage; strike alignment unproven, current scans ~0 gap.
- **2026-06-20 · CME weather futures — rejected for this strategy.** Monthly/
  seasonal HDD/CDD/CAT index ($20×index), not daily-high binaries. Instrument +
  horizon mismatch, large notional vs $3,050 capital. Revisit only on a pivot to
  monthly temperature-risk products.
- **2026-06-20 · Frontend redesign for strategy decisions (no config change).**
  Per `docs/research/md/2026-06-20-frontend-strategy-dashboard-optimization.md`:
  re-point the dashboard at decision metrics (net-edge-after-fees + risk-headroom +
  expectancy hero, replacing the misleading win-rate headline — live book is +$100.04
  net but wins only 6/22 by count), and add two read-only analytics panels: (1) a
  calibration/reliability diagram of model_P vs blend_P vs market_P with consistency
  bars + Brier (data exists in paper_trades⋈observations; retires the hard-coded
  brier=0.20), (2) a paper-vs-live divergence + fill-quality monitor for KORD/KMIA.
  Trim dead Polymarket toggle + hard-coded crons[]="ok" ticks; demote the frozen
  param-sweep behind progressive disclosure; fix over-aggressive reduced-motion. New
  analytics endpoint must use walk-forward (no look-ahead). Frontend-only; safe to
  build during freeze, but sequence after the higher-EV data items above.

## Evaluated and rejected

- **2026-06-10 · Anti-stacking (max signals/day) + edge-cap sizing.**
  Shipped on one bad day's evidence, reverted same day: both reduce Sharpe
  and total return across the full sample. Remain available as dashboard
  what-if toggles.
- **2026-06-09 · Multi-bracket, Kelly, EMOS feature additions.** All null
  results vs single-bracket + blend baseline (see memory/project notes).
  Don't re-test on similar data.

## Backtest tab v4 revamp — shipped + deferred (2026-06-20)

Display-only revamp (branch `redesign/backtest-revamp`, `?v=4`). Shipped: retired
the US map (redundant with the city select) → inline best-Sharpe stat; dropped the
Polymarket toggle; tucked min-entry / max-signals / edge-cap / depth-cap behind an
Advanced disclosure; net-edge / expectancy / fill-rate chips + ledger strip;
equity-curve drawdown shading; a compact model-calibration panel; an **independent
sim-strategy control** (curve + chips only, separate from the ladder's signal
strategy); and a first-open entrance-animation fix. Deferred (not built):

- **Per-city best-Sharpe in the city selector.** The old background `sweepBest()`
  (one fetch per city) was removed with the map to spare the memory-constrained
  box; only the selected city's Sharpe is computed now. A lazy, on-demand sweep
  could annotate each `<option>` if wanted.
- **Calibrate the blended/effective probability**, not just raw `modelP`. Current
  calibration panel uses the raw model only; a blend-aware reliability view (and
  Brier) is the bigger analytics item already noted in the frontend plan above.
- **Paper-vs-live divergence + fill-quality monitor** — still open from the
  frontend-optimization plan; out of scope for this display pass.
