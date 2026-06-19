"""CLI entrypoint: render a research Markdown paper to HTML.

    uv run python scripts/render_research.py docs/research/md/<slug>.md
"""

import sys

from weather_markets.research_render import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
