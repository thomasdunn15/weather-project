"""
Pipeline health check: runs daily after the paper-trade cron, alerts on
silent failures that would cost data-accumulation days.

Checks (in order; multiple can fire per run):
  1. Paper-trade cron actually fired today (paper_trade.log mtime past 14:45 UTC).
  2. Today's 00Z ECMWF forecast is in the DB (model='ifs', expected by ~07 UTC).
  3. Most recent observation is within 36 hours.
  4. Most recent Kalshi price snapshot is within 30 minutes.

On any failure: append to /var/log/weather/health_alerts.log and exit 1.
On all passing: write nothing (empty alert log = healthy pipeline).

The alert log staying empty is the success signal — `tail` it occasionally
or set MAILTO in crontab to get email on non-zero exit.

Run with: uv run python scripts/check_pipeline_health.py
"""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from weather_markets.db import get_connection


ALERT_LOG = Path("/var/log/weather/health_alerts.log")
PAPER_TRADE_LOG = Path("/var/log/weather/paper_trade.log")
PAPER_TRADE_CRON_HOUR = 14
PAPER_TRADE_CRON_MINUTE = 45
EXPECTED_FORECAST_MODEL = "ifs"
EXPECTED_FORECAST_INIT_HOUR = 0
STATION_ID = "KNYC"
OBSERVATION_MAX_DAYS_BEHIND = 2     # Allow 1 day natural lag (CF6 publishes after midnight ET)
PRICE_SNAPSHOT_MAX_AGE_MINUTES = 30


def emit_alert(now: datetime, symptom: str) -> None:
    """Append a timestamped ALERT line to the alert log."""
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ALERT_LOG.open("a") as f:
        f.write(f"[{now.isoformat()}] ALERT: {symptom}\n")
    print(f"ALERT: {symptom}")


def check_paper_trade_cron(now: datetime, alerts: list[str]) -> None:
    """Did the paper-trade cron fire today?"""
    expected_after = datetime.combine(
        now.date(), time(PAPER_TRADE_CRON_HOUR, PAPER_TRADE_CRON_MINUTE), tzinfo=timezone.utc,
    )
    if now < expected_after:
        return  # Cron hasn't been due yet today — don't alert.

    if not PAPER_TRADE_LOG.exists():
        alerts.append(f"paper_trade.log does not exist at {PAPER_TRADE_LOG}")
        return

    mtime = datetime.fromtimestamp(PAPER_TRADE_LOG.stat().st_mtime, tz=timezone.utc)
    if mtime < expected_after:
        alerts.append(
            f"paper_trade.log not appended since cron was due "
            f"(latest mtime: {mtime.isoformat()}, expected after {expected_after.isoformat()})"
        )


def check_forecast_freshness(now: datetime, alerts: list[str]) -> None:
    """Today's expected forecast init must be in the DB."""
    expected_init = datetime.combine(
        now.date(), time(EXPECTED_FORECAST_INIT_HOUR, 0), tzinfo=timezone.utc,
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM forecasts WHERE station_id = %s AND model = %s AND init_time = %s LIMIT 1",
                (STATION_ID, EXPECTED_FORECAST_MODEL, expected_init),
            )
            if cur.fetchone() is None:
                alerts.append(
                    f"no {EXPECTED_FORECAST_MODEL} forecast for {expected_init.isoformat()} "
                    "(ECMWF 00Z ingest cron at 07 UTC may have failed)"
                )


def check_observation_freshness(now: datetime, alerts: list[str]) -> None:
    """Latest observation date should be at most OBSERVATION_MAX_DAYS_BEHIND days
    behind today. Observations are once-daily and CF6 publishes after midnight ET,
    so a 1-day natural lag is expected."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                (STATION_ID,),
            )
            latest = cur.fetchone()[0]
    if latest is None:
        alerts.append("observations table is empty")
        return
    days_behind = (now.date() - latest).days
    if days_behind > OBSERVATION_MAX_DAYS_BEHIND:
        alerts.append(
            f"latest observation is {latest} ({days_behind} days behind today, "
            f"max {OBSERVATION_MAX_DAYS_BEHIND})"
        )


def check_price_snapshot_freshness(now: datetime, alerts: list[str]) -> None:
    """The latest Kalshi price snapshot should be very recent (every-5-min cron)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(snapshot_at) FROM prices")
            latest = cur.fetchone()[0]
    if latest is None:
        alerts.append("prices table is empty")
        return
    age_minutes = (now - latest).total_seconds() / 60
    if age_minutes > PRICE_SNAPSHOT_MAX_AGE_MINUTES:
        alerts.append(
            f"latest price snapshot is {latest.isoformat()} "
            f"({age_minutes:.1f}m old, max {PRICE_SNAPSHOT_MAX_AGE_MINUTES}m)"
        )


def main() -> None:
    now = datetime.now(tz=timezone.utc)
    alerts: list[str] = []

    check_paper_trade_cron(now, alerts)
    check_forecast_freshness(now, alerts)
    check_observation_freshness(now, alerts)
    check_price_snapshot_freshness(now, alerts)

    if not alerts:
        print(f"[{now.isoformat()}] all checks passed")
        return

    for symptom in alerts:
        emit_alert(now, symptom)

    raise SystemExit(1)


if __name__ == "__main__":
    main()
