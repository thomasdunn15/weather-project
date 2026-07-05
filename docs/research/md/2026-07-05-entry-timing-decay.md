# Entry-timing decay study — is there a better intraday entry time?

**Date:** 2026-07-05 · **Branch:** `research/entry-timing-decay` (unmerged) ·
**Script:** `scripts/analysis/entry_timing_decay.py` · **Read-only** (no cron/config changed).

## Question
Current live decision times: **KORD 14:46, KMIA 15:30, KDFW 17:32 UTC.** Is there a
better intraday entry time, given (a) how the model−market edge decays through the
morning vs (b) the fill/liquidity cost of entering earlier? Core hypothesis (from the
Miami walk-book 55¢→61¢ repricing): the market reprices *toward* our forecast before
our decision time, so we may be entering **late** and forfeiting edge.

## Method
- **Universe:** decision-time-fired `paper_trades` per city (KORD combined_hrrr n=950,
  KMIA combined n=575, KDFW combined n=394), joined to strikes + observed high.
- **Grid:** absolute UTC hour marks + the exact decision time (T0). `prices` top-of-book
  is **hourly (top-of-hour) across the full history** and only went 5-min on 2026-06-04,
  so hour marks are the only apples-to-apples long-history series; T0 uses the real
  decision-time bid/ask/mid stored in `paper_trades`.
- **A) decay:** median |raw edge| and |blend edge| per candidate. **B) fill:** maker-flow
  fill inference (miami_fill_rate method, always posting at own touch) + near-money depth,
  on the 26-day `orderbook_snapshots` window, fill window entry→20:00 UTC (production
  cancel). **C1) gross P&L/Sharpe** (long history, 100% fill, production smart-exec entry
  price). **C2) fill-adjusted P&L/Sharpe** (26-day, directional). Sharpe = per-day P&L,
  annualized by realized trade frequency (mirrors `dallas_watchlist.py`; deploy bar 2.5).

## Validity: the model_p-staleness verdict (the main threat)
`model_prob_yes` is a **single fixed value** per (target_date, ticker): `forecast_init_time`
hour = 0 for all 1919 rows and `COUNT(DISTINCT model_prob_yes) == row count`. The 00Z
ensemble is fully ingested by ~07:00 UTC and the EMOS fit uses only prior-day settled data.
So for **any** entry ≥ ~07:30 UTC (our earliest grid point is 11:00), the signal we'd use
earlier is **identical** to the one at the current decision time. Earlier-entry edge is
therefore **real and computable, not hindsight** — the entire intraday edge change is
market-driven. This validity concern is moot in practice because the data shows **no
earlier edge to capture** (below).

## Results (median edge; * = current decision time)

**A) Edge decay — the market does NOT reprice toward us before entry.**

| city | T−3h | T−1.5h | ~T−0.5h | **DEC*** | ~T+0.5h | ~T+1.5h |
|---|---|---|---|---|---|---|
| KORD med\|raw\| | 17.2% | 17.1% | 18.8% | **18.8%** | 19.3% | 20.3% |
| KMIA med\|raw\| | 15.4% | 15.4% | 17.1% | **16.6%** | 17.9% | 20.4% |
| KMIA med\|blend\| | 7.9% | 8.6% | 8.7% | **9.4%** | 7.1% | 5.8% |
| KDFW med\|raw\| | 16.1% | 18.1% | 19.4% | **19.5%** | 20.2% | 20.2% |

Edge is **flat-to-rising into the decision**, not shrinking. KMIA's *blend* edge (its
live trigger) **peaks at DEC** (9.4%). The walk-book 55→61 anecdote does not generalize
to a systematic pre-entry repricing we could harvest by moving earlier.

**C1) Gross P&L/Sharpe by entry time (long history, 100% fill):**

