"""Stale JS against a fresh payload is the failure this guards.

2026-08-31: a field was removed from /api/forecastex, the JS reading it was
updated, and the hand-maintained `?v=N` in index.html was NOT bumped. Browsers
kept the previous app.js, ran it against the new payload, and the tab died on
`undefined.toLocaleString()`. index() now stamps each asset from its own mtime,
so the bump cannot be forgotten — these tests hold that property.
"""
import os
import re

import pytest
from starlette.testclient import TestClient

from dashboard.app import STATIC_DIR, app

client = TestClient(app)
ASSET_RE = re.compile(r'"(/static/[^"?]+)\?v=(\d+)"')


def _assets(html: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in ASSET_RE.finditer(html)}


def test_every_static_url_is_stamped_with_its_own_mtime():
    found = _assets(client.get("/").text)
    assert found, "no stamped /static/ URLs in index.html"
    for url, v in found.items():
        path = STATIC_DIR / url.removeprefix("/static/")
        assert path.is_file(), url
        assert v == int(path.stat().st_mtime), url


def test_touching_one_asset_changes_only_that_stamp(tmp_path):
    """The actual guarantee: edit a file, its URL changes, the others don't."""
    target = STATIC_DIR / "app.js"
    before = _assets(client.get("/").text)
    st = target.stat()
    os.utime(target, (st.st_atime, st.st_mtime + 60))
    try:
        after = _assets(client.get("/").text)
        assert after["/static/app.js"] == before["/static/app.js"] + 60
        others = {k for k in before if k != "/static/app.js"}
        assert all(after[k] == before[k] for k in others)
    finally:
        os.utime(target, (st.st_atime, st.st_mtime))


def test_html_is_revalidated_or_the_stamps_never_arrive():
    """Without no-cache the browser reuses this HTML while index.html itself is
    unchanged — and then never sees the new stamp for the asset that changed."""
    assert client.get("/").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("name", ["app.js", "css/components.css"])
def test_stamped_url_serves_the_file(name):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200 and r.content
