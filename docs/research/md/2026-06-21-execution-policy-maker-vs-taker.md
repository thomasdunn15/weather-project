# Order-Entry Execution Policy: Resolving the Maker-vs-Taker Dilemma

*2026-06-21 · status: draft*

## Question

Given a fired signal `(ticker, side, model edge E, current book)`, what **order-entry
policy** maximizes *realized after-fee* edge and out-of-sample Sharpe? This is the
maker-vs-taker dilemma: a marketable order fills but walks the book and inflates the
average price; a passive limit gets a better price but may not fill. The goal is a
concrete, implementable **execution playbook** (a decision rule with per-city
parameters), validated walk-forward — for the live/watchlist cities KORD (primary),
KMIA, and Dallas/KDFW. Read-only research; no live or config changes.

## TL;DR / Verdict

**Confidence: medium on the price/structure conclusions, low on the Sharpe ranking.**

1. **The dilemma is smaller than it looks at production scale, because the bot already
   does the right thing: it posts resting GTC *limits*, never a marketable sweep.** A
   full-size (500-lot) sweep against the real book would walk ~25 levels and pay
   **+2.7¢ to +7.2¢ over the ask** — enough to erase the entire (thin, uncertain) edge.
   The single most important rule is therefore **never send a marketable order for full
   size**; always rest a limit. The current code (`place_limit_order`) already complies.
2. **Whether to rest at the ask (taker) or 1¢ inside (maker) is decided by the spread,
   which is city-specific.** KORD spreads are tight (median **1¢**) → on **62%** of KORD
   signals there is *no maker room*, so crossing at the ask is correct. KMIA (median 3¢)
   and Dallas (median 2¢) have real spread to capture.
3. **Where a spread exists, posting inside is the better trade**: it captures ~1–3¢ of
   spread, and — critically — **shows no adverse selection** (on filled maker orders,
   realized edge ≥ the taker edge in all three cities). The only cost of the maker is a
   **~50–70% fill rate within the actionable cron window** (matching the live KMIA 52%),
   versus ~90% for crossing.
4. **Kalshi charges makers ~¼ the fee of takers** (and historically zero). The project's
   `kalshi_fee_cents` charges a flat 7% to *both*, so production backtests and this sim
   **understate the maker advantage by ~¾ of the fee** (~1¢/contract at mid-price).
5. **The deploy-bar question cannot be honestly answered on this data.** With ~12 days
   of book and 3–4 out-of-sample test days, the walk-forward OOS Sharpe is dominated by
   noise and fill-volume artifacts, and bootstrap CIs on per-contract edge span zero for
   every policy. **No policy reliably clears 2.5 OOS here, and none can be shown to** —
   the honest read is *defer the Sharpe ranking; act on the mechanical price evidence.*

**Bottom line:** the deployed `EXECUTION_MODE="smart"` (edge-aware cross-vs-post) with
per-city thresholds is well-aligned with the evidence. The actionable improvements are
(a) a maker/taker-aware fee model, (b) a depth/size cap for Dallas, and (c) a time-based
re-quote. Execution recovers a few cents of an already-thin edge; it does not create edge.

## Methods & Data

**All numbers net of Kalshi fees; read-only `SELECT`s + a stdlib simulation
(`/tmp/exec_sim.py`); no DB writes, no `--live`.** Worktree `research/exec-policy-maker-taker`.

Internal sources:

| Source | Volume / window | Use |
|---|---|---|
| `live_trades` | 40 orders, 2026-06-04→06-21 | **Ground-truth** fill rates & realized slippage (the live forward test) |
| `orderbook_snapshots` | 14.7M rows, 2026-06-10→06-21 (~12 d), 888 tickers | L2 depth ladder → simulate fills at realistic prices |
| `paper_trades` | signal universe; 89 dedup signals in the book window | The fired-signal set (edge, side, quote, entry price) |
| `contracts` / `observations` | strikes + observed daily high | Settlement → win/loss for realized PnL |

