# Migration: Nuremberg (Hetzner EU) → Ashburn VA (Hetzner US)

**Why:** Polymarket began geo-gating order placement on 2026-08-30 (`403
GEO_BLOCKED_STATE`, "Trading isn't available in Bavaria"). Kalshi has not yet,
but the whole operation trades US-regulated venues from a German IP, and Kalshi
is where the money is (+$3,346 cumulative). Secondary driver: DISK. Measured growth over the last 14 days is 852 MB/day
(orderbook 506, prices 281, PM orderbook 65), and the old box has 16 GB free —
**19 days, not the two months first estimated from lifetime averages.**

**Scope:** full migration. Ashburn becomes primary; Nuremberg is decommissioned.

**Active work ≈ 4–5 hours, spread over 3–4 calendar days** (the elapsed time is
the parallel-run soak, not labour).

Only ORDER PLACEMENT is geo-blocked — reads (balances, positions, orderbook) work
fine from Germany, verified 2026-08-31. So there is no rush on the data side; the
urgency is only on the ~4 live-trader crons.

---

## Phase 0 — Commit and push FIRST (30 min) ⚠️ BLOCKING

There are 40 uncommitted files on `feat/ibkr-forecastex-execution`. A clone on
the new box would silently omit a week of work, including money-path fixes:
PM bracket semantics, YES-leg price inversion, GEFS per-station timeout,
ForecastEx cap sizing, the PM win-field reconciler fix, dashboard ET timestamps.

    git status                       # read it, do not blind-add
    git add -A && git commit
    git push -u origin feat/ibkr-forecastex-execution

Verify from another machine that the push landed before touching anything else.

## Phase 1 — Provision (20 min)

Hetzner Cloud → Ashburn, VA. Size for where you are going:

- **CPX31 (4 vCPU / 8 GB / 160 GB)** minimum, CPX41 if budget allows.
- Current box is 7.6 GB with NO swap and OOM is a standing risk with Postgres +
  dashboard + IBKR gateway + ingestion competing. **Add 4 GB swap this time.**
- Ubuntu 24.04 to match (`Python 3.12.3` comes from the distro).

        fallocate -l 4G /swapfile && chmod 600 /swapfile
        mkswap /swapfile && swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab

Create the `tdunn` user, copy your SSH pubkey, disable password auth.

## Phase 2 — Base system (45 min)

