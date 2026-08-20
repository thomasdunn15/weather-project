"""The stray-dashboard check must actually fire — a health check that can only
pass is worse than none, because it reads as coverage.

Context: worktree dev servers stacking up OOM-killed prod Postgres on
2026-06-19 while live trading was running.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import check_pipeline_health as h


def _run(repo_root, monkeypatch):
    monkeypatch.setattr(h, "REPO_ROOT", Path(repo_root))
    alerts: list[str] = []
    h.check_stray_dashboards(datetime.now(timezone.utc), alerts)
    return alerts


def test_dashboards_outside_the_repo_are_flagged(monkeypatch):
    """Point REPO_ROOT somewhere impossible: every running dashboard becomes
    'stray', which proves the /proc scan finds real processes."""
    alerts = _run("/nonexistent-repo", monkeypatch)
    if not alerts:
        pytest.skip("no dashboard running on this box to detect")
    assert all("stray dashboard running from" in a for a in alerts)
    assert all("/nonexistent-repo" in a for a in alerts)


def test_one_alert_per_directory_not_per_pid(monkeypatch):
    """A single dashboard is a shell + uv + python; it must report once."""
    alerts = _run("/nonexistent-repo", monkeypatch)
    if not alerts:
        pytest.skip("no dashboard running on this box to detect")
    dirs = [a.split("running from ")[1].split(" (expected")[0] for a in alerts]
    assert len(dirs) == len(set(dirs))


def test_the_repos_own_dashboard_is_not_flagged(monkeypatch):
    """The prod dashboard runs from the repo root and must never alert."""
    assert _run(h.REPO_ROOT, monkeypatch) == []


def test_unreadable_processes_do_not_crash_the_check(monkeypatch):
    """/proc entries vanish mid-scan and other users' processes are opaque;
    neither may take down the whole health run."""
    real = Path.read_bytes

    def explode(self, *a, **kw):
        if "cmdline" in str(self):
            raise PermissionError("simulated")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", explode)
    assert _run("/nonexistent-repo", monkeypatch) == []
