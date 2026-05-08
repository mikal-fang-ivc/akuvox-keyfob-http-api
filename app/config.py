from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_title: str
    app_host: str
    app_port: int
    session_secret: str
    session_max_age: int
    csv_path: Path
    managers_json_path: Path
    srelay_always_value: str
    srelay_never_value: str
    auth_mode: str
    dev_login_email: str
    allowlist_domain: str
    allowlist_emails: set[str]
    google_client_id: str
    google_client_secret: str
    broker_url: str
    dev_login_username: str
    dev_login_password: str
    akuvox_scheme: str
    akuvox_ip: str
    akuvox_display_name: str
    akuvox_username: str
    akuvox_password: str
    akuvox_verify_ssl: bool
    akuvox_debug: bool
    akuvox_timeout_seconds: float
    audit_log_path: Path


def _split_emails(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _parse_bool(raw: str, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_auth_mode(requested: str, client_id: str, client_secret: str) -> str:
    """Return a supported auth mode, falling back to dev when Google is unavailable."""
    mode = (requested or "").strip().lower()
    if mode not in {"dev", "google", "both"}:
        mode = "dev"
    if mode in {"google", "both"} and not (client_id and client_secret):
        return "dev"
    return mode


def load_settings(base_dir: Path) -> Settings:
    csv_path = Path(os.getenv("CSV_PATH", "warehouse-keyfobs.csv"))
    if not csv_path.is_absolute():
        csv_path = base_dir / csv_path

    managers_json_path = Path(os.getenv("MANAGERS_JSON_PATH", "managers.json"))
    if not managers_json_path.is_absolute():
        managers_json_path = base_dir / managers_json_path

    audit_log_path = base_dir / "audit.log"

    return Settings(
        app_title=os.getenv("APP_TITLE", "Impressions Warehouse").strip() or "Impressions Warehouse",
        app_host=os.getenv("APP_HOST", "192.168.13.86"),
        app_port=int(os.getenv("APP_PORT", "43127")),
        session_secret=os.getenv("SESSION_SECRET", "replace-me"),
        session_max_age=int(os.getenv("SESSION_MAX_AGE", "3600")),
        csv_path=csv_path,
        managers_json_path=managers_json_path,
        srelay_always_value=os.getenv("SRELAY_ALWAYS_VALUE", "1001-2;").strip(),
        srelay_never_value=os.getenv("SRELAY_NEVER_VALUE", "1002-2;").strip(),
        auth_mode=_resolve_auth_mode(
            os.getenv("AUTH_MODE", "both").strip().lower(),
            os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        ),
        dev_login_email=os.getenv("DEV_LOGIN_EMAIL", "localadmin@impressionsvanity.com").strip(),
        allowlist_domain=os.getenv("ALLOWLIST_DOMAIN", "impressionsvanity.com").strip().lower(),
        allowlist_emails=_split_emails(os.getenv("ALLOWLIST_EMAILS", "")),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        broker_url=os.getenv("BROKER_URL", "").strip().rstrip("/"),
        dev_login_username=os.getenv("DEV_LOGIN_USERNAME", "admin").strip(),
        dev_login_password=os.getenv("DEV_LOGIN_PASSWORD", "admin").strip(),
        akuvox_scheme=os.getenv("AKUVOX_SCHEME", "http").strip().lower(),
        akuvox_ip=os.getenv("AKUVOX_IP", "192.168.0.88").strip(),
        akuvox_display_name=os.getenv("AKUVOX_DISPLAY_NAME", "Lobby Door 1st Floor").strip() or "Lobby Door 1st Floor",
        akuvox_username=os.getenv("AKUVOX_USERNAME", "admin").strip(),
        akuvox_password=os.getenv("AKUVOX_PASSWORD", "httpapi").strip(),
        akuvox_verify_ssl=_parse_bool(os.getenv("AKUVOX_VERIFY_SSL", "true"), default=True),
        akuvox_debug=_parse_bool(os.getenv("AKUVOX_DEBUG", "false"), default=False),
        akuvox_timeout_seconds=float(os.getenv("AKUVOX_TIMEOUT_SECONDS", "8")),
        audit_log_path=audit_log_path,
    )
