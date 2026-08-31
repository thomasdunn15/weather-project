# Prompt: live signals terminal

Paste everything below the line into a fresh Claude Code session started in
`/home/tdunn/weather-project`.

---

Build me a **live-updating terminal dashboard** that shows today's tradeable
signals across all three venues — Kalshi, Polymarket US, and ForecastEx — in one
screen, and keeps itself current until end of day.

## What it must show

One row per candidate contract, grouped by venue, with at least:

`venue · city · contract · side · model_p · market_p · edge · threshold · entry¢ · status`

`status` is the important column. Each row is in exactly one state:

- **LIVE** — currently clears its venue/city edge threshold, no order placed
- **PLACED** — an order exists for it today (see "Pinning" below)
- **FILLED** — the order filled (show fill count and average price)

## The live behaviour I want

Re-evaluate on a loop (default every 60s, `--interval` to change):

- A signal that **drops below** its edge threshold **disappears** from the list.
- A signal that **rises above** threshold **appears**.
- **Once an order has been placed for a contract, it is PINNED** — it stays on
  the list for the rest of the day no matter what the edge does afterwards, and
  its row switches to PLACED/FILLED. This is the whole point: I want to see what
  we actually did alongside what is currently actionable.

Show a header with the clock, next decision time per venue, and a footer noting
when each venue's data was last refreshed. Make stale data obvious — if a quote
is older than ~10 minutes, mark it, don't silently show it as current.

## Hard requirements

**READ-ONLY. It must never place, cancel, or modify an order.** No calls to
`create_order`, `place_order`, `submit_order`, `reply`, or any DELETE on an order
endpoint. This is a monitor. Assume I will run it unattended.

**Python via `uv run`** — never `.venv/bin/python`.

**This box has 7.6GB RAM and no swap**, and a prod Postgres has been OOM-killed
before by stacked dev servers. Keep it to one process, poll politely, do not
spawn a web server.

## Where the data lives — and the traps

DB is `psql -d weather` (local peer auth, no password). Read
`docs/context/data-model.md` first.

**Which contracts are in scope.** Only the cities actually being traded per
venue. Kalshi live is **KMIA only** right now (one cron, `--city KMIA`), and
`data/halt/` holds halt markers (KDFW, KORD, KPHX) that must exclude a city.
Polymarket US runs 5 stations, ForecastEx runs KMIA and KDFW. Read the configs,
do not hardcode a guess: `scripts/live_trade.py` (CITY_CONFIG),
`scripts/live_trade_polymarket.py`, `scripts/live_trade_forecastex.py`.

**Polymarket bracket semantics — corrected 2026-08-23, do not regress.**
`gte92lt93` means **"92 to 93" inclusive**, NOT "92 only". The slug is
misleading. Use `contracts.strike_low` / `strike_high`, which are correct, via
`evaluation.kalshi_equivalent_bracket`. Getting this wrong halves `model_p` and
inverts side selection — it put us on both sides of the same Miami bracket. See
`docs/decisions/2026-08-23-pm-bracket-semantics-merge.md`.

**Polymarket prices are quoted on the YES leg** regardless of which side you are
buying. The price paid for NO is `1 - yes_price`. Reading the same-named book
side surfaces junk 1¢ levels as the touch.

**ForecastEx settles on Weather Underground, not the NWS CLI** in our
`observations` table — the gap runs to -2.4°F on some stations. It applies a
rolling CLI→WU offset; reuse the existing logic in
`src/weather_markets/forecastex.py` rather than reimplementing it, and never
score FX against `observations`.

**Kalshi `B92.5` covers strikes 92–93 inclusive**, both ends. `greater_than` is
strictly above; `less_than` strictly below.

**Edge threshold is per venue AND per city**, and some cities use a blend or a
union rule rather than raw edge. Take these from the live configs, not from a
constant you invent.

## Pinning: where "placed" comes from

- Kalshi → `live_trades` (`fill_status`, `fill_count`)
- Polymarket → `pm_live_trades` (`fill_count`, `fill_avg_price_cents`)
- ForecastEx → `fx_live_trades` (`ibkr_order_id`, `fill_count`)

A row is PLACED if a row exists for today's `target_date` and that contract.
Note `fill_count` is written by the reconcilers (13:05/20:05 for PM, 05:30/20:10
for FX), so it can legitimately read 0 for hours after a real fill — do not
render an unreconciled order as a no-fill. Say "unreconciled" instead.

## Deliverables

1. `scripts/live_signals_terminal.py` — the tool, with `--interval`,
   `--once` (single render, for piping/cron), and `--venue` to filter.
2. Tests: bracket→probability, threshold add/remove transitions, and that a
   PLACED row survives its edge dropping below threshold.
3. A short docstring at the top explaining every non-obvious decision.

## Working style

Read the relevant code before writing — `evaluation.py`, `blend.py`, the three
live traders, and `docs/context/strategy.md`. Prefer reusing existing functions
over reimplementing signal logic; if the terminal computes edge differently from
the live trader, the terminal is wrong and it is worse than useless.

Run `uv run pytest` before you tell me it's done. One test,
`test_kord_dry_run_exits_cleanly`, fails already for unrelated reasons (a
`data/halt/KORD` marker exists) — that one is expected.

When you are finished, summarise what you built and what you deliberately left
out. I am going to have a second Claude review it, and I want you to apply that
review's suggested changes.