| entry | KORD Sharpe | KMIA Sharpe | KDFW Sharpe |
|---|---|---|---|
| ~T−3h | 2.60 | 1.04 | 1.98 |
| ~T−1.5h | 2.62–2.67 | 0.96 | 1.63 |
| ~T−0.5h | 2.66 | 1.22 | 1.23 |
| **DEC*** | **2.61** | **2.10** | **4.52** |
| ~T+0.5h | 3.27 | 0.56 | 1.02 |
| ~T+1.5h | 3.85 | 1.76 | 1.12 |

- **KMIA:** peaks at DEC (2.10, tied with the −90m point); earlier and later both worse.
- **KDFW:** a **sharp peak exactly at 17:00–17:32** (4.52), collapsing on both sides — the
  current 17:32 is essentially optimally placed (the "time-of-day study" that set it holds up).
- **KORD:** flat through the morning, then gross Sharpe/P&L keep **rising into the early
  afternoon** (15:00→3.27, 16:00→3.85 vs DEC 2.61). The only city hinting a **later** move
  helps — never earlier.

**B) Maker fill vs entry time (26-day):** earlier maker posts fill *better* (longer window
to the 20:00 cancel): KORD median 100% at 11:00–14:00 → 61% at DEC → 56% at 16:00; KMIA
94%→23%; KDFW 32%→16%. So the "thinner book earlier" penalty does **not** exist for maker
orders. Anchor cross-check (→20:00 vs the forward-test's →EOD): KORD DEC 61% (mean 54%) vs
~90%; KMIA DEC 23% median / **46% mean** vs ~52%. Directionally consistent; the →20:00 cut
removes Miami's 20–24 UTC surge so it reads lower (expected). KMIA/KDFW cross by design, so
instantaneous opposite-side depth (roughly flat through the morning) governs their fills.

**C2) Fill-adjusted (26-day):** too small/noisy to drive a verdict (24 trades; the recent
26-day slice is a poor KORD/KDFW stretch, so DEC reads negative there while the 950/394-row
gross C1 is strongly positive). Presented as directional only.

## Verdicts
- **KORD (Chicago) — KEEP 14:46.** Edge does not decay before entry; if anything a *later*
  entry (~15:00–15:30) shows a gross-edge lift (Sharpe 2.61→3.27), but maker fills degrade
  after ~15:00 and the 26-day fill-adjusted slice is inconclusive. **Do not move without a
  30-day paper forward-test at ~15:15.** Moving earlier is clearly worse. This is the only
  city with any move signal, and it points **later, not earlier.**
- **KMIA (Miami) — KEEP 15:30.** Blend edge and gross P&L both peak at DEC; earlier and
  later are worse. Hypothesis rejected.
- **KDFW (Dallas) — KEEP 17:32.** Gross Sharpe peaks sharply at 17:00–17:32 and collapses
  on both sides; fills also worsen after DEC. Current time is optimally placed.

**Bottom line:** the "enter earlier" hypothesis is **rejected** for all three cities. The
market does not systematically reprice toward our fixed 00Z forecast before our decision
times; each city's current time sits at or before its edge peak. No cron change recommended;
the single item worth a forward-test is a *modestly later* KORD entry.

## Caveats
- Universe = decision-fired signals only (paper_trades logs nothing else), so we measure
  "is another time better for the trades we take," not brackets that would fire only earlier.
- Long-history grid is hourly (top-of-hour) + exact T0; sub-hour structure between marks is
  unresolved pre-2026-06-04.
- Fill inference is depth-depletion (no trade tape), 26-day window, directional; anchors
  reproduced approximately (→20:00 vs →EOD gap).
- C1 is gross (100% fill). KORD's later-entry lift is gross-only and needs a fill-aware
  forward test before any move.

## Verification
`uv run pytest` → **121 passed** (parity 8/8). (A benign at-exit SIGSEGV fires during
interpreter teardown — herbie/scipy/psycopg C-extension cleanup — *after* the 121-passed
line; pre-existing/environmental, unrelated to this branch's standalone script.) Parity
files, `live_trade.py`, `monitor_fills.py` untouched (`git status` = one new file).
