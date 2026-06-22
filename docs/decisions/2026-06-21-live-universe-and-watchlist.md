# Live universe & watchlist — formalized 2026-06-21

> **SUPERSEDED for Dallas by [2026-06-22-dallas-live-override.md](2026-06-22-dallas-live-override.md).**
> On 2026-06-22 the operator took **Dallas (KDFW) LIVE at minimal size** as a deliberate
> override of the deploy bar — the Dallas **paper-watchlist** status recorded below no longer
> holds. Chicago + Miami below are unchanged. The deploy bar itself is **not** relaxed.

**Decision:** Formally fix the live trading universe at **Chicago (KORD) + Miami (KMIA)**,
and define the tiers below it (watchlist / paper-watchlist / rejected). **No live config
changes** — Chicago and Miami are already the live cities; this record makes the boundary
explicit and data-driven, and stands up forward tracking for the one promotion candidate.

This is documentation + a paper-watchlist, **not a live param flip.** Nothing here clears
the deploy bar that would justify adding or changing a live city. See
[../context/decisions.md](../context/decisions.md), [edge-test-protocol.md](edge-test-protocol.md),
and memory `feedback_deploy_bar`.

## The deploy bar (unchanged)

Promote a city/config to live **only if** its **out-of-sample (walk-forward) Sharpe > 2.5**
on realistic execution (net Kalshi fees; the stricter of maker ~70%-fill / taker ~99%-fill)
— **not** the in-sample / dashboard / best-of-~360-configs number, which manufactures
Sharpe 3–6 for almost any city. Robustness = positive at **baseline AND both history halves
AND walk-forward**. As of 2026-06-21 nothing new clears the bar.

## Tiers

Source: per-city diagnostic `docs/research/md/2026-06-20-per-city-strategy-diagnostic.md`
(21,318 settled high-temp signals, 1-contract sizing, fee-aware net P&L, single 70/30
walk-forward fold). Memories: `project_per_city_diagnostic_finding`,
`project_p4_model_weighted_backtest_finding`, `feedback_deploy_bar`.

| City | Tier | Baseline | Both halves | Walk-fwd OOS (profit / n / ¢/trade / Sharpe) | Rationale |
|---|---|:--:|:--:|---|---|
| **Chicago (KORD)** | **LIVE** | ✅ | ✅ | +$3.02 / 69 / +4.38¢ / **1.58** | Robust edge; one of two cities passing all sign gates. Already live. |
| **Miami (KMIA)** | **LIVE** | ✅ | ✅ | +$2.66 / 102 / +2.61¢ / **1.00** | Robust edge (blend-only); passes all sign gates. Already live. |
| **Seattle (KSEA)** | **NOT live — monitor** | ✅ | ✅ | +$2.04 / 56 / +3.64¢ / **1.76** | Sign-robust but OOS Sharpe ~1.5–1.8, **below the 2.5 bar**. User's explicit call: not live yet. Thin/decaying. |
| **Dallas (KDFW)** | **~~PAPER-WATCHLIST~~ → LIVE (override 2026-06-22)** | ❌ | ❌ | +$3.17 / 27 / +11.74¢ / **4.52** | The **only** city clearing OOS Sharpe > 2.5 — but on **n=27**, with **negative baseline (−$7.18, Sharpe −1.93)** and both halves negative. The diagnostic calls it a "tuned OOS blip, not trustworthy." **Taken live at minimal size 2026-06-22 by operator override** (not a bar clearance) to gather honest live data — see [2026-06-22-dallas-live-override.md](2026-06-22-dallas-live-override.md). |
| **Los Angeles (KLAX)** | **REJECTED** | ❌ | ❌ | +$2.31 / 22 / +10.50¢ / 2.33 | Single-fold OOS marginally positive but **Sharpe 2.33 < 2.5** and baseline/both-halves negative — in-sample mirage, fails the gates. |
| **Las Vegas (KLAS)** | **REJECTED** | ❌ | ❌ | −$2.22 / 26 / −8.54¢ / **−2.65** | Gorgeous in-sample, **negative out-of-sample**. Fails outright. |

