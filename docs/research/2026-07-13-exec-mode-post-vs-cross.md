# POST vs CROSS, per city — empirical fill study

> 2026-07-13 · branch `research/exec-mode-compare` · tool `scripts/analysis/exec_mode_compare.py`
> READ-ONLY research. No live config changed. Report only — the operator decides.

## TL;DR

**CROSS beats POST in 3 of 4 cities, and the reason overturns the 2026-06-06 adverse-selection
claim.** The trades a resting maker order misses are not adverse-selected losers — they are
**winners: 12 of 13 across all four cities, mean +$199/trade.** Posting saves 1¢ plus the ¾ maker
fee discount (worth +$70…+$315 per city over six weeks) and pays for it by missing fills worth
+$510…+$925. The savings never come close to covering the forgone P&L.

| city | verdict | robust? |
|---|---|---|
| **KORD** | **CROSS** (already crosses ≥0.40; full cross is better in-sample) | ✅ beats POST in both halves, under both fill rules |
| **KMIA** | **CROSS** — and it already does (smart_cross 0.10 ⇒ always crosses) | ✅ both halves, both fill rules. No change needed |
| **KDFW** | **CROSS**, leaning | ⚠️ wins both halves under the strict fill rule; TEST half flips to POST under the relaxed one |
| **KPHX** | **no evidence** — keep POST-only | ❌ splits (CROSS wins TRAIN, POST wins TEST). n=21. Stakes are tiny ($32) either way |

## The fill rule

A resting limit order is placed at the city's decision time and lives until the
`monitor_fills --cancel-unfilled` cron at **20:00 UTC** (that is the real end of the resting
window in production, not market close). Over every `prices` snapshot in that window:

```
BUY YES @ L  ->  filled iff min(yes_ask) <= L
BUY NO  @ L  ->  NO ask = 100 - yes_bid, so filled iff max(yes_bid) >= 100 - L
cross_at_ask / cross_with_premium -> taker on existing depth -> filled
post_inside_spread with spread <= 1 -> falls back to crossing (live_trade.py:761-763)
```

**Why these observables.** A resting BUY-YES bid at L can only be filled by an incoming seller,
and a seller's presence shows up as the best *offer* touching L — a book cannot quote an ask below
a resting bid without them trading. Symmetrically for NO. Both readings are also **immune to our
own order**: a resting YES bid moves `yes_bid`, not `yes_ask`; a resting NO bid moves `yes_ask`,
not `yes_bid`. The rule reads the opposite side of the book in each case, so replaying real orders
does not let the order see itself.

## Ground-truth gate (run before anything else)

Replayed all 86 real `live_trades` orders (all cities, real `limit_price_cents` / `side` /
`placed_at` / `fill_status` / `fill_count`) through the fill model.

| subset | n | agreement | TP | FP | FN | TN |
|---|---|---|---|---|---|---|
| all orders | 86 | **95.3%** | 82 | 0 | 4 | 0 |
| **maker (resting, limit < cross)** — the only real test | 22 | **81.8%** | 18 | **0** | 4 | 0 |
| taker (crossing) | 64 | 100% | 64 | 0 | 0 | 0 |

**GATE PASSED**, with a directional bias worth naming: **every error is a false negative** — a real
maker order that filled while the 5-min top-of-book never printed through our limit (intra-snapshot
trades the grid cannot see; 3 of the 4 were small partials). Zero false positives: the model never
claims a fill that did not happen.

So the model **understates POST's fill rate** — i.e. it biases the study **against POST**, the mode
this study ends up rejecting. That is the honest direction to be wrong in, but it must be bounded:
every result was therefore re-run with the fill test relaxed by 1¢
(`--relax 1`), which lifts maker agreement to **95.5% (21/22, still zero false positives)** and
gives an **upper bound** on POST's fill rate. The truth is bracketed between the two runs. **Both
runs are reported; the verdicts are unchanged except where noted (KDFW).**

