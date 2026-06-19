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
