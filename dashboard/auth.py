"""Single-operator login for the dashboard.

Stdlib only — scrypt for the password, HMAC-SHA256 for the session cookie —
because one user needs neither a user table nor a session store, and the fewer
moving parts in an auth path the fewer places it can be wrong.

FAILS CLOSED. If DASHBOARD_USER / DASHBOARD_PASSWORD_HASH / DASHBOARD_SECRET are
not all set, every request gets a 503 rather than a dashboard. The loopback-only
bind was the only thing standing between the write endpoints and the internet;
the moment a reverse proxy goes in front of this, that guarantee is gone, and a
"login is optional in dev" switch is exactly the kind that ships to prod.

The cookie is stateless: `<expiry>.<hmac(secret, expiry)>`, 30 days. It survives
restarts, which matter here — the dashboard restarts on every deploy and the
operator reads it from a phone. There is deliberately no per-token revocation;
rotating DASHBOARD_SECRET logs everyone out, which for one user is the same
thing.

    uv run python -m dashboard.auth secret     # -> DASHBOARD_SECRET=... for .env
    uv run python -m dashboard.auth hash       # prompts, -> DASHBOARD_PASSWORD_HASH=...
"""
from __future__ import annotations

import asyncio
import getpass
import hashlib
import hmac
import secrets
import sys
import time
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from weather_markets.config import settings

COOKIE = "wx_session"
TTL_S = 30 * 86400
# scrypt parameters: ~50 ms on this box. Memory-hard, so a leaked hash is not
# cheaply brute-forced on a GPU the way a bare SHA would be. n=2^15, r=8 needs
# 128*r*n = 32 MiB, which is exactly OpenSSL's default maxmem — it raises
# "memory limit exceeded" unless the cap is stated.
_SCRYPT = dict(n=2 ** 15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
_FAIL_DELAY_S = 1.0      # per wrong password; a single operator never notices it


# --- password -----------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str | None) -> bool:
    try:
        algo, salt_hex, h_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        salt, want = bytes.fromhex(salt_hex), bytes.fromhex(h_hex)
    except ValueError:
        return False
    got = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(got, want)


# --- session cookie -----------------------------------------------------------
def _sign(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, now: float | None = None) -> str:
    exp = str(int((now if now is not None else time.time()) + TTL_S))
    return f"{exp}.{_sign(secret, exp)}"


def check_token(secret: str, token: str | None, now: float | None = None) -> bool:
    try:
        exp, sig = (token or "").split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(secret, exp)):
        return False
    try:
        return int(exp) > (now if now is not None else time.time())
    except ValueError:
        return False


def configured() -> bool:
    return bool(settings.dashboard_user and settings.dashboard_password_hash
                and settings.dashboard_secret)


def _https(request: Request) -> bool:
    """Behind Caddy the app sees http; Caddy says what the client used."""
    return (request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https")


def _safe_next(raw: str | None) -> str:
    """Only a same-site path. `//evil.com` is a protocol-relative URL — the
    classic open redirect — and is refused along with anything not rooted."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


# --- middleware ---------------------------------------------------------------
_NOT_CONFIGURED = ("dashboard login is not configured: set DASHBOARD_USER, "
                   "DASHBOARD_PASSWORD_HASH and DASHBOARD_SECRET in .env "
                   "(see dashboard/auth.py)\n")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/login", "/logout"):
            return await call_next(request)
        if not configured():
            return Response(_NOT_CONFIGURED, status_code=503, media_type="text/plain")
        if check_token(settings.dashboard_secret, request.cookies.get(COOKIE)):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "login required"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(path, safe='/')}", status_code=302)


# --- routes -------------------------------------------------------------------
router = APIRouter()

# Inline CSS on purpose: /static is behind the login, and the login page must
# render for someone who is, by definition, not logged in.
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in</title>
<style>
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f14;color:#e6edf3;
       font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  form{width:min(360px,90vw);padding:28px;border:1px solid #232b35;border-radius:12px;background:#111821}
  h1{margin:0 0 18px;font-size:17px;letter-spacing:.06em;text-transform:uppercase;color:#9aa7b5}
  label{display:block;font-size:12px;color:#9aa7b5;margin:12px 0 4px}
  input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #2a3440;border-radius:8px;
        background:#0b0f14;color:#e6edf3;font-size:15px}
  input:focus{outline:2px solid #5ee6c0;outline-offset:1px;border-color:#5ee6c0}
  button{margin-top:18px;width:100%;padding:12px;border:0;border-radius:8px;background:#5ee6c0;color:#062018;
         font-weight:700;font-size:14px;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
  .err{margin-top:12px;padding:10px 12px;border-radius:8px;background:#3a1518;color:#ff8f8f;font-size:13px}
</style></head><body>
<form method="post" action="/login" autocomplete="on">
  <h1>Weather desk</h1>
  <input type="hidden" name="next" value="{next}">
  <label for="u">Email</label>
  <input id="u" name="username" type="email" autocomplete="username" required autofocus>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
  {error}
</form></body></html>"""


def _page(next_path: str, error: str = "") -> str:
    err = f'<div class="err">{error}</div>' if error else ""
    return _PAGE.replace("{next}", next_path.replace('"', "&quot;")).replace("{error}", err)


@router.get("/login", include_in_schema=False)
async def login_form(request: Request) -> Response:
    if not configured():
        return Response(_NOT_CONFIGURED, status_code=503, media_type="text/plain")
    nxt = _safe_next(request.query_params.get("next"))
    if check_token(settings.dashboard_secret, request.cookies.get(COOKIE)):
        return RedirectResponse(nxt, status_code=302)
    return HTMLResponse(_page(nxt))


@router.post("/login", include_in_schema=False)
async def login_submit(request: Request) -> Response:
    if not configured():
        return Response(_NOT_CONFIGURED, status_code=503, media_type="text/plain")
    # Parsed by hand: python-multipart is not installed and a form of three
    # fields does not justify a dependency.
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    user = (form.get("username") or [""])[0]
    pw = (form.get("password") or [""])[0]
    nxt = _safe_next((form.get("next") or [""])[0])

    # Both checks always run, in constant time, so a wrong username costs the
    # same as a wrong password and reveals nothing about which it was.
    ok_user = hmac.compare_digest(user.encode(), (settings.dashboard_user or "").encode())
    ok_pw = verify_password(pw, settings.dashboard_password_hash)
    if not (ok_user and ok_pw):
        await asyncio.sleep(_FAIL_DELAY_S)
        return HTMLResponse(_page(nxt, "Wrong email or password."), status_code=401)

    resp = RedirectResponse(nxt, status_code=303)
    resp.set_cookie(COOKIE, make_token(settings.dashboard_secret), max_age=TTL_S,
                    httponly=True, samesite="lax", secure=_https(request), path="/")
    return resp


@router.get("/logout", include_in_schema=False)
async def logout() -> Response:
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE, path="/")
    return resp


# --- CLI ----------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "secret":
        print(f"DASHBOARD_SECRET={secrets.token_hex(32)}")
        return 0
    if cmd == "hash":
        # getpass keeps the password out of the shell history and the terminal;
        # stdin is accepted for non-interactive use, and is never echoed.
        pw = getpass.getpass("password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        if not pw:
            print("empty password refused", file=sys.stderr)
            return 1
        print(f"DASHBOARD_PASSWORD_HASH={hash_password(pw)}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
