"""Ops-copilot digest CLI: gathers read-only evidence from our own data and
runs the B0 reasoning engine to produce today's operator digest.

READ-ONLY end to end. This script has no ability to place or adjust a trade —
it only reads Postgres and (unless --no-kalshi) Kalshi's read-only portfolio
endpoints, then writes a markdown report. Every suggestion in the digest
requires explicit operator approval; nothing here acts on its own.

Usage:
  uv run python scripts/ops_digest.py
  uv run python scripts/ops_digest.py --out docs/digests/$(date -u +%F)-ops-digest.md
  uv run python scripts/ops_digest.py --no-kalshi   # skip the live settlements pull (DB evidence only)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from weather_markets.copilot import render_digest, run_digest
from weather_markets.db import get_connection


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=None, help="also write the markdown digest here")
    p.add_argument("--no-kalshi", action="store_true",
                    help="skip the live /portfolio/settlements pull (DB evidence only)")
    args = p.parse_args()

    kalshi = None
    if not args.no_kalshi:
        from weather_markets.kalshi_api import KalshiClient

        kalshi = KalshiClient()
    try:
        with get_connection() as conn:
            result = run_digest(conn, kalshi=kalshi)
    finally:
        if kalshi is not None:
            kalshi.close()

    text = render_digest(result)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n")
        print(f"\n[written to {out_path}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
