"""Agentic trade-decision advisor — the B3 live experiment.

Per city, per decision time: takes the BASELINE signals that
scripts/live_trade.py::compute_signals_for_today already produced (calibrated
EMOS/blend output + market context, strictly as-of the decision cutoff), runs
the B0 reasoning engine (matrix -> specialists -> debate -> master) over
as-of evidence chunks, and proposes bounded ADJUSTMENTS to those decisions.
It emits a decision object; the existing execution layer consumes it. This
module never imports the Kalshi client and cannot place orders.

Hypothesis + guardrails + judgment criteria:
docs/decisions/2026-07-22-agent-advisor-experiment.md

Hard guardrails, baked in:
- Allowed actions are ONLY keep / resize / skip / flip on baseline-fired
  signals. The agent cannot ADD trades, lower thresholds, or produce a
  numeric temperature forecast — it reasons about the calibrated output,
  never replaces it.
- size_multiplier clamped to [0, MAX_SIZE_MULTIPLIER].
- Live use is double-gated: CITY_CONFIG[city]["agent_advisor"] (absent =
  off) AND city in ADVISOR_LIVE_CITIES (empty until an operator override).
- advise_signals_for_live is fail-safe: ANY exception returns the baseline
  signals unchanged.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timezone
from typing import Literal, Sequence

from pydantic import BaseModel, ValidationError

from weather_markets.reasoning.client import Completer
from weather_markets.reasoning.engine import EngineResult, ReasoningEngine
from weather_markets.reasoning.matrix import Matrix
from weather_markets.reasoning.retriever import Chunk

# ---------------------------------------------------------------------------
# Flags / bounds
# ---------------------------------------------------------------------------

# LIVE gate. Empty = paper-only. Adding a city here is a manual operator
# override (like Dallas 2026-06-22 / Phoenix 2026-07-10): tiny size, only
# after the agent beats baseline out-of-sample per the experiment doc.
ADVISOR_LIVE_CITIES: frozenset[str] = frozenset()

MAX_SIZE_MULTIPLIER = 1.5
MAX_DEBATE_ROUNDS = 1  # one critique pass — keeps daily API cost bounded

# model_source suffixes for the paired paper arms (scripts/agent_advisor_log.py).
BASE_TAG = "[AB-BASE]"
AGENT_TAG = "[AB-AGENT]"


class AdvisorError(RuntimeError):
    """Engine ran but its proposal could not be parsed/validated."""


# ---------------------------------------------------------------------------
# Matrix (embedded — pure data, no file dependency)
# ---------------------------------------------------------------------------

MATRIX = Matrix.model_validate({
    "name": "trade-advisor",
    "description": "Should today's baseline signals be kept, resized, skipped, or flipped?",
    "points": [
        {"id": "calibration", "name": "Forecast calibration",
         "description": "How trustworthy are today's EMOS/blend probabilities — "
                        "recent hit rate, Brier, ensemble spread vs normal."},
        {"id": "market", "name": "Market context",
         "description": "Bid/ask, spread, book depth: what the market is saying "
                        "and what execution will cost."},
        {"id": "regime", "name": "Regime",
         "description": "Recent performance of this exact signal, spread regime, "
                        "anything unusual about today vs the training window."},
        {"id": "execution", "name": "Execution & risk",
         "description": "Fees, sizing, per-trade max loss, exec path (maker vs "
                        "cross), risk-envelope context."},
    ],
})


# ---------------------------------------------------------------------------
# Decision objects
# ---------------------------------------------------------------------------

Action = Literal["keep", "resize", "skip", "flip"]


class SignalAdjustment(BaseModel):
    ticker: str
    action: Action = "keep"
    size_multiplier: float = 1.0  # clamped to [0, MAX_SIZE_MULTIPLIER]
    why: str = ""


class AdvisorProposal(BaseModel):
    city: str
    target_date: date
    adjustments: dict[str, SignalAdjustment]  # keyed by ticker; absent = keep
    debate_rounds: int = 0
    n_ungrounded: int = 0
    decision_text: str = ""


# ---------------------------------------------------------------------------
# Retriever backend: deterministic scope filter over as-of chunks
# ---------------------------------------------------------------------------

class ScopedRetriever:
    """Returns every chunk tagged inside the specialist's matrix scope.

    Deterministic (no keyword ranking): the chunk set is small and built
    as-of the decision cutoff, so each specialist should see ALL of its
    slice, always."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = list(chunks)

    def retrieve(self, query: str, matrix_scope: Sequence[str]) -> list[Chunk]:
        scope = set(matrix_scope)
        return [c for c in self._chunks if scope & set(c.tags)]


