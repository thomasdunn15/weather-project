"""Alert helper. File-based for now; swap to Discord/email later by adding a
new `_dispatch` implementation without touching callers.

Convention:
    severity: 'info' | 'warn' | 'critical'
    source:   short string identifying the caller, e.g. 'live_trade', 'fill_monitor'
    message:  human-readable string

Every alert is appended to /var/log/weather/alerts.log AND printed to stderr.
Critical alerts also write a marker file at ~/.kalshi/alert_critical so cron
healthcheck can detect them.

Example:
    from weather_markets.alerts import send_alert
    send_alert('preflight failed: cumulative drawdown $-350', severity='critical',
               source='live_trade')
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ALERT_LOG = Path("/var/log/weather/alerts.log")
CRITICAL_MARKER = Path.home() / ".kalshi" / "alert_critical"

VALID_SEVERITY = {"info", "warn", "critical"}


def send_alert(message: str, severity: str = "info", source: str = "unknown") -> None:
    if severity not in VALID_SEVERITY:
        severity = "info"
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [{severity.upper():<8}] [{source}] {message}\n"

    # Print to stderr so cron output captures it
    sys.stderr.write(line)

    # Append to log file (best-effort: don't crash the caller if log write fails)
    try:
        ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ALERT_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        sys.stderr.write(f"WARN: could not write to {ALERT_LOG}: {e}\n")

    # Critical also drops a marker file
    if severity == "critical":
        try:
            CRITICAL_MARKER.parent.mkdir(parents=True, exist_ok=True)
            CRITICAL_MARKER.write_text(line)
        except Exception as e:
            sys.stderr.write(f"WARN: could not write critical marker: {e}\n")


def clear_critical_marker() -> None:
    """Clear the critical marker file. Call this after acknowledging/handling
    a critical alert (e.g., from a status-check script)."""
    if CRITICAL_MARKER.exists():
        CRITICAL_MARKER.unlink()


def has_critical_alert() -> bool:
    """Returns True if there's an unacknowledged critical alert."""
    return CRITICAL_MARKER.exists()
