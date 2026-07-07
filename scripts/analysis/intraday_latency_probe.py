"""Intraday LATENCY probe (research/intraday-latency-probe).

GO/NO-GO GATE: does the market LAG a fresh intraday model release long enough to
be capturable? This is the ONLY way ingesting intraday forecasts could pay off,
because the forecasts are PUBLIC -- so the only possible edge is SPEED (reacting
to a run before the market fully reprices it).

Context: the sibling gate (research/intraday-fair-value) already proved our fair
does NOT beat the market on hourly-average accuracy -- the market is sharp and
well calibrated. That gate sampled the market once per HOUR, so it could have
MISSED a transient dislocation in the minutes right after a run arrives. THIS
probe zooms into the short post-arrival window at the native 5-min price cadence.

For each (day, city, bracket, run) we measure, using ONLY data available at the
run's realistic arrival time t0:
  1. NEWS  = Delta_fair = (this-run EMOS fair) - (prior-run EMOS fair).
  2. LATENCY = does the market MID drift toward the news over t0+15/30/60/120m?
     (fee-free by construction). Identification: split by run DIRECTION (up-runs
     Delta_fair>0 vs down-runs<0) -- generic time/outcome convergence would move
     both the same way; genuine news-following moves up-runs up and down-runs down.
  3. NEWS TRUE = does Delta_fair predict the settlement outcome (is reacting to
     the run pointed the right way, or is it noise)? (fee-free.) Both LATENCY and
     NEWS-TRUE must hold for an edge to exist.
  4. MONEY  = simulate a react-fast TAKER trade at t0: if |run_fair - market|
     exceeds a threshold, cross the spread toward the run. Two exits:
       (a) hold to SETTLEMENT (adds outcome variance);
       (b) CONVERGENCE -- exit when the market mid reaches run_fair (isolates the
           latency capture: grabbing the drift, not the outcome).
     Reported GROSS (pre-fee) AND NET (after the 7% Kalshi taker fee), per city
     per run -- so "does the market lag at all" (gross) is separated from "is it
     tradeable after fees" (net).

REUSE: the no-look-ahead run-fair machinery is copied verbatim from the gate
(scripts/analysis/intraday_fair_value.py on research/intraday-fair-value):
  * ens_stats / rolling-45d 00Z EMOS fit (fit_emos) / emos_probs_on_stats affine
    map / fetch_contracts_high / fetch_obs / contract_resolved_yes.
The ONLY new machinery is the 5-min-resolution market-response window and the
react-fast money simulation -- both strictly measured AFTER t0 (no look-ahead).

--------------------------------------------------------------------------------
ARRIVAL TIME t0 (CRITICAL -- the whole test is invalid if t0 is wrong)
--------------------------------------------------------------------------------
The `forecasts` table has NO ingest/created timestamp column (verified: columns
are init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f).
So t0 is the standard product-availability lag (dissemination + our Herbie/AWS
ingest), STATED as an assumption:
  * GEFS 06Z ensemble usable ~11:00Z   (hours BEFORE every decision)
  * GEFS 12Z ensemble usable ~16:30Z   (mid-afternoon: ~1h BEFORE KDFW 17:32Z;
                                         AFTER KORD 14:46Z / KMIA 15:30Z)
  * GEFS 18Z ensemble usable ~22:00Z   (late; at/after settlement window)
  * IFS  12Z ensemble usable ~18:40Z   (gate used IFS_12Z_AVAIL_HOUR=18)
  -> COMBINED 12Z fair needs BOTH GEFS+IFS, so it is available at max(...) ~18:40Z.
We test each run; the 12Z runs are the a-priori interesting ones (arrive during
active trading). We SWEEP t0 +/- an hour as a robustness check (T0_SWEEP_MIN).

DATA REALITY: intraday runs for the LIVE cities begin only ~2026-06-02/03
(KORD/KMIA ~33 days, KDFW ~28 days). IFS runs at 00Z & 12Z ONLY; GEFS at
00/06/12/18Z. So the 12Z is the only cycle that refreshes BOTH models. ~33 days
is a SMALL sample -- results are directional. The affine EMOS map is fit on the
same composition it is applied to (GEFS-only fit for GEFS runs; combined fit for
combined runs) so Delta_fair reflects only the change in the ensemble, not a
calibration/composition artifact.

Run:  cd /home/tdunn/wt-latency && uv run python scripts/analysis/intraday_latency_probe.py
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    NoForecastDataError,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs
from weather_markets.evaluation import contract_resolved_yes

# ---------------------------------------------------------------- config
CITIES = [
    ("KORD", "KXHIGHCHI", "14:46"),
    ("KMIA", "KXHIGHMIA", "15:30"),
    ("KDFW", "KXHIGHTDAL", "17:32"),
]
WINDOW_DAYS = 45
MIN_TRAIN_DAYS = 30
EPS = 1e-6
MIN_DATE = date(2026, 5, 25)            # intraday era (first runs ~06-02/03)
OFFSETS_MIN = [15, 30, 60, 120]         # market-response horizons after t0
BEFORE_LOOKBACK_MIN = 60                 # window for the "just before t0" mid
AFTER_TOL_MIN = 20                       # grab first tick within delta .. delta+tol
CONV_WINDOW_MIN = 120                    # convergence-exit search window

# Runs: (name, this_models, this_init, prior_models, prior_init, t0(h,m), note)
RUNS = [
    ("GEFS-06Z", ["gefs"], 6, ["gefs"], 0, (11, 0),
     "GEFS 06Z vs 00Z; lands ~11Z, hours BEFORE all decisions"),
    ("GEFS-12Z", ["gefs"], 12, ["gefs"], 6, (16, 30),
     "GEFS 12Z vs 06Z (pure incremental GEFS news); lands ~16:30Z, ~1h pre-KDFW"),
    ("GEFS-18Z", ["gefs"], 18, ["gefs"], 12, (22, 0),
     "GEFS 18Z vs 12Z; lands ~22Z, late / near settlement"),
    ("COMB-12Z", ["gefs", "ifs"], 12, ["gefs", "ifs"], 0, (18, 40),
     "Combined 12Z (BOTH models) vs 00Z static; needs IFS -> ~18:40Z (evening)"),
]
# t0 robustness sweep (minutes offset applied to the nominal t0)
T0_SWEEP_MIN = [-60, 0, 60]


# ---------------------------------------------------------------- proper-scoring helpers
def clip(p):
    return min(1.0 - 1e-9, max(1e-9, p))


def brier(p, y):
    return (p - y) ** 2


def kalshi_fee_cents(entry_price_cents, maker=False):
    """Kalshi per-contract fee, cents. Byte-mirror of dashboard/sim_python.py
    kalshi_fee_cents (NOT imported, to avoid touching the parity file):
      taker $0.07*P*(1-P), maker 1/4 that; round UP to 1c, min 1c; 0 at degenerate."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    return max(1, math.ceil(rate * p * (1.0 - p) * 100))


