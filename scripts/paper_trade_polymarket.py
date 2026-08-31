"""Daily Miami-on-Polymarket paper logger (forward validation of the venue port).

Same model as the Kalshi Miami paper config (EMOS combined gefs+ifs 00Z, rolling
45d) but evaluated against Polymarket US contracts: PM bracket semantics
(normalized via kalshi_equivalent_bracket), PM quotes from our 5-min snapshotter,
logged into paper_trades under a PM-specific model_source. NO ORDERS — paper only.
Scored later by export_pt_dataset.py (platform-aware since 2026-08-09).

Cron (daily, right after the Kalshi paper log at the same decision time):

  uv run python scripts/paper_trade_polymarket.py            # insert
  uv run python scripts/paper_trade_polymarket.py --dry-run  # print only
"""
import argparse
import math
import statistics
from datetime import date, datetime, timedelta, timezone

from weather_markets.aggregation import compute_combined_daily_highs
from weather_markets.db import get_connection
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.evaluation import kalshi_equivalent_bracket

# All 5 Polymarket US weather stations (extended from Miami-only 2026-08-12
# after the 4-city replay came back positive: LAX 28.1c/tr, SFO 22.9, MDW 16.2,
# NYC 16.6 @0.25). model_source per city; Miami keeps its original label.
# v2 = inclusive-pair bracket semantics (2026-08-23). The unsuffixed labels
# above these are FROZEN: they were generated while PM `between` brackets were
# read as half-open, which halved model_prob_yes and could invert side choice.
# paper_trades is keyed (target_date, ticker, model_source), so v2 rows sit
# BESIDE the old series instead of overwriting it — the old numbers stay
# auditable. See docs/analysis-snapshots/2026-08-23-pre-bracket-fix/.
STATIONS = {
    "KMIA": "EMOS combined 00Z Miami PM v2 (rolling 45d)",
    "KNYC": "EMOS combined 00Z NYC PM v2 (rolling 45d)",
    "KLAX": "EMOS combined 00Z Los Angeles PM v2 (rolling 45d)",
    "KSFO": "EMOS combined 00Z San Francisco PM v2 (rolling 45d)",
    "KMDW": "EMOS combined 00Z Chicago Midway PM v2 (rolling 45d)",
}
MODELS = ["gefs", "ifs"]
INIT_HOUR = 0
WINDOW_DAYS = 45
EDGE_THRESHOLD = 0.10          # log at 0.10 like the Kalshi paper config; filter later
MAX_QUOTE_AGE_MIN = 30

INSERT_SQL = """
    INSERT INTO paper_trades (
        logged_at, target_date, ticker, model_source,
        forecast_init_time, ensemble_mean, ensemble_std,
        emos_mu, emos_sigma, model_prob_yes,
        market_yes_bid, market_yes_ask, market_mid_prob, market_snapshot_at,
        edge, edge_threshold, position, entry_price_cents, notes
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (target_date, ticker, model_source) DO NOTHING
"""


def run_station(conn, station: str, model_source: str, now, dry_run: bool) -> None:
    target = now.date()
    init_time = datetime(target.year, target.month, target.day, INIT_HOUR, tzinfo=timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    ensemble = compute_combined_daily_highs(
        init_time, target, conn, station_id=station, models=MODELS)
    if len(ensemble) < 2:
        print(f"{stamp} PM paper {station}: no forecast — skip")
        return
    emos = fit_emos_rolling(target, conn, window_days=WINDOW_DAYS,
                            station_id=station, model="combined", init_hour=INIT_HOUR)
    if emos is None:
        print(f"{stamp} PM paper {station}: EMOS unfittable — skip")
        return
    mean = statistics.mean(ensemble)
    std = statistics.stdev(ensemble)
    mu = emos["a"] + emos["b"] * mean
    var = emos["c"] + emos["d"] * std ** 2
    if var <= 0:
        print(f"{stamp} PM paper {station}: bad EMOS var — skip")
        return
    sigma = math.sqrt(var)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (p.ticker) p.ticker, c.bracket_type,
                   c.strike_low, c.strike_high, p.yes_bid, p.yes_ask, p.snapshot_at
            FROM prices p JOIN contracts c ON c.ticker = p.ticker
            WHERE c.platform = 'polymarket' AND c.station_id = %s AND c.target_date = %s
              AND p.snapshot_at >= %s AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
            ORDER BY p.ticker, p.snapshot_at DESC
            """,
            (station, target, now - timedelta(minutes=MAX_QUOTE_AGE_MIN)),
        )
        quotes = cur.fetchall()
    if not quotes:
        print(f"{stamp} PM paper {station}: no fresh PM quotes — skip")
        return

    brackets = [
        kalshi_equivalent_bracket("polymarket", bt, sl, sh) | {"ticker": t}
        for t, bt, sl, sh, _, _, _ in quotes
    ]
    probs = gaussian_to_bracket_probs(mu, sigma, brackets)

    n = 0
    with conn.cursor() as cur:
        for (ticker, _bt, _sl, _sh, bid, ask, snap), b in zip(quotes, brackets):
            mid = (bid + ask) / 200.0
            p_model = probs[b["ticker"]]
            edge = p_model - mid
            if abs(edge) < EDGE_THRESHOLD:
                continue
            if edge > 0:
                position, entry = "BUY_YES", ask
            else:
                position, entry = "BUY_NO", 100 - bid
            if entry <= 0 or entry >= 100:
                continue
            if dry_run:
                print(f"  DRY {ticker} {position} entry={entry} edge={edge:+.3f} "
                      f"model={p_model:.3f} mid={mid:.3f}")
            else:
                cur.execute(INSERT_SQL, (
                    now, target, ticker, model_source,
                    init_time, mean, std, mu, sigma, p_model,
                    bid, ask, mid, snap, edge, EDGE_THRESHOLD,
                    position, entry, f"pm-paper; ensemble_members={len(ensemble)}"))
            n += 1
        conn.commit()
    print(f"{stamp} PM paper {station}: {n} signals "
          f"({'dry-run' if dry_run else 'logged'}) from {len(quotes)} quoted brackets; "
          f"mu={mu:.1f} sigma={sigma:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print signals, insert nothing")
    args = parser.parse_args()
    now = datetime.now(tz=timezone.utc)
    conn = get_connection()
    try:
        for station, model_source in STATIONS.items():
            try:
                run_station(conn, station, model_source, now, args.dry_run)
            except Exception as e:
                conn.rollback()
                print(f"{now.isoformat(timespec='seconds')} PM paper {station}: FAILED - {e}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
