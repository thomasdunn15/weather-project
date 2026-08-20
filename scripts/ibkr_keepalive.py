"""Keep the IBKR gateway session alive, and make its death LOUD.

Two separate problems, only one of which this can solve:

  IDLE TIMEOUT (solvable). The brokerage session drops after ~5 idle minutes.
  A /tickle on a cron holds it open indefinitely, so a trader firing at 15:30
  does not find a session that quietly lapsed at 09:00.

  DAILY SSO EXPIRY (not solvable here). IBKR expires the underlying single
  sign-on roughly every 24h, plus a weekly Sunday shutdown. No amount of
  tickling revives that — it needs a browser login, or OAuth, or IBeam.

So the real job is the second half: when the session IS dead, say so somewhere
a human will see BEFORE the decision time, rather than letting the trader
discover it at 15:30 and log a 401 into a file nobody reads.

Alerts fire on STATE CHANGE only. A session that has been down overnight should
not write 288 identical alerts before breakfast.

  uv run python scripts/ibkr_keepalive.py
  uv run python scripts/ibkr_keepalive.py --quiet   # cron: only speak on change
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from weather_markets.alerts import send_alert
from weather_markets.ibkr import IBKRClient, IBKRError

STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "ibkr_session_state"


def read_state() -> str:
    try:
        return STATE_FILE.read_text().strip()
    except OSError:
        return "unknown"


def write_state(state: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(state)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true", help="print only on state change")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    prev = read_state()
    client = IBKRClient()

    try:
        client.tickle()
        st = client.auth_status()
        alive = bool(st.get("authenticated"))
        detail = (f"authenticated={st.get('authenticated')} "
                  f"connected={st.get('connected')} competing={st.get('competing')}")
    except IBKRError as e:
        alive = False
        detail = str(e)[:160]

    state = "alive" if alive else "dead"
    changed = state != prev
    write_state(state)

    if changed:
        if alive:
            send_alert(f"IBKR gateway session restored ({detail})",
                       severity="info", source="ibkr_keepalive")
        else:
            # Critical: with no session the ForecastEx trader cannot place an
            # order, and its failure would otherwise be a line in a log file.
            send_alert(
                f"IBKR gateway session DEAD — ForecastEx trading is offline. "
                f"Re-login: ssh -N -L 5000:localhost:5000 tdunn@<host> then open "
                f"https://localhost:5000 . ({detail})",
                severity="critical", source="ibkr_keepalive")

    if changed or not a.quiet:
        print(f"[{now.isoformat(timespec='seconds')}] session {state}"
              f"{' (CHANGED from ' + prev + ')' if changed else ''} — {detail}")
    return 0 if alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
