# Pre-fix snapshot — Polymarket bracket semantics, 2026-08-23

Frozen record of every Polymarket-derived row **as generated under the OLD
(half-open) bracket assumption**, captured before `kalshi_equivalent_bracket`
was corrected. Nothing here is regenerated. New analysis is added ALONGSIDE it,
never over it, so any earlier conclusion stays auditable against the numbers
that actually produced it.

| file | rows | sha |
|---|---|---|
| `pm_paper_trades_prefix.csv` | 112 | `9148c903d608886d96a13c96c9baf910` |
| `pm_live_trades_prefix.csv`  | 4   | `2b9e22ba2744d94805c3651965e93235` |

## The assumption being retired

`evaluation.kalshi_equivalent_bracket` mapped a Polymarket `between` bracket
`[a, b)` to Kalshi's inclusive `a..b-1`:

```python
if bracket_type == "between":       # [a, b) -> integers a..b-1
    return {..., "strike_high": strike_high - 1}
```

So `gte92lt93` was scored as **92 only**.

## Why that is wrong

Two independent proofs.

**Tiling.** Polymarket ladders step by 2 on every station, same day:

```
KMIA  88-89 90-91 92-93 94-95
KLAX  77-78 79-80 81-82 83-84
KMDW  74-75 76-77 78-79 80-81
KNYC  80-81 82-83 84-85 86-87
KSFO  69-70 71-72 73-74 75-76
```

Under half-open semantics 89, 91, 93 and 95 would be covered by no contract at
all. A market must tile its outcome space, so the brackets are inclusive pairs.

**The venue says so.** `GET /v1/markets/tc-temp-miahigh-2026-08-23-gte92lt93f`:

> title: `92 to 93`
> description: "Will the highest temperature recorded at Miami International
> Airport (KMIA) ... be **between 92F and 93F**? Outcome verified from NWS
> Climatological Report."

The `gte{a}lt{b}` slug is a naming artifact. `contracts.strike_low/strike_high`
already held the correct inclusive pair; the `-1` corrupted it downstream.

## Blast radius

| consumer | affected? | note |
|---|---|---|
| `paper_trade_polymarket.py` signals | **YES** | `model_prob_yes` is P(low only), not P(pair) |
| `live_trade_polymarket.py` signals | **YES** | side selection can invert — see below |
| `contract_resolved_yes` (PM settle) | **in principle** | both settled trades score identically either way; verified, not assumed |
| `export_pt_dataset.py` | YES | consumes the same normalizer |
| Kalshi anything | **NO** | the branch is `platform == "polymarket"` only |
| ForecastEx | **NO** | `forecastex.py` states its contracts need no normalization |

### The concrete inversion

2026-08-23 KMIA, same strikes (92-93) on both venues:

| | model_p | market | edge | side |
|---|---|---|---|---|
| Kalshi `B92.5` (correct) | 0.710 | 0.605 | +0.105 | BUY_YES |
| PM `gte92lt93` (buggy) | 0.251 | 0.610 | −0.359 | BUY_NO |

A 150-lot BUY_NO filled on that signal. Correct edge was **+0.100 → BUY_YES**.

### Settled PM P&L is NOT affected

Both closed trades resolve the same under either reading, so realized P&L
(`+$63.01` cumulative) needs no restatement:

| date | contract | high | old reading | new reading | outcome |
|---|---|---|---|---|---|
| 08-20 | `gte93lt94` NO | 93 | 93 only → YES | 93-94 → YES | NO loses, both |
| 08-21 | `gte92lt93` NO | 94 | 92 only → NO | 92-93 → NO | NO wins, both |

Luck, not design: the highs landed outside the ambiguous degree.

## Merge rule for the corrected pass

`paper_trades` is keyed `(target_date, ticker, model_source)`. Corrected rows
therefore carry a **distinct `model_source`** rather than replacing anything, the
same way `combined` / `combined_hrrr` / `combined+blend` already coexist for
Chicago. Old and new sit side by side and are directly diffable; no UPDATE and
no DELETE is issued against historical rows.