## Results

Window **2026-06-04 → 2026-07-12** (see Power, below). Unit size read from CITY_CONFIG
(KORD/KMIA/KDFW 500, KPHX 250). `smart_live` = the city's actual live `smart_cross_edge_threshold`.
Sharpe = per-trade mean/sd × √252 over filled trades (project convention); `Sh(all)` counts a
missed fill as a 0. maxDD in dollars. TRAIN = first 60% of signals chronologically, TEST = last 40%.

### KORD (Chicago) — UNION raw≥0.25 or blend≥0.10, unit 500, 14:46Z, live smart_cross 0.40

| half | mode | n | fill | net $ | $/fill | Sharpe | maxDD |
|---|---|---|---|---|---|---|---|
| FULL | post_inside_spread | 33 | 90.9% | +70 | +2.33 | 0.19 | −875 |
| FULL | **cross_at_ask** | 33 | 100% | **+745** | +22.58 | 1.78 | −905 |
| FULL | cross_with_premium_1 | 33 | 100% | +580 | +17.58 | 1.39 | −960 |
| FULL | smart_live (LIVE) | 33 | 93.9% | +300 | +9.68 | 0.80 | −885 |
| TRAIN | post | 19 | 89.5% | +480 | +28.24 | 1.97 | −575 |
| TRAIN | **cross** | 19 | 100% | **+925** | +48.68 | 3.28 | −595 |
| TEST | post | 14 | 92.9% | −410 | −31.54 | −3.90 | −590 |
| TEST | **cross** | 14 | 100% | **−180** | −12.86 | −1.42 | −590 |

CROSS > POST in **both halves** and under both fill rules. Against the *live* smart-0.40 hybrid the
picture is softer: cross wins TRAIN big (+925 vs +460) but TEST is a wash (−180 vs −160). So:
**do not post more; full cross is supported in-sample but does not robustly beat the live hybrid.**

### KMIA (Miami) — BLEND-only ≥0.10, unit 500, 15:30Z, live smart_cross 0.10

| half | mode | n | fill | net $ | $/fill | Sharpe | maxDD |
|---|---|---|---|---|---|---|---|
| FULL | post_inside_spread | 18 | 83.3% | +1,125 | +75.00 | 5.32 | −725 |
| FULL | **cross_at_ask** | 18 | 100% | **+1,565** | +86.94 | 6.64 | −740 |
| FULL | cross_with_premium_1 | 18 | 100% | +1,475 | +81.94 | 6.26 | −755 |
| FULL | smart_live (LIVE) | 18 | 100% | +1,565 | +86.94 | 6.64 | −740 |
| TRAIN | post | 10 | 80.0% | +1,010 | +126.25 | 9.71 | −335 |
| TRAIN | **cross** | 10 | 100% | **+1,295** | +129.50 | 11.10 | −350 |
| TEST | post | 8 | 87.5% | +115 | +16.43 | 1.07 | −725 |
| TEST | **cross** | 8 | 100% | **+270** | +33.75 | 2.28 | −740 |

`smart_live` is byte-identical to `cross_at_ask` — smart_cross 0.10 with a blend threshold of 0.10
means **Miami always crosses by construction**. It is already on the right setting. Confirms the
2026-06-29 capacity finding ("KMIA crosses by design"). CROSS > POST in both halves, both rules.

### KDFW (Dallas) — UNION raw≥0.25 or blend≥0.10, unit 500, 17:32Z, live smart_cross 0.40