# ---------------------------------------------------------------- data fetch (reused from gate)
def fetch_contracts_high(conn, station, series):
    out = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT target_date, ticker, bracket_type, strike_low, strike_high
                 FROM contracts WHERE station_id=%s AND series=%s
                ORDER BY target_date, bracket_type, strike_low""",
            (station, series),
        )
        for td, tk, bt, sl, sh in cur.fetchall():
            out[td].append({"ticker": tk, "bracket_type": bt,
                            "strike_low": sl, "strike_high": sh})
    return out


def fetch_obs(conn, station):
    with conn.cursor() as cur:
        cur.execute("SELECT date, high_temp_f FROM observations WHERE station_id=%s",
                    (station,))
        return {d: float(h) for d, h in cur.fetchall()}


def ens_stats(conn, station, models, init_hour, d):
    """(mean, std) of the combined daily-high ensemble at init_hour on day d.
    Verbatim from gate ens_stats (statistics.mean/stdev on the flat member list)."""
    init = datetime(d.year, d.month, d.day, init_hour, 0, tzinfo=timezone.utc)
    try:
        vals = compute_combined_daily_highs(init, d, conn, station_id=station, models=models)
    except NoForecastDataError:
        return None
    if len(vals) < 2:
        return None
    return statistics.mean(vals), statistics.stdev(vals)


def emos_probs_on_stats(fit, mean_t, std_t, contracts):
    """Apply an already-fit EMOS affine map to an ensemble stat (verbatim from gate)."""
    mu = fit["a"] + fit["b"] * mean_t
    sigma = math.sqrt(max(fit["c"] + fit["d"] * std_t ** 2, EPS))
    return gaussian_to_bracket_probs(mu, sigma, contracts)


def fetch_two_sided_ticks(conn, station, series, min_date):
    """{(target_date, ticker): [(snapshot_at, yes_bid, yes_ask), ...]} sorted by time.
    Only two-sided, sane quotes; the raw 5-min cadence (NOT hour-collapsed)."""
    out = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.target_date, p.ticker, p.snapshot_at, p.yes_bid, p.yes_ask
                 FROM prices p JOIN contracts c ON c.ticker=p.ticker
                WHERE c.station_id=%s AND c.series=%s AND c.target_date>=%s
                  AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
                  AND p.yes_ask>=p.yes_bid AND p.yes_ask>0
                ORDER BY c.target_date, p.ticker, p.snapshot_at""",
            (station, series, min_date),
        )
        for td, tk, ts, yb, ya in cur.fetchall():
            out[(td, tk)].append((ts, int(yb), int(ya)))
    return out


