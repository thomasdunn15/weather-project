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

from weather_markets.alerts import clear_critical_marker, send_alert
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
        # TICKLE ONLY A SESSION WE BELIEVE IS ALIVE. Tickling a dead one is
        # actively harmful: it refreshes the SSO layer (sso/validate keeps
        # returning RESULT=True, ssoExpires resets) while the brokerage layer
        # still refuses ssodh_init. The gateway will not rebind a fresh browser
        # login while it holds a session it considers valid, so the zombie
        # blocks the very recovery it is asking for.
        #
        # That is exactly 2026-08-26: a 43-hour-old SSO held open by this cron,
        # IB Key approvals landing nowhere, and "nothing happens" on the login
        # page. Letting a dead SSO expire is what makes re-login work.
        if prev == "alive":
            client.tickle()
        st = client.auth_status()
        if not st.get("authenticated"):
            # SSO can be valid while the BROKERAGE session was never opened —
            # the state the gateway's own web page cannot show you. Recover it
            # here instead of paging a human for a handshake a machine can do.
            try:
                client.ssodh_init()
            except IBKRError:
                pass
            else:
                st = client.auth_status()
        alive = bool(st.get("authenticated"))
        # SSO age is the field that tells a human WHICH failure this is: a young
        # SSO that will not promote is a gateway problem worth a restart; an old
        # one simply needs a browser login. Neither auth_status nor the gateway
        # web page shows it, which is why the last three outages looked identical.
        age = client.sso_age_hours()
        detail = (f"authenticated={st.get('authenticated')} "
                  f"connected={st.get('connected')} competing={st.get('competing')} "
                  f"sso_age={'none' if age is None else f'{age:.1f}h'}")
    except IBKRError as e:
        alive = False
        detail = str(e)[:160]

    state = "alive" if alive else "dead"
    changed = state != prev
    write_state(state)

    if changed:
        if alive:
            # Clear the marker too, or the login banner nags about an outage
            # that has already been fixed and stops being believed.
            clear_critical_marker()
            send_alert(f"IBKR gateway session restored ({detail})",
                       severity="info", source="ibkr_keepalive")
        else:
            # Critical: with no session the ForecastEx trader cannot place an
            # order, and its failure would otherwise be a line in a log file.
            send_alert(
                f"IBKR gateway session DEAD — ForecastEx trading is offline. "
                f"Re-login: ssh -N -L 5000:localhost:5000 tdunn@<host> then open "
                f"https://localhost:5000 . If IB Key completes but the page just "
                f"sits there, the gateway is holding a stale session — restart it "
                f"(tmux kill-session -t ibkr; then bin/run.sh root/conf.yaml in "
                f"~/ibkr-gateway) and log in again. ({detail})",
                severity="critical", source="ibkr_keepalive")

    if changed or not a.quiet:
        print(f"[{now.isoformat(timespec='seconds')}] session {state}"
              f"{' (CHANGED from ' + prev + ')' if changed else ''} — {detail}")
    return 0 if alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