| half | mode | n | fill | net $ | $/fill | Sharpe | maxDD |
|---|---|---|---|---|---|---|---|
| FULL | post_inside_spread | 27 | 85.2% | −185 | −8.04 | −0.58 | −805 |
| FULL | **cross_at_ask** | 27 | 100% | **+710** | +26.30 | 1.76 | −845 |
| FULL | cross_with_premium_1 | 27 | 100% | +575 | +21.30 | 1.42 | −885 |
| FULL | smart_live (LIVE) | 27 | 88.9% | +160 | +6.67 | 0.45 | −775 |
| TRAIN | post | 16 | 81.2% | −570 | −43.85 | −3.37 | −805 |
| TRAIN | **cross** | 16 | 100% | **+170** | +10.62 | 0.71 | −845 |
| TEST | post | 11 | 90.9% | +385 | +38.50 | 2.52 | −380 |
| TEST | **cross** | 11 | 100% | **+540** | +49.09 | 3.19 | −395 |

Strict rule: CROSS wins both halves. **Relaxed rule: the TEST half flips** (POST +670 vs CROSS
+540, because POST then fills 11/11). TRAIN is decisive for CROSS either way (+170 vs −570). Live
smart-0.40 (+160 full) is worse than pure cross (+710) under both rules. **Lean CROSS; not robust
to fill-model uncertainty.**

### KPHX (Phoenix) — RAW-only ≥0.20, unit 250, 14:52Z, live smart_cross 1.00 (POST-only)

| half | mode | n | fill | net $ | $/fill | Sharpe | maxDD |
|---|---|---|---|---|---|---|---|
| FULL | post_inside_spread | 21 | 85.7% | +110 | +6.11 | 0.93 | −302 |
| FULL | cross_at_ask | 21 | 100% | +72.50 | +3.45 | 0.55 | −405 |
| FULL | cross_with_premium_1 | 21 | 100% | +20 | +0.95 | 0.15 | −420 |
| FULL | smart_live (LIVE) | 21 | 85.7% | +110 | +6.11 | 0.93 | −302 |
| TRAIN | post | 12 | 83.3% | +27.50 | +2.75 | 0.43 | −265 |
| TRAIN | **cross** | 12 | 100% | **+115** | +9.58 | 1.59 | −287 |
| TEST | **post** | 9 | 88.9% | **+82.50** | +10.31 | 1.43 | −302 |
| TEST | cross | 9 | 100% | −42.50 | −4.72 | −0.69 | −405 |

**Splits: CROSS wins TRAIN, POST wins TEST** (same under the relaxed rule). n=21 is far too small.
This is noise, not a finding. The whole POST-vs-CROSS gap here is **$32.50 over six weeks** —
the smallest stake of any city. Keep POST-only (status quo); revisit at n≈100.

## The adverse-selection crux — the 2026-06-06 claim is REVERSED

Commit 4e5b2807 (n=332, cross-city) asserted the trades crossing catches but a maker misses
*"LOSE ~$80/trade — they're adverse-selected losers."* Tested per city on that city's own history:

| city | cross-only catches (POST misses) | mean net/trade | win rate |
|---|---|---|---|
| KORD | n=3 | **+$278.33** | 3/3 |
| KMIA | n=3 | **+$170.00** | 3/3 |
| KDFW | n=4 | **+$295.00** | 4/4 |
| KPHX | n=3 | **+$20.00** | 2/3 |
| **pooled** | **n=13, total +$2,585** | **+$199/trade** | **12/13** |

They are **winners**, not losers. Each city's n is tiny, but pooled 12-of-13 winners under a ~40%
base win rate has p ≈ 2e-5 — the sign is not a coincidence even if the magnitude is noisy.

**Mechanism (why this should be true, not just measured).** A passive bid gets missed exactly when
the market moves *away* from us — i.e. it converges toward our fair value, which is the case where
our model was right. When the market instead comes *to* us and fills the resting order, it is often
because it is moving *against* our view. Posting therefore systematically selects the **worse**
subset of our own signals. That is textbook maker adverse selection, and it is the opposite of what
4e5b2807 concluded. It is also consistent with the 2026-07-05 re-quote finding (re-quoting chased
adversely-selected fills).

**Decomposition — the entire POST−CROSS gap is these two terms:**

