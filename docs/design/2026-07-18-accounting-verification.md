# Accounting tab — adversarial pre-merge verification (2026-07-18)

**Verifier:** independent (read-only). **Branch:** `feat/accounting-tab` (worktree `/home/tdunn/wt-accounting-tab`, all work uncommitted in working tree; branch tip = `8061483`, i.e. OLD main). **Preview:** `http://127.0.0.1:8001`. **Prod target:** `:8000`.

## VERDICT: GO — with 2 required pre-merge steps (both mechanical)

Every dollar the tab serves is live and correct. The withdrawal fix is real and the reconciliation ties to the cent WITH withdrawals. Tax math is correct, FL = $0. Migration 006 is purely additive. `uv run pytest` = **129 passed** (incl. sim parity). No hardcoded `1400` in production code.

**Two things MUST happen for a clean deploy (neither is a defect in the accounting logic):**
1. **Merge `data_live.py` via git, do NOT copy the file.** The branch's `data_live.py` was built off old main and is MISSING both just-merged live-tab fixes (`_daily_realized_series` and the `_vwap_entry_yes` NO-side fix). A git 3-way merge restores them cleanly (simulated: clean, 0 conflicts, all 3 fixes present). Overwriting main's file with the branch's would REGRESS both live-tab fixes.
2. **Resolve the trivial `index.html` conflict** — both main and the branch bumped the `<script src="/static/app.js?v=N">` cache-bust line (main→v9, branch→v10). Keep v10 (or higher). This is the only merge conflict.

---

## Per-value verification

Independent ground truth computed by calling `KalshiClient` directly (`GET /portfolio/{balance,deposits,withdrawals,settlements,positions,orders}`) in the worktree, and by re-querying the live DB. Compared against the running `:8001` `/api/accounting` payload.

Note on "live-moving" rows: `portfolioValue`, `accountValue`, `cumulativePnl`, `openUnrealized` are marked-to-market and legitimately change between two calls seconds apart. The :8001 payload (16:53:45), my independent recompute (~16:54), and the DB snapshot row (16:52) show pv = 309.65 / 346.29 / 369.08 respectively — same source (`get_balance().portfolio_value`), just three capture times. Every fee/realized/transfer quantity that should NOT move is **identical** across all three.

| Value | Tab (:8001) | Independent | Status | Source |
|---|---|---|---|---|
| Withdrawals total | 1400.00 (1 row, id `019f4dd3…`, 2026-07-10, ACH) | 1400.00 | **PASS** | `GET /portfolio/withdrawals`, status='applied' |
| Deposits total | 3050.00 (1000+1000+1000+50) | 3050.00 | **PASS** | `GET /portfolio/deposits`, status='applied' |
| Referral credit | 14.99 | 14.99 (documented constant) | **PASS** | audited non-API constant, disclosed in UI |
| Cash | 4267.32 | 4267.32 | **PASS** | `get_balance().balance_dollars` |
| Portfolio value | 309.65 | 346.29 (live mark) | **PASS** | `get_balance().portfolio_value` |
| Account value | 4576.97 | 4613.61 (live mark) | **PASS** | cash + pv |
| Open cost basis | 319.27 | 319.27 | **PASS** | `get_positions()` total_traded_dollars |
| Open-order margin | 55.00 | 55.00 | **PASS** | `get_orders(resting)` buy-only × price |
| Net external capital | 1664.99 | 1664.99 | **PASS** | 3050 + 14.99 − 1400 |
| Cumulative P&L | 2911.98 | 2948.62 (live mark) | **PASS** | account_value − net_external |
| Total realized | 2921.60 | 2921.60 | **PASS** | cumulative − open_unrealized (mark cancels) |
| Settled gross (YTD) | 1654.81 | 1654.81 | **PASS** | Σ(revenue − cost) settlements |
| Settled fees (YTD) | 124.83 | 124.83 | **PASS** | Σ fee_cost |
| Settled net (YTD) | 1529.98 | 1529.98 | **PASS** | gross − fees |
| N settled (YTD) | 114 | 114 (all in 2026) | **PASS** | settlement count |
| Intraday realized (plug) | 1391.62 | 1391.62 | **PASS** | total_realized − alltime_net |
| Realized net taxable | 2921.60 | 2921.60 | **PASS** | ytd_net + intraday |
| FL state tax | 0.00 | 0.00 | **PASS** | hardcoded stateRate=0 |

### (a) Are withdrawals live and correct (incl. the $1,400)? — YES
`data_accounting.fetch_transfers()` calls `_paginate(... "/portfolio/withdrawals" ...)` (new `KalshiClient.get_withdrawals`) and filters `status=='applied'`. It returns the single real withdrawal: **$1,400.00, ACH, id `019f4dd3-4b2e-70d5-a26a-08853ba25b7d`, finalized 2026-07-10** — exactly the operator's out-of-band withdrawal. I called the endpoint myself and got 1400.00. Grep of the whole diff for `1400`/`140000`/`1,400` hits **only test files** (fixtures) — **zero hardcodes in production code**. The only non-live constant in the module is `REFERRAL_CREDIT = 14.99` (documented, audited, disclosed in the UI as "audited, non-API").

### (b) Does the reconciliation tie to the cent WITH withdrawals? — YES
Identity used everywhere (data_accounting, migration 006, snapshot script, and now `reconcile_by_city` via the `withdrawals=` param): `net P&L = account_value − deposits − referral + withdrawals`.
Independent check: `4613.61 − 3064.99 + 1400.00 = 2948.62` == `cumulativePnl` → **MATCH=True**. Withdrawals genuinely enter the identity — this fixes the pre-existing bug where `account_value − deposits` (no withdrawal term) under-reported P&L by exactly the $1,400 pulled. Withdrawals are also correctly **neutral to realized P&L** (a withdrawal lowers cash by W and adds W back in the identity → net zero on `total_realized`), so they do not inflate the taxable base.

