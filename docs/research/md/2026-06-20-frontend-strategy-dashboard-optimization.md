# Optimizing the Trading Desk Frontend for Strategy Decisions

*2026-06-20 · status: draft*

> Scope confirmed with the user: **research + recommendations only** (no code changes this
> session), with a **balanced** emphasis on live-ops *and* strategy-diagnostics. All trading
> config is read-only and untouched; this paper respects the CONFIG FREEZE (2026-06-12 →
> 2026-07-10). The redesign is frontend-only; nothing here changes a threshold, sizing rule,
> or risk number.

## Question

The current ISOBAR dashboard (`dashboard/static/`) is visually strong but built as a generic
"P&L + positions + backtest playground." As a quant operating this stack, **what should the
frontend surface to (a) decide whether the edge is real before the 2026-07-10 re-evaluation,
and (b) confirm the live system is safe and executing well right now** — while trimming dead
weight and keeping a modern, professionally-animated look?

The binding question behind every panel: *does this pixel help me prove or disprove a positive
edge after fees, or keep the live book inside its risk envelope?* If not, it is fat.

## TL;DR / Verdict

**Confidence: high** on the diagnosis (it is grounded in this repo's own data and findings),
**medium** on the exact layout (design is iterative; numbers below should be A/B-validated in
the browser).

The UI is **rendering the wrong headline and hiding the decisive evidence.** Three changes
carry ~80% of the value:

1. **Replace the 9-metric "democratic" hero with a decision hero.** Today win-rate leads — and
   it is *actively misleading*: the live book is **+$100.04 net of fees on 22 settled trades but
   wins only 6 of 22 by count** (27%). The edge is expectancy-driven (a few large NO-side
   payoffs), so the headline must be **net realized edge after fees + risk headroom + expectancy
   / profit factor**, not win-rate.
2. **Add the one panel that answers "is the edge real": a calibration / reliability view** of
   `model_P` vs `blend_P` vs `market_P` against outcomes. All the data exists (21,734 paper rows
   over 722 days); the backend just never computes it. This is the single highest-value creative
   addition.
3. **Add a paper-vs-live divergence monitor.** The open risk to scaling is that Chicago's *live*
   fills have diverged from *paper* expectation. The dashboard should make that gap, plus the
   fill-rate haircut, impossible to miss.

Trim: the dead Polymarket toggle, the hard-coded `crons[]="ok"` / `brier=0.20` placeholders
(they manufacture false confidence), and the prominence of the frozen param-sweep. Keep the
thermal-glass aesthetic and the diff-driven motion — both are good; just point them at the
metrics that matter and fix the over-aggressive reduced-motion handling.

## Methods & Data

**Internal — frontend & backend map (read-only):**
- Read `dashboard/static/{index.html, app.js (1,405 LOC), css/*.css}` and the build notes;
  catalogued every render function, component, CSS token, and animation.
- Read `dashboard/{app.py, data_live.py, data_backtest.py, kalshi_ws.py}` and
  `docs/context/dashboard.md`; inventoried the full `/api/live` and `/api/backtest` payloads,
  including fields computed but **not surfaced**.
- Read `docs/context/{strategy,goals-metrics,decisions,data-model}.md`.

**Internal — live data reality (`psql -d weather`, SELECT-only):**
- `live_trades` overview, by-city, fill-status/settlement distributions.
- `paper_trades` coverage (rows, date span, distinct tickers), per-city average edge.
- Schema of `prices` / `forecasts` for freshness fields.

**Internal — prior findings (this repo's memory):** per-city diagnostic (2026-06-20),
market-blend (2026-06-09), fill-rate forward test (2026-06-05).

**External — verified against source:** NN/G *8 Design Guidelines for Complex Applications*
[1]; trader-dashboard hierarchy / F-pattern / space-rule guidance [2]; NN/G chartjunk &
preattentive-processing guidance [3]; reliability-diagram / calibration verification literature
(AMS consistency bars; PNAS CORP) [4][5]; Smashing Magazine accessible-animation practice
(`prefers-reduced-motion` = reduce, not remove; adapt essential motion) [6].

## Internal Findings

### F1 — The live book is small but *expectancy-positive*, and win-rate misrepresents it

`live_trades`, all cities, 2026-06-04 → 2026-06-19:

| Metric | Value |
|---|---|
| Orders placed | 28 |
| Filled (filled/partial) | 22 |
| Settled | 22 |
| **Net realized P&L (after fees)** | **+$100.04** |
| Fees paid | $23.30 |
| Wins by count | 6 / 22 (**27%**) |
| Fill-status mix | 20 filled · 2 partial · 4 cancelled · 2 rejected |
| Settlement mix | 14 NO · 8 YES · 6 open |

The book makes money while losing most individual bets — classic NO-side bracket payoff
structure (small frequent losses, occasional large win). **A win-rate headline (the current
hero) tells the operator the strategy is failing when it is not.** The correct headline metrics
are net-edge-after-fees, expectancy ($/settled trade ≈ +$4.55), profit factor, and avg-win ÷
avg-loss. Fees are **~19% of net realized** — material enough to deserve a permanent line, never
hidden.

### F2 — Edge is concentrated in 3 cities; most of the map should read "do not trade"

From the per-city diagnostic (fee-aware net P&L reconstructed over 21,318 settled signals, 11
city series):

| Universe | Net P&L | Sharpe | Note |
|---|---|---|---|
| 11-city baseline (\|edge\|≥0.10) | **−$149** | −2.62 | loses after fees |
| Robust subset (Chicago, Miami, Seattle) | **+$46.51** | **2.37** | P/DD 3.50; profitable at baseline, in both history halves, *and* walk-forward |
| No-edge cities (NY/DEN/AUS/NOLA/LV/PHX) | negative OOS | — | do not trade |

6 of 11 cities have an in-sample-profitable config that flips negative out-of-sample → per-city
tuning is mostly overfitting, and **edge is decaying (H2 ≪ H1).** The map on the backtest tab
currently colors every city by Sharpe as if all are tradable; it should *visually privilege the
robust subset and mark the rest "do not trade."*

### F3 — The market does most of the work; the model is anti-informative in 2 cities

Benter-style logistic blend on settled `paper_trades`, 70/30 time-split, test-set Brier:

| City | β_model | β_market | Market share | Test Brier (model → blend) |
|---|---|---|---|---|
| KORD | +0.19 | +0.38 | 67% | 0.204 → 0.143 (**−30%**) |
| KNYC | +0.19 | +0.91 | 83% | 0.219 → 0.124 (−43%) |
| KMIA | +0.55 | +0.70 | 56% | 0.221 → 0.179 (−19%) |
| KDEN | +0.20 | +1.04 | 84% | 0.203 → 0.138 (−32%) |
| KAUS | **−0.10** | +1.17 | 92% | 0.169 → 0.151 (−11%) |
| KLAX | **−0.07** | +1.22 | 95% | 0.183 → 0.130 (−29%) |

The dashboard already returns blend coefficients (`blend.{alpha,betaModel,betaMarket,marketShare,
nTrain}`) but buries them in a single mini-bar. **A senior reader wants this table front-and-center
with the negative-β cities flagged red** — it is the cleanest statement of "where our model adds
value vs where we are just riding the market."

### F4 — Execution mode is an expectancy decision the UI should monitor, not hide

Fill-rate forward test (332 resolved trades, dashboard empirical comparison):

| Mode | Fill rate | $/filled | Final return | Max DD |
|---|---|---|---|---|
| **post_inside_spread** | **75%** | **+$35** | +291% | −24% |
| cross_at_ask | 99% | +$6 | +69% | −66% |
| cross_with_premium=1 | 99% | +$3 | +35% | −72% |
| Live `live_trades` (current) | 22/28 ≈ 79% by order | +$4.55 net | — | — |

The 80 trades crossing catches but the maker misses **lose ~$80 each** (adverse selection) —
missing them is *net beneficial*. So fill-rate is not a number to maximize; it is a
expectancy-coupled diagnostic. The live tab should show **today's realized fill % and average
slippage-vs-mid per city**, so a drift (e.g. fill rate dropping <60%) is caught early.

### F5 — Paper-vs-live divergence is the unresolved risk to scaling

The per-city diagnostic flagged Chicago **live −$124 (n=17 fills, 2 wk) vs paper +$21** at the
time of that study — the central open tension ("resolve fills/slippage vs variance before
scaling"). Whatever its current sign (aggregate book is +$100 net today), **the gap between what
paper predicts and what live realizes is the most decision-relevant number on the system, and it
appears nowhere in the UI.** This is the second flagship addition.

### F6 — The backend already computes more than the UI shows

Available in payloads but under-surfaced or placeholder:

| Field(s) | Where | Status | Opportunity |
|---|---|---|---|
| `emosMu`, `emosSigma`, `ensMean`, `ensSpread`, per-bracket `modelP/blendP/mktP` + `observed` | `/api/backtest` | shown only as scalars | feeds a **reliability diagram** / PIT view directly |
| `blend.{betaModel,betaMarket,marketShare}` | `/api/backtest` | tiny mini-bar | promote to F3 table |
| `live.{connected,ageMs,marks,source}`, `hrrr.age`, `nextCron`, `killArmed` | `/api/live` | small pill / footer | promote to a **system-health + risk-headroom** strip |
| `cities[].risk.{cumUsed,cumKill,todayUsed,todayKill}`, `agg.*` | `/api/live` | conic dials only | **kill-switch headroom gauges** (how close to halt) |
| `strat[].brier = 0.20` | `/api/backtest` | **hard-coded placeholder** | remove or compute real Brier (the calibration work yields it) |
| `crons[].status = "ok"`, `last = "—"` | `/api/live` | **hard-coded** | replace with real last-run/exit, or remove the green ticks (false safety) |

## External Context

- **Lead with one number, not nine.** Eye-tracking shows users scan dense screens in an
  **F-pattern**; guidance is to give the single most important metric the most space/contrast
  (the "40-30-20-10" space rule) and avoid the "democratic layout" where every metric is equal
  weight — benchmark layouts against a **time-to-answer < 30 s** [2]. The current 9-up equal hero
  is exactly the anti-pattern. [1] (NN/G) similarly stresses easing the transition between
  primary and secondary info (hover tooltips for precise values) and **reducing clutter without
  reducing capability** via staged/progressive disclosure — the right home for the frozen
  param-sweep.
- **Cut chartjunk; use preattentive encodings.** NN/G: remove ornamental gradients/3D/decoration;
  communicate quantity with **length and 2-D position**, which the visual system reads
  pre-attentively [3]. The thermal ramp and glass are fine *as long as* color encodes data
  (edge/temperature) rather than decoration.
- **Calibration is a picture, and there is a right way to draw it.** Reliability diagrams plot
  predicted probability against observed frequency; **consistency/uncertainty bars** let you see
  whether deviations are significant rather than noise [4], and the modern **CORP** method
  (isotonic/PAV regression) yields provably consistent, reproducible, optimally-binned diagrams
  [5]. This is the discipline's standard answer to "is the probability model honest" — precisely
  the question this project must answer by 2026-07-10.
- **Animation should be functional, and reduced-motion means *reduce*, not *delete*.** Keep motion
  that conveys state/relationship (count-ups that show a delta, draw-on that shows a series);
  drop purely decorative motion. For `prefers-reduced-motion`, **adapt** essential animations
  (slow/soften) rather than zeroing them, because some motion carries meaning, and excessive or
  fast motion can trigger vestibular discomfort [6]. Typical UI durations sit in the 200–500 ms
  band [6].

## Recommendation

A frontend-only redesign in three priority tiers. **None of these change trading config**;
items needing a backend computation are additive (new read-only analytics), not strategy
changes. The one idea that touches strategy posture — *stop trading no-edge cities* — is already
in the backlog from the per-city diagnostic; the UI here only *visualizes* it.

### P0 — Re-point the existing UI at the right metrics (cheap, no backend work)

1. **Decision hero (Live tab).** Replace the 9-equal-metric band with an F-pattern hero:
   - **Primary (largest, top-left):** *Net realized edge after fees* (cumulative), with the
     7-day sparkline already available (`series[]`) and a permanent `after $X fees` subline.
   - **Secondary (top-right):** *Risk headroom* — two horizontal fuel-gauges (cum P&L vs −$1,000;
     today vs −$300) built from `agg.*`; turns amber/red as `killArmed` approaches. This is the
     glanceable "are we safe" answer.
   - **Secondary:** *Expectancy* ($/settled trade), *profit factor*, *avg win ÷ avg loss* —
     computed client-side from `fills[]`/positions. Demote win-rate to a small subline.
   - **Tertiary strip:** balance / cash / portfolio + system health (WS `source·ageMs`,
     `hrrr.age`, `nextCron` countdown).
2. **Per-city: live cities first.** Render KORD & KMIA as full cards (realized, unrealized,
   risk-headroom gauge, **today's fill % + avg slippage**), and collapse paper/backtest cities
   into a secondary "watchlist" row. Add a **paper-vs-live Δ** chip per live city (F5).
3. **Honest motion.** Fix the reduced-motion block: instead of `0.001ms` on everything (which
   kills the count-ups that *convey* the delta), keep essential count-ups/draw-on but **slow and
   soften** them under `prefers-reduced-motion`, and drop only decorative motion (map pulse,
   shimmer) [6]. Gate live-poll tweens so a 2 s poll never restarts the 2,400 ms entrance draw.
4. **Promote the blend table (Backtest tab).** Turn `blend.*` into the F3 table with
   **negative-β cities flagged**, and a one-line "market does N% of the work here" callout.

### P1 — The two flagship additions (need a small read-only backend analytics endpoint)

5. **Calibration / reliability panel** — the "is the edge real" centerpiece. New endpoint
   aggregates settled `paper_trades ⋈ observations` into reliability bins for `model_P`,
   `blend_P`, `market_P`, with consistency bars and Brier/Brier-skill per series, per city and
   pooled [4][5]. Render as the lead visual of the (renamed) **Research** tab: three overlaid
   reliability curves on the 45° line + a Brier table. Also retires the hard-coded `brier=0.20`.
6. **Paper-vs-live divergence monitor** — per live city, plot *cumulative paper-expected* vs
   *cumulative live-realized* P&L on one axis, annotate the running gap and the realized fill-rate
   haircut (F4/F5). This is the panel that tells you whether it is safe to scale.
7. **Edge-decay strip** — rolling Brier (or rolling realized net-edge) over the 722-day span to
   show H1 vs H2 decay (F2), so "is the edge eroding" is a glance, not a query.

### P2 — Trim the fat & polish

8. **Remove dead/misleading controls:** the **Polymarket toggle** (venue expansion is future;
   ForecastEx, not Polymarket, is the live candidate — backlog), the **hard-coded `crons[]`
   green ticks** (wire real cron last-run/exit or delete — false safety is worse than no panel),
   and the placeholder chart legends.
9. **Demote the param-sweep under the freeze.** Move strategy/edge/sizing pickers into a
   collapsed "What-if (config frozen until 2026-07-10)" drawer with a freeze banner — progressive
   disclosure [1], and it stops the UI from inviting changes that are frozen.
10. **Map encodes the thesis:** highlight the robust subset (CHI/MIA/SEA) with the selection
    treatment and tag the rest "do not trade" (F2), instead of coloring all cities as tradable.
11. **Housekeeping:** retire legacy CSS aliases (`--pos/--neg/...`), wire the unused `.skeleton`
    shimmer into backfill loading states, add hover tooltips for precise values on every chart
    [1], and add `z-index` management to map-dot hover labels.

### Proposed Live-tab hero (annotated mockup)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  NET REALIZED EDGE (after fees)          RISK HEADROOM                 EXPECTANCY       │
│   +$100.04   ▁▂▃▄▅▆█  ▲ today +$x         cum  ███████░░░ 90% to kill   +$4.55 /trade   │
│   after $23.30 fees · 22 settled          day  ████░░░░░░ 41% used      PF 1.7 · W/L 4.2│
│                                                                          win 27% (6/22) │
├──────────────────────────────────────────────────────────────────────────────────────┤
│  bal $3,150  cash $2,940  port $210   │ ws·2 live·1.2s │ HRRR 45m │ next live_trade 3:12│
├──────────────────────────────────────────────────────────────────────────────────────┤
│  KORD Chicago  [LIVE]      paper↔live Δ +$x   │  KMIA Miami [LIVE]   paper↔live Δ −$y   │
│   realized +$.. unreal +$..  risk ███░ 30%    │   realized +$.. unreal +$..  risk ██░ 22%│
│   fill 79% · slip +0.4¢ · edge≥25%/10% blend  │   fill 83% · slip +0.2¢ · blend≥10%      │
└──────────────────────────────────────────────────────────────────────────────────────┘
  watchlist (paper): KSEA ·· KAUS ·· KDEN ·· KLAX ·· KPHX            [expand ▸]
```

### Proposed Research-tab lead (annotated mockup)

```
┌─ CALIBRATION — is the probability honest? ───────────┬─ BLEND CONTRIBUTION ─────────────┐
│ obs freq                                             │ city  β_model β_mkt  mkt-share   │
│ 1.0│                              ·· market          │ KORD  +0.19  +0.38   67%  ✓      │
│    │                        ·▵ blend (Brier .143)    │ KMIA  +0.55  +0.70   56%  ✓      │
│ .5 │              ·▵·  ____/  model (Brier .204)     │ KAUS  −0.10  +1.17   92%  ⚠ model│
│    │        __·▵·/      consistency bars ▕▏          │ KLAX  −0.07  +1.22   95%  ⚠ anti-│
│ 0  └────────────────────────────────→ predicted p   │           "market does the work" │
├─ EDGE DECAY (rolling Brier) ─────────────────────────┴──────────────────────────────────┤
│ H1 ▁▂▂▃  →  H2 ▄▅▆▆   edge eroding; robust subset = Chicago · Miami · Seattle only      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
   What-if (config frozen until 2026-07-10)  ▸                          [bracket ladder ▾]
```

### Effort / impact summary

| # | Change | Backend? | Effort | Impact |
|---|---|---|---|---|
| 1 | Decision hero (edge/headroom/expectancy) | no | M | ★★★ |
| 2 | Live-cities-first + fill/slip + paper↔live Δ | no | M | ★★★ |
| 5 | Calibration / reliability panel | small additive | L | ★★★ |
| 6 | Paper-vs-live divergence monitor | small additive | M | ★★★ |
| 3 | Honest reduced-motion + poll-gating | no | S | ★★ |
| 4 | Promote blend table, flag negative-β | no | S | ★★ |
| 7 | Edge-decay strip | small additive | M | ★★ |
| 8–11 | Trim Polymarket/placeholders, demote sweep, map, housekeeping | no | S–M | ★★ |

## Limitations & Threats to Validity

- **Live sample is tiny (22 settled).** Every live-derived number (expectancy, fill rate,
  paper-vs-live Δ) is high-variance; the UI must show n and confidence, not imply precision.
- **Design is iterative.** The mockups encode the *information hierarchy*, not final visuals;
  the exact hero metrics and gauge thresholds should be A/B'd in-browser against a time-to-answer
  benchmark [2], not shipped on assertion.
- **Calibration/divergence panels assume a new read-only aggregation endpoint** over
  `paper_trades ⋈ observations`; they are additive analytics, but they are not free, and must be
  built to avoid look-ahead (use the same walk-forward discipline as `walkforward_blends`).
- **Freeze boundary.** This paper deliberately stops at *visualizing* the edge-concentration and
  execution findings. Acting on them (dropping no-edge cities, changing execution mode) is a
  strategy decision reserved for the 2026-07-10 re-evaluation and already tracked in the backlog.
- **Memory point-in-time risk.** The Chicago live −$124 figure (F5) is a prior snapshot; the
  current aggregate book is +$100 net. The recommendation depends only on the *existence* of a
  paper-vs-live gap worth monitoring, not on that specific number.

## Sources

**External (verified against source):**
1. NN/G — *8 Design Guidelines for Complex Applications* (progressive/staged disclosure; ease
   primary↔secondary; reduce clutter without reducing capability).
   https://www.nngroup.com/articles/complex-application-design/
2. *Top Dashboard Design Best Practices for Traders* (F-pattern, 40-30-20-10 space rule, inverted
   pyramid, time-to-answer < 30 s). https://chartswatcher.com/pages/blog/top-dashboard-design-best-practices-for-traders-in-2025
3. NN/G — *Clutter-Free Charts / Data Visualizations for Dashboards* (chartjunk; preattentive
   length + 2-D position). https://www.nngroup.com/videos/chartjunk/ ·
   https://www.nngroup.com/videos/data-visualizations-dashboards/
4. Bröcker & Smith — *Increasing the Reliability of Reliability Diagrams*, Weather and Forecasting
   22(3), 2007 (consistency bars). https://journals.ametsoc.org/view/journals/wefo/22/3/waf993_1.xml
5. Dimitriadis, Gneiting & Jordan — *Stable reliability diagrams for probabilistic classifiers*,
   PNAS 2021 (CORP / PAV isotonic binning). https://www.pnas.org/doi/10.1073/pnas.2016191118
6. Smashing Magazine — *Creating Accessible UI Animations*, 2023 (`prefers-reduced-motion` =
   reduce not remove; adapt essential motion; durations).
   https://www.smashingmagazine.com/2023/11/creating-accessible-ui-animations/

**Internal (this session, read-only; reproducible):**
- `psql -d weather` — `live_trades` overview / by-city / fill-status & settlement;
  `paper_trades` coverage & per-city edge; `\d prices`, `\d forecasts`.
- Frontend map: `dashboard/static/{index.html, app.js, css/*.css}` (+ build notes).
- Backend contract: `dashboard/{app.py, data_live.py, data_backtest.py, kalshi_ws.py}`;
  `docs/context/{dashboard,strategy,goals-metrics,decisions,data-model}.md`.
- Memory findings: `project_per_city_diagnostic_finding`, `market-blend-finding`,
  `fill-rate-forward-test`.