NY / Denver / Austin / New Orleans / Phoenix: no edge anywhere — do not trade (the honest
"best parameter" is *flat*). The all-11-city baseline portfolio **loses** −$149 (Sharpe −2.62);
the Chicago+Miami(+Seattle) robust subset is the only profitable, walk-forward-confirmed
slice (+$46.51, Sharpe 2.37, P/DD 3.50). This is the data-driven reason the repo previously
listed as "inferred only" for why Chicago & Miami were the first live cities.

## Validated per-city params (reference)

Walk-forward-confirmed "truly best" params from the diagnostic (the parameter that is both
composite-best on full history **and** survives the 70/30 fold):

| City | Family | Threshold | Side | Price band |
|---|---|---|---|---|
| Chicago | combined + HRRR | \|edge\| ≥ 0.25 | both | all prices |
| Miami | GEFS | \|edge\| ≥ 0.15 | both | 10–90¢ |
| Seattle (watchlist) | combined | \|edge\| ≥ 0.15 | both | 10–90¢ |

**Open execution thread (separate, NOT changed here):** live KORD does **not** run the
diagnostic's raw combined+HRRR T0.25 rule — it runs a **UNION (raw ≥ 25% OR blend ≥ 10%)**
at unit-500 (`scripts/live_trade.py CITY_CONFIG["KORD"]`). The diagnostic evaluated 1-contract
raw thresholds, not the union, and got OOS Sharpe 1.58; the P4/deploy-bar work
(`project_p4_model_weighted_backtest_finding`) put KORD flat+blend OOS at 2.25 (stricter exec)
/ 3.55 (maker-only). Reconciling which KORD config the deploy bar is measured against — and the
fill-rate/execution question that drags maker→stricter — is a **distinct open thread**
(`project_fill_rate_forward_test`). It is **deliberately out of scope for this record**: no live
KORD params are touched here.

## Dallas paper-watchlist — what was stood up

- **Rule tracked:** KORD-style **UNION at raw T=0.25** — fire if `|raw_edge| ≥ 0.25` OR
  `|blend_edge| ≥ 0.10` (raw side wins the tie-break; blend-only takes the blend side).
- **How samples accumulate:** the daily paper cron (`scripts/paper_trade_log.py`) already logs
  the Dallas **raw** signal (`model_source = "EMOS combined 00Z Dallas (rolling 45d)"`) every
  trading day — 357 settled rows as of 2026-06-20. **No cron or live-config change is needed**
  for the forward sample to grow. (The cron logs no Dallas *blend* variant — `get_blend` needs
  ≥100 settled and Dallas never had one logged — so the tracker reconstructs the blend leg
  itself with the production lookahead-free `walkforward_blends`.)
- **Tracker:** `scripts/analysis/dallas_watchlist.py` (read-only; paper_trades only). Reports
  full-sample (in-sample, context only) and **forward-OOS since 2026-06-21** (the graduation
  clock) net P&L, ¢/trade, daily annualized Sharpe, P/DD, win%, vs the 2.5 bar:

  ```
  uv run python scripts/analysis/dallas_watchlist.py
  ```

  In-sample union (context, selection-biased): 111 trades, +$8.44, +7.60¢/trade, Sharpe 3.41,
  P/DD 4.10. Forward-OOS: 0 trades on 2026-06-21 (data ends 06-20) — fills in daily.

- **Graduation gate:** promote Dallas to live **only** if the **forward** OOS holds
  **Sharpe > 2.5 on a meaningfully larger sample** (the n=27 blip is not enough) — and ideally
  turns baseline/both-halves positive. Until then: paper only.

## Hard constraints honored

- No live trading params changed (`scripts/live_trade.py` untouched; KORD/KMIA configs intact).
- Paper + docs only. The watchlist is reconstructed from already-logged paper signals.
- Deploy bar reaffirmed, not relaxed.

## See also

[../context/decisions.md](../context/decisions.md) · [../context/strategy.md](../context/strategy.md) ·
[../backlog.md](../backlog.md) · [edge-test-protocol.md](edge-test-protocol.md) ·
`docs/research/md/2026-06-20-per-city-strategy-diagnostic.md`