Code paths read (faithfully re-implemented in the sim): `dashboard/sim_python.py`
(fee fn + execution modes), `scripts/live_trade.py` (`place_with_guaranteed_fill`,
`EXECUTION_MODE="smart"`, `SMART_CROSS_EDGE_THRESHOLD`, `CITY_CONFIG`),
`src/weather_markets/kalshi_api.py` (V2 `place_limit_order`: `post_only`,
`time_in_force=GTC`, price levers, `POST /portfolio/events/orders`),
`src/weather_markets/evaluation.py::contract_resolved_yes` (settlement convention),
`scripts/analysis/dallas_watchlist.py` (PnL/Sharpe convention),
`scripts/analysis/best_time_of_day.py`.

**Book reconstruction.** For each signal I take the latest orderbook snapshot at/before
the decision time (`coalesce(market_snapshot_at, logged_at)`). Kalshi books are bids-only;
the ask ladder for BUY_YES is synthesized from NO bids (`ask = 100 − no_bid`), per the
production convention (`cross = 100 − best opposite bid`). The maker fill model uses the
**post-decision** evolution: a passive buy at price `L` fills if the opposite-side bid
ever reaches `≥ 100 − L` within a horizon (+30m / +60m / by-close). Settlement uses the
integer daily high with the canonical bracket rule (`between` inclusive, `greater_than`
strict `>low`, `less_than` strict `<high`).

**Policies simulated** at the production size of **500 contracts**: `market` (instant
sweep), `limit_ask` (rest at the ask = `cross_at_ask`), `post1`/`post2` (maker 1¢/2¢
inside), `premium1`/`premium2` (cross at ask+k), `smart` (cross if `|E|≥X` else post),
`ladder` (50% take / 50% maker), `chase` (post, then cross at +60m), `depthcap` (buy only
marginally +EV depth). Validation: walk-forward (params on first 70% of days, measured on
last 30%) and bootstrap 95% CIs.

External: optimal-execution / maker-taker microstructure literature and the current
Kalshi fee schedule (cited below).

## Internal Findings

### 1. Live ground truth — the actual per-city fill rate

The open "compute fill rate when asked" item, from the live `cross_at_ask`/`smart`
forward test (Wilson 95% CI on order fill):

| City (series) | Orders | Contract fill % | Order fill % (95% CI) | Unfilled orders |
|---|---|---|---|---|
| **KORD** `KXHIGHCHI` | 25 | **90.0%** | 80% [61, 91] | 2 |
| **KMIA** `KXHIGHMIA` | 9 | **52.2%** | 56% [27, 81] | 4 |
| **Dallas** `KXHIGHTDAL` | 0 | — | — | — |

KORD fills ~90% of contracts; KMIA only ~52% (its cancels cluster *before* 2026-06-17,
when the smart threshold was 0.40 → KMIA never crossed → chronic missed fills; lowering
it to 0.10 fixed this). **Dallas has zero live fills** — its book-sim below is entirely
unvalidated by live data.

### 2. Books are thin at the touch — so a full-size sweep is destructive

| City | n | qty@ask (median) | qty@ask (p25) | ≥500 @ ask | spread (median) |
|---|---|---|---|---|---|
| KORD | 34 | 19 | 8 | **9%** | **1.0¢** |
| KMIA | 12 | 16 | 8 | 8% | 3.0¢ |
| Dallas | 43 | 39 | 6 | 5% | 2.0¢ |

Only ~5–9% of signals have the full 500 lot resting at the best ask. **A marketable
500-lot order walks the book.** Yet live `cross_at_ask` fills ~90% — because a *resting
GTC limit* captures arriving flow over minutes that a single snapshot can't show. The
lesson: a resting limit ≠ an instant sweep. The snapshot sim therefore gives a robust
read on **price** (mechanical), an upper-bound on **sweep slippage**, and only a
lower-bound on resting fill quantity (use the live numbers in §1 for that).