### (c) Is the tax math correct and FL = $0? — YES
- FL: payload `stateRate=0.0, stateTax=0.0, stateName="Florida"`; UI renders `$0.00` with "no state income tax". PASS.
- Reserve (client-side): `max(0, realizedNetTaxable) × fedRate + stateTax`. Verified to the cent at 4 rates against my recompute: 24%→**701.18**, 32%→**934.91**, 37%→**1080.99**, 26.8%(§1256)→**782.99**. `max(0,…)` correctly zeroes reserve on a net loss.
- Taxable base excludes open positions (uses realized only) and withdrawals (they cancel). PASS.
- Disclaimer: prominent top banner **"Estimate only — not tax advice"** (unsettled ordinary vs §1256 treatment, 1099 variance, "consult a professional") plus a fine-print footer restating base composition and "does not file, remit, or advise." PASS.

### (d) Is migration 006 safe to apply to prod? — YES (and already applied)
`006_account_equity_snapshots.sql` is a single `CREATE TABLE IF NOT EXISTS account_equity_snapshots (…)` — a brand-new isolated table, PK `snapshot_date`, **no ALTER/DROP, no touch of any existing table**. Purely additive; re-running is a no-op. **State note: the table already exists in the live DB with a schema that matches the file exactly**, so migration 006 has effectively already been applied (re-applying is harmless).

### (e) Does pytest (incl. sim parity) pass? — YES
`uv run pytest` in the worktree → **129 passed, 1 warning** (harmless Herbie deprecation). Explicitly ran `test_accounting.py + test_snapshot_account_equity.py + test_sim_parity.py` → **16 passed**. Sim parity intact (the branch does not touch `sim_python.py`/the parity slice, and `app.js` changes are additive/disjoint).

### (f) Will merging conflict with / regress the live-tab fix on main? — NO regression via git; 1 trivial conflict
- `data_live.py`: 3-way merge simulated with `git merge-file` (base=8061483, ours=branch, theirs=main) → **clean, 0 conflict markers**, merged file contains **all three** changes (`_daily_realized_series` ×3, `open_action` NO-side fix ×1, and the accounting `withdrawals=` fix ×1). The branch's edit (withdrawals in `_kalshi_reconciliation`) and main's edits (`_daily_realized_series`, `_vwap_entry_yes`) are in disjoint regions. **Caveat: the branch's working-tree `data_live.py` in isolation LACKS both live-tab fixes** — it must be brought in by a git merge, never by copying the branch file over main's.
- `app.js`: 3-way merge **clean, 0 conflicts** (main edited `pnlChartSVG` ~line 142; branch added accounting functions ~line 1516 + the `switchTab` tab-list). No regression to the rolling cumulative-P&L graph.
- `index.html`: **1 conflict** — the `<script src="app.js?v=N">` cache-bust line (main v9 vs branch v10). Resolve to v10+. No logic involved.

---

## Deploy-state findings (partial deploy already executed ahead of approval)

These are not accounting defects, but the deploy has been partly performed before this verification/merge:
1. **Migration 006 already applied to prod** (table exists, exact schema match). Fine — additive.
2. **1 snapshot row already written** to the live DB: `2026-07-18`, created 16:52:53 UTC (a manual `uv run python scripts/snapshot_account_equity.py` from the worktree, not the cron whose time is 04:15). Row identity checks out: `4636.40 − 3050 − 14.99 + 1400 = 2971.41` = `computed_pnl_dollars` ✓. The write path is benign: idempotent upsert into the new isolated table; touches no existing table and no trading state.
3. **Snapshot cron already installed** in the live crontab (`15 4 * * * … scripts/snapshot_account_equity.py`), pointing at `/home/tdunn/weather-project` (main). Since the script is **not yet merged to main**, this cron currently **fails harmlessly** to `/var/log/weather/equity_snapshot.log` every day at 04:15 (the cron comment acknowledges this). Merging the branch to main clears it. The crontab hard-rule (edit `docs/crontab.txt` then install) was followed.

**Implied deploy order:** merge branch → main first, then the already-applied migration/cron become fully functional. Nothing needs to be un-done.

## Minor notes / known ceilings (none blocking)

- **Intraday-realized plug (~$1,392, ~48% of the taxable base)** is derived as `total_realized − alltime_net`, i.e. an identity residual, because Kalshi's per-fill feed is capped/mis-signed and can't be itemized. It is internally consistent and honestly disclosed in the UI (ⓘ tooltip). It absorbs *any* balance-vs-settlement discrepancy into the taxable base — acceptable and disclosed, but not independently itemizable.
- **Single-tax-year assumption:** `realizedNetTaxable = ytd_net + intraday_realized` is exact only because all 114 settlements are in 2026 (`alltime_net == ytd_net`, confirmed). On/after 2027-01-01 the all-time intraday plug would mix prior-year realized cash into the current-year base. Add a year filter (or a snapshot-delta approach) before the next tax year. Not a now-issue (July 2026).
- **Transfer partial-failure edge:** in `data_live._kalshi_reconciliation`, if the deposits fetch returns rows but the withdrawals fetch transiently returns none, `withdrawals=0` would be used with live deposits (brief under-count). Primary path is fully live; the whole block is wrapped in try/except → None fallback. Low risk.

## What I did NOT do
Modified no code. Did not run migration 006, did not commit, did not merge, did not restart/kill `:8000` or `:8001`. All DB access was SELECT-only; all Kalshi calls were GET. Merge simulations used `git merge-file -p` on scratchpad copies (no repo state touched).
