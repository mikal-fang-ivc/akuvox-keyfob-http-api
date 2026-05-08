from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .akuvox import AkuvoxClient
from .config import Settings, load_settings
from .csv_store import CsvStore
from .managers_store import ManagersStore
from .models import ManagerUpsertRequest, NameUpdateRequest

BASE_DIR = Path(__file__).resolve().parent.parent
settings = load_settings(BASE_DIR)

app = FastAPI(title="Akuvox Simple Web")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=False,
    same_site="lax",
    max_age=settings.session_max_age,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

csv_store = CsvStore(settings.csv_path)
akuvox_client = AkuvoxClient(settings)
managers_store = ManagersStore(settings.managers_json_path, settings.dev_login_email)
oauth = OAuth()


def is_allowed_email(email: str, cfg: Settings) -> bool:
    em = email.strip().lower()
    if not em:
        return False
    if cfg.allowlist_emails and em in cfg.allowlist_emails:
        return True
    return em.endswith(f"@{cfg.allowlist_domain}")


def is_allowed_google_domain(userinfo: dict[str, Any], cfg: Settings) -> bool:
    """Validate Google hosted domain when provided in ID token/userinfo."""
    expected = (cfg.allowlist_domain or "").strip().lower()
    if not expected:
        return True

    hd = str(userinfo.get("hd", "")).strip().lower()
    email = str(userinfo.get("email", "")).strip().lower()
    return (hd == expected) or email.endswith(f"@{expected}")


def require_user(request: Request) -> dict[str, Any]:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_limited_or_full(request: Request) -> dict[str, Any]:
    user = require_user(request)
    role = str(user.get("role", "")).strip().lower()
    if role not in {"limited", "full"}:
        raise HTTPException(status_code=403, detail="Insufficient access level")
    return user


def require_full_access(request: Request) -> dict[str, Any]:
    user = require_user(request)
    role = str(user.get("role", "")).strip().lower()
    if role != "full":
        raise HTTPException(status_code=403, detail="Full access required")
    return user


def write_audit(action: str, actor: str, detail: dict[str, Any]) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor,
        "detail": detail,
    }
    settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.audit_log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def to_akuvox_schedule_srelay(csv_value: str) -> str:
    """Convert CSV format like '1001-2;' into Akuvox format like '1001-2SA'."""
    value = (csv_value or "").strip()
    if not value:
        return ""
    if value.endswith(";"):
        return value[:-1] + "SA"
    return value


if settings.auth_mode in {"google", "both"}:
    if not settings.google_client_id or not settings.google_client_secret:
        # config.py already falls back to "dev" when creds are absent, but
        # guard here in case settings is constructed manually.
        pass
    else:
        oauth.register(
            name="google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "user": user,
            "app_title": settings.app_title,
            "auth_mode": settings.auth_mode,
            "akuvox_display_name": settings.akuvox_display_name,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user=Depends(require_full_access)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "user": user,
            "app_title": settings.app_title,
            "akuvox_display_name": settings.akuvox_display_name,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "app_title": settings.app_title,
            "auth_mode": settings.auth_mode,
            "error": error,
            "prefill_username": "",
        },
    )