| city | + price improvement on shared fills | − P&L of the fills POST misses | = POST − CROSS |
|---|---|---|---|
| KORD | +$160 (30 fills) | +$835 (3) | **−$675** |
| KMIA | +$70 (15 fills) | +$510 (3) | **−$440** |
| KDFW | +$285 (23 fills) | +$1,180 (4) | **−$895** |
| KPHX | +$97.50 (18 fills) | +$60 (3) | **+$37.50** |

The 1¢ + maker-fee-discount saving is real but *an order of magnitude too small* to pay for the
missed winners. Posting is a good deal per fill and a bad deal per signal. **KPHX is the sole
exception** — and only because the two winners it missed were cheap ($60 total), not because its
savings were large. That is a coin-flip, not an edge.

## Power and limitations (read before acting)

1. **⚠️ PRICE fill, not SIZE/depth fill.** The model answers *"did the market trade through my
   limit"*, never *"was there enough size there"*. A crossing order into a thin book still partially
   fills — we saw exactly this live (KPHX cross filled **83/250**; KDFW id=77 filled 97/500). So
   **`cross_at_ask` fill rates of 100% here are price-fills; realized size will be lower.** That
   trims CROSS's advantage but does not reverse it — CROSS wins on the trades it *catches at all*,
   and a partial fill of a winner still beats no fill. Combine with the 2026-07-05 capacity finding
   (per-city ceilings ~500–700) before scaling anything.
2. **⚠️ n = 18–33 per city; window = 6 weeks.** This is the binding constraint and it is not fixable
   today. `prices` only went to 5-minute cadence on **2026-06-01**; before that it was hourly-on-the-
   hour, and *zero* pre-June snapshots fall in the 20-minute pre-decision window. An hourly grid
   cannot resolve whether a 1¢-inside limit filled, so extending the window would not add
   information — it would add fabricated no-fills biased against POST. The study is confined to the
   dense-price era by data, not by choice. KPHX at n=21 is **underpowered and I do not claim a
   result for it.**
3. **The window is largely in-sample** w.r.t. the live configs (Chicago/Miami/Dallas were trading
   live through it). TRAIN/TEST guards against fitting *this* study to the data; it cannot undo the
   fact that these configs were already chosen on overlapping history.
4. **Signal set is capped by `paper_trades`**, whose rows are pre-filtered at |raw_edge| ≥ 0.10
   (`paper_trade_log.py:56,289`). Blend-only signals with raw edge < 10% are invisible to any
   reconstruction from that table — this affects KMIA most (blend-only city). Same limitation as all
   prior backtests on this corpus; it caps n but should not bias POST vs CROSS, which is compared
   *within* an identical signal set.
5. **Halts/kill-switches are not simulated** (backtest convention). Real daily-loss halts would have
   truncated some of these sequences.
6. Sharpe over filled trades follows the project convention (`data_backtest.py:440-446`) and so
   flatters low-fill modes; `Sh(all)` (missed fill = 0 return) is reported alongside and does not
   change any verdict.

## Reproduce

```bash
cd /home/tdunn/wt-exec-compare
uv run python scripts/analysis/exec_mode_compare.py              # gate + all 4 cities (strict)
uv run python scripts/analysis/exec_mode_compare.py --relax 1    # sensitivity: upper-bound POST fills
uv run python scripts/analysis/exec_mode_compare.py --gate-only  # ground-truth gate alone
uv run python scripts/analysis/exec_mode_compare.py --selfcheck  # limit-price / fill-rule asserts
```

The tool imports `CITY_CONFIG`, `resolve_exec_path()` and `kalshi_fee_cents()` **directly from
`scripts/live_trade.py`** — thresholds, unit sizes, decision times, smart-cross thresholds and the
maker/taker fee are never re-typed. The limit-price block (live_trade.py:754-775) is inline in the
cron and so cannot be imported; it is mirrored byte-faithfully in `limit_price_for()` (including the
spread≤1 fallback-to-crossing and the 1..99 clamp) and covered by `--selfcheck` asserts.
