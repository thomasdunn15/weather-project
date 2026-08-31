# Migration: Nuremberg (Hetzner EU) → Ashburn VA (Hetzner US)

**Why:** Polymarket began geo-gating order placement on 2026-08-30 (`403
GEO_BLOCKED_STATE`, "Trading isn't available in Bavaria"). Kalshi has not yet,
but the whole operation trades US-regulated venues from a German IP, and Kalshi
is where the money is (+$3,346 cumulative). Secondary driver: the current box is
75 GB at 79% with ~250 MB/day of orderbook growth — roughly two months to full.

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

**Decision: carry the orderbook tables or not.** Only the *writers*
(`snapshot_kalshi_orderbook.py`, `snapshot_polymarket_orderbook.py`) are in
cron; every reader (`walk_book_capacity.py`, `reasoning_demo.py`) is research
-only. Nothing in the daily trading path reads them. Trimming takes 38 GB → 21 GB.

Trimmed (recommended — archive the two orderbook tables separately if wanted):

    pg_dump -d weather --no-owner \
      --exclude-table-data='orderbook_snapshots*' \
      --exclude-table-data='polymarket_orderbook_snapshots*' \
      | ssh newhost 'psql -d weather -v ON_ERROR_STOP=1'

Everything:

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