### 3. The price/edge frontier (size 500, net fees) — the well-powered result

`slip_vs_ask` is the deterministic, well-powered signal (the others are confounded by
fill quantity and a tiny settled sample — see Limitations). Representative rows:

**KORD/Chicago** (n=34)

| policy | ctr fill % | avg entry ¢ | slip vs ask ¢ | edge/ctr ¢ |
|---|---|---|---|---|
| market (sweep) | 100% | 32.5 | **+4.31** | −6.70 |
| limit_ask (cross) | 17%* | 28.1 | 0.00 | −2.87 |
| post1 (maker) | 53%* | 27.5 | **−0.65** | −2.13 |
| smart | 62%* | 27.7 | −0.42 | −2.39 |

**KMIA/Miami** (n=12)

| policy | ctr fill % | avg entry ¢ | slip vs ask ¢ | edge/ctr ¢ |
|---|---|---|---|---|
| market (sweep) | 100% | 49.6 | +2.69 | +6.38 |
| limit_ask (cross) | 22%* | 46.9 | 0.00 | +9.18 |
| post1 (maker) | 84%* | 45.4 | **−1.50** | **+10.64** |
| chase | 62%* | 46.1 | −0.83 | +9.91 |

**Dallas/KDFW** (n=43)

| policy | ctr fill % | avg entry ¢ | slip vs ask ¢ | edge/ctr ¢ |
|---|---|---|---|---|
| market (sweep) | 100% | 32.4 | **+7.22** | −5.98 |
| limit_ask (cross) | 19%* | 25.2 | 0.00 | +0.90 |
| post1 (maker) | 60%* | 23.8 | −1.44 | +0.15 |
| chase | 42%* | 24.8 | −0.35 | +1.25 |

\* `ctr fill %` here is *snapshot* fill (filled/requested against the frozen book); real
resting GTC limits fill far more over time (live §1). It is **not** the policy's true fill
rate — it is shown to expose that `limit_ask`'s "good" PnL/Sharpe elsewhere is a
low-fill-volume artifact, not edge.

The mechanical price ladder is unambiguous and certain: **maker (−0.7 to −1.5¢ vs ask)
< limit@ask (0) < premium (+0.5 to +1¢) < sweep (+2.7 to +7.2¢)**. Demanding immediacy
for full size costs the most; posting inside captures the spread.

### 4. No adverse selection on filled maker orders

The classic fear: a resting order fills precisely when information has moved against it.
Comparing the **same signals**, maker price vs taker price, on maker-filled orders:

| City | maker-filled n | edge @ maker ¢ | edge @ taker ¢ | price gain ¢ |
|---|---|---|---|---|
| KORD | 30 | −2.13 | −2.87 | +0.73 |
| KMIA | 11 | +10.64 | +9.18 | +1.45 |
| Dallas | 39 | +0.15 | −1.36 | +1.49 |

In all three, the maker's price saving flows straight through to realized edge — i.e.
**resting orders are not picked off** in these slow-information temperature markets. The
maker's only real cost is *missed fills* (opportunity cost), not getting run over.

### 5. Realistic maker fill rate (book model, by horizon)

| City | maker-eligible | no-room (must cross) | fill @30m | fill @60m | fill @close |
|---|---|---|---|---|---|
| KORD | 13 | **21 (62%)** | 54% | 54% | 100% |
| KMIA | 10 | 2 | 60% | 70% | 100% |
| Dallas | 21 | **22 (51%)** | 43% | 48% | 90% |

Within the actionable cron window (~30–60m) maker capture is **~50–70%** — consistent
with live KMIA (52%). It only reaches ~90–100% *by close*, which is too late to be useful
(edge has decayed; near settlement). And on KORD, **62% of signals have no maker room at
all** (1¢ spread) — there is simply nothing to capture, so crossing is correct.

