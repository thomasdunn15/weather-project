"""Per-city strategy parameter optimisation on EQUITY-CURVE CONSISTENCY (read-only).

Objective (deliberately NOT terminal P&L or Sharpe alone — those reward
front-loaded curves that decay, the "Miami alpha-decay" failure mode): for each
(city, model, raw edge-threshold) build the chronological cumulative equity
curve (1 contract, net taker fee) from the logged paper_trades and rank configs
by OUT-OF-SAMPLE non-decay + drawdown-adjusted consistency.

Every bracket with |edge|>=0.10 (plus a sparse blend variant) is logged in
paper_trades with the stored `edge`, so any (model, threshold) config is
backtestable offline by re-filtering on |edge|. City + model are encoded in
`model_source`; low-vs-high settlement is read from `contracts.series`
(KXLOWT* -> daily low, else daily high).

Scoring convention (VERIFIED against Dallas combined: @0.10=-$4.69, @0.25=+$7.26):
  entry_price_cents = cost of the side held (BUY_YES=ask, BUY_NO=100-bid).
  net_cents(1 contract) = ((100-entry) if won else -entry) - fee
  fee = max(1, ceil(0.07 * p*(1-p) * 100)),  p = entry/100   (Kalshi taker fee)
  won = contract_resolved_yes(obs, contract) matched to position;
        obs = daily low for KXLOWT* series else daily high.

Chronological order = target_date (logged_at is a backfill artifact, unusable).

THE GATE (hard): OOS split TRAIN=first 60% of trades, TEST=last 40%.
  Pass requires BOTH halves net-positive AND test_slope >= 0.7*train_slope
  (net $/trade) — i.e. no alpha decay into the out-of-sample tail.

Consistency metrics (reported for every config): %-time within 5% of running
max, max drawdown ($ and %), longest underwater streak (# trades), fraction of
rolling-30-trade windows net-positive, sign of the recent-25% window slope.

Ranking: OOS gate = hard filter; then drawdown-adjusted consistency composite;
terminal net$ is a TIEBREAK only. Plateau check reports adjacent-threshold net$
so a lone spike is visible.

ANALYSIS ONLY. Read-only DB (SELECT). Writes a JSON dump to /tmp; no DB/config
writes. Run:
    cd /home/tdunn/weather-project && uv run python scripts/analysis/city_param_optimize.py
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes

OUT_JSON = "/tmp/city_param_optimize.json"

# Raw-only grid. 0.10 included as baseline / left plateau neighbour; the
# RECOMMENDATION is only ever drawn from SELECTABLE_THRESHOLDS.
GRID_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
SELECTABLE_THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35]

# Confidence floors on n_trades at the chosen threshold.
MIN_N_OPTIMISE = 30   # below this: do not recommend (too thin)
MIN_N_CONF = 40       # below this: flag low confidence

# City -> {model_key: model_source}. Only models that actually exist with
# enough data per the paper_trades census. blend_source is the thin live-signal
# variant (reported, never optimised on).
CITIES = [
    # (label, station, ordered model list, blend_source, live_baseline)
    dict(label="Chicago (KORD)", station="KORD",
         models={"combined": "EMOS combined 00Z Chicago (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Chicago (rolling 45d)"},
         blend="EMOS combined+blend 00Z Chicago (rolling 45d)",
         live=("combined_hrrr", 0.25), live_desc="combined_hrrr, union raw>=0.25 / blend>=0.10 (LIVE)"),
    dict(label="Miami (KMIA)", station="KMIA",
         models={"combined": "EMOS combined 00Z Miami (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Miami (rolling 45d)"},
         blend="EMOS combined+blend 00Z Miami (rolling 45d)",
         live=("combined", 0.10), live_desc="combined, BLEND-ONLY 0.10 (LIVE)"),
    dict(label="Dallas (KDFW)", station="KDFW",
         models={"combined": "EMOS combined 00Z Dallas (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Dallas (rolling 45d)"},
         blend="EMOS combined+blend 00Z Dallas (rolling 45d)",
         live=("combined", 0.25), live_desc="combined, union raw>=0.25 (LIVE)"),
    dict(label="Seattle (KSEA)", station="KSEA",
         models={"combined": "EMOS combined 00Z Seattle (rolling 45d)"},
         blend="EMOS combined+blend 00Z Seattle (rolling 45d)",
         live=None, live_desc="paper only (monitor)"),
    dict(label="Phoenix (KPHX)", station="KPHX",
         models={"combined": "EMOS combined 00Z Phoenix (rolling 45d)"},
         blend="EMOS combined+blend 00Z Phoenix (rolling 45d)",
         live=None, live_desc="paper only"),
    dict(label="Austin (KAUS)", station="KAUS",
         models={"combined": "EMOS combined 00Z Austin (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Austin (rolling 45d)"},
         blend=None, live=None, live_desc="paper only"),
    dict(label="Denver (KDEN)", station="KDEN",
         models={"combined": "EMOS combined 00Z Denver (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Denver (rolling 45d)"},
         blend="EMOS combined+blend 00Z Denver (rolling 45d)",
         live=None, live_desc="paper only"),
    dict(label="Los Angeles (KLAX)", station="KLAX",
         models={"combined": "EMOS combined 00Z Los Angeles (rolling 45d)",
                 "combined_hrrr": "EMOS combined_hrrr 00Z Los Angeles (rolling 45d)"},
         blend=None, live=None, live_desc="paper only (rejected)"),
    dict(label="Las Vegas (KLAS)", station="KLAS",
         models={"combined": "EMOS combined 00Z Las Vegas (rolling 45d)"},
         blend="EMOS combined+blend 00Z Las Vegas (rolling 45d)",
         live=None, live_desc="paper only (rejected)"),
    dict(label="New Orleans (KMSY)", station="KMSY",
         models={"combined": "EMOS combined 00Z New Orleans (rolling 45d)"},
         blend=None, live=None, live_desc="paper only"),
    dict(label="New York (KNYC)", station="KNYC",
         models={"combined_hrrr": "EMOS combined_hrrr 00Z NYC (rolling 45d)"},
         blend=None, live=None, live_desc="paper only (highs; combined-only not logged)"),
]

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def fee_cents(entry: int) -> int:
    p = entry / 100.0
    return max(1, math.ceil(0.07 * p * (1 - p) * 100))


def net_cents(row: dict) -> int:
    """Net P&L in cents for 1 contract, project taker-fee convention."""
    is_low = row["series"].startswith("KXLOWT")
    obs_raw = row["low_temp_f"] if is_low else row["high_temp_f"]
    obs = int(round(float(obs_raw)))
    contract = {"bracket_type": row["bracket_type"],
                "strike_low": row["strike_low"], "strike_high": row["strike_high"]}
    resolved = contract_resolved_yes(obs, contract)
    won = resolved if row["position"] == "BUY_YES" else (not resolved)
    entry = int(row["entry_price_cents"])
    return ((100 - entry) if won else -entry) - fee_cents(entry)


def load_rows(conn) -> list[dict]:
    sql = """
        SELECT pt.target_date, pt.ticker, pt.model_source, pt.edge, pt.position,
               pt.entry_price_cents, c.series, c.bracket_type,
               c.strike_low, c.strike_high, o.high_temp_f, o.low_temp_f
        FROM paper_trades pt
        JOIN contracts c ON c.ticker = pt.ticker
        JOIN observations o ON o.station_id = c.station_id AND o.date = c.target_date
        ORDER BY pt.target_date, pt.ticker
    """
    cols = ["target_date", "ticker", "model_source", "edge", "position",
            "entry_price_cents", "series", "bracket_type", "strike_low",
            "strike_high", "high_temp_f", "low_temp_f"]
    out = []
    with conn.cursor() as cur:
        cur.execute(sql)
        for rec in cur.fetchall():
            r = dict(zip(cols, rec))
            r["abs_edge"] = abs(float(r["edge"]))
            r["net"] = net_cents(r)
            out.append(r)
    return out

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def annualised_sharpe(trades: list[dict]) -> float | None:
    """Annualised Sharpe on the daily-aggregated P&L series (tiebreak only)."""
    daily = defaultdict(int)
    for t in trades:
        daily[t["target_date"]] += t["net"]
    dates = sorted(daily)
    if len(dates) < 3:
        return None
    pnls = [daily[d] for d in dates]
    sd = pstdev(pnls)
    if sd == 0:
        return None
    span = (dates[-1] - dates[0]).days
    if span <= 0:
        return None
    ppy = len(dates) / (span / 365.25)
    return (mean(pnls) / sd) * math.sqrt(ppy)


def equity_stats(trades: list[dict]) -> dict:
    """Consistency + OOS metrics for a chronologically-sorted trade list."""
    pnls = [t["net"] for t in trades]           # cents, chronological
    n = len(pnls)
    total = sum(pnls)

    # cumulative curve, running max, drawdown, underwater streak, %-at-high
    eq = 0
    peak = 0                                     # start-of-curve reference = 0
    maxdd = 0
    maxdd_peak = 0
    at_high = 0
    cur_uw = 0
    longest_uw = 0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > maxdd:
            maxdd = dd
            maxdd_peak = peak
        # within 5% of running max (only meaningful once peak is positive)
        if peak > 0 and eq >= 0.95 * peak:
            at_high += 1
        # underwater = strictly below the running max
        if eq < peak:
            cur_uw += 1
            longest_uw = max(longest_uw, cur_uw)
        else:
            cur_uw = 0
    maxdd_pct = (maxdd / maxdd_peak) if maxdd_peak > 0 else None
    pct_at_high = at_high / n if n else 0.0

    # rolling 30-trade windows net-positive
    if n >= 30:
        wins = sum(1 for i in range(n - 29) if sum(pnls[i:i + 30]) > 0)
        roll_pos = wins / (n - 29)
    else:
        roll_pos = None

    # recent 25% window slope (cents/trade) and sign
    q_start = int(0.75 * n)
    recent = pnls[q_start:] if n - q_start > 0 else pnls
    recent_slope = sum(recent) / len(recent) if recent else 0.0

    # OOS 60/40 split (by trade index, chronological)
    k = int(0.60 * n)
    train, test = pnls[:k], pnls[k:]
    tr_net, te_net = sum(train), sum(test)
    tr_slope = tr_net / len(train) if train else 0.0
    te_slope = te_net / len(test) if test else 0.0
    gate = (tr_net > 0 and te_net > 0 and te_slope >= 0.7 * tr_slope)

    # drawdown-adjusted consistency composite (only informative when total>0)
    dd_ratio = (total / (total + maxdd)) if (total + maxdd) > 0 else 0.0
    comp_parts = [dd_ratio, pct_at_high]
    if roll_pos is not None:
        comp_parts.append(roll_pos)
    composite = mean(comp_parts)

    return dict(
        n=n, net=total, sharpe=annualised_sharpe(trades),
        maxdd=maxdd, maxdd_pct=maxdd_pct, pct_at_high=pct_at_high,
        longest_uw=longest_uw, roll_pos=roll_pos,
        recent_slope=recent_slope,
        train_net=tr_net, test_net=te_net, train_n=len(train), test_n=len(test),
        train_slope=tr_slope, test_slope=te_slope, gate=gate,
        dd_ratio=dd_ratio, composite=composite,
    )


def select(rows, model_source, thr):
    sub = [r for r in rows if r["model_source"] == model_source and r["abs_edge"] >= thr]
    sub.sort(key=lambda r: (r["target_date"], r["ticker"]))
    return sub

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def m(c):  # cents -> $ str
    return f"${c/100:+,.2f}"


def fmt_stats_line(thr, s, tag=""):
    sh = "  n/a " if s["sharpe"] is None else f"{s['sharpe']:5.2f}"
    rp = " n/a" if s["roll_pos"] is None else f"{s['roll_pos']*100:3.0f}%"
    ddp = " n/a" if s["maxdd_pct"] is None else f"{s['maxdd_pct']*100:3.0f}%"
    g = "PASS" if s["gate"] else "fail"
    return (f"  thr>={thr:.2f} n={s['n']:4d} net={m(s['net']):>9} "
            f"Shrp={sh} DD={m(-s['maxdd']):>8}({ddp}) hi={s['pct_at_high']*100:3.0f}% "
            f"roll+={rp} uw={s['longest_uw']:3d} | "
            f"TR={m(s['train_net']):>8}/{s['train_slope']:+5.1f}c "
            f"TE={m(s['test_net']):>8}/{s['test_slope']:+5.1f}c {g} "
            f"cmp={s['composite']:.2f}{tag}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    conn = get_connection()
    try:
        rows = load_rows(conn)
    finally:
        conn.close()

    # ---- validation sanity check against known Dallas values ----
    v10 = sum(r["net"] for r in select(rows, "EMOS combined 00Z Dallas (rolling 45d)", 0.10))
    v25 = sum(r["net"] for r in select(rows, "EMOS combined 00Z Dallas (rolling 45d)", 0.25))
    print("=" * 118)
    print(f"VALIDATION  Dallas combined @0.10 = {m(v10)} (expect -$4.69)   "
          f"@0.25 = {m(v25)} (expect +$7.26)   "
          f"{'OK' if (v10 == -469 and v25 == 726) else 'MISMATCH!'}")
    print("=" * 118)

    report = {}
    for city in CITIES:
        label = city["label"]
        print(f"\n{'='*118}\n{label}    [live: {city['live_desc']}]\n{'='*118}")
        creport = {"models": {}, "blend": None, "live": None,
                   "recommendation": None, "near_miss": None}

        # per model x threshold
        candidates = []   # (model_key, thr, stats)
        for mkey, msrc in city["models"].items():
            grid = {}
            for thr in GRID_THRESHOLDS:
                sub = select(rows, msrc, thr)
                if not sub:
                    continue
                s = equity_stats(sub)
                grid[thr] = s
                if thr in SELECTABLE_THRESHOLDS and s["n"] >= MIN_N_OPTIMISE:
                    candidates.append((mkey, thr, s))
            creport["models"][mkey] = {str(t): _jsonable(v) for t, v in grid.items()}
            if grid:
                print(f"\n  model = {mkey}   ({msrc})")
                for thr in GRID_THRESHOLDS:
                    if thr in grid:
                        base = ""
                        if city["live"] and city["live"] == (mkey, thr):
                            base = "  <== LIVE raw-leg"
                        print(fmt_stats_line(thr, grid[thr], base))

        # blend variant (report only, never optimised)
        if city["blend"]:
            bsub = select(rows, city["blend"], 0.10)
            if bsub:
                bs = equity_stats(bsub)
                creport["blend"] = _jsonable(bs)
                print(f"\n  blend @0.10 (THIN — report only): n={bs['n']} net={m(bs['net'])} "
                      f"(live Miami signal uses this; not robust to evaluate)")

        # ---- recommendation ----
        # Prefer OOS-passing configs with enough trades to trust (n>=MIN_N_CONF).
        # Only fall back to thin (n<MIN_N_CONF) passers if no confident one exists,
        # and then flag low confidence. This stops the ranker from chasing a fat
        # slope that only exists because a high threshold left <40 trades.
        passers = [(mk, t, s) for (mk, t, s) in candidates if s["gate"]]
        conf_passers = sorted([p for p in passers if p[2]["n"] >= MIN_N_CONF],
                              key=lambda x: (x[2]["composite"], x[2]["net"]), reverse=True)
        thin_passers = sorted([p for p in passers if p[2]["n"] < MIN_N_CONF],
                              key=lambda x: (x[2]["composite"], x[2]["net"]), reverse=True)
        chosen = conf_passers or thin_passers

        # Near-miss: highest-net config with n>=MIN_N_CONF that is robustly
        # OOS-positive (test net & slope > 0, slope >= 0.55x train) but FAILS the
        # strict 0.7 ratio — i.e. a fat, well-populated curve with mild decay.
        near = None
        for (mk, t, s) in sorted(candidates, key=lambda x: x[2]["net"], reverse=True):
            if s["gate"]:
                continue
            if (s["n"] >= MIN_N_CONF and s["test_net"] > 0 and s["train_slope"] > 0
                    and s["test_slope"] > 0 and s["test_slope"] >= 0.55 * s["train_slope"]):
                near = (mk, t, s)
                break

        rec = None
        if chosen:
            mk, t, s = chosen[0]
            grid = {float(k): v for k, v in
                    {str(tt): equity_stats(select(rows, city["models"][mk], tt))
                     for tt in GRID_THRESHOLDS if select(rows, city["models"][mk], tt)}.items()}
            neigh = {}
            for d in (-0.05, 0.05):
                nt = round(t + d, 2)
                if nt in grid:
                    neigh[nt] = grid[nt]["net"]
            plateau_ok = len(neigh) > 0 and all(v > 0 for v in neigh.values())
            low_conf = s["n"] < MIN_N_CONF
            rec = dict(model=mk, thr=t, stats=_jsonable(s),
                       neighbours={str(k): v for k, v in neigh.items()},
                       plateau_ok=plateau_ok, low_conf=low_conf)
            nb = "  ".join(f"{k:.2f}:{m(v)}" for k, v in sorted(neigh.items()))
            if not plateau_ok:
                verdict = "GO? lone spike — plateau weak"
            elif low_conf:
                verdict = "GO? thin (n<40) — forward-paper-test, low confidence"
            else:
                verdict = "GO (forward-paper-test)"
            print(f"\n  --> RECOMMEND: {mk} @ raw>={t:.2f}  n={s['n']}  net={m(s['net'])}  "
                  f"OOS TRAIN {m(s['train_net'])}/{s['train_slope']:+.1f}c -> "
                  f"TEST {m(s['test_net'])}/{s['test_slope']:+.1f}c  composite={s['composite']:.2f}")
            print(f"      plateau neighbours: {nb or 'none'}   -> {verdict}")
        else:
            print("\n  --> RECOMMEND: HOLD — no (model,threshold) passes the OOS non-decay gate.")

        if near:
            mk, t, s = near
            creport["near_miss"] = dict(model=mk, thr=t, stats=_jsonable(s))
            print(f"      near-miss (higher-n, robust OOS, fails strict 0.7 ratio): "
                  f"{mk} @ raw>={t:.2f}  n={s['n']}  net={m(s['net'])}  "
                  f"TEST {m(s['test_net'])}/{s['test_slope']:+.1f}c  (train {s['train_slope']:+.1f}c) "
                  f"roll+={'n/a' if s['roll_pos'] is None else f'{s['roll_pos']*100:.0f}%'}")
        creport["recommendation"] = rec

        # ---- live baseline stat block ----
        if city["live"]:
            lmk, lthr = city["live"]
            lsrc = city["models"].get(lmk)
            lsub = select(rows, lsrc, lthr) if lsrc else []
            if lmk == "combined" and city["label"].startswith("Miami"):
                # KMIA live is blend-only; show the blend curve as the true live baseline
                pass
            if lsub:
                ls = equity_stats(lsub)
                creport["live"] = _jsonable(ls)
                print(f"\n  LIVE baseline ({lmk} @ raw>={lthr:.2f}): "
                      + fmt_stats_line(lthr, ls).strip())
        report[label] = creport

    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # ---- paste-ready summary table ----
    print(f"\n\n{'='*118}\nSUMMARY — current live vs recommended (consistency-optimised)\n{'='*118}")
    print("Legend: P=OOS gate pass, f=fail (front-loaded/decaying); TE=test-half net$/trade slope.")
    hdr = (f"{'City':<20}{'Live cfg':<18}{'Live net/OOS':<24}"
           f"{'Recommended':<20}{'Rec net/OOS':<24}{'Verdict':<26}")
    print(hdr)
    print("-" * 118)
    for city in CITIES:
        cr = report[city["label"]]
        live = cr["live"]
        if live:
            live_s = f"{m(live['net'])} TE{live['test_slope']:+.1f}c {'P' if live['gate'] else 'f'}"
            live_cfg = f"{city['live'][0]}@{city['live'][1]:.2f}"
        else:
            live_s = "paper-only"
            live_cfg = "-"
        rec = cr["recommendation"]
        if rec:
            rs = rec["stats"]
            rec_cfg = f"{rec['model']}@{rec['thr']:.2f}"
            rec_s = f"{m(rs['net'])} TE{rs['test_slope']:+.1f}c PASS n={rs['n']}"
            if not rec["plateau_ok"]:
                verdict = "GO? plateau weak"
            elif rec["low_conf"]:
                verdict = "GO? thin n<40, low conf"
            else:
                verdict = "GO forward-test"
        else:
            rec_cfg, rec_s, verdict = "HOLD", "-", "HOLD keep current"
        print(f"{city['label']:<20}{live_cfg:<18}{live_s:<24}{rec_cfg:<20}{rec_s:<24}{verdict:<26}")

    # near-miss (higher-n robust-but-decaying) callouts
    print("-" * 118)
    print("Higher-n 'near-miss' configs (robustly OOS-positive, fail strict 0.7 ratio by mild decay):")
    for city in CITIES:
        nm = report[city["label"]].get("near_miss")
        if nm:
            s = nm["stats"]
            print(f"  {city['label']:<20}{nm['model']}@{nm['thr']:.2f}  n={s['n']:<4} "
                  f"net={m(s['net'])}  TEST {m(s['test_net'])}/{s['test_slope']:+.1f}c "
                  f"(train {s['train_slope']:+.1f}c)  maxDD={m(-s['maxdd'])}")

    print(f"\nFull machine-readable results -> {OUT_JSON}")


def _jsonable(s: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}


if __name__ == "__main__":
    main()
