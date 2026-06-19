# `/research` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-level `/research <topic>` slash command that runs a hybrid (internal data/code + external web) research session and emits a full quant report as Markdown + rendered HTML under `docs/research/`.

**Architecture:** Core rendering logic lives in the library (`src/weather_markets/research_render.py`, importable + unit-tested); `scripts/render_research.py` is a thin CLI wrapper (matching the repo's "library in `src/`, thin entrypoints in `scripts/`" pattern). The slash command (`.claude/commands/research.md`) is a prompt that drives the research workflow and calls the render script. Papers are stored as `docs/research/md/<slug>.md` sources rendered to `docs/research/html/<slug>.html`.

**Tech Stack:** Python 3.12 via `uv`, `markdown` (Python-Markdown) for md→html, pytest for tests, Claude Code slash command markdown.

## Global Constraints

- Python is invoked via `uv run` — never `.venv/bin/python` directly.
- Tests run with `uv run pytest`.
- The render output HTML must be **self-contained**: embedded `<style>`, no external stylesheet links, no JS, no network fetches.
- Paper paths: source `docs/research/md/YYYY-MM-DD-<slug>.md`, rendered `docs/research/html/YYYY-MM-DD-<slug>.html` (same basename, UTC date, kebab-case slug).
- Library import path is `weather_markets.<module>` (package root is `src/weather_markets/`).
- Commit messages end with the trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Trading stays read-only / freeze-aware (no `--live`, no DB writes, no config changes); enforced in the command prompt, not the render code.

---

### Task 1: Render module + CLI wrapper

**Files:**
- Modify: `pyproject.toml` (add `markdown` dependency, via `uv add`)
- Create: `src/weather_markets/research_render.py`
- Create: `scripts/render_research.py`
- Test: `tests/test_research_render.py`

**Interfaces:**
- Produces (consumed by Task 3's command via the CLI, and by the test):
  - `render_markdown(md_text: str, *, title: str) -> str` — full self-contained HTML document.
  - `html_path_for(md_path: Path) -> Path` — maps `.../md/<name>.md` → `.../html/<name>.html`.
  - `render_file(md_path: Path) -> Path` — reads md, writes html, returns the html path.
  - `main(argv: list[str]) -> int` — CLI entry (`argv[1]` is the md path).

- [ ] **Step 1: Add the `markdown` dependency**

Run: `cd /home/tdunn/weather-project && uv add markdown`
Expected: `pyproject.toml` gains `markdown` under `[project] dependencies`; `uv.lock` updates; exit 0.

- [ ] **Step 2: Write the failing test**

Create `tests/test_research_render.py`:

```python
from pathlib import Path

from weather_markets.research_render import (
    html_path_for,
    main,
    render_markdown,
)


def test_render_produces_self_contained_html():
    html = render_markdown("# My Title\n\nSome **bold** text.\n", title="My Title")
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html                 # CSS embedded inline
    assert 'rel="stylesheet"' not in html    # never links external CSS
    assert "<script" not in html             # no JS
    assert "<title>My Title</title>" in html
    assert "<strong>bold</strong>" in html


def test_render_supports_tables():
    html = render_markdown("| a | b |\n| - | - |\n| 1 | 2 |\n", title="t")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_html_path_maps_md_dir_to_html_dir():
    md_path = Path("docs/research/md/2026-06-19-foo.md")
    assert html_path_for(md_path) == Path("docs/research/html/2026-06-19-foo.html")


def test_main_writes_html_using_h1_as_title(tmp_path):
    md_dir = tmp_path / "docs" / "research" / "md"
    md_dir.mkdir(parents=True)
    md_file = md_dir / "2026-06-19-sample.md"
    md_file.write_text("# Sample Paper\n\nbody\n", encoding="utf-8")

    rc = main(["render_research.py", str(md_file)])

    assert rc == 0
    out = tmp_path / "docs" / "research" / "html" / "2026-06-19-sample.html"
    assert out.exists()
    assert "<title>Sample Paper</title>" in out.read_text(encoding="utf-8")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /home/tdunn/weather-project && uv run pytest tests/test_research_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'weather_markets.research_render'` (collection error).

- [ ] **Step 4: Implement the render module**

Create `src/weather_markets/research_render.py`:

```python
"""Render a research Markdown paper to a self-contained, styled HTML file.

Maps ``docs/research/md/<slug>.md`` -> ``docs/research/html/<slug>.html``.

Usage (always via uv, per CLAUDE.md):
    uv run python scripts/render_research.py docs/research/md/2026-06-19-foo.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import markdown

_CSS = """
:root { --fg:#1a1a1a; --muted:#666; --accent:#0b8457; --border:#e2e2e2;
  --bg:#fff; --code-bg:#f6f8fa; }
* { box-sizing:border-box; }
body { margin:0; background:#fafafa; color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.65; font-size:16px; }
.paper { max-width:820px; margin:48px auto; padding:56px 64px; background:var(--bg);
  border:1px solid var(--border); border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
h1 { font-size:2rem; line-height:1.2; margin:0 0 .25em;
  border-bottom:2px solid var(--fg); padding-bottom:.3em; }
h2 { font-size:1.35rem; margin:1.8em 0 .6em;
  border-bottom:1px solid var(--border); padding-bottom:.2em; }
h3 { font-size:1.1rem; margin:1.4em 0 .5em; }
em { color:var(--muted); }
a { color:#0366d6; text-decoration:none; }
a:hover { text-decoration:underline; }
table { border-collapse:collapse; width:100%; margin:1.2em 0; font-size:.93rem; }
th, td { border:1px solid var(--border); padding:8px 12px; text-align:left; }
th { background:var(--code-bg); font-weight:600; }
tr:nth-child(even) td { background:#fbfbfb; }
code { font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace; font-size:.88em;
  background:var(--code-bg); padding:.15em .4em; border-radius:4px; }
pre { background:var(--code-bg); border:1px solid var(--border); border-radius:6px;
  padding:14px 16px; overflow:auto; }
pre code { background:none; padding:0; }
blockquote { margin:1.2em 0; padding:.4em 1em; border-left:4px solid var(--accent);
  background:#f7fbf9; color:var(--muted); }
hr { border:none; border-top:1px solid var(--border); margin:2em 0; }
@media print { body { background:#fff; }
  .paper { border:none; box-shadow:none; margin:0; max-width:none; } }
""".strip()

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<main class="paper">
{body}
</main>
</body>
</html>
"""


def render_markdown(md_text: str, *, title: str) -> str:
    """Convert research Markdown to a complete self-contained HTML document."""
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )
    return _HTML_TEMPLATE.format(title=title, css=_CSS, body=body)


def html_path_for(md_path: Path) -> Path:
    """Map ``.../md/<name>.md`` to ``.../html/<name>.html``."""
    return md_path.parent.parent / "html" / (md_path.stem + ".html")


def _title_from(md_text: str, *, default: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return default


def render_file(md_path: Path) -> Path:
    """Read a Markdown paper, render it, write the HTML, return the html path."""
    md_text = md_path.read_text(encoding="utf-8")
    html = render_markdown(md_text, title=_title_from(md_text, default=md_path.stem))
    out_path = html_path_for(md_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render_research.py <path-to-md>", file=sys.stderr)
        return 2
    md_path = Path(argv[1])
    if not md_path.exists():
        print(f"error: no such file: {md_path}", file=sys.stderr)
        return 1
    out_path = render_file(md_path)
    print(f"rendered: {out_path}")
    return 0
```

- [ ] **Step 5: Create the thin CLI wrapper**

Create `scripts/render_research.py`:

```python
"""CLI entrypoint: render a research Markdown paper to HTML.

    uv run python scripts/render_research.py docs/research/md/<slug>.md
"""

import sys

from weather_markets.research_render import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/tdunn/weather-project && uv run pytest tests/test_research_render.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
cd /home/tdunn/weather-project
git add pyproject.toml uv.lock src/weather_markets/research_render.py scripts/render_research.py tests/test_research_render.py
git commit -m "feat: add research paper md->html render module + CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Research folder scaffolding + report template

**Files:**
- Create: `docs/research/md/.gitkeep`
- Create: `docs/research/html/.gitkeep`
- Create: `docs/research/_template.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `docs/research/_template.md` (copied by Task 3's command to start each paper); the `md/` and `html/` directories the render script reads/writes.

- [ ] **Step 1: Create the tracked empty directories**

Create `docs/research/md/.gitkeep` with empty content.
Create `docs/research/html/.gitkeep` with empty content.

- [ ] **Step 2: Create the report template**

Create `docs/research/_template.md`:

```markdown
# <Research topic — replace with the question, phrased as a title>

*<YYYY-MM-DD> · status: draft*

## Question
<What we're trying to find out, and why it matters now.>

## TL;DR / Verdict
<1–3 sentence answer. State confidence (low / medium / high) and the single biggest caveat.>

## Methods & Data
<Internal: which DB tables/queries, code paths, dry-runs/backtests. External: search angles + source types. Enough detail to reproduce.>

## Internal Findings
<Results from your own data. Use tables and concrete numbers — no hand-waving.>

## External Context
<What the literature / other market participants do. Every claim cited.>

## Limitations & Threats to Validity
<Sample size, regime dependence, look-ahead bias, data gaps — anything that could flip the verdict.>

## Recommendation
<Actionable next step. Freeze-aware: if it implies a strategy/config change, mark it as a backlog proposal (and add it to docs/backlog.md), not an action.>

## Sources
<Numbered list: external URLs + the internal queries/commands run, so the paper is reproducible.>
```

- [ ] **Step 3: Verify the template has all required sections**

Run: `cd /home/tdunn/weather-project && grep -c '^## ' docs/research/_template.md`
Expected: `8` — the eight `##` sections: Question, TL;DR / Verdict, Methods & Data, Internal Findings, External Context, Limitations & Threats to Validity, Recommendation, Sources. (The `# <topic>` title is a single `#`, not counted.) If grep returns anything else, a section is missing or misnamed — fix before committing.

- [ ] **Step 4: Commit**

```bash
cd /home/tdunn/weather-project
git add docs/research/md/.gitkeep docs/research/html/.gitkeep docs/research/_template.md
git commit -m "feat: scaffold docs/research with md/html dirs + report template

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `/research` slash command + end-to-end smoke test

**Files:**
- Create: `.claude/commands/research.md`

**Interfaces:**
- Consumes: `docs/research/_template.md` (Task 2), `scripts/render_research.py` (Task 1), the `docs/research/md` + `docs/research/html` dirs (Task 2).
- Produces: the `/research` user-facing command.

- [ ] **Step 1: Create the slash command**

Create `.claude/commands/research.md`:

```markdown
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
```

- [ ] **Step 2: End-to-end smoke test (render a sample paper)**

Run:
```bash
cd /home/tdunn/weather-project
cp docs/research/_template.md docs/research/md/2026-06-19-smoke-test.md
uv run python scripts/render_research.py docs/research/md/2026-06-19-smoke-test.md
test -f docs/research/html/2026-06-19-smoke-test.html && echo OK
grep -q 'rel="stylesheet"' docs/research/html/2026-06-19-smoke-test.html && echo "FAIL: external css" || echo "self-contained OK"
```
Expected: `rendered: docs/research/html/2026-06-19-smoke-test.html`, then `OK`, then `self-contained OK`.

- [ ] **Step 3: Remove the smoke-test artifacts (keep the folder clean)**

Run:
```bash
cd /home/tdunn/weather-project
rm docs/research/md/2026-06-19-smoke-test.md docs/research/html/2026-06-19-smoke-test.html
```

- [ ] **Step 4: Commit**

```bash
cd /home/tdunn/weather-project
git add .claude/commands/research.md
git commit -m "feat: add /research slash command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- If `uv add markdown` reports the dependency already present, that's fine — continue.
- The render module deliberately has **no** trading/DB logic; all read-only/freeze safety is enforced by the command prompt in Task 3.
- `.claude/commands/research.md` is picked up by Claude Code as the `/research` command once the file exists (no restart needed in most clients; reopen the session if it doesn't appear).