### 6. Depth-aware size cap — and a skill-vs-edge warning

Max marginally +EV contracts when sweeping to the **model's** fair value:

| City | median N\* | p25 N\* | % signals N\* < 500 |
|---|---|---|---|
| KORD | 1894 | 1172 | 6% |
| KMIA | 1383 | 1147 | 8% |
| Dallas | 760 | 395 | **33%** |

At 500 lots KORD/KMIA almost never over-bet the model's edge; **Dallas walks into
negative model-edge depth 33% of the time** → it needs a size cap. **But** the `depthcap`
policy, which sizes to model-fair, *realizes* badly (−5.9¢/ctr on KORD) — because the
model's fair value is over-optimistic (skill ≠ edge; the market does most of the work).
**Do not size to model-fair.** Use a conservative price-based cap instead (don't buy
beyond ask+2¢).

### 7. Walk-forward OOS Sharpe — uninformative on 12 days

| City | train/test days | best X (train) | smart | market | limit_ask | post1 |
|---|---|---|---|---|---|---|
| KORD | 7 / 4 | 0.25 | 9.02 | −1.79 | 13.59 | 8.01 |
| KMIA | 4 / 3 | 0.40 | −2.85 | −5.64 | 8.58 | −2.85 |
| Dallas | 7 / 3 | 0.50 | −8.24 | −0.61 | 11.95 | −6.65 |

These swing wildly with 3–4 test days and `limit_ask` "wins" only because it trades a
tiny, cheap, fill-selected sliver — a **low-fill artifact**, not edge. Bootstrap 95% CIs
on KORD per-contract edge confirm nothing is distinguishable:

| policy | n | mean ¢ | 95% CI |
|---|---|---|---|
| market | 30 | −6.70 | [−21.6, +8.1] |
| limit_ask | 30 | −2.87 | [−17.5, +11.8] |
| post1 | 30 | −2.13 | [−16.2, +12.8] |
| smart | 30 | −2.39 | [−16.6, +12.9] |

Every CI spans zero and they overlap entirely. **The fill-rate↔price↔Sharpe frontier
resolves on price and fill, not on Sharpe**, at this sample size. The P4 result (maker
3.55 vs taker 2.25 OOS) used a much longer settled history; it is the better basis for the
*Sharpe* claim, and it agrees in direction with the mechanical price evidence here.

### 8. Time-of-day (lower priority)

`best_time_of_day.py` already covers KORD/KMIA and, by design, holds fill rate constant
(assumes fills at cron-time) — so any apparent late-day P&L edge there is a fill-rate
artifact, not a time edge. With only ~12 days of intraday book, a per-hour execution
optimum is **underpowered**; I did not extend it. The horizon table (§5) is the
defensible time dimension: maker fills accrue over 30–60m, not instantly.

## External Context

