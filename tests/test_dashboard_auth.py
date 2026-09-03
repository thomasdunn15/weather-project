"""The login is the only thing between the write endpoints and the internet
once a reverse proxy goes in front of the dashboard. Every property here is one
that, if it silently regressed, would not show up as a broken page.
"""
import time

import pytest
from starlette.testclient import TestClient

from dashboard import auth
from dashboard.app import app
from weather_markets.config import settings

USER, PW = "op@example.com", "correct horse"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_user", USER)
    monkeypatch.setattr(settings, "dashboard_password_hash", auth.hash_password(PW))
    monkeypatch.setattr(settings, "dashboard_secret", "s" * 64)
    monkeypatch.setattr(auth, "_FAIL_DELAY_S", 0)      # do not sleep in tests
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def unconfigured(monkeypatch):
    for k in ("dashboard_user", "dashboard_password_hash", "dashboard_secret"):
        monkeypatch.setattr(settings, k, None)
    return TestClient(app, follow_redirects=False)


# --- primitives -----------------------------------------------------------------
def test_password_round_trip_and_salting():
    h1, h2 = auth.hash_password(PW), auth.hash_password(PW)
    assert h1 != h2, "same password must not hash identically (no salt?)"
    assert auth.verify_password(PW, h1) and auth.verify_password(PW, h2)
    assert not auth.verify_password(PW + "x", h1)
    assert not auth.verify_password(PW, None)
    assert not auth.verify_password(PW, "garbage")


def test_token_rejects_tamper_wrong_secret_and_expiry():
    tok = auth.make_token("k", now=1_000_000)
    assert auth.check_token("k", tok, now=1_000_001)
    assert not auth.check_token("other", tok, now=1_000_001)
    exp, sig = tok.split(".")
    assert not auth.check_token("k", f"{int(exp) + 1}.{sig}", now=1_000_001)   # forged expiry
    assert not auth.check_token("k", tok, now=1_000_000 + auth.TTL_S + 1)       # expired
    assert not auth.check_token("k", None) and not auth.check_token("k", "nodot")


def test_next_refuses_open_redirects():
    assert auth._safe_next("/api/live") == "/api/live"
    assert auth._safe_next("//evil.example") == "/"
    assert auth._safe_next("https://evil.example") == "/"
    assert auth._safe_next(None) == "/"


# --- the gate -------------------------------------------------------------------
def test_unconfigured_fails_closed(unconfigured):
    """No credentials => no dashboard. NOT an open dashboard."""
    assert unconfigured.get("/").status_code == 503
    assert unconfigured.get("/api/live").status_code == 503
    assert unconfigured.get("/static/app.js").status_code == 503
    assert unconfigured.get("/login").status_code == 503


def test_anonymous_is_redirected_or_401(configured):
    r = configured.get("/")
    assert r.status_code == 302 and r.headers["location"].startswith("/login?next=")
    assert configured.get("/static/app.js").status_code == 302
    assert configured.get("/api/live").status_code == 401
    assert configured.post("/api/robinhood/entry", json={}).status_code == 401
    assert configured.delete("/api/robinhood/entry/1").status_code == 401


def test_login_sets_cookie_and_opens_the_door(configured):
    assert configured.get("/login").status_code == 200
    r = configured.post("/login", data={"username": USER, "password": PW, "next": "/api/backtest/cities"})
    assert r.status_code == 303 and r.headers["location"] == "/api/backtest/cities"
    assert auth.COOKIE in r.cookies
    c = r.headers["set-cookie"].lower()
    assert "httponly" in c and "samesite=lax" in c
    assert "secure" not in c, "plain http over the SSH tunnel must still be able to log in"
    assert configured.get("/api/backtest/cities").status_code == 200
    assert configured.get("/static/app.js").status_code == 200


def test_secure_flag_follows_the_proxy_header(configured):
    r = configured.post("/login", data={"username": USER, "password": PW},
                        headers={"x-forwarded-proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()


@pytest.mark.parametrize("user,pw", [(USER, "wrong"), ("who@example.com", PW), ("", "")])
def test_wrong_credentials_are_401_without_a_cookie(configured, user, pw):
    r = configured.post("/login", data={"username": user, "password": pw})
    assert r.status_code == 401 and auth.COOKIE not in r.cookies
    assert configured.get("/api/live").status_code == 401


def test_logout_clears_the_cookie(configured):
    configured.post("/login", data={"username": USER, "password": PW})
    assert configured.get("/api/backtest/cities").status_code == 200
    r = configured.get("/logout")
    assert r.status_code == 302
    assert configured.get("/api/backtest/cities").status_code == 401


def test_rotating_the_secret_logs_everyone_out(configured, monkeypatch):
    configured.post("/login", data={"username": USER, "password": PW})
    assert configured.get("/api/backtest/cities").status_code == 200
    monkeypatch.setattr(settings, "dashboard_secret", "t" * 64)
    assert configured.get("/api/backtest/cities").status_code == 401
