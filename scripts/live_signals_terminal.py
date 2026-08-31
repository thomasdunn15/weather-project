"""Live read-only signals terminal — Kalshi + Polymarket US + ForecastEx, one screen.

    uv run python scripts/live_signals_terminal.py                 # 60s refresh
    uv run python scripts/live_signals_terminal.py --once           # single render
    uv run python scripts/live_signals_terminal.py --venue kalshi --interval 30

READ-ONLY. It opens one Postgres connection and reads. It never constructs
KalshiClient / PolymarketClient / IBKRClient and never calls create_order /
place_order / submit_order / reply / DELETE — tests/test_live_signals_terminal.py
greps this file to keep it that way. Safe to leave running unattended.

Non-obvious decisions, in the order they'll bite you:

* SIGNALS ARE IMPORTED, NEVER REIMPLEMENTED. Each venue's row comes from the
  same function its live cron calls: live_trade.compute_signals_for_today,
  live_trade_polymarket.today_signals, live_trade_forecastex.signals. A monitor
  that computed edge its own way would be worse than no monitor. The two PM/FX
  functions were lifted out of their main()s for exactly this; the third gained
  an optional kwarg (below). If you change a threshold, change it in the trader.

* IT RE-PRICES AGAINST *NOW*, NOT THE DECISION TIME. The crons deliberately
  freeze the book at each city's pre-committed decision time. A live monitor
  must not, or it would show a 15:30 snapshot at 19:00. So each signal function
  takes an as-of cutoff and we pass `now`. The cutoff shifts only TODAY's quote
  lookup — ForecastEx's walk-forward blend history stays pinned to decision_utc,
  because moving it would refit the blend on a training set the cron never saw.

* SCOPE COMES FROM THE CONFIGS, NOT FROM A LIST HERE. Kalshi = every
  CITY_CONFIG entry with is_active and no halt/<CITY> file (today: KMIA alone).
  Polymarket = live_trade_polymarket.STATION (KMIA — the five-station roster is
  the *paper* logger and the depth snapshotter, not the live probe). ForecastEx
  = its own CITY_CONFIG, gated by halt/ALL and halt/FX_<CITY> only: it settles
  on Weather Underground rather than the NWS CLI, so a Kalshi halt on the same
  city is a different bet and deliberately does NOT cascade (halt/KDFW exists;
  ForecastEx Dallas still trades).

* PINNING. Once an order exists in live_trades / pm_live_trades / fx_live_trades
  for today, its row is pinned for the rest of the day and cannot fall off when
  the edge decays — that is the whole point. The pin key is
  (venue, contract, SIDE), not contract alone: if the model has since flipped
  sides on a contract we already traded, you get both rows and can see the flip
  instead of having it silently overwritten. A pinned row still shows the
  *current* model/market/edge when the signal is still firing, and the values
  recorded at placement when it is not.

* fill_count == 0 IS NOT A NO-FILL. It is written by the reconcilers (PM 13:05
  and 20:05, FX 05:30 and 20:10, Kalshi monitor_fills every 15min), so it reads
  0 for hours after a genuine fill. Those rows render "PLACED · unreconciled".
  Only Kalshi carries an intraday fill_status, so only Kalshi can say "unfilled"
  and mean it.

* STALENESS IS SHOWN, NOT HIDDEN. Every row carries the age of the quote it was
  priced off; over STALE_MINUTES it turns red. ForecastEx has no order book at
  all — the "market" is the last trade, which is legitimately hours old on a
  quiet strike, and that is a fact about the venue you want on screen.

* PRICE CONVENTIONS ARE THE TRADERS'. Polymarket quotes both legs on the YES
  token, so a NO entry is 100 − yes_bid; that arithmetic lives in
  choose_signals and we display its output untouched. Bracket labels come from
  contracts.strike_low/high via kalshi_equivalent_bracket — never from the PM
  slug, whose `gte92lt93` means the inclusive pair 92–93, not 92 alone.

Exits when the UTC date rolls over ("until end of day"), or on Ctrl-C.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_trade                          # noqa: E402
import live_trade_forecastex as fx         # noqa: E402
import live_trade_polymarket as pm         # noqa: E402
from weather_markets.db import get_connection  # noqa: E402

STALE_MINUTES = 10
# Polymarket's live probe has no decision_utc constant of its own — it is a
# cron entry. Source of truth: docs/crontab.txt, `47 14 * * * live_trade_polymarket.py --live`.
PM_DECISION_UTC = (14, 47)
VENUES = ("kalshi", "polymarket", "forecastex")


@dataclass(frozen=True)
class Row:
    venue: str
    city: str
    contract: str          # full ticker — the pin identity
    label: str             # human bracket, e.g. "92-93"
    side: str              # YES / NO
    model_p: float | None
    market_p: float | None
    edge: float | None
    threshold: float | None   # None = we cannot know which rule fired (see placed_rows)
    entry: int | None      # cents
    status: str            # LIVE / PLACED / FILLED
    detail: str = ""
    quoted_at: datetime | None = None

    @property
    def key(self):
        return (self.venue, self.contract, self.side)


# --------------------------------------------------------------------------
# pure core (tested)
# --------------------------------------------------------------------------
def merge(live: list[Row], placed: list[Row]) -> list[Row]:
    """Pinned rows first, then still-firing signals; both by |edge| descending.

    A placed row keeps its PLACED/FILLED status forever, but adopts the live
    numbers — threshold included — while its signal is still firing, so you can
    watch the edge decay under a position you already have. When it is no
    longer firing its threshold stays None: see placed_rows.
    """
    by_key = {r.key: r for r in live}
    out = []
    for p in placed:
        cur = by_key.get(p.key)
        out.append(p if cur is None else replace(
            p, model_p=cur.model_p, market_p=cur.market_p, edge=cur.edge,
            threshold=cur.threshold, quoted_at=cur.quoted_at))
    pinned = {p.key for p in placed}
    out.sort(key=lambda r: -abs(r.edge or 0))
    rest = sorted((r for r in live if r.key not in pinned),
                  key=lambda r: -abs(r.edge or 0))
    return out + rest


def bracket_label(bracket_type: str, low, high) -> str:
    if bracket_type == "greater_than":
        return f">{low:g}"
    if bracket_type == "less_than":
        return f"<{high:g}"
    return f"{low:g}-{high:g}"


def age_minutes(ts: datetime | None, now: datetime) -> float | None:
    return None if ts is None else (now - ts).total_seconds() / 60.0


# --------------------------------------------------------------------------
# venue collectors — each returns (rows, notes)
# --------------------------------------------------------------------------
def _contract_labels(conn, today: date) -> dict[str, str]:
    """ticker -> human bracket, for Kalshi and Polymarket alike.

    Polymarket strikes go through kalshi_equivalent_bracket first: the raw
    `gte{a}` tails are half-open on that venue, and its `between` pairs are
    inclusive despite the slug (see evaluation.kalshi_equivalent_bracket).
    """
    from weather_markets.evaluation import kalshi_equivalent_bracket
    with conn.cursor() as cur:
        cur.execute("""SELECT ticker, platform, bracket_type, strike_low, strike_high
                       FROM contracts WHERE target_date=%s""", (today,))
        out = {}
        for tk, plat, bt, lo, hi in cur.fetchall():
            b = kalshi_equivalent_bracket(plat, bt, lo, hi)
            out[tk] = bracket_label(b["bracket_type"], b["strike_low"], b["strike_high"])
    return out


def kalshi_rows(conn, today: date, now: datetime, labels: dict) -> tuple[list[Row], list[str]]:
    rows, notes = [], []
    for city, cfg in live_trade.CITY_CONFIG.items():
        if not cfg.get("is_active"):
            continue
        halts = live_trade.check_halts(city)
        if halts:
            notes.append(f"{city} HALTED: {'; '.join(halts)}")
            continue
        buf = io.StringIO()   # compute_signals_for_today narrates to stdout
        with contextlib.redirect_stdout(buf):
            sigs = live_trade.compute_signals_for_today(conn, city, today, snapshot_cutoff=now)
        for line in buf.getvalue().splitlines():
            if "HALT" in line or "skipping" in line:
                notes.append(f"{city}: {line.strip()}")
        for s in sigs:
            blend_fired = s["signal_source"] in ("blend", "union_blend_only")
            rows.append(Row(
                venue="kalshi", city=city, contract=s["ticker"],
                label=labels.get(s["ticker"], s["ticker"]),
                side=s["side"].upper(),
                model_p=s["blend_p"] if blend_fired else s["model_p"],
                market_p=s["market_mid"], edge=s["edge"],
                threshold=cfg["blend_edge_threshold"] if blend_fired else cfg["edge_threshold"],
                entry=s["limit_price"], status="LIVE",
                detail=s["signal_source"], quoted_at=s["market_snapshot_at"]))
    return rows, notes


def pm_rows(conn, today: date, now: datetime, labels: dict) -> tuple[list[Row], list[str]]:
    if pm.HALT_FILE.exists():
        return [], [f"{pm.STATION} HALTED: {pm.HALT_FILE.name} present"]
    sigs, note = pm.today_signals(conn, today, now)
    rows = [Row(
        venue="polymarket", city=pm.STATION, contract=s["ticker"],
        label=labels.get(s["ticker"], s["ticker"]),
        side="YES" if s["intent"].endswith("LONG") else "NO",
        model_p=s["p_model"], market_p=s["mid"], edge=s["edge"],
        threshold=pm.EDGE_THRESHOLD, entry=s["entry"], status="LIVE",
        detail=f"IOC<={pm.order_bound_cents(s['entry'])}c", quoted_at=s["snapshot_at"])
        for s in sigs]
    return rows, ([] if sigs else [f"{pm.STATION}: {note}"])


def fx_rows(conn, today: date, now: datetime, _labels: dict) -> tuple[list[Row], list[str]]:
    rows, notes = [], []
    spreads = {c["station"]: c["median_c"]
               for c in json.loads(fx.SPREAD_JSON.read_text())["cities"]}
    for city, cfg in fx.CITY_CONFIG.items():
        reason = fx.halted(city)
        if reason:
            notes.append(f"{city} HALTED: {reason}")
            continue
        spread = spreads.get(city)
        if spread is None:
            notes.append(f"{city}: no measured spread")
            continue
        picks, note = fx.signals(conn, city, cfg, today, spread, as_of=now)
        if picks is None:
            notes.append(f"{city}: {note}")
            continue
        if not picks:
            notes.append(f"{city}: nothing over {cfg['edge_threshold']:.0%} ({note})")
        for p in picks:
            rows.append(Row(
                venue="forecastex", city=city, contract=p["ticker"],
                label=f">{p['strike']:g}", side=p["side"].upper(),
                model_p=p["p_model"], market_p=p["last_px"] / 100.0, edge=p["edge"],
                threshold=cfg["edge_threshold"], entry=p["entry"], status="LIVE",
                detail=f"post @{p['limit']}c", quoted_at=p["snapshot_at"]))
    return rows, notes


# --------------------------------------------------------------------------
# pinning — what we actually did today
# --------------------------------------------------------------------------
def _fill_status(fill_count, avg_cents, explicit: str | None = None) -> tuple[str, str]:
    """(status, detail). fill_count==0 means "the reconciler has not run yet",
    NOT "no fill" — only Kalshi's fill_status can assert that, and only once it
    has moved off pending."""
    if fill_count:
        avg = f" @ {avg_cents:.0f}c" if avg_cents is not None else ""
        # partial / partial_resting: part of the order is still working
        rest = f" ({explicit})" if explicit and explicit not in ("filled", "pending", "unknown") else ""
        return "FILLED", f"{fill_count:g}{avg}{rest}"
    if explicit and explicit not in ("pending", "unknown"):
        return "PLACED", explicit
    return "PLACED", "unreconciled"


def placed_rows(conn, today: date, labels: dict) -> list[Row]:
    """Today's orders, from the three trade tables. Pinned forever.

    threshold is deliberately None on every row. None of the three tables
    records WHICH rule fired — live_trades has model_source but not
    signal_source — so on a UNION city (KORD/KDFW: raw 0.25 OR blend 0.10) we
    cannot tell which of the two a given trade cleared. merge() fills it in
    from the live signal when the row is still firing; otherwise it renders
    "—". A blank is honest, a guessed number is not.
    """
    out = []
    with conn.cursor() as cur:
        cur.execute("""SELECT t.ticker, c.station_id, t.side, t.limit_price_cents,
                              t.model_prob_yes, t.market_mid_prob, t.edge,
                              t.fill_status, t.fill_count, t.fill_price_cents
                       FROM live_trades t LEFT JOIN contracts c ON c.ticker=t.ticker
                       WHERE t.target_date=%s""", (today,))
        for tk, city, side, lim, mp, mkt, edge, fs, fc, fpx in cur.fetchall():
            status, detail = _fill_status(fc, fpx, fs)
            out.append(Row("kalshi", city or "?", tk, labels.get(tk, tk),
                           (side or "").upper(), mp, mkt, edge,
                           None, lim, status, detail))

        cur.execute("""SELECT t.ticker, c.station_id, t.intent, t.limit_price_cents,
                              t.model_prob_yes, t.market_mid_prob, t.edge,
                              t.fill_count, t.fill_avg_price_cents
                       FROM pm_live_trades t LEFT JOIN contracts c ON c.ticker=t.ticker
                       WHERE t.target_date=%s""", (today,))
        for tk, city, intent, lim, mp, mkt, edge, fc, favg in cur.fetchall():
            status, detail = _fill_status(fc, favg)
            out.append(Row("polymarket", city or pm.STATION, tk, labels.get(tk, tk),
                           "YES" if str(intent).endswith("LONG") else "NO",
                           mp, mkt, edge, None, lim, status, detail))

        cur.execute("""SELECT fx_contract_id, station_id, side, strike, limit_price_cents,
                              model_prob_yes, market_last_prob, edge, ibkr_order_id,
                              fill_count, fill_avg_price_cents
                       FROM fx_live_trades WHERE target_date=%s""", (today,))
        for tk, city, side, strike, lim, mp, mkt, edge, oid, fc, favg in cur.fetchall():
            status, detail = _fill_status(fc, favg)
            out.append(Row("forecastex", city, tk, f">{strike:g}", (side or "").upper(),
                           mp, mkt, edge, None,
                           lim, status, detail if oid else f"{detail} (no order id)"))
    return out


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
def decision_times(today: date) -> dict[str, list[tuple[str, datetime]]]:
    out = {v: [] for v in VENUES}
    for city, cfg in live_trade.CITY_CONFIG.items():
        if cfg.get("is_active") and not live_trade.check_halts(city):
            out["kalshi"].append((city, datetime(today.year, today.month, today.day,
                                                 cfg["decision_hour"], cfg["decision_minute"],
                                                 tzinfo=timezone.utc)))
    out["polymarket"].append((pm.STATION, datetime(today.year, today.month, today.day,
                                                   *PM_DECISION_UTC, tzinfo=timezone.utc)))
    for city, cfg in fx.CITY_CONFIG.items():
        if not fx.halted(city):
            out["forecastex"].append((city, datetime(today.year, today.month, today.day,
                                                     *cfg["decision_utc"], tzinfo=timezone.utc)))
    return out


def venue_freshness(conn, today: date) -> dict[str, datetime | None]:
    """Newest quote we hold per venue, whether or not anything is firing.

    Derived from prices, not from the rows on screen: on a quiet day no venue
    fires and the rows would tell you nothing about whether the feed is alive.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT c.platform, max(p.snapshot_at)
                       FROM prices p JOIN contracts c ON c.ticker = p.ticker
                       WHERE c.target_date=%s GROUP BY c.platform""", (today,))
        return dict(cur.fetchall())


def _freshness_caption(ts: datetime | None, now: datetime) -> str:
    age = age_minutes(ts, now)
    if age is None:
        return "[bold red]no quotes today[/]"
    mark = "[bold red] STALE[/]" if age > STALE_MINUTES else ""
    return f"data {ts:%H:%M:%S}Z ({age:.0f}m ago){mark}"


def _decision_caption(entries, now) -> str:
    if not entries:
        return "no active city"
    bits = []
    for city, when in sorted(entries, key=lambda e: e[1]):
        if when > now:
            mins = (when - now).total_seconds() / 60
            bits.append(f"{city} {when:%H:%M}Z in {mins:.0f}m")
        else:
            bits.append(f"{city} {when:%H:%M}Z passed")
    return "decision: " + ", ".join(bits)


def venue_table(venue: str, rows: list[Row], notes: list[str], now: datetime,
                decisions, fresh: datetime | None) -> Table:
    t = Table(title=f"[bold]{venue.upper()}[/]", title_justify="left",
              caption=(_decision_caption(decisions.get(venue, []), now) + "   |   "
                       + _freshness_caption(fresh, now)),
              caption_justify="left", expand=False, pad_edge=False,
              box=box.SIMPLE_HEAD)
    # Every column here is load-bearing, and an 80-column terminal (what you get
    # piping --once to a file) fits them only just. Three things buy the room:
    # no vertical rules, abbreviated headers, and dropping the raw ticker —
    # the longest cell on the row and the one nobody reads, since venue + city
    # + bracket already name the contract. `note` is the only column allowed to
    # widest, so it absorbs whatever width is left over. The old separate
    # `note` column got squeezed to zero width at 80, taking "unreconciled"
    # with it — the one qualifier that must never be lost — so it now lives
    # inside `status`, which is the same fact anyway.
    for col, just in (("city", "left"), ("brkt", "left"), ("side", "left"),
                      ("model", "right"), ("mkt", "right"), ("edge", "right"),
                      ("thr", "right"), ("px", "right"), ("age", "right"),
                      ("status", "left")):
        # status is the ONLY wrappable column: rich shrinks wrappable columns
        # first, so this is what keeps the numbers un-ellipsized at 80. It costs
        # a second line on "PLACED unreconciled" there, and none at >=100.
        t.add_column(col, justify=just, no_wrap=(col != "status"),
                     overflow="fold" if col == "status" else "ellipsis")
    for r in rows:
        age = age_minutes(r.quoted_at, now)
        if age is None:
            # only a pinned row that is no longer firing gets here: its
            # model/market/edge are the values recorded when we placed it.
            age_txt = Text("@entry", style="dim")
        elif age > STALE_MINUTES:
            # "!" not "STALE": the header carries the threshold, and the word
            # cost five columns the table does not have at 80 wide.
            age_txt = Text(f"{age:.0f}m!", style="bold red")
        else:
            age_txt = Text(f"{age:.0f}m")
        status_cell = Text(r.status, style={"LIVE": "bold cyan", "PLACED": "bold yellow",
                                            "FILLED": "bold green"}[r.status])
        if r.detail:
            status_cell.append("  " + r.detail, style="dim")
        edge_style = "green" if (r.edge or 0) > 0 else "red"
        t.add_row(
            r.city, r.label, r.side,
            f"{r.model_p:.3f}" if r.model_p is not None else "—",
            f"{r.market_p:.3f}" if r.market_p is not None else "—",
            Text(f"{r.edge:+.3f}" if r.edge is not None else "—", style=edge_style),
            f"{r.threshold:.2f}" if r.threshold is not None else "—",
            f"{r.entry}c" if r.entry is not None else "—",
            age_txt, status_cell)
    if not rows:
        t.add_row(*["[dim]—[/]"] * 10)
    for n in notes:
        t.caption += f"\n[dim]{n}[/]"
    return t


def tick(conn, today: date, now: datetime, venues) -> Group:
    labels = _contract_labels(conn, today)
    pins = placed_rows(conn, today, labels)
    decisions = decision_times(today)
    fresh = venue_freshness(conn, today)
    collectors = {"kalshi": kalshi_rows, "polymarket": pm_rows, "forecastex": fx_rows}
    tables = []
    for v in venues:
        try:
            live, notes = collectors[v](conn, today, now, labels)
        except Exception as e:                      # one bad venue must not blank the screen
            live, notes = [], [f"ERROR: {type(e).__name__}: {e}"]
        rows = merge(live, [p for p in pins if p.venue == v])
        tables.append(venue_table(v, rows, notes, now, decisions, fresh.get(v)))
    header = Text.assemble(
        (f"{now:%Y-%m-%d %H:%M:%S}Z", "bold"),
        (f"   local {now.astimezone():%H:%M:%S}   ", "dim"),
        ("READ-ONLY MONITOR", "bold magenta"),
        (f"   stale > {STALE_MINUTES}m", "dim"))
    return Group(header, *tables)


def _safe_tick(conn, today: date, now: datetime, venues):
    """(renderable, conn). A DB blip must land on screen, not kill an unattended
    monitor — at startup exactly as much as mid-loop, so both paths come through
    here. conn=None means "connect on this tick"."""
    try:
        if conn is None:
            conn = get_connection()
        return tick(conn, today, now, venues), conn
    except Exception as e:
        with contextlib.suppress(Exception):
            conn.close()
        return Text(f"{now:%H:%M:%S}Z  reconnecting after {type(e).__name__}: {e}",
                    style="bold red"), None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between refreshes")
    ap.add_argument("--once", action="store_true", help="render once and exit")
    ap.add_argument("--venue", action="append", choices=VENUES, help="repeatable filter")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="target date (debug)")
    a = ap.parse_args()
    venues = a.venue or list(VENUES)
    console = Console()
    conn = None
    try:
        now = datetime.now(timezone.utc)
        today = a.date or now.date()
        if a.once:
            # deliberately NOT guarded: --once is for cron/pipes, which want a
            # traceback and a nonzero exit, not a red banner and success.
            conn = get_connection()
            console.print(tick(conn, today, now, venues))
            return 0
        from rich.live import Live
        first, conn = _safe_tick(conn, today, now, venues)
        with Live(first, console=console, auto_refresh=False, screen=True) as screen:
            while True:
                time.sleep(a.interval)
                now = datetime.now(timezone.utc)
                if a.date is None and now.date() != today:
                    break            # end of day: stop rather than drift onto stale rows
                view, conn = _safe_tick(conn, today, now, venues)
                screen.update(view, refresh=True)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
