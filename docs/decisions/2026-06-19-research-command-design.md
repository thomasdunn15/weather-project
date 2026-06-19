# `/research` command — design spec

*2026-06-19 · status: approved design, pre-implementation*

## Purpose

A project-level Claude Code slash command, `/research <topic>`, that runs a
hybrid (internal + external) research session on a topic and produces a
professional research paper as both Markdown source and rendered HTML, filed
under `docs/research/`.

Goal: turn an open question ("does combining 00Z runs give edge?", "how do
others calibrate ensemble forecasts to prediction markets?") into a durable,
decision-oriented, reproducible document.

## Scope of "research" — hybrid

Each run gathers evidence from two sides and weaves them into one paper:

- **Internal (your system):** query the `weather` Postgres DB, read the
  codebase, run read-only dry-runs/backtests, analyze logs.
- **External (web):** web search + fetch, reusing the `deep-research` approach
  (fan out queries, fetch sources, verify claims before asserting them).

## Output

Two artifacts per run, same basename:

- `docs/research/md/YYYY-MM-DD-<slug>.md` — Markdown source (greppable/diffable).
- `docs/research/html/YYYY-MM-DD-<slug>.html` — self-contained styled HTML
  (embedded CSS, no external files or server; double-click to open).

`<slug>` is a kebab-case slug derived from the topic. Date is the run date (UTC).

## Folder layout

```
docs/research/
  md/                         # markdown sources, one per paper
    YYYY-MM-DD-<slug>.md
  html/                       # rendered papers
    YYYY-MM-DD-<slug>.html
  _template.md                # report skeleton (kept at root, NOT a paper)
scripts/
  render_research.py          # md -> self-contained styled html
.claude/commands/
  research.md                 # the /research slash command
```

## Components

### 1. `.claude/commands/research.md`

Project-level slash command (versioned in the repo). Receives the topic via
`$ARGUMENTS`. Its body is a prompt instructing Claude to run the workflow below.

### 2. Workflow the command drives

1. **Scope check (lightweight):** restate the research question + assumptions,
   and list the internal sources (DB tables, code paths, logs/dry-runs) and
   external angles it will pursue. One short confirmation, then proceed.
2. **Internal evidence:** query the `weather` DB, read code, run read-only
   dry-runs/backtests, analyze logs.
3. **External evidence:** web search + fetch; verify claims before asserting.
4. **Write** `docs/research/md/YYYY-MM-DD-<slug>.md` from `_template.md`.
5. **Render** to `docs/research/html/YYYY-MM-DD-<slug>.html` via the script.
6. **Report** both file paths + how to open the HTML.

### 3. `docs/research/_template.md` — full quant report skeleton

Sections:

- **Question** — what we're trying to find out.
- **TL;DR / Verdict** — 1–3 sentence answer + confidence.
- **Methods & Data** — DB queries, code paths, web sources used.
- **Internal Findings** — results from your data/backtests (tables, numbers).
- **External Context** — what the literature/market does, cited.
- **Limitations & Threats to Validity**.
- **Recommendation** — actionable, freeze-aware (→ backlog if it implies a
  strategy change).
- **Sources** — links + queries, reproducible.

### 4. `scripts/render_research.py` (run via `uv`)

- Input: a Markdown path under `docs/research/md/`.
- Output: self-contained `.html` under `docs/research/html/` with the same
  basename (maps `md/` → `html/` automatically).
- Mechanism: Python `markdown` library + an embedded professional CSS template
  (clean typography, styled tables, code blocks, blockquotes). Tables-first;
  any charts the research step generates are embedded as base64 PNG so the file
  stays self-contained.
- Invocation: `uv run python scripts/render_research.py docs/research/md/<file>.md`

## Safety (freeze-aware, baked in)

- Strictly **read-only** for trading: no `--live`, no DB writes, no
  config/strategy changes.
- Per CONFIG FREEZE (until 2026-07-10): any recommendation that implies a
  strategy change is written as a proposal in the paper **and** appended to
  `docs/backlog.md` — never acted on.

## Out of scope (YAGNI v1)

- Auto-generated index page for `docs/research/`.
- Charts by default (add only when a question clearly needs one).
- PDF export.
- Scheduling / recurring research.

## Open question for implementation

- `scripts/render_research.py` needs the `markdown` package available under
  `uv`. Implementation plan will confirm/add it to the project's dependencies.
