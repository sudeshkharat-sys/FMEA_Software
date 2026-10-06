"""Shared-password gate for LAN use. Off when running from source; the exe launcher turns it on (TASKFLOW_AUTH=1).
Every page and API route needs a signed login cookie; the password is stored salted+hashed in taskflow_config.json
next to the exe. Same idea as pc_receiver_viewer."""
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .paths import DATA_DIR

CONFIG = DATA_DIR / "taskflow_config.json"
COOKIE = "taskflow_session"
SESSION_SECS = 12 * 3600
MAX_FAILS, LOCK_SECS = 5, 300
_fails: dict[str, list[float]] = {}


def enabled() -> bool:
    return os.environ.get("TASKFLOW_AUTH") == "1"


def _load() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def _save(cfg: dict):
    CONFIG.write_text(json.dumps(cfg, indent=2))


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()


def set_password(pw: str):
    cfg = _load()
    cfg["salt"] = secrets.token_hex(16)
    cfg["hash"] = _hash(pw, cfg["salt"])
    cfg.setdefault("secret", secrets.token_hex(32))
    cfg["secret"] = secrets.token_hex(32)  # new secret: everyone is logged out after a password change
    _save(cfg)


def ensure_password() -> str | None:
    """First run: make a random password, write FIRST_RUN_PASSWORD.txt, return it. Otherwise None."""
    cfg = _load()
    if cfg.get("hash") and cfg.get("secret"):
        return None
    pw = os.environ.get("TASKFLOW_PASSWORD") or secrets.token_urlsafe(9)
    set_password(pw)
    (DATA_DIR / "FIRST_RUN_PASSWORD.txt").write_text(
        f"TaskFlow login password:\n{pw}\n\nShare it with your team, then delete this file.\n"
        "Change it any time:  TaskFlow.exe --set-password\n")
    return pw


def _sign(exp: str) -> str:
    return hmac.new(_load().get("secret", "").encode(), exp.encode(), hashlib.sha256).hexdigest()


def _valid(cookie: str | None) -> bool:
    try:
        exp, sig = (cookie or "").split(".")
        return int(exp) > time.time() and hmac.compare_digest(sig, _sign(exp))
    except Exception:
        return False


def _locked(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < LOCK_SECS]
    return len(_fails[ip]) >= MAX_FAILS


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>TaskFlow · Sign in</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f6f7;font:15px system-ui,sans-serif;color:#111}
form{background:#fff;border:1px solid #e6e6e9;border-radius:20px;padding:32px;width:min(340px,86vw);box-shadow:0 10px 40px rgba(0,0,0,.08)}
h1{margin:0 0 4px;color:#e11d2e;letter-spacing:.02em;font-size:26px} p{margin:0 0 18px;color:#6b6b73}
input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #d4d4d9;border-radius:10px;font:inherit;margin-bottom:12px}
button{width:100%;padding:11px;border:0;border-radius:10px;background:#111;color:#fff;font:inherit;font-weight:600;cursor:pointer}
.e{color:#d92d20;margin:0 0 12px;font-size:13px}</style>
<form method=post action=/login><h1>TASKFLOW</h1><p>Enter the team password to continue.</p>@@ERR@@
<input type=password name=password placeholder=Password autofocus required><button>Sign in</button></form>"""


def install(app):
    @app.middleware("http")
    async def gate(request: Request, call_next):
        if not enabled() or request.url.path in ("/login", "/logout") or _valid(request.cookies.get(COOKIE)):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Please sign in again"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login")
    async def login_page():
        return HTMLResponse(PAGE.replace("@@ERR@@", ""))

    @app.post("/login")
    async def login(request: Request):
        ip = request.client.host if request.client else "?"
        if _locked(ip):
            return HTMLResponse(PAGE.replace('@@ERR@@', '<div class=e>Too many wrong attempts. Try again in a few minutes.</div>'), status_code=429)
        form = (await request.body()).decode()
        from urllib.parse import parse_qs
        pw = parse_qs(form).get("password", [""])[0]
        cfg = _load()
        if cfg.get("hash") and hmac.compare_digest(_hash(pw, cfg.get("salt", "")), cfg["hash"]):
            _fails.pop(ip, None)
            exp = str(int(time.time()) + SESSION_SECS)
            r = RedirectResponse("/", status_code=303)
            r.set_cookie(COOKIE, f"{exp}.{_sign(exp)}", max_age=SESSION_SECS, httponly=True, samesite="lax")
            return r
        _fails.setdefault(ip, []).append(time.time())
        return HTMLResponse(PAGE.replace('@@ERR@@', '<div class=e>Wrong password</div>'), status_code=401)

    @app.get("/logout")
    async def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(COOKIE)
        return r
