---
description: Run a hybrid (internal data + web) research session and produce a quant report (md + html) under docs/research/
argument-hint: <topic or question to research>
---

You are running a research session for the weather-project trading stack.

**Topic:** $ARGUMENTS

Produce a rigorous, decision-oriented research paper as BOTH Markdown and HTML.

## Hard constraints
- **Read-only for trading.** Never run `scripts/live_trade.py --live`. Never write to the `weather` DB. Never change trading config/strategy. Allowed: DB `SELECT`s (`psql -d weather`), dry-runs (no `--live`), backtests, log reads.
- **Respect CONFIG FREEZE (until 2026-07-10).** If a finding implies a strategy/config change, write it as a proposal in the Recommendation section AND append a one-line entry to `docs/backlog.md`. Do not act on it.
- **Python via `uv run`** — never `.venv/bin/python` directly.

## Workflow
1. **Scope check.** Restate the question and your assumptions; list the internal sources (DB tables, code paths, logs, dry-runs/backtests) and external angles you'll pursue. Ask the user to confirm or adjust, then proceed.
2. **Internal evidence.** Query `psql -d weather`, read code under `src/` and `scripts/`, run read-only dry-runs/backtests, analyze logs. Capture concrete numbers and tables.
3. **External evidence.** Web search + fetch. Verify each external claim against its source before asserting it; cite everything.
4. **Write the paper.** Copy `docs/research/_template.md` to `docs/research/md/<YYYY-MM-DD>-<slug>.md` (UTC date; `<slug>` = kebab-case of the topic) and fill in every section. Use tables for internal numbers. Keep the verdict honest about confidence and limitations.
5. **Render to HTML.** Run `uv run python scripts/render_research.py docs/research/md/<YYYY-MM-DD>-<slug>.md` — writes the styled HTML to `docs/research/html/`.
6. **Report.** Print both file paths and tell the user they can open the HTML in a browser.
