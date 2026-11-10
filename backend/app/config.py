"""Runtime settings.

Every value can be overridden with an environment variable (prefix ``DP_``),
which is how the Docker / Proxmox OCI-LXC deployment is configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# backend/app/config.py -> project root is two levels up from ``app``.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    host: str
    port: int
    frontend_dir: Path
    log_level: str

    # Session lifetime, in minutes.
    session_idle_minutes: int
    session_absolute_minutes: int
    cookie_name: str
    cookie_secure: bool

    # PBX connection defaults.
    tls_verify: bool
    default_base_url: str
    request_timeout_seconds: int

    # Brute-force protection for /api/auth/login.
    login_max_failures: int
    login_window_seconds: int

    # Behind an Nginx/Traefik/Cloudflare reverse proxy, trust X-Forwarded-For.
    trust_proxy_headers: bool

    # Second password required by delete operations (desktop hard-coded 871211My).
    delete_password: str

    # Audit log: empty = memory only; a path appends JSONL (persist via a mounted volume).
    audit_file: str
    audit_max_entries: int


def load_settings() -> Settings:
    return Settings(
        app_name=_str("DP_APP_NAME", "Anderson Deltapath-Automation"),
        version=_str("DP_VERSION", "2.0.0-alpha.18"),
        host=_str("DP_HOST", "0.0.0.0"),
        port=_int("DP_PORT", 8080),
        frontend_dir=Path(_str("DP_FRONTEND_DIR", str(PROJECT_ROOT / "frontend"))),
        log_level=_str("DP_LOG_LEVEL", "INFO").upper(),
        session_idle_minutes=_int("DP_SESSION_IDLE_MINUTES", 60),
        session_absolute_minutes=_int("DP_SESSION_ABSOLUTE_MINUTES", 480),
        cookie_name=_str("DP_COOKIE_NAME", "dp_session"),
        cookie_secure=_bool("DP_COOKIE_SECURE", False),
        tls_verify=_bool("DP_TLS_VERIFY", False),
        default_base_url=_str("DP_DEFAULT_BASE_URL", ""),
        request_timeout_seconds=_int("DP_REQUEST_TIMEOUT", 30),
        login_max_failures=_int("DP_LOGIN_MAX_FAILURES", 5),
        login_window_seconds=_int("DP_LOGIN_WINDOW_SECONDS", 300),
        trust_proxy_headers=_bool("DP_TRUST_PROXY_HEADERS", False),
        delete_password=_str("DP_DELETE_PASSWORD", "871211My"),
        audit_file=_str("DP_AUDIT_FILE", ""),
        audit_max_entries=_int("DP_AUDIT_MAX_ENTRIES", 2000),
    )


settings = load_settings()
