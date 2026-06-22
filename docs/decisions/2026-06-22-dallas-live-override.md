# Dallas (KDFW) goes LIVE — operator override of the deploy bar, 2026-06-22

> **REVISION 2026-06-22 (same day, after the section below was written).** The operator
> made two further calls that change the risk profile materially:
> 1. **Scaled Dallas from the initial MINIMAL 50 contracts to FULL 500** (KORD/KMIA parity:
>    daily-loss $150, cumulative-kill $500, max-open 5000; aggregate → **$450 daily /
>    $1,500 cumulative**). The "wrong call is cheap" framing below **no longer holds** — this
>    is now a **full-size live bet on a config with no proven OOS edge**, taken on the
>    operator's explicit instruction. This also pre-empts the doc's own "promote to full size
>    only after forward OOS clears 2.5" gate — that gate was overridden too.
> 2. **Moved the decision time 16:02 → 17:32 UTC** per the time-of-day study
>    (`scripts/analysis/best_time_of_day.py --city KDFW`): the ~17:00–17:30 window had the
>    highest in-sample P&L (17:30 total +$512 / t=2.59 vs 16:00 +$101 / t=0.54 over n=101).
>    **Caveat:** that study assumes the order **fills** at the mid at every candidate time
>    (fill rate not modeled) and 17:30 is the best of 14 times tested — so the move is a
>    **forward experiment** to test whether the late-day effect is real or a fill mirage, not
>    a proven optimum. `:32` offset (not `:30`) avoids the on-the-minute monitor_fills/`*/5`
>    pile-up on the no-swap box.
>
> The original minimal-size rationale is preserved below for the record; the config block,
> aggregate, cron, and graduation sections have been updated to the current full-size values.

**Decision:** Take **Dallas (KDFW)** LIVE on Kalshi under the KORD-style **UNION-25%**
rule — initially at **minimal size** (see revision above for the same-day scale-up to full
size) — as a deliberate **OPERATOR OVERRIDE** of the standing
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