# ---------------------------------------------------------------- tick helpers (strictly no look-ahead)
def mid_before(ticks, t0):
    """Last two-sided mid (prob) with ts <= t0 and ts >= t0-BEFORE_LOOKBACK_MIN."""
    lo = t0 - timedelta(minutes=BEFORE_LOOKBACK_MIN)
    best = None
    for ts, yb, ya in ticks:
        if ts > t0:
            break
        if ts >= lo:
            best = (ts, (yb + ya) / 200.0)
    return best  # (ts, mid) or None


def tick_at_or_after(ticks, tmin, tol_min):
    """First tick with tmin <= ts <= tmin+tol_min. Returns (ts, yb, ya) or None.
    Used for the response points and the money-entry book -- STRICTLY after t0."""
    hi = tmin + timedelta(minutes=tol_min)
    for ts, yb, ya in ticks:
        if ts < tmin:
            continue
        if ts <= hi:
            return (ts, yb, ya)
        return None
    return None


# ---------------------------------------------------------------- simple stats
def ols(xs, ys):
    """(slope, pearson_r, n) for y ~ x. None if degenerate."""
    n = len(xs)
    if n < 3:
        return None
    mx = statistics.mean(xs); my = statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / sxx, sxy / math.sqrt(sxx * syy), n


# ---------------------------------------------------------------- fair caches
def build_fits(conn, station, models, train_dates, obs):
    """Rolling-45d EMOS fit on this composition's 00Z stats, per target day.
    Returns {target_day: fit or None}. No look-ahead: window is [d-45, d-1]."""
    cache00 = {}
    lo_needed = min(train_dates) - timedelta(days=WINDOW_DAYS)
    d = lo_needed
    hi = max(train_dates)
    while d <= hi:
        s = ens_stats(conn, station, models, 0, d)
        if s is not None:
            cache00[d] = s
        d += timedelta(days=1)
    fits = {}
    for target in train_dates:
        lo = target - timedelta(days=WINDOW_DAYS)
        tm, ts_, to = [], [], []
        dd = lo
        while dd <= target - timedelta(days=1):
            if dd in cache00 and dd in obs:
                m, s = cache00[dd]
                tm.append(m); ts_.append(s); to.append(obs[dd])
            dd += timedelta(days=1)
        fits[target] = fit_emos(tm, ts_, to) if len(tm) >= MIN_TRAIN_DAYS else None
    return fits