def build_chunks(city: str, cfg: dict, signals: list[dict], conn, today: date) -> list[Chunk]:
    """As-of evidence for the engine. STRICT no-look-ahead: every query is
    bounded by the city's decision-time cutoff or by target_date < today."""
    cutoff = datetime.combine(
        today, dtime(cfg["decision_hour"], cfg["decision_minute"]), tzinfo=timezone.utc
    )
    chunks: list[Chunk] = []

    # -- calibration: today's forecast + recent settled accuracy of this signal
    s0 = signals[0]
    chunks.append(Chunk(
        id="cal-today", source="emos", tags=["calibration"],
        text=(f"Today's EMOS for {city}: mu={s0['emos_mu']:.2f}F sigma={s0['emos_sigma']:.2f}F "
              f"from ensemble mean={s0['ensemble_mean']:.2f}F std={s0['ensemble_std']:.2f}F "
              f"(models: {', '.join(cfg['models'])}, rolling 45d fit)."),
    ))
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*),
                      AVG(CASE WHEN (pt.position='BUY_YES') =
                               (CASE c.bracket_type
                                     WHEN 'greater_than' THEN o.high_temp_f >  c.strike_low
                                     WHEN 'less_than'    THEN o.high_temp_f <  c.strike_high
                                     ELSE o.high_temp_f >= c.strike_low AND o.high_temp_f <= c.strike_high
                                END)
                           THEN 1.0 ELSE 0.0 END),
                      AVG(ABS(pt.edge)),
                      AVG(pt.ensemble_std)
               FROM paper_trades pt
               JOIN contracts c ON c.ticker = pt.ticker
               JOIN observations o ON o.station_id = c.station_id AND o.date = pt.target_date
               WHERE pt.model_source = %s
                 AND pt.target_date >= %s - INTERVAL '45 days'
                 AND pt.target_date < %s""",
            (cfg["paper_model_source"], today, today),
        )
        n, winrate, avg_edge, avg_std = cur.fetchone()
    if n:
        chunks.append(Chunk(
            id="cal-recent", source="paper_trades", tags=["calibration", "regime"],
            text=(f"Last 45d settled paper record of '{cfg['paper_model_source']}': "
                  f"n={n}, win rate {float(winrate):.0%}, mean |edge| {float(avg_edge):.1%}, "
                  f"mean ensemble std {float(avg_std):.2f}F "
                  f"(today's ensemble std: {s0['ensemble_std']:.2f}F)."),
        ))

    # -- per-signal market context + baseline decision
    for i, s in enumerate(signals, 1):
        spread = s["yes_ask"] - s["yes_bid"]
        chunks.append(Chunk(
            id=f"sig-{i}", source="live_signal", ref=s["ticker"],
            tags=["market", "calibration"],
            text=(f"Signal {s['ticker']}: baseline says BUY {s['side'].upper()} "
                  f"(source={s['signal_source']}). Model P(yes)={s['model_p']:.3f}"
                  + (f", blend P(yes)={s['blend_p']:.3f}" if s.get("blend_p") is not None else "")
                  + f", market mid={s['market_mid']:.3f}, edge={s['edge']:+.1%}. "
                  f"YES bid/ask {s['yes_bid']}/{s['yes_ask']}c (spread {spread}c). "
                  f"Entry cost {s['cross_price']}c/contract (NO cost = 100 - YES bid)."),
        ))
        chunks.append(Chunk(
            id=f"exe-{i}", source="live_signal", ref=s["ticker"], tags=["execution"],
            text=(f"Execution for {s['ticker']}: path={s['exec_path']} "
                  f"(limit {s['limit_price']}c, post_only={s['post_only']}). "
                  f"Unit size {cfg.get('unit_contracts', 0)} contracts -> max loss "
                  f"${cfg.get('unit_contracts', 0) * s['cross_price'] / 100:.0f} if it loses. "
                  f"Taker fee ~7c x P x (1-P) per contract; maker 1/4 of that."),
        ))
        # book depth as-of cutoff (may be empty for thin books)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT side, SUM(qty) FROM orderbook_snapshots
                   WHERE ticker = %s
                     AND snapshot_at = (SELECT MAX(snapshot_at) FROM orderbook_snapshots
                                        WHERE ticker = %s AND snapshot_at <= %s)
                   GROUP BY side""",
                (s["ticker"], s["ticker"], cutoff),
            )
            depth = dict(cur.fetchall())
        if depth:
            chunks.append(Chunk(
                id=f"book-{i}", source="orderbook_snapshots", ref=s["ticker"], tags=["market"],
                text=(f"Book depth {s['ticker']} (latest snapshot <= decision time): "
                      f"YES {depth.get('yes', 0)} contracts resting, NO {depth.get('no', 0)}."),
            ))

    # -- regime: recent per-contract P&L of this signal + spread regime
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*), AVG(pt.market_yes_ask - pt.market_yes_bid)
               FROM paper_trades pt
               WHERE pt.model_source = %s
                 AND pt.target_date >= %s - INTERVAL '28 days' AND pt.target_date < %s""",
            (cfg["paper_model_source"], today, today),
        )
        n28, spread28 = cur.fetchone()
    chunks.append(Chunk(
        id="reg-spread", source="paper_trades", tags=["regime", "execution"],
        text=(f"Spread regime: last-28d mean spread on this signal "
              f"{'unknown (no trades)' if not n28 else f'{float(spread28):.1f}c across {n28} logged trades'}. "
              f"Regime guard halts live trading above 5c average."),
    ))
    chunks.append(Chunk(
        id="reg-today", source="live_signal", tags=["regime"],
        text=(f"Today {today.isoformat()} {city}: {len(signals)} baseline signal(s) fired "
              f"at decision time {cutoff.strftime('%H:%M')} UTC. "
              f"Strategy: {cfg['live_model_source_tag']}."),
    ))
    return chunks


# ---------------------------------------------------------------------------
# Engine question + proposal parsing
# ---------------------------------------------------------------------------

def _question(city: str, cfg: dict, signals: list[dict], today: date) -> str:
    lines = "\n".join(
        f"- {s['ticker']}: BUY {s['side'].upper()} @ {s['cross_price']}c, edge {s['edge']:+.1%}"
        for s in signals
    )
    return (
        f"City {cfg['city_name']} ({city}), target date {today.isoformat()}. "
        f"The validated baseline strategy fired these signal(s):\n{lines}\n\n"
        "For each signal, decide whether to keep it as-is, resize it (scale the "
        "contract count), skip it, or flip its side. The baseline is the "
        "product of a year of validation — deviate ONLY where the evidence "
        "specifically supports it; when in doubt, keep. You may NOT propose "
        "new trades, new thresholds, or your own temperature forecast.\n\n"
        "MASTER: your \"decision\" field must be STRICT JSON only, shaped as "
        '{"adjustments": [{"ticker": "...", "action": "keep|resize|skip|flip", '
        '"size_multiplier": 1.0, "why": "..."}]}. '
        f"size_multiplier is capped at {MAX_SIZE_MULTIPLIER}. Omitted tickers are kept."
    )


def parse_adjustments(decision_text: str, known_tickers: set[str]) -> dict[str, SignalAdjustment]:
    """Parse the master's decision text into validated, clamped adjustments.

    Unknown tickers are DROPPED (the agent may only touch baseline signals).
    Raises AdvisorError if the text holds no valid adjustments JSON."""
    start, end = decision_text.find("{"), decision_text.rfind("}")
    if start == -1 or end <= start:
        raise AdvisorError(f"no JSON in master decision: {decision_text[:200]!r}")
    try:
        payload = json.loads(decision_text[start:end + 1])
        items = [SignalAdjustment.model_validate(a) for a in payload.get("adjustments", [])]
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AdvisorError(f"master decision failed validation: {exc}") from exc

    out: dict[str, SignalAdjustment] = {}
    for adj in items:
        if adj.ticker not in known_tickers:
            continue
        mult = min(max(adj.size_multiplier, 0.0), MAX_SIZE_MULTIPLIER)
        if adj.action == "keep":
            mult = 1.0
        elif adj.action == "skip":
            mult = 0.0
        out[adj.ticker] = adj.model_copy(update={"size_multiplier": mult})
    return out


def propose(city: str, cfg: dict, signals: list[dict], today: date,
            completer: Completer, chunks: Sequence[Chunk]) -> AdvisorProposal:
    """Run the reasoning engine over as-of chunks -> validated proposal.

    Pure given (completer, chunks): no DB, no network of its own. Callers
    build chunks with build_chunks(conn=...) or inject fakes in tests."""
    engine = ReasoningEngine(ScopedRetriever(chunks), completer,
                             max_debate_rounds=MAX_DEBATE_ROUNDS)
    result: EngineResult = engine.run(_question(city, cfg, signals, today), MATRIX)
    adjustments = parse_adjustments(result.decision.text, {s["ticker"] for s in signals})
    return AdvisorProposal(
        city=city, target_date=today, adjustments=adjustments,
        debate_rounds=result.debate_rounds,
        n_ungrounded=len(result.decision.ungrounded),
        decision_text=result.decision.text,
    )


# ---------------------------------------------------------------------------
# Applying a proposal to the baseline signal list
# ---------------------------------------------------------------------------

def flip_signal(s: dict) -> dict:
    """Opposite side of a baseline signal. NO cost = 100 - YES bid; executed
    as a taker (limit at cross) so the flip actually happens as intended."""
    out = dict(s)
    if s["side"] == "yes":
        out["side"] = "no"
        out["cross_price"] = 100 - int(s["yes_bid"])
    else:
        out["side"] = "yes"
        out["cross_price"] = int(s["yes_ask"])
    out["cross_price"] = max(1, min(99, out["cross_price"]))
    out["limit_price"] = out["cross_price"]
    out["post_only"] = False
    out["exec_path"] = "cross_at_ask"
    out["p_win"] = 1.0 - s["p_win"]
    out["agent_flipped"] = True
    return out


def apply_adjustments(signals: list[dict], proposal: AdvisorProposal) -> list[dict]:
    """Baseline signals -> agent-adjusted signals. Never mutates the input.

    skip drops the signal; resize/flip set 'agent_multiplier' (the placement
    loop multiplies the sized contract count by it; absent key = 1.0 = the
    byte-for-byte baseline path)."""
    out: list[dict] = []
    for s in signals:
        adj = proposal.adjustments.get(s["ticker"])
        if adj is None or adj.action == "keep":
            out.append(dict(s))
            continue
        if adj.action == "skip" or adj.size_multiplier <= 0.0:
            continue
        s2 = flip_signal(s) if adj.action == "flip" else dict(s)
        s2["agent_multiplier"] = adj.size_multiplier
        out.append(s2)
    return out


def advise_signals_for_live(city: str, cfg: dict, signals: list[dict],
                            conn, today: date) -> list[dict]:
    """The ONLY entry point live_trade.py calls, and only when
    cfg['agent_advisor'] is set. Fail-safe by contract: any gate miss,
    engine error, or parse failure returns the baseline signals unchanged."""
    try:
        if city not in ADVISOR_LIVE_CITIES:
            print(f"  agent advisor: {city} not in ADVISOR_LIVE_CITIES; baseline unchanged")
            return signals
        from weather_markets.reasoning.client import ClaudeClient
        chunks = build_chunks(city, cfg, signals, conn, today)
        proposal = propose(city, cfg, signals, today, ClaudeClient(), chunks)
        adjusted = apply_adjustments(signals, proposal)
        for t, adj in proposal.adjustments.items():
            print(f"  agent advisor: {t} -> {adj.action} x{adj.size_multiplier:.2f} ({adj.why[:120]})")
        return adjusted
    except Exception as e:
        print(f"  agent advisor FAILED ({type(e).__name__}: {e}); baseline unchanged")
        return signals