@app.get("/login/google")
async def login_google(request: Request):
    if settings.auth_mode not in {"google", "both"}:
        return RedirectResponse(url="/login", status_code=302)

    if settings.broker_url:
        return_to = str(request.url_for("auth_callback"))
        return RedirectResponse(url=f"{settings.broker_url}/login?return_to={return_to}")

    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        prompt="select_account",
        hd=settings.allowlist_domain,
    )


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle dev-mode username/password form submission."""
    if settings.auth_mode not in {"dev", "both"}:
        return RedirectResponse(url="/login", status_code=302)

    def _bad(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "app_title": settings.app_title, "auth_mode": settings.auth_mode, "error": msg, "prefill_username": username},
            status_code=401,
        )

    if username.strip() != settings.dev_login_username or password != settings.dev_login_password:
        return _bad("Invalid username or password.")

    email = settings.dev_login_email.strip().lower()
    role = managers_store.get_role(email)
    if not role:
        return _bad("Dev login email is not in managers.json.")

    request.session["user"] = {"email": email, "name": username.strip(), "mode": "dev", "role": role}
    write_audit("login", email, {"mode": "dev", "role": role})
    return RedirectResponse(url="/", status_code=302)


@app.get("/auth/callback")
async def auth_callback(request: Request, token: str | None = None):
    if settings.broker_url and token:
        try:
            # We fetch JWKS from broker to verify token
            # For simplicity, we assume RS256 and look for keys at /.well-known/jwks.json
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{settings.broker_url}/.well-known/jwks.json")
                res.raise_for_status()
                jwks_data = res.json()

            # PyJWT can handle multiple keys from JWKS
            # But let's simplify: find the key that matches the 'kid'
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            jwk_key = next((k for k in jwks_data["keys"] if k["kid"] == kid), None)
            if not jwk_key:
                raise HTTPException(status_code=403, detail="Invalid token kid")

            # Convert JWK to PEM/Public Key for PyJWT
            # Authlib has tools for this, but PyJWT also supports JWK directly starting 2.10
            # Since we have 2.9.0, we'll use a hack or simple decoding
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk_key))

            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience="akuvox-local",  # Must match BROKER_AUDIENCE
                options={"leeway": 60},  # Allow 60 seconds of clock skew
            )
            email = payload.get("email", "").strip().lower()
            userinfo = {"email": email, "name": email.split("@")[0], "email_verified": True}
        except Exception as e:
            return RedirectResponse(url=f"/login?error=Authentication+failed.+Please+contact+your+administrator.", status_code=302)
    else:
        token_obj = await oauth.google.authorize_access_token(request)
        userinfo = token_obj.get("userinfo") or {}
        email = str(userinfo.get("email", "")).strip().lower()

    email_verified = bool(userinfo.get("email_verified"))

    role = managers_store.get_role(email)
    if not email:
        return RedirectResponse(url="/login?error=Could+not+retrieve+your+Google+account+email.", status_code=302)
    if not email_verified:
        return RedirectResponse(url="/login?error=Your+Google+account+email+is+not+verified.", status_code=302)
    if not is_allowed_google_domain(userinfo, settings):
        return RedirectResponse(url="/login?error=Your+Google+account+is+not+from+an+allowed+domain.", status_code=302)
    if not role:
        return RedirectResponse(url=f"/login?error=Access+denied.+{email}+is+not+authorised+to+use+this+application.", status_code=302)

    request.session["user"] = {
        "email": email,
        "name": userinfo.get("name", email.split("@")[0]),
        "email_verified": email_verified,
        "mode": "google",
        "role": role,
    }
    write_audit("login", email, {"mode": "google", "role": role})
    return RedirectResponse(url="/", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    user = request.session.get("user") or {}
    write_audit("logout", user.get("email", "unknown"), {})
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def api_me(user=Depends(require_user)):
    return {"ok": True, "user": user}


@app.get("/api/users")
async def api_users(user=Depends(require_limited_or_full)):
    _ = user
    return {"ok": True, "items": csv_store.list_users()}


@app.post("/api/users/{user_id}/name")
async def api_update_name(user_id: int, body: NameUpdateRequest, user=Depends(require_limited_or_full)):
    change = csv_store.update_name(user_id, body.new_name.strip())
    write_audit("update_name", user["email"], change)
    return {"ok": True, "change": change}


@app.post("/api/users/{user_id}/toggle-srelay")
async def api_toggle_srelay(user_id: int, user=Depends(require_limited_or_full)):
    change = csv_store.toggle_srelay(
        user_id,
        always_value=settings.srelay_always_value,
        never_value=settings.srelay_never_value,
    )
    write_audit("toggle_srelay", user["email"], change)
    return {"ok": True, "change": change}


@app.post("/api/users/{user_id}/sync-akuvox")
async def api_sync_akuvox(user_id: int, user=Depends(require_full_access)):
    row = csv_store.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    csv_user_id = str(row.get("UserId", "")).strip()
    csv_name = str(row.get("Name", "")).strip()
    csv_schedule_relay = str(row.get("Schedule-Relay", "")).strip()
    csv_schedule_srelay = str(row.get("Schedule-SRelay", "")).strip()
    csv_schedule_srelay_akuvox = to_akuvox_schedule_srelay(csv_schedule_srelay)

    if not csv_user_id:
        raise HTTPException(status_code=400, detail="CSV row missing UserId")

    try:
        users_result = akuvox_client.get_users()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Akuvox rejected user/get",
                "status_code": exc.response.status_code,
                "url": str(exc.request.url),
                "response": exc.response.text[:400],
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Akuvox connection error on get: {exc}") from exc

    device_items = ((users_result.get("data") or {}).get("item") or []) if isinstance(users_result, dict) else []
    device_item = next((item for item in device_items if str(item.get("UserID", "")).strip() == csv_user_id), None)
    if not device_item:
        raise HTTPException(
            status_code=404,
            detail=f"Akuvox user not found by UserID {csv_user_id}",
        )

    updated_item = dict(device_item)
    updated_item["Name"] = csv_name
    updated_item["ScheduleRelay"] = csv_schedule_relay
    updated_item["ScheduleSRelay"] = csv_schedule_srelay_akuvox

    payload = {
        "target": "user",
        "action": "set",
        "data": {
            "item": [updated_item],
        },
    }

    if settings.akuvox_debug:
        print(
            f"[AKUVOX_DEBUG] sync-akuvox id={user_id} actor={user.get('email', '')} "
            f"csv.Schedule-Relay={csv_schedule_relay!r} "
            f"csv.Schedule-SRelay={csv_schedule_srelay!r} "
            f"mapped.ScheduleSRelay={csv_schedule_srelay_akuvox!r}",
            flush=True,
        )
        print(f"[AKUVOX_DEBUG] sync-akuvox id={user_id} payload={payload}", flush=True)

    try:
        result = akuvox_client.set_user(payload)
    except httpx.HTTPStatusError as exc:
        if settings.akuvox_debug:
            print(
                f"[AKUVOX_DEBUG] sync-akuvox upstream status error id={user_id} status={exc.response.status_code} "
                f"url={str(exc.request.url)} body={exc.response.text[:600]}",
                flush=True,
            )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Akuvox rejected the request",
                "status_code": exc.response.status_code,
                "url": str(exc.request.url),
                "response": exc.response.text[:400],
            },
        ) from exc
    except httpx.HTTPError as exc:
        if settings.akuvox_debug:
            print(f"[AKUVOX_DEBUG] sync-akuvox upstream connection error id={user_id} err={exc}", flush=True)
        raise HTTPException(status_code=502, detail=f"Akuvox connection error: {exc}") from exc

    if settings.akuvox_debug:
        print(f"[AKUVOX_DEBUG] sync-akuvox id={user_id} result={result}", flush=True)

    if isinstance(result, dict):
        retcode = result.get("retcode")
        message = str(result.get("message", "")).strip().lower()
        # Akuvox set uses retcode=1 with message=OK on success for this model.
        if not ((isinstance(retcode, int) and retcode >= 0) and message == "ok"):
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Akuvox API returned an error",
                    "retcode": retcode,
                    "api_message": result.get("message", ""),
                },
            )
    else:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Akuvox API returned non-JSON response",
            },
        )

    write_audit("sync_akuvox", user["email"], {"id": user_id, "payload": payload, "result": result})
    return {"ok": True, "result": result}


@app.get("/api/admin/managers")
async def api_list_managers(user=Depends(require_full_access)):
    _ = user
    return {"ok": True, "items": managers_store.list_managers()}


@app.post("/api/admin/managers")
async def api_upsert_manager(body: ManagerUpsertRequest, user=Depends(require_full_access)):
    email = body.email.strip().lower()
    role = body.role.strip().lower()
    if settings.allowlist_domain and not email.endswith(f"@{settings.allowlist_domain}"):
        raise HTTPException(status_code=400, detail=f"Email must be in @{settings.allowlist_domain}")

    try:
        managers_store.upsert(email, role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit("manager_upsert", user["email"], {"email": email, "role": role})
    return {"ok": True, "items": managers_store.list_managers()}


@app.delete("/api/admin/managers/{email}")
async def api_delete_manager(email: str, user=Depends(require_full_access)):
    normalized = email.strip().lower()
    if normalized == str(user.get("email", "")).strip().lower():
        raise HTTPException(status_code=400, detail="You cannot remove your own account")

    try:
        managers_store.remove(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit("manager_delete", user["email"], {"email": normalized})
    return {"ok": True, "items": managers_store.list_managers()}


@app.get("/api/admin/audit-log")
async def api_audit_log(user=Depends(require_full_access), limit: int = 200):
    _ = user
    if not settings.audit_log_path.exists():
        return {"ok": True, "items": []}
    lines = settings.audit_log_path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"ok": True, "items": entries[-limit:]}


@app.get("/health")
async def health():
    return {"ok": True}
