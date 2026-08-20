"""Digest tab data — reads the latest cron-produced ops-copilot digest file.

Deliberately does NOT run the reasoning engine (no LLM call, no DB query) on
every page load: `scripts/ops_digest.py` writes one markdown file per day into
`docs/digests/`, and this module just reads the newest one. Keeps the tab
free, instant, and safe under the box's no-swap/OOM constraints.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import markdown

DIGESTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "digests"


def get_digest_data() -> dict:
    files = sorted(DIGESTS_DIR.glob("*-ops-digest.md")) if DIGESTS_DIR.is_dir() else []
    if not files:
        return {"exists": False, "asOf": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    latest = files[-1]
    text = latest.read_text()
    return {
        "exists": True,
        "file": latest.name,
        "generatedAt": datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "asOf": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "html": markdown.markdown(text, extensions=["tables"]),
    }