# ---------------------------------------------------------------- main
def main():
    conn = get_connection()
    print("=" * 96)
    print("INTRADAY LATENCY PROBE  --  does the market lag a fresh intraday run enough to capture?")
    print("=" * 96)
    print(f"MIN_DATE={MIN_DATE}  offsets(min)={OFFSETS_MIN}  before_lookback={BEFORE_LOOKBACK_MIN}m"
          f"  after_tol={AFTER_TOL_MIN}m  conv_window={CONV_WINDOW_MIN}m")
    print("t0 arrival assumptions (no ingest column): "
          "GEFS 06Z~11:00Z, 12Z~16:30Z, 18Z~22:00Z; IFS/COMB 12Z~18:40Z")
    print("Drift + hit-rate are fee-free by construction; MONEY is reported GROSS and NET (7% taker).\n")

    grand = {}   # (city, run) -> summary dict for the final verdict table

    for station, series, dec in CITIES:
        contracts_by_date = fetch_contracts_high(conn, station, series)
        obs = fetch_obs(conn, station)
        ticks = fetch_two_sided_ticks(conn, station, series, MIN_DATE)
        days = sorted(d for d in contracts_by_date
                      if d in obs and d < date.today() and d >= MIN_DATE)
        print("#" * 96)
        print(f"# {station}  (series {series}, decision {dec}Z) -- {len(days)} settled intraday-era days")
        print("#" * 96)

        comps = {tuple(r[1]) for r in RUNS} | {tuple(r[3]) for r in RUNS}
        fit_by_comp = {comp: build_fits(conn, station, list(comp), days, obs) for comp in comps}

        for name, tmods, tinit, pmods, pinit, (h, m), note in RUNS:
            fits = fit_by_comp[tuple(tmods)]
            pfits = fit_by_comp[tuple(pmods)]

            rows = []
            for d in days:
                fit = fits.get(d)
                pfit = pfits.get(d)
                if fit is None or pfit is None:
                    continue
                s_this = ens_stats(conn, station, tmods, tinit, d)
                s_prior = ens_stats(conn, station, pmods, pinit, d)
                if s_this is None or s_prior is None:
                    continue
                cons = contracts_by_date[d]
                p_this = emos_probs_on_stats(fit, s_this[0], s_this[1], cons)
                p_prior = emos_probs_on_stats(pfit, s_prior[0], s_prior[1], cons)
                ohigh = int(round(obs[d]))
                t0 = datetime.combine(d, dtime(h, m), tzinfo=timezone.utc)
                conv_hi = t0 + timedelta(minutes=CONV_WINDOW_MIN)
                for c in cons:
                    tk = c["ticker"]
                    if tk not in p_this or tk not in p_prior:
                        continue
                    tks = ticks.get((d, tk))
                    if not tks:
                        continue
                    mb = mid_before(tks, t0)
                    if mb is None:
                        continue
                    entry = tick_at_or_after(tks, t0, AFTER_TOL_MIN)
                    afters = {}
                    for off in OFFSETS_MIN:
                        a = tick_at_or_after(tks, t0 + timedelta(minutes=off), AFTER_TOL_MIN)
                        afters[off] = (a[1] + a[2]) / 200.0 if a else None
                    # forward mid path (for convergence exit): strictly after entry
                    path = None
                    if entry is not None:
                        path = [(ts, (yb + ya) / 200.0) for ts, yb, ya in tks
                                if entry[0] <= ts <= conv_hi]
                    rows.append({
                        "d": d, "tk": tk, "c": c,
                        "dfair": p_this[tk] - p_prior[tk],
                        "run_fair": p_this[tk], "prior_fair": p_prior[tk],
                        "y": 1 if contract_resolved_yes(ohigh, c) else 0,
                        "m_before": mb[1], "m_before_ts": mb[0],
                        "entry": entry,
                        "m_t0": (entry[1] + entry[2]) / 200.0 if entry else None,
                        "afters": afters, "path": path, "t0": t0,
                    })

            if not rows:
                print(f"\n  [{name}]  no usable rows  ({note})")
                continue
            _report_run(conn, station, series, dec, name, tmods, tinit, pmods, pinit,
                        (h, m), note, rows, contracts_by_date, obs, fits, pfits, ticks, grand)

    # ------------------------------------------------------------ final verdict table
    print("\n" + "=" * 96)
    print("VERDICT TABLE  (per city x run)")
    print("=" * 96)
    print(f"  {'city':<5} {'run':<9} {'n':>4} | {'d60_slope':>9} {'r60':>6} | "
          f"{'up60c':>7} {'dn60c':>7} | {'news+%':>7} {'hit':>5} | "
          f"{'settle_g':>8} {'settle_n':>8} {'conv_g':>7} {'conv_n':>7} {'ntr':>4}")
    print("  " + "-" * 104)
    for (city, run), s in grand.items():
        print(f"  {city:<5} {run:<9} {s['n']:>4} | "
              f"{_f(s.get('slope60')):>9} {_f(s.get('r60')):>6} | "
              f"{_f(s.get('up_d60c')):>7} {_f(s.get('dn_d60c')):>7} | "
              f"{_f(s.get('news_impr_pct')):>7} {_f(s.get('hit')):>5} | "
              f"{_f(s.get('settle_g')):>8} {_f(s.get('settle_n')):>8} "
              f"{_f(s.get('conv_g')):>7} {_f(s.get('conv_n')):>7} {s.get('ntr', 0):>4}")
    print("\nLegend (edge>=3c react-fast taker, cents per contract):")
    print("  d60_slope = OLS slope of market-mid drift(cents) at t0+60m on Delta_fair(prob); r60 = pearson r")
    print("  up60c/dn60c = mean market drift(cents) at +60m for up-runs / down-runs (identification split)")
    print("  news+% = Brier improvement of run_fair over prior_fair (>0 = news is true); hit = directional hit-rate")
    print("  settle_g/n = hold-to-settlement avg P&L, GROSS/NET; conv_g/n = convergence-exit avg P&L, GROSS/NET")
    print("  ntr = number of react-fast trades fired")
    conn.close()