- **Maker/taker & adverse selection.** The maker–taker design exists precisely because
  posting visible limit orders invites adverse selection from informed flow, so exchanges
  pay makers (rebate / lower fee) to compensate; optimal placement trades off execution
  probability against picking-off risk. Our finding of *no* adverse selection is
  consistent with a market where information arrives slowly and is largely already in the
  public forecast — the maker is compensated (spread) without being systematically
  run over.
  ([arXiv:1610.00261](https://arxiv.org/pdf/1610.00261),
  [CFA Institute](https://blogs.cfainstitute.org/marketintegrity/2014/12/18/hft-price-improvement-adverse-selection-an-expensive-way-to-get-tighter-spreads/))
- **Optimal execution / market impact.** Splitting orders and using passive limits to
  avoid sweeping the book is the standard remedy for temporary impact (Almgren–Chriss
  lineage; limit-vs-market execution with fill uncertainty).
  ([arXiv:1604.04963](https://arxiv.org/pdf/1604.04963),
  [arXiv:1106.5040](https://arxiv.org/pdf/1106.5040)) — supports "never sweep full size."
- **Kalshi fee schedule (the material one).** Taker fee `= ceil(0.07·P·(1−P)·100)¢`;
  **maker fee `≈ 1.75%·P·(1−P)`, one-quarter of the taker rate** (2026), and Kalshi's own
  guidance historically described **resting orders as fee-exempt**. Either way, the
  project's `kalshi_fee_cents` (flat 7% for all fills) **overcharges makers ~4×**, making
  the maker policy look worse than reality in backtests by ~¾ of the fee (~1¢/ctr at
  mid-price; ~0 at the extremes due to the 1¢ floor).
  ([Kalshi: Makers and Takers](https://news.kalshi.com/p/makers-and-takers),
  [Market Math: Kalshi fees 2026](https://marketmath.io/platforms/kalshi))

## Limitations & Threats to Validity

- **Tiny samples.** 40 live orders (KORD n=25, KMIA n=9, Dallas n=0); ~12 days of book;
  89 signals (81 settled); 3–4 walk-forward test days. The **Sharpe and realized-edge
  rankings are not statistically distinguishable** (all bootstrap CIs span zero). Treat
  every PnL/Sharpe number as illustrative, not decisive.
- **Snapshot fill understates resting depth.** The book-sim fills against one frozen
  snapshot, so it under-counts the liquidity a GTC limit captures over time (live proves
  ~90% fill vs ~17% snapshot for KORD). The **price** results are robust (mechanical); the
  **fill-quantity / net$ / Sharpe** results are not — lean on live §1 for fill rate.
- **No trade prints.** Maker fill is inferred from book *touch* (opposite bid reaching our
  price), not actual executions, and assumes full-size fill on touch (live suggests
  partials). Queue position is not modeled.
- **Skill ≠ edge.** `depthcap`-to-model-fair loses money: the model's edge is largely
  illusory (market does most of the work). Execution can only *preserve* the small,
  uncertain underlying edge — it cannot manufacture one. A policy that merely "improves
  fill rate" at converged prices is a liquidity artifact.
- **Fee model bias.** The flat-7% fee in code/sim understates the maker advantage; the
  true maker edge is ~1¢/ctr better than every maker row above.
- **Dallas is unvalidated live** (paper-watchlist only) and is *not* a robust-edge city
  (per-city diagnostic) — its execution numbers are the least trustworthy.

## Recommendation

The deployed `EXECUTION_MODE="smart"` is already well-aligned with the evidence. Proposed
**execution playbook** (decision rule; per-city parameters). Per CONFIG-FREEZE handling,
each item is a **backlog proposal, not an action** (mirrored to `docs/backlog.md`):

**Decision rule (per fired signal):**
1. **Never send a marketable order for full size.** Always a resting GTC limit. *(Already
   true via `place_limit_order`; add an explicit guard that the requested `count` never
   exceeds available depth at ≤ ask+2¢, so a fat-finger can't sweep.)*
2. **If spread ≤ 1¢ → cross at the ask** (`limit = ask`, `post_only=False`). No maker room
   to capture (KORD: 62% of signals).
3. **Else if `|E| ≥ X_city` → cross at the ask.** High conviction ⇒ fill certainty
   dominates the ~1–3¢ spread.
4. **Else → post 1¢ inside** (`limit = best_bid+1`, `post_only=True`), GTC; **re-quote**:
   if unfilled after **T = 45 min**, cross at the ask **only if `|E| ≥ Y_city`**, else let
   it expire. Captures spread (no adverse selection) while bounding missed-fill cost.
5. **Cap size** at `min(unit_contracts, depth at price ≤ ask+2¢)` — a *price-based* cap,
   **not** model-fair depth (which over-bets). Matters mainly for Dallas (33% of signals).

**Per-city parameters** (from spread structure + fill rates):

| City | X (cross-if-edge≥) | Y (re-quote cross-if-edge≥) | T | Notes |
|---|---|---|---|---|
| KORD | 0.40 *(current — keep)* | 0.25 | 45m | Tight 1¢ spreads → mostly crosses anyway; maker matters only on the wide-spread tail |
| KMIA | 0.10 *(current — keep)* | 0.10 | 45m | Wide 3¢ spreads + high maker edge (+10.6¢) & no adverse selection → lean maker; the 0.40 era caused the 52% fill |
| Dallas | 0.25 + **size cap** | 0.25 | 45m | Watchlist only; add the price-based size cap; do not promote on execution numbers |

**Concrete backlog items (proposals — validate before any live change):**
1. **Maker/taker-aware fee model.** Make `kalshi_fee_cents` take a `maker: bool` and apply
   ~1.75%·P·(1−P) (or 0) for `post_only` fills. Re-run the P4 maker-vs-taker backtest with
   it — the maker case is currently understated by ~¾ of the fee. *(Highest value: cheap,
   improves every backtest's accuracy.)*
2. **Time-based re-quote in the fill loop.** `place_with_guaranteed_fill` only crosses on a
   would-cross race, not on elapsed time. Add a monitor pass that crosses an unfilled
   maker after T=45m iff `|E| ≥ Y`. (TIF is GTC-only — no IOC exposed — so this is a
   cancel+repost, which `kalshi_api` already supports via `DELETE /portfolio/orders/{id}`.)
3. **Price-based depth/size cap** for thin books (Dallas), as in rule 5.
4. **Keep accumulating orderbook + live fills.** The binding constraint on *this* question
   is sample size: re-run this study at ~60 days of book / ≥30 live fills per city before
   trusting any OOS Sharpe ranking or a finely-tuned threshold.

**Does it clear the 2.5 OOS bar?** Not answerable on 12 days (CIs span zero; OOS Sharpe is
noise/artifact). The mechanical evidence (never sweep; capture spread where it exists;
maker isn't adversely selected; maker fees are ~4× overcharged in code) all points the
same direction as the longer-history P4 result (maker 3.55 > taker 2.25), which remains
the better basis for the Sharpe claim. **Recommendation: keep `smart`, fix the fee model,
add the re-quote + Dallas size cap — and re-adjudicate the bar on a larger forward sample.**

## Sources

External:
1. Limit Order Strategic Placement with Adverse Selection Risk — https://arxiv.org/pdf/1610.00261
2. Optimal Execution of Limit and Market Orders with Fill Uncertainty — https://arxiv.org/pdf/1604.04963
3. Optimal HFT with limit and market orders — https://arxiv.org/pdf/1106.5040
4. CFA Institute — Price Improvement & Adverse Selection — https://blogs.cfainstitute.org/marketintegrity/2014/12/18/hft-price-improvement-adverse-selection-an-expensive-way-to-get-tighter-spreads/
5. Kalshi — Makers and Takers (resting orders fee-exempt) — https://news.kalshi.com/p/makers-and-takers
6. Market Math — Kalshi Fees 2026 (maker = ¼ taker) — https://marketmath.io/platforms/kalshi

Internal (reproducible):
- `psql -d weather` SELECTs on `live_trades`, `orderbook_snapshots`, `paper_trades`, `contracts`, `observations` (see Methods).
- Simulation: `/tmp/exec_sim.py` (stdlib + `psql COPY`; book reconstruction, 10 policies, settlement, adverse-selection, walk-forward, bootstrap CI). Net of Kalshi V2 fees.
- Code re-implemented: `dashboard/sim_python.py` (`kalshi_fee_cents`, execution modes), `scripts/live_trade.py` (`place_with_guaranteed_fill`, `resolve_exec_path`, `SMART_CROSS_EDGE_THRESHOLD`, `CITY_CONFIG`), `src/weather_markets/kalshi_api.py` (`place_limit_order`), `src/weather_markets/evaluation.py` (`contract_resolved_yes`), `scripts/analysis/dallas_watchlist.py`.
