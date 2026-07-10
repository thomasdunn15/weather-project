# 2026-07-10 — Phoenix (KPHX) live, operator override (MINIMAL size)

**Decision:** Take Phoenix (KPHX, series `KXHIGHTPHX`) **live with real money at minimal 50-unit
size**, as an operator override of the OOS-Sharpe > 2.5 deploy bar. Fourth live city
(Chicago + Miami + Dallas + Phoenix). Seattle explicitly stays paper-only.

## Why (the honest evidence)
- Phoenix does **NOT** clear the deploy bar. The case for it: the paper series
  `EMOS combined 00Z Phoenix (rolling 45d)` shows a **concentrated, high-conviction edge** — raw
  |edge| ≥ 0.20 → **+11.7¢/contract net** of the 7% taker fee, and **both halves of the recent
  6-month window are positive** (H1 +4.8, H2 +2.6). The edge *concentrates* at high conviction
  (0.15 → +5.2¢, 0.20 → +11.7¢), the signature of a real signal (same shape as Miami/Dallas),
  not broad noise. Plausible mechanism: desert climate is low-variance / predictable.
- The case against (why it's an override, not a graduation): the sample is **young and thin** —
  Kalshi listed `KXHIGHTPHX` ~2026-02, so ~5 months, n ≈ 63 at 0.20. +11.7¢ over 63 trades could
  be a hot start. Book **depth is UNMEASURED** (no walk-book study). And the dry-run shows the
  signal firing on **extreme brackets with very large edges** (e.g. B113.5 YES +58%), which may be
  model over-confidence at the tails (WEATHER-5K: models weakest at extremes).

## Config (`scripts/live_trade.py` CITY_CONFIG["KPHX"])
- **Signal: RAW-only @ 0.20** (`use_union=False`, `use_blend=False`, `edge_threshold=0.20`).
  Blend is disabled because Phoenix blend paper is n=13 — too thin to fit/trust.
- Model: EMOS `combined` (GEFS+IFS) 00Z, rolling 45d — the exact signal paper_trade_log logs daily.
- Execution: `smart_cross_edge_threshold=0.40` → **post (maker)** unless |edge| ≥ 40%; conservative
  on an unmeasured book (don't walk depth).
- **Size: `unit_contracts=250`, `max_contracts_per_trade=250`** — operator-set 2026-07-10 (5× the 50-unit
  minimal I recommended). Book depth is **UNMEASURED**; at 250 the >40%-edge signals CROSS the book.
- Risk envelope: **daily-loss $125, cumulative-kill $375, max-open 2500** (scaled 5× with size — a single
  250-lot loss can be ~$60–190, so the $25/$75 minimal limits would have been incoherent at this size).
- Decision time: **14:52 UTC** — matches the paper-signal snapshot (~14:45) where the +11.7¢ edge was
  measured; offset from the 14:45 paper / 14:46 KORD pile-up. **TUNE via best_time_of_day** once live
  data accumulates (no Phoenix time-of-day study exists yet).
- Aggregate limits bumped: daily $450 → **$575**, cumulative $1,500 → **$1,875** (+$125 / +$375).

## Verification (2026-07-10)
- Dry-run (`--city KPHX`, no `--live`): loads clean, RAW-ONLY mode confirmed, 3 signals at 250-unit =
  ~$277 total notional / max-loss (B109.5 NO $192.50 POSTS as maker; B111.5 NO $67.50 posts; B113.5 YES
  $17.50 crosses — the crossing one is the cheapest). Preflight passes.
- `uv run pytest` → 121 passed, parity intact.

## Graduation / de-risk criteria
- **Scale beyond 250 ONLY after** (a) the forward live edge holds for ~30+ days AND (b) a walk-book
  capacity study measures Phoenix book depth (mirror `walk_book_capacity.py --station KPHX`).
- Re-check calibration at the extreme brackets — if the large-edge tail bets systematically lose,
  tighten the threshold or halt.
- Kill switch: `touch halt/KPHX` (per-city) or the aggregate kill; the $25 daily / $75 cumulative
  limits auto-halt.

## Status
Config committed; cron line staged in `docs/crontab.txt` but **NOT installed** pending operator
go-live. First live fire (once installed): 2026-07-11 14:52 UTC.
