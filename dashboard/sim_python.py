"""Python reference P&L simulation — the authoritative counterpart to the
browser sim in static/app.js (jsComputeSim).

Moved verbatim from the former scripts/dashboard.py. The dashboard itself now
runs the sim client-side in JS; this module exists so tests/test_sim_parity.py
can keep the two implementations in lockstep (it AST-extracts these four
functions and runs them against the V8 port).

All P&L is net of Kalshi trading fees (per-contract entry fee).
"""
from __future__ import annotations

import math
import random

import pandas as pd


def _kelly_fraction(p_win: float, entry_price_cents: int) -> float:
    """Full Kelly fraction for a binary contract. Returns 0 if no positive edge."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0.0
    b = (100 - entry_price_cents) / entry_price_cents
    f = p_win - (1 - p_win) / b
    return max(0.0, f)


def _apply_stake_cap(
    raw_stake: float,
    balance: float,
    max_stake_pct: float | None,
    max_stake_dollars: float | None,
) -> tuple[float, bool]:
    """Clamp `raw_stake` to whichever cap binds (pct of bankroll, $ ceiling).
    Returns (clamped_stake, was_capped). A None cap is treated as +inf.

    Required because uncapped Kelly bets the model's full conviction (up to
    100% of bankroll on near-certain trades), which guarantees ruin on one
    loss. Scaling needs it too: at high overfit means, 5% compounds to fantasy
    multi-billion balances unreachable at Kalshi depth (~$1k per side)."""
    pct_cap = balance * max_stake_pct if max_stake_pct is not None else float("inf")
    dollar_cap = max_stake_dollars if max_stake_dollars is not None else float("inf")
    cap = min(pct_cap, dollar_cap)
    if raw_stake > cap:
        return cap, True
    return raw_stake, False


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Kalshi trading fee per contract in cents.

    Formula (per Kalshi docs): $0.07 × contracts × P × (1−P), rounded UP to the
    nearest $0.01 per fill. Charged on the entry trade only; no fee at settlement.
    Returns 0 for degenerate prices (≤0 or ≥100)."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    fee_dollars = 0.07 * p * (1.0 - p)
    return max(1, math.ceil(fee_dollars * 100))


def simulate_pnl(
    df: pd.DataFrame,
    starting_balance: float,
    sizing_type: str,
    *,
    contracts: int = 1,
    kelly_fraction: float = 0.5,
    scaling_pct: float = 0.05,
    amount_dollars: float = 25.0,
    execution_mode: str = "cross",
    max_stake_pct: float | None = 0.05,
    max_stake_dollars: float | None = None,
    max_contracts_per_trade: int | None = None,
    empirical_fills: dict | None = None,
) -> pd.DataFrame:
    """Walk resolved trades chronologically and compute cumulative balance.

    sizing_type:
      - "unit"    — buy `contracts` contracts per trade (constant; ignores bankroll).
      - "amount"  — stake = `amount_dollars` per trade (constant; ignores bankroll).
                    Contracts = amount_dollars / (entry_price/100). Like unit, but
                    risks the same DOLLARS regardless of contract price — at 10c
                    entry you get 10x more contracts than at 100c entry.
      - "kelly"   — stake = bankroll × kelly_fraction × Kelly-optimal fraction;
                    bankroll compounds. Bets MORE on high-edge trades.
      - "scaling" — stake = bankroll × scaling_pct (fixed % of CURRENT bankroll);
                    bankroll compounds but the % is constant regardless of edge.
                    Risk-per-trade is deterministic; aggressiveness doesn't depend
                    on the model's confidence in any particular signal.

    max_stake_pct / max_stake_dollars: stake caps applied to Kelly and Scaling.
    Both are evaluated; the lower binds. Set either to None to disable that cap.
    Defaults to 5% of bankroll, matching live_trade.py's MAX_STAKE_DOLLARS
    ($50 on $1k bankroll). Without these caps, Kelly blows up to $0 when a
    near-1.0 model_prob says "bet 50%+ of bankroll" and that trade loses, and
    Scaling compounds to multi-billion fantasy numbers that can't actually be
    filled on Kalshi's ~$1k-depth markets.

    execution_mode:
      - "cross"      — pay the cross-spread (entry_price_cents). Always fills.
      - "limit_100"  — post 1¢ inside the spread, assume 100% fills.
      - "limit_70"   — same limit price, 70% deterministic fill rate.
      - "limit_50"   — same limit price, 50% deterministic fill rate.
      Missed limit fills produce $0 P&L (no fee, no exposure). Fill is
      seeded so the curve is deterministic across reruns.

    All P&L is net of Kalshi trading fees (per-contract entry fee).
    """
    resolved = (
        df[df["won"].notna()]
        .sort_values(["target_date", "logged_at"])
        .reset_index(drop=True)
    )

    # execution_mode names ending in "_emp_<mode>" use empirical fill lookup from
    # the precomputed dict. Format: "emp:post_inside_spread" / "emp:cross_at_ask" /
    # "emp:cross_with_premium_1". The fills dict is keyed by row index.
    is_empirical = execution_mode.startswith("emp:")
    emp_mode_key = execution_mode[4:] if is_empirical else None

    fill_rate = ({"cross": 1.0, "limit_100": 1.0, "limit_70": 0.7, "limit_50": 0.5}
                 .get(execution_mode, 1.0))
    rng = random.Random(42)

    history = [{"date": None, "balance": starting_balance, "trade_pnl": 0.0}]
    balance = starting_balance

    for idx, row in resolved.iterrows():
        cross_entry = int(row["entry_price_cents"])
        won = bool(row["won"])

        if is_empirical:
            # Empirical: limit_price + fill bool come from precomputed dict
            emp = (empirical_fills or {}).get(idx, {}).get(emp_mode_key)
            if emp is None:
                # Missing data — skip with $0 P&L
                entry = cross_entry
                empirical_did_fill = False
            else:
                entry = int(emp["limit_price"])
                empirical_did_fill = bool(emp["filled"])
        elif execution_mode == "cross":
            entry = cross_entry
        else:
            bid, ask = row["market_yes_bid"], row["market_yes_ask"]
            if pd.isna(bid) or pd.isna(ask) or ask <= bid + 1:
                # No room to post inside the spread — fall back to cross.
                entry = cross_entry
            else:
                entry = max(1, cross_entry - int(ask - bid - 1))

        # Bracket label for display (same logic as Edge by bracket table)
        bt = row.get("bracket_type")
        if bt == "greater_than":
            bracket_str = f">{int(row['strike_low'])}°"
        elif bt == "less_than":
            bracket_str = f"<{int(row['strike_high'])}°"
        else:
            bracket_str = f"{int(row['strike_low'])}-{int(row['strike_high'])}°"

        if is_empirical:
            filled = empirical_did_fill
        else:
            filled = rng.random() < fill_rate
        if not filled:
            history.append({
                "date": pd.Timestamp(row["target_date"]),
                "balance": balance,
                "trade_pnl": 0.0,
                "ticker": row.get("ticker"),
                "bracket": bracket_str,
                "side": row.get("position"),
                "edge": float(row.get("edge", 0)),
                "entry_price_cents": entry,
                "contracts": 0,
                "stake_dollars": 0.0,
                "won": bool(row["won"]),
                "filled": False,
            })
            continue

        fee_per_contract = kalshi_fee_cents(entry) / 100.0  # dollars

        was_capped = False  # only relevant for kelly/scaling; unit/amount ignore caps
        if sizing_type == "unit":
            num_contracts_actual = int(contracts)
            gross_pnl = contracts * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - contracts * fee_per_contract
            stake_dollars = contracts * entry / 100.0
        elif sizing_type == "amount":
            # Fixed dollars per trade — like unit but in $ instead of contract count.
            # Doesn't compound (uses amount_dollars, not bankroll-derived value).
            stake = float(amount_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(num_contracts)  # round DOWN — never over-bet
            actual_stake = num_contracts_actual * entry / 100.0
            total_fee = num_contracts_actual * fee_per_contract
            gross_pnl = num_contracts_actual * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - total_fee
            stake_dollars = actual_stake
        elif sizing_type == "scaling":
            # Fixed % of CURRENT bankroll, no Kelly multiplier
            b = (100 - entry) / entry
            raw_stake = balance * scaling_pct
            stake, was_capped = _apply_stake_cap(raw_stake, balance, max_stake_pct, max_stake_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(round(num_contracts))
            total_fee = num_contracts * fee_per_contract
            gross_pnl = stake * b if won else -stake
            trade_pnl = gross_pnl - total_fee
            stake_dollars = stake
        else:  # kelly
            p_win = row["model_prob_yes"] if row["position"] == "BUY_YES" else (1 - row["model_prob_yes"])
            b = (100 - entry) / entry
            f = _kelly_fraction(p_win, entry) * kelly_fraction
            raw_stake = balance * f  # dollars
            stake, was_capped = _apply_stake_cap(raw_stake, balance, max_stake_pct, max_stake_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(round(num_contracts))
            total_fee = num_contracts * fee_per_contract
            gross_pnl = stake * b if won else -stake
            trade_pnl = gross_pnl - total_fee
            stake_dollars = stake

        # Apply max_contracts_per_trade depth cap if set. Models real-world
        # Kalshi book depth — beyond ~1500 contracts at the touch you'd get
        # partial fills, so cap the simulated position size to a realistic max.
        # Recompute stake / fees / pnl from the capped contract count.
        if max_contracts_per_trade is not None and num_contracts_actual > max_contracts_per_trade:
            num_contracts_actual = int(max_contracts_per_trade)
            stake_dollars = num_contracts_actual * entry / 100.0
            total_fee_capped = num_contracts_actual * fee_per_contract
            gross_pnl = num_contracts_actual * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - total_fee_capped

        balance += trade_pnl
        history.append({
            "date": pd.Timestamp(row["target_date"]),
            "balance": balance,
            "trade_pnl": trade_pnl,
            "ticker": row.get("ticker"),
            "bracket": bracket_str,
            "side": row.get("position"),
            "edge": float(row.get("edge", 0)),
            "entry_price_cents": entry,
            "contracts": num_contracts_actual,
            "stake_dollars": stake_dollars,
            "won": bool(row["won"]),
            "filled": True,
            "stake_capped": was_capped,
        })

    return pd.DataFrame(history)
