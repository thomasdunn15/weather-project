# Agent-advisor experiment (B3) — 2026-07-22

## Hypothesis (and the prior against it)

An agentic reasoning layer (B0 engine: matrix → specialists → debate →
master) that sees the calibrated EMOS/blend output, live market/orderbook
context, and the day's regime can improve the baseline trade decisions by
**bounded adjustment only** — keep / resize / skip / flip.

The prior is that it CANNOT: our own research says this market is efficient
(market-blend does 56–95% of the work; the intraday fair-value gate,
latency probe, foundation models, Kelly, multi-bracket, and EMOS-feature
studies were all null). This is a **measured experiment run to be killed on
evidence**, not an adoption. Expected outcome: null.

## What it is

- `src/weather_markets/reasoning/advisor.py` — imports the B0 engine
  unchanged; supplies a deterministic `ScopedRetriever` over as-of evidence
  chunks (EMOS/ensemble state, per-signal bid/ask/spread/book depth ≤ the
  decision-time cutoff, 45d settled record, spread regime, fee/sizing
  facts) and an embedded 4-point matrix (calibration / market / regime /
  execution).
- The master's proposal parses into a typed `AdvisorProposal`; the existing
  execution layer consumes the adjusted signal list. The advisor **never
  touches the exchange** (no Kalshi imports).
- Paper arms: `scripts/agent_advisor_log.py` logs paired rows to
  `paper_trades` — `"<paper_model_source> [AB-BASE]"` (exact live-config
  decisions) and `"… [AB-AGENT]"` (agent-adjusted, skips included) — per
  city, minutes after each live decision time.

## Guardrails

1. **Off by default.** Live path requires BOTH `CITY_CONFIG[city]["agent_advisor"]`
   (no city sets it) AND membership in `advisor.ADVISOR_LIVE_CITIES`
   (empty). With the flag absent, `live_trade.py` behavior is byte-for-byte
   baseline (hook not executed; `agent_multiplier` key never present).
2. **Fail-safe.** Any engine/parse/DB error inside `advise_signals_for_live`
   returns the baseline signals unchanged. In the paper logger an engine
   failure logs NO agent rows (day excluded from the A/B) and exits nonzero.
3. **Bounded actions.** keep/resize/skip/flip on baseline-fired signals
   only; multipliers clamped to [0, 1.5]; unknown tickers dropped. The
   agent cannot add trades, lower thresholds, or emit its own temperature
   forecast (EMOS won that; TS foundation models lost).
4. **Conventions respected.** NO cost = 100 − YES bid; strict as-of-decision-time
   data (price/book queries bounded by the CITY_CONFIG cutoff; recent-record
   queries bounded by `target_date < today`); settlements stay authoritative
   for live P&L (untouched).
5. **Kill switch.** `touch halt/AGENT` disables the paper logger; removing
   the cron lines or the city flag kills live use. Existing halt files /
   risk envelope are untouched and still run first.

## How it is judged

`uv run python scripts/analysis/agent_ab_report.py` — settles both arms
against observed highs (same `contract_resolved_yes` convention as the
dashboard), identical scoring for both arms (cross entry, taker fee, unit
sizing; agent rows scaled by their multiplier), **paired days only**.

- **Burn-in:** ≥ 30 settled paired days per city, all cities paper.
- **Beats baseline:** agent net P&L > baseline AND agent Sharpe > baseline,
  out-of-sample (the burn-in is forward data by construction).
- **Live:** only after that, only via manual operator override at tiny size
  (Dallas/Phoenix precedent), and the Sharpe > 2.5 deploy bar still applies.
- **Kill:** if after burn-in the agent does not beat baseline, `touch
  halt/AGENT`, remove the cron lines, and record the null here.

## Cost

~6 Claude calls per city per day (4 Haiku specialists, 1 Sonnet debate,
1 Opus master; 1 debate round cap). Cron lines ship **commented** in
`docs/crontab.txt` — run one city manually first, then uncomment +
`crontab docs/crontab.txt` to start the burn-in.
