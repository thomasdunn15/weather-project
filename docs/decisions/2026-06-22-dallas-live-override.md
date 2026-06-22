# Dallas (KDFW) goes LIVE — operator override of the deploy bar, 2026-06-22

**Decision:** Take **Dallas (KDFW)** LIVE on Kalshi under the KORD-style **UNION-25%**
rule, at **minimal size**, as a deliberate **OPERATOR OVERRIDE** of the standing
**"out-of-sample walk-forward Sharpe > 2.5"** deploy bar. Dallas does **not** clear that
bar on trustworthy evidence (see below). It goes live anyway — at the smallest risk
envelope in the universe — specifically to **gather honest, forward live data** under
real fills, which the paper watchlist cannot produce (fill rate, slippage, adverse
selection are only observable live).

This **supersedes** the Dallas **paper-watchlist** status set in
[2026-06-21-live-universe-and-watchlist.md](2026-06-21-live-universe-and-watchlist.md).
The live universe is now **Chicago + Miami + Dallas**.

> This is an override, not a clearance. The deploy bar is **not** relaxed for any other
> city. Dallas is live on the operator's explicit call to buy information, with the risk
> deliberately sized so a wrong call is cheap.

## The evidence this overrides

Source: per-city diagnostic `docs/research/md/2026-06-20-per-city-strategy-diagnostic.md`
and the watchlist tracker `scripts/analysis/dallas_watchlist.py`. Memories
`project_per_city_diagnostic_finding`, `feedback_deploy_bar`.

- **Production baseline (|edge| ≥ 0.10): LOSES** — **−$7.18, Sharpe −1.93**, and is
  **negative in BOTH history halves**. This is the honest full-sample read.
- **The only positive signal** is a single walk-forward fold (combined, T0.25, both,
  10–90¢): **+$3.17 on n=27**, +11.74¢/trade, **OOS Sharpe 4.52** — which clears the
  2.5 bar, but on a tiny, almost-certainly-noisy sample the diagnostic itself flags as a
  **"tuned OOS blip, not trustworthy."**
- **In-sample union (selection-biased, context only):** ~**Sharpe 3.60** — in-sample, so
  it overstates; not evidence of edge.
- **Forward OOS:** **n=1** (the graduation clock only started 2026-06-21). Nowhere near a
  decision-grade sample.
- **Live fills to date: 0.** No real-execution data exists for Dallas at all — which is
  the whole reason for going live small.

Net: the case for Dallas is an in-sample mirage plus an n=27 blip. Under the normal bar it
stays on paper. The operator is overriding to convert "paper-plausible" into "live-tested."

## The exact live config (scripts/live_trade.py `CITY_CONFIG["KDFW"]`)

```python
"KDFW": {
    "city_name": "Dallas",
    "models": ["gefs", "ifs"],
    "emos_model": "combined",
    "model_source":       "EMOS combined 00Z Dallas (rolling 45d)",
    "paper_model_source": "EMOS combined 00Z Dallas (rolling 45d)",
    "live_model_source_tag": "EMOS combined UNION raw25+blend10 00Z Dallas (rolling 45d) [LIVE]",
    "decision_hour": 16, "decision_minute": 0,   # 16:00 UTC
    "use_union": True, "use_blend": True,
    "edge_threshold": 0.25,                # raw leg (KORD parity)
    "blend_edge_threshold": 0.10,          # blend leg (KORD parity)
    "smart_cross_edge_threshold": 0.40,    # exec (KORD parity)
    "sizing_mode": "unit",
    "unit_contracts": 50,                  # MINIMAL — 10× smaller than KORD/KMIA (500)
    "amount_dollars": 50.0,                # unused (sizing_mode=unit)
    "max_contracts_per_trade": 50,
    "daily_loss_limit_dollars": 25.0,      # tightest in the universe
    "cumulative_kill_dollars": 75.0,       # tightest in the universe
    "max_open_contracts": 500,             # 10× smaller than KORD/KMIA (5000)
    "is_active": True,
}
```

Strategy = **UNION**: fire if `|raw_edge| ≥ 0.25` OR `|blend_edge| ≥ 0.10`; raw side wins
the tie-break (verified on live KORD: when both fire they agree). Model = EMOS "combined"
(GEFS+IFS) 00Z, rolling 45d — the **same** signal `scripts/paper_trade_log.py` already logs
daily as `"EMOS combined 00Z Dallas (rolling 45d)"` and that `dallas_watchlist.py` tracks.

**Aggregate risk envelope** updated for the new city:
`AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS` **300 → 325** (= Chicago $150 + Miami $150 + Dallas $25),
`AGGREGATE_CUMULATIVE_KILL_DOLLARS` **1000 → 1075** (= $500 + $500 + Dallas $75).

**Cron** (`docs/crontab.txt`): fires `0 16 * * *` (16:00 UTC) — after 00Z ingest (IFS 00Z
07 UTC + 13 UTC retry; GEFS/HRRR retries 13:46 & 14:30) and after KMIA's 15:30 decision, so
no live-trade collision. KDFW is in `weather_markets.stations.STATIONS`, so the existing
all-station 13:46 + 14:30 GEFS/IFS retries already refresh its 00Z forecasts (14:30 retry is
90 min pre-decision) — no dedicated Dallas pre-trade re-ingest needed. The only job on the
16:00 minute is the lightweight `check_pipeline_health.py`; the box already runs heavier
concurrent ingest crons at 13:46 & 14:30, so the overlap is within tolerance.

## Dashboard

Dallas now gets its **own** per-city card next to Chicago and Miami
(`dashboard/data_live.py` per-city loop emits it automatically from `CITY_CONFIG`). Dallas
(`KXHIGHTDAL` / station `KDFW`) is **excluded from the "Other Cities" rollup** in both the
realized-P&L SQL and the unrealized position sum, so it is not double-counted. The live grid
generalized from a 2-city special case to N cities (`app.js` → `g-${n}`; CSS `g-5` added;
asset cache-bust bumped `?v=6 → ?v=7`). The JS↔Python backtest sim parity slice was **not**
touched.

## Graduation / exit criteria

- **Promote to full size** only if the **forward** OOS holds **Sharpe > 2.5 on a
  meaningfully larger sample** — re-evaluate once forward **n ≥ ~30** settled trades (the
  n=27 blip is not enough), and ideally once baseline/both-halves turn positive. Track with:
  ```
  uv run python scripts/analysis/dallas_watchlist.py
  ```
  (the live FORWARD-OOS read is the verdict; the in-sample figures are context only).
- **Halt immediately** if the cumulative-kill (−$75) trips, or by hand at any time:
  ```
  touch halt/KDFW      # per-city halt
  touch halt/ALL       # aggregate halt (stops KORD + KMIA + KDFW)
  ```
- **Demote back to paper** if forward OOS confirms the diagnostic's "no robust edge" read
  (negative or sub-bar on n ≥ ~30).

## See also

[2026-06-21-live-universe-and-watchlist.md](2026-06-21-live-universe-and-watchlist.md) (superseded for Dallas) ·
[../context/strategy.md](../context/strategy.md) · [../context/operations.md](../context/operations.md) ·
[edge-test-protocol.md](edge-test-protocol.md) ·
`docs/research/md/2026-06-20-per-city-strategy-diagnostic.md` · memory `feedback_deploy_bar`