def _f(x):
    if x is None:
        return "-"
    return f"{x:+.3f}" if abs(x) < 100 else f"{x:+.1f}"


def _report_run(conn, station, series, dec, name, tmods, tinit, pmods, pinit,
                t0hm, note, rows, contracts_by_date, obs, fits, pfits, ticks, grand):
    n = len(rows)
    print(f"\n  [{name}]  n={n} bracket-days  ({note})")

    # ---- (A) LATENCY: drift ~ Delta_fair, with up/down identification (fee-free) ----
    print("    LATENCY (market MID drift after t0 vs run news Delta_fair; fee-free):")
    print(f"      {'horizon':>8} | {'slope(c/prob)':>13} {'pearson_r':>10} {'n':>4} | "
          f"{'up_drift_c':>11} {'dn_drift_c':>11} {'flat_drift_c':>12}")
    slopes = {}
    for off in OFFSETS_MIN:
        xs, ys, up, dn, flat = [], [], [], [], []
        for r in rows:
            a = r["afters"][off]
            if a is None:
                continue
            drift_c = (a - r["m_before"]) * 100.0
            xs.append(r["dfair"]); ys.append(drift_c)
            (up if r["dfair"] > 0.03 else dn if r["dfair"] < -0.03 else flat).append(drift_c)
        res = ols(xs, ys)
        slope = res[0] if res else None
        rr = res[1] if res else None
        slopes[off] = (slope, rr, len(xs),
                       statistics.mean(up) if up else None,
                       statistics.mean(dn) if dn else None)
        print(f"      {off:>6}m | {_f(slope):>13} {_f(rr):>10} {len(xs):>4} | "
              f"{(_f(statistics.mean(up)) if up else '-'):>11} "
              f"{(_f(statistics.mean(dn)) if dn else '-'):>11} "
              f"{(_f(statistics.mean(flat)) if flat else '-'):>12}")

    # gap-to-run: how much of the news is UNPRICED just before t0, and does it close?
    gseq = []
    for tag, sel in [("before", "m_before"), ("t0", "m_t0")]:
        gs = [abs(r["run_fair"] - r[sel]) * 100.0 for r in rows if r[sel] is not None]
        gseq.append((tag, statistics.mean(gs) if gs else None, len(gs)))
    for off in OFFSETS_MIN:
        gs = [abs(r["run_fair"] - r["afters"][off]) * 100.0
              for r in rows if r["afters"][off] is not None]
        gseq.append((f"+{off}m", statistics.mean(gs) if gs else None, len(gs)))
    print("      |run_fair - market| gap (cents) by time vs t0: "
          + "  ".join(f"{t}={_f(g)}(n{k})" for t, g, k in gseq))

    # ---- (B) NEWS TRUE (fee-free) ----
    b_run = statistics.mean(brier(r["run_fair"], r["y"]) for r in rows)
    b_prior = statistics.mean(brier(r["prior_fair"], r["y"]) for r in rows)
    impr = (b_prior - b_run) / b_prior * 100.0 if b_prior > 0 else None
    dirs = [(r["dfair"], r["y"] - r["prior_fair"]) for r in rows if abs(r["dfair"]) > 0.01]
    hit = statistics.mean(1.0 if (a > 0) == (b > 0) else 0.0 for a, b in dirs) if dirs else None
    print(f"    NEWS TRUE: Brier prior_fair={b_prior:.4f} run_fair={b_run:.4f} "
          f"-> improvement={_f(impr)}%  |  directional hit-rate={_f(hit)} (n={len(dirs)})")

    # ---- (C) MONEY: react-fast TAKER at t0; settlement + convergence exits; gross+net ----
    print("    MONEY (react-fast taker at t0; cents/contract; GROSS then NET of 7% taker fee):")
    money_row = {}
    for tau in (0.03, 0.05):
        agg = {"settle_g": [], "settle_n": [], "conv_g": [], "conv_n": [], "wins_n": 0}
        ntr = 0
        for r in rows:
            e = r["entry"]
            if e is None or r["m_t0"] is None:
                continue
            _, yb, ya = e
            edge = r["run_fair"] - r["m_t0"]
            if edge > tau:                       # BUY YES, cross at ask
                side = "YES"; entry_c = ya
            elif -edge > tau:                    # BUY NO, cross at (100-yb)
                side = "NO"; entry_c = 100 - yb
            else:
                continue
            if entry_c <= 0 or entry_c >= 100:
                continue
            fee = kalshi_fee_cents(entry_c, maker=False)

            def mark(mid):                        # value of this position (cents) at a yes-mid
                return mid * 100.0 if side == "YES" else 100.0 - mid * 100.0

            settle_val = 100.0 * (r["y"] if side == "YES" else (1 - r["y"]))
            settle_g = settle_val - entry_c
            settle_n = settle_val - entry_c - fee

            # convergence exit: first forward tick whose mid reaches run_fair; else last mid in window
            exit_mid = None
            for ts, mid in (r["path"] or []):
                if ts <= e[0]:
                    continue
                if (side == "YES" and mid >= r["run_fair"]) or \
                   (side == "NO" and mid <= r["run_fair"]):
                    exit_mid = mid
                    break
            if exit_mid is None:
                fwd = [mid for ts, mid in (r["path"] or []) if ts > e[0]]
                exit_mid = fwd[-1] if fwd else r["m_t0"]
            conv_g = mark(exit_mid) - mark(r["m_t0"])          # pure mid-to-mid drift capture
            conv_n = mark(exit_mid) - entry_c - fee            # cross-in + fee, exit at observed mid

            agg["settle_g"].append(settle_g); agg["settle_n"].append(settle_n)
            agg["conv_g"].append(conv_g); agg["conv_n"].append(conv_n)
            agg["wins_n"] += 1 if settle_n > 0 else 0
            ntr += 1

        def mean_or_none(k):
            return statistics.mean(agg[k]) if agg[k] else None
        sg, sn = mean_or_none("settle_g"), mean_or_none("settle_n")
        cg, cn = mean_or_none("conv_g"), mean_or_none("conv_n")
        wr = agg["wins_n"] / ntr if ntr else None
        print(f"      edge>={tau*100:.0f}c: trades={ntr:>3} | "
              f"SETTLE gross={_f(sg)} net={_f(sn)} | "
              f"CONV gross={_f(cg)} net={_f(cn)} | settle-net winrate={_f(wr)}")
        if abs(tau - 0.03) < 1e-9:
            money_row = {"settle_g": sg, "settle_n": sn, "conv_g": cg, "conv_n": cn, "ntr": ntr}

    # ---- t0 robustness sweep (does the drift slope survive +/- 1h on the arrival assumption?) ----
    sweep = []
    for off_t0 in T0_SWEEP_MIN:
        xs, ys = [], []
        for r in rows:
            t0s = r["t0"] + timedelta(minutes=off_t0)
            tks = ticks.get((r["d"], r["tk"]))
            mb = mid_before(tks, t0s)
            a = tick_at_or_after(tks, t0s + timedelta(minutes=60), AFTER_TOL_MIN)
            if mb is None or a is None:
                continue
            xs.append(r["dfair"]); ys.append(((a[1] + a[2]) / 200.0 - mb[1]) * 100.0)
        res = ols(xs, ys)
        sweep.append((off_t0, res[0] if res else None, res[1] if res else None, len(xs)))
    print("    t0 SWEEP (drift@+60m slope on Delta_fair at shifted arrival): "
          + "  ".join(f"t0{o:+d}m: slope={_f(sl)} r={_f(rr)} n={k}" for o, sl, rr, k in sweep))

    # ---- no-look-ahead spot check ----
    bad = sum(1 for r in rows if r["m_before_ts"] > r["t0"])
    sample = next(((r["m_before_ts"], r["t0"], r["entry"][0]) for r in rows if r["entry"]), None)
    print(f"    NO-LOOK-AHEAD: m_before ts <= t0 for all rows: "
          f"{'PASS' if bad == 0 else 'FAIL(' + str(bad) + ')'}"
          + (f"  e.g. before={sample[0]:%H:%M} <= t0={sample[1]:%H:%M} < entry={sample[2]:%H:%M}"
             if sample else ""))

    grand[(station, name)] = {
        "n": n, "slope60": slopes[60][0], "r60": slopes[60][1],
        "up_d60c": slopes[60][3], "dn_d60c": slopes[60][4],
        "news_impr_pct": impr, "hit": hit, **money_row,
    }


if __name__ == "__main__":
    main()