Source: the committed per-city numbers in
[2026-06-21-live-universe-and-watchlist.md](2026-06-21-live-universe-and-watchlist.md)
and the watchlist tracker `scripts/analysis/dallas_watchlist.py` (run it for the live read).
The fuller per-city diagnostic write-up
(`docs/research/md/2026-06-20-per-city-strategy-diagnostic.md`) is a **local, uncommitted**
research note (same numbers). Memories `project_per_city_diagnostic_finding`, `feedback_deploy_bar`.

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
    "decision_hour": 17, "decision_minute": 32,  # 17:32 UTC (time-of-day study; :32 offset = OOM hygiene)
    "use_union": True, "use_blend": True,
    "edge_threshold": 0.25,                # raw leg (KORD parity)
    "blend_edge_threshold": 0.10,          # blend leg (KORD parity)
    "smart_cross_edge_threshold": 0.40,    # exec (KORD parity)
    "sizing_mode": "unit",
    "unit_contracts": 500,                 # FULL size — KORD/KMIA parity (scaled from 50 same day)
    "amount_dollars": 50.0,                # unused (sizing_mode=unit)
    "max_contracts_per_trade": 500,
    "daily_loss_limit_dollars": 150.0,     # KORD/KMIA parity (scaled from $25)
    "cumulative_kill_dollars": 500.0,      # KORD/KMIA parity (scaled from $75)
    "max_open_contracts": 5000,            # KORD/KMIA parity (scaled from 500)
    "is_active": True,
}
```

(Original minimal-size config was unit 50 / daily $25 / cum $75 / max-open 500 / 16:02 UTC —
scaled to the above on 2026-06-22 per the revision note at the top.)

Strategy = **UNION**: fire if `|raw_edge| ≥ 0.25` OR `|blend_edge| ≥ 0.10`; raw side wins
the tie-break (verified on live KORD: when both fire they agree). Model = EMOS "combined"
(GEFS+IFS) 00Z, rolling 45d — the **same** signal `scripts/paper_trade_log.py` already logs
daily as `"EMOS combined 00Z Dallas (rolling 45d)"` and that `dallas_watchlist.py` tracks.

**Aggregate risk envelope** (after the full-size scale-up):
`AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS` **300 → 450** (= Chicago $150 + Miami $150 + Dallas $150),
`AGGREGATE_CUMULATIVE_KILL_DOLLARS` **1000 → 1500** (= $500 + $500 + Dallas $500).
(Initial minimal-size step set these to 325 / 1075; the same-day full-size scale-up took them to 450 / 1500.)

**Cron** (`docs/crontab.txt`): fires `32 17 * * *` (17:32 UTC; moved same-day from 16:02 per
the time-of-day study — see revision note). Still after 00Z ingest (IFS 00Z 07 UTC + 13 UTC
retry; GEFS/HRRR retries 13:46 & 14:30) and after KORD 14:46 / KMIA 15:30, so no live-trade
collision. KDFW is in `weather_markets.stations.STATIONS`, so the existing all-station 13:46 +
14:30 GEFS/IFS retries already refresh its 00Z forecasts (well before 17:32) — no dedicated
Dallas pre-trade re-ingest needed. Offset to **:32** (not :30) to clear the on-the-minute
pile-up with the `0,30` monitor_fills + `*/5` snapshots — cheap insurance on a no-swap box
where a prior concurrent-load spike OOM-killed Postgres.

## Dashboard

Dallas now gets its **own** per-city card next to Chicago and Miami
(`dashboard/data_live.py` per-city loop emits it automatically from `CITY_CONFIG`). Dallas
(`KXHIGHTDAL` / station `KDFW`) is **excluded from the "Other Cities" rollup** in both the
realized-P&L SQL and the unrealized position sum, so it is not double-counted. The live grid
generalized from a 2-city special case to N cities (`app.js` → `g-${n}`; CSS `g-5` added;
asset cache-bust bumped `?v=6 → ?v=7`). The JS↔Python backtest sim parity slice was **not**
touched.

## Graduation / exit criteria

The original plan was to *promote to full size only after* forward OOS cleared 2.5; the
same-day scale-up **pre-empted that gate**, so full size is now in place from the start and
the forward-OOS read instead governs whether Dallas **stays live at full size** or is pulled.

- **Validate forward** — re-evaluate once forward **n ≥ ~30** settled trades (the n=27 blip
  is not enough), ideally once baseline/both-halves turn positive. Two things to confirm,
  because of the full-size + 17:32 changes:
  1. **Edge:** does the live FORWARD-OOS Sharpe actually hold **> 2.5**? Track with:
     ```
     uv run python scripts/analysis/dallas_watchlist.py
     ```
     (live forward read is the verdict; in-sample figures are context only).
  2. **The 17:32 fill hypothesis:** do the late-day signals actually **fill** at the modeled
     prices, or was the time-of-day P&L a fill mirage? Compare realized live fills vs the
     in-sample assumption.
- **Halt immediately** if the cumulative-kill (now **−$500**) trips, or by hand at any time:
  ```
  touch halt/KDFW      # per-city halt
  touch halt/ALL       # aggregate halt (stops KORD + KMIA + KDFW)
  ```
- **Demote back to paper (or back to minimal size)** if forward OOS confirms the diagnostic's
  "no robust edge" read (negative or sub-bar on n ≥ ~30). At full size this matters more — a
  sub-bar Dallas now loses real money, not pennies.

## See also

[2026-06-21-live-universe-and-watchlist.md](2026-06-21-live-universe-and-watchlist.md) (superseded for Dallas) ·
[../context/strategy.md](../context/strategy.md) · [../context/operations.md](../context/operations.md) ·
[edge-test-protocol.md](edge-test-protocol.md) ·
`scripts/analysis/dallas_watchlist.py` (live forward-OOS read) ·
`docs/research/md/2026-06-20-per-city-strategy-diagnostic.md` (local, uncommitted) ·
memory `feedback_deploy_bar`