Pin the versions — a TimescaleDB mismatch makes restore painful.

    PostgreSQL 17.9   (pgdg apt repo)
    TimescaleDB 2.26.4 (timescale apt repo)
    uv 0.11.8         (curl -LsSf https://astral.sh/uv/install.sh | sh)

    sudo -u postgres createuser --superuser tdunn
    sudo -u postgres createdb -O tdunn weather
    psql -d weather -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
    sudo mkdir -p /var/log/weather && sudo chown tdunn:tdunn /var/log/weather

Local peer auth, no password — same as now (see CLAUDE.md).

## Phase 3 — Secrets (10 min)

Two files, never in git:

    scp ~/.kalshi/key.pem   newhost:~/.kalshi/key.pem     # chmod 600
    scp .env                newhost:~/weather-project/.env # chmod 600

`.env` keys that must be present (values from the old box):
`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `DATABASE_URL`,
`IBKR_ACCOUNT_ID`, `KALSHI_API_BASE`, `KALSHI_KEY_ID`, `KALSHI_KEY_PATH`,
`LOG_LEVEL`, `POLYMARKETDATA_API_KEY`, `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET`.

`KALSHI_KEY_PATH` is absolute — confirm it still resolves on the new box.

## Phase 4 — Data (45 min – 2 h, mostly waiting)

**Stream it. Do not dump to a file** — only 16 GB is free on the old box and a
full dump will not fit.

Sizes: `prices` 20 GB, `orderbook_snapshots` 15 GB,
`polymarket_orderbook_snapshots` 2.7 GB, `forecasts` 620 MB,
`observations` 25 MB.

**DECISION (2026-08-31): carry EVERYTHING. Do not trim.** The two orderbook
tables are already compressed (policy: compress_after 30 days). The table that
is NOT compressed is `prices` — 20 GB, 119 uncompressed chunks, the biggest
object in the database and the one backtests actually need. Compressing it is
worth more than trimming both orderbook tables and keeps every row:

    trim both orderbook tables   frees 17.7 GB, loses an unrecreatable capture
    compress `prices`            frees ~18 GB (10x typical on bid/ask), loses nothing

    pg_dump -d weather --no-owner | ssh newhost 'psql -d weather -v ON_ERROR_STOP=1'

TimescaleDB note: restore may need `SELECT timescaledb_pre_restore();` before and
`timescaledb_post_restore();` after. Check the 2.26 docs for the exact dance —
this is the step most likely to bite.

**Verify before proceeding:**

    -- run on BOTH, numbers must match
    SELECT 'forecasts',    count(*) FROM forecasts
    UNION ALL SELECT 'observations', count(*) FROM observations
    UNION ALL SELECT 'prices',       count(*) FROM prices
    UNION ALL SELECT 'contracts',    count(*) FROM contracts
    UNION ALL SELECT 'paper_trades', count(*) FROM paper_trades
    UNION ALL SELECT 'live_trades',  count(*) FROM live_trades
    UNION ALL SELECT 'pm_live_trades',count(*) FROM pm_live_trades
    UNION ALL SELECT 'fx_live_trades',count(*) FROM fx_live_trades;

    -- P&L must tie exactly; this is the number the kill switches read
    SELECT sum(realized_pnl_cents) FROM live_trades;
    SELECT sum(realized_pnl_cents) FROM pm_live_trades;   -- expect +9438

## Phase 5 — Repo and env (20 min)

    git clone git@github.com:thomasdunn15/weather-project.git
    cd weather-project && git checkout feat/ibkr-forecastex-execution
    uv sync
    uv run pytest      # expect 260 passed, 1 known failure
                       # (test_kord_dry_run_exits_cleanly — pre-existing)

Do NOT copy `.venv` (618 MB, rebuilt by `uv sync`).

**`data/` IS GITIGNORED AND MUST BE COPIED BY HAND (3.4 MB).** Missed on the
first pass, and it took the ForecastEx/Robinhood tab down with a 500 on
2026-08-31 — a fresh clone has no `data/` directory at all:

    rsync -av data/ newhost:~/weather-project/data/

`forecastex_spread.json` and `forecastex_settlements.json` are read by
`live_trade_forecastex.py` itself, so this is a CUTOVER blocker for that city,
not just a dashboard nicety. `forecastex_settlements.json` also stops the 05:00
backtest cron re-downloading every settled ladder from scratch.

`~/data/{gefs,ifs,hrrr,aifs}` (312 MB) is a separate GRIB download cache outside
the repo. It rebuilds on demand — leave it.

## Phase 6 — Services as systemd, not tmux (1 h)

Three services currently run in hand-started tmux sessions. They die on reboot
and exist nowhere in version control. CLAUDE.md already lists "persistent
dashboard service" as a known gap — fix it here rather than recreating it.

    dashboard     uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
    ibkr gateway  cd ~/ibkr-gateway && bin/run.sh root/conf.yaml
    monitor_loop  uv run python scripts/monitor_fills.py --loop 15 ...

Write three units in `/etc/systemd/system/`, each with `Restart=always`,
`User=tdunn`, `WorkingDirectory=/home/tdunn/weather-project`,
`EnvironmentFile=/home/tdunn/weather-project/.env`. Then
`systemctl enable --now weather-dashboard weather-ibkr weather-monitor`.

**The IBKR gateway is the hard part.** Copy `~/ibkr-gateway` wholesale (it is a
Java app: `bin/ build/ dist/ root/conf.yaml`), confirm it still binds loopback,
then re-authenticate through the SSH tunnel:

    ssh -N -L 5000:localhost:5000 tdunn@newhost   # then open https://localhost:5000

Budget real time here — it has needed a restart twice this week, and a stale SSO
presents as "login does nothing" (see `scripts/ibkr_keepalive.py` header).

## Phase 6b — Compress `prices` (20 min + background)

The single highest-value step for disk. Without it the new box has ~143 days of
runway; with it, 900+.

    ALTER TABLE prices SET (timescaledb.compress,
                            timescaledb.compress_segmentby = 'ticker');
    SELECT add_compression_policy('prices', INTERVAL '7 days');

**CHECK FIRST:** compressed chunks are read-only on older TimescaleDB versions.
If any `backfill_*` script rewrites `prices` history, a 7-day delay will block
it — widen the interval or decompress before backfilling. Verify against
`scripts/backfill_*.py` before enabling.

Consider `forecasts` too (620 MB, 127 uncompressed chunks) — smaller win, same
one-liner.

## Phase 7 — Parallel run, 2–3 days (30 min active)

Install the crontab with **every live trader commented out**:

    cp docs/crontab.txt /tmp/crontab.new
    # comment out: live_trade.py, live_trade_polymarket.py, live_trade_forecastex.py
    crontab /tmp/crontab.new

Let both boxes ingest side by side for 2–3 days, then diff:

    -- on both, for the same day
    SELECT model, count(DISTINCT station_id), count(*) FROM forecasts
    WHERE init_time >= CURRENT_DATE - 2 GROUP BY 1 ORDER BY 1;
    SELECT count(*) FROM paper_trades WHERE target_date >= CURRENT_DATE - 2;

Paper trades should match row for row. If they do, the model pipeline is
faithful. Also confirm on the new box:

- `/var/log/weather/*.log` are being written by the right jobs
- the dashboard serves correct numbers (`/api/live` cash must equal the Kalshi
  venue balance; `/api/accounting` identity `netExternalCapital + cumulativePnl
  = accountValue` must hold)
- `uv run python scripts/ibkr_keepalive.py` reports a live session

## Phase 7b — Polymarket moved early (2026-08-31)

Polymarket is the ONLY thing the geo-block breaks, and it has been broken since
08-29 (403 `GEO_BLOCKED_STATE` every day). So it moved ahead of the rest rather
than waiting for Phase 8: there is nothing to lose by moving a cron that always
fails, and the sooner it runs from Virginia the sooner we know placement works.

    NUREMBERG   Kalshi KMIA armed  ·  Polymarket DISARMED
    ASHBURN     Kalshi guarded off ·  Polymarket ARMED

`docs/crontab-ashburn.txt` holds the Ashburn side; it differs from
`docs/crontab.txt` in exactly those two lines and is DELETED at cutover, when
Ashburn takes `docs/crontab.txt` wholesale.

**This splits the P&L record.** `pm_live_trades` rows now land only in Ashburn's
database, and `reconcile_pm_trades.py` only ever UPDATEs — it never INSERTs — so
Nuremberg cannot learn about them from the venue either. Consequences:

- Nuremberg's dashboard under-reports Polymarket from 2026-09-01 onward. Expected.
- **The Phase 8 delta-sync must NOT copy `pm_live_trades` from Nuremberg.** It
  would overwrite the only copy of the new rows with a stale one. Sync the
  Kalshi-side tables only.
- **`rh_entries` (manual Robinhood positions, migration 012) is written by
  whichever box's dashboard the operator pressed the button on.** Before
  Tailscale (2026-09-03) that was Nuremberg over the SSH tunnel; after, it is
  Ashburn. Rows were copied 2026-09-03. At cutover, copy any Nuremberg rows
  newer than that — they are the only record those positions exist.

## Phase 7c — MOVE `halt/`. IT IS GITIGNORED. ⚠️

Same class of miss as `data/`, and worse consequences. `halt/` carries the
kill-switch state and a fresh clone has none of it:

    halt/KORD    KORD cumulative $-708.22 below -$500   (2026-07-24)
    halt/KDFW    KDFW cumulative $-615.06 below -$500   (2026-08-07)
    halt/KPHX    KPHX cumulative $-384.23 below -$375   (2026-07-21)
    halt/FX_KDFW operator hold
    halt/FX_KMIA operator hold — ForecastEx retired

Without these, a cutover box would happily re-arm three cities that were halted
for losses the moment anyone uncommented their crons.

    rsync -av halt/ newhost:~/weather-project/halt/

Re-run this immediately before cutover, not just once — a kill switch can fire
in the parallel-run window.

## Phase 8 — Cutover (30 min, do it after a decision time, not before)

Traders move last and atomically — running both boxes live would double every
order.

1. On **Nuremberg**: `touch halt/ALL` and comment out all live-trader crons.
2. Confirm no open positions anywhere (Kalshi positions endpoint, PM positions,
   IBKR live orders).
3. On **Ashburn**: uncomment the live traders, `crontab docs/crontab.txt`.
4. Remove `halt/ALL` on Ashburn only.
5. Watch the first live run end to end. Do not walk away for it.

Polymarket should now place orders — the geo-block was the whole reason for this.
Worth confirming with Polymarket support that the account is in good standing,
given it traded from a German IP from 08-13 to 08-30.

## Phase 9 — Decommission (later, unhurried)

Keep Nuremberg powered off but not deleted for ~2 weeks. If you trimmed the
orderbook tables, dump them to object storage before deleting the box — that
depth data is a live capture that cannot be recreated.

---

## Time summary

    Phase 0  commit + push          30 min   BLOCKING
    Phase 1  provision              20 min
    Phase 2  base system            45 min
    Phase 3  secrets                10 min
    Phase 4  data transfer          45 min – 2 h   (mostly waiting)
    Phase 5  repo + env             20 min
    Phase 6  systemd services        1 h           (IBKR is the risk)
    Phase 7  parallel verify        30 min active over 2–3 days
    Phase 8  cutover                30 min
                                   ─────────
                          active ≈ 4–5 hours, elapsed 3–4 days

## Things that will bite

1. **TimescaleDB restore** — version mismatch or a missed `pre_restore`/
   `post_restore` is the most likely hard failure.
2. **IBKR gateway** — flakiest component you own; a stale SSO looks like a
   broken login page.
3. **Absolute paths** — `KALSHI_KEY_PATH`, cron paths, `HALT_DIR`, log paths.
   All 44 cron lines use absolute paths; they should port unchanged, but the
   `uv` binary path (`/home/tdunn/.local/bin/uv`) must exist.
4. **Cron verification takes a full 24 h cycle.** 44 jobs, 27 distinct scripts —
   you will not know they all fire until a day has passed. This is why Phase 7
   exists and why cutover happens after, not during.

---

## Executed 2026-09-11 — consolidation onto Ashburn

Ashburn had run the full pipeline in parallel since 08-31 (identical crontab
minus the Kalshi trader, own copy of every ingest, dashboard as systemd, schema
fingerprints and secrets byte-identical, health check green daily). The delta
that still lived only in Nuremberg, and what was done with it:

| item | action |
|---|---|
| 22 unpushed branches + today's threshold commit | pushed; origin holds 24 heads |
| `rh_entries` ids 13–37 (phone entries after 09-03) | staged + inserted on Ashburn, sequence advanced; both boxes 26 rows / max 37 |
| `paper_trades` gaps since 08-31 | insert-where-missing both ways of the diff: Ashburn 491 vs Nuremberg 486 |
| `live_trades` ids 189–212 (Kalshi orders since 08-31) | copied at cutover (Phase 8 below) |
| `~/ibkr-gateway`, `~/.notebooklm`, `~/.claude-mem`, Claude memory, `outputs/`, `halt/`, `data/` | rsync'd (`--update` where Ashburn writes too) |
| `/var/log/weather` (709 MB) | `archive-weather-01-2026-09-11.tar.gz` (16 MB) on Ashburn |
| Tailscale | installed on Ashburn; `tailscale up` + `tailscale serve --bg 8000` are operator steps (browser auth) |
| phone SSH key | added to Ashburn `authorized_keys` |
| `docs/crontab-ashburn.txt` | deleted; `docs/crontab.txt` now arms both traders and is the only crontab |

**Not merged, deliberately:** the snapshot hypertables differ by 0.07–0.2% since
08-31 (timing noise; Ashburn's own capture is complete and it has MORE
forecasts). `pm_live_trades` was never copied from Nuremberg (Phase 7b rule).
IB Gateway is copied but not started — ForecastEx is retired (`halt/FX_*`).

### Phase 8 executed 2026-09-11 23:30 UTC

Window: after the 20:00 cancel-unfilled, before the 04:00 reconcile — no Kalshi
order in flight. Nuremberg crontab emptied (saved at
`~/crontab-weather-01-final-2026-09-11.txt`), dashboard tmux killed, uvicorn
stopped; Tailscale serve could not be reset without sudo and dies with the box.
`live_trades` 189–212 staged + inserted on Ashburn, sequence advanced;
`rh_entries` and `halt/` re-synced; `docs/crontab.txt` installed on Ashburn
(40 active lines, Kalshi 15:30 and Polymarket 14:47 both armed; pre-cutover
copy at `~/crontab-ashburn-pre-cutover-2026-09-11.txt`).

**Verify:** both boxes 208 `live_trades` rows / max id 212, 26 `rh_entries`,
6 `fx_live_trades`. Kalshi realized did NOT tie at first: 210,111c Nuremberg vs
198,322c Ashburn. Cause: rows 187 and 188 (the 08-31 15:30 orders) were managed
by BOTH boxes that evening — each box's 20:00 cancel finalized one row and left
the other `partial_resting`, which `reconcile_live_trades.py` never settles.
Ashburn's 187 was repaired from Nuremberg's settled copy; Ashburn now holds both
(187 yes +264.61, 188 no +146.72) and sums to **224,783c ($2,247.83)**, 174
settled. This is the number the Kalshi kill switch reads.

**Found en route, NOT fixed (separate decision):** `reconcile_one` computes
`per_contract_pnl * count` with `lt.count` = ORDER size, not `fill_count`. Row
187 filled 22 of 500 yet is booked as 500 contracts (+$264.61 instead of
~+$11). Every partial fill is overstated the same way, and the cumulative kill
switch sums this column.

**Still operator:** `sudo tailscale up` + `sudo tailscale serve --bg 8000` on
Ashburn (phone dashboard → `https://weather-ashburn.tailde76e8.ts.net`); watch
the first Kalshi fire from Ashburn at 15:30 UTC 2026-09-12; Hetzner snapshot +
delete of Nuremberg after a few clean days (Phase 9).
