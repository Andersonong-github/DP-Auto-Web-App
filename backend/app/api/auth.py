"""Authentication endpoints.

Login model (agreed with the operator): the login form takes the *Deltapath
PBX* credentials directly.  The backend performs the PBX login, keeps the
resulting PHP session (cookies + relaxed TLS) in server memory, and hands the
browser nothing but an opaque HttpOnly session id.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response

from ..config import settings
from ..models import LoginRequest, SessionResponse
from ..pbx import engine as pipeline_engine
from ..pbx.rest_client import RestClient
from ..security import (
    clear_session_cookie,
    client_ip,
    current_session,
    login_throttle,
    set_session_cookie,
)
from ..sessions import store
from .audit import audit as audit_log

logger = logging.getLogger("dpauto.auth")

pipeline_registry = pipeline_engine.registry

router = APIRouter()

# Never let the proxy/framework follow the user into these.
_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def _normalise_base_url(raw: str) -> str:
    """Validate and normalise the PBX address coming from the login form."""
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise HTTPException(status_code=400, detail={"code": "bad_url", "message": "Please enter the PBX server address."})
    if "://" not in value:
        # RestClient applies the same private-IP heuristic; mirror it so the
        # validation below sees a real scheme.
        host = value.split("/")[0].split(":")[0]
        value = ("http://" if RestClient._is_private_ip(host) else "https://") + value

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail={"code": "bad_url", "message": "Only http:// or https:// addresses are supported."})
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail={"code": "bad_url", "message": "The address is missing a host name."})
    if parsed.hostname.lower() in _BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail={"code": "bad_url", "message": "This address is blocked by security policy."})
    return value


def _friendly_login_error(raw: str) -> str:
    text = (raw or "").lower()
    if "ssl" in text or "certificate" in text:
        return "TLS handshake failed: the PBX certificate cannot be verified or only legacy TLS is supported. Check the address and allow skipping certificate verification if needed."
    if "connection error" in text or "timed out" in text or "timeout" in text or "name or service" in text:
        return "Cannot reach the PBX: check the server address, port and network connectivity."
    if "rejected" in text or "login failed" in text:
        return "Login rejected: wrong username or password."
    if not text:
        return "Login failed: the PBX returned no error details."
    return f"Login failed: {raw[:200]}"


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    wait = login_throttle.retry_after(ip)
    if wait:
        raise HTTPException(
            status_code=429,
            detail={"code": "throttled", "message": f"Too many failed logins, please retry in {wait} seconds."},
            headers={"Retry-After": str(wait)},
        )

    base_url = _normalise_base_url(payload.base_url)
    verify = settings.tls_verify if payload.tls_verify is None else bool(payload.tls_verify)
    username = payload.username.strip()

    client = RestClient(base_url, verify=verify)
    ok = client.login(username, payload.password)
    if not ok:
        login_throttle.record_failure(ip)
        raw = getattr(client, "last_error", "") or ""
        logger.warning("PBX login failed for %s@%s from %s: %s", username, base_url, ip, raw[:200])
        audit_log.record(
            "login_failed",
            actor=username,
            source_ip=ip,
            summary=f"Login failed: {base_url}",
            detail={"baseUrl": base_url, "reason": raw[:300]},
            ok=False,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_failed",
                "message": _friendly_login_error(raw),
                "raw": raw[:500],
            },
        )

    login_throttle.reset(ip)
    session = store.create(
        client=client,
        base_url=client.base_url,
        username=username,
        login_mode=client.login_mode,
        client_ip=ip,
    )
    set_session_cookie(response, session.sid)
    logger.info("PBX login ok: %s@%s (mode=%s) from %s", username, client.base_url, client.login_mode, ip)
    audit_log.record(
        "login",
        actor=username,
        source_ip=ip,
        summary=f"Login successful: {client.base_url} ({client.login_mode})",
        detail={"baseUrl": client.base_url, "loginMode": client.login_mode},
    )
    return session.public()


@router.get("/session", response_model=SessionResponse)
def session_info(request: Request) -> dict:
    session = current_session(request)
    if session is None:
        return {"authenticated": False}
    return session.public()


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    sid = request.cookies.get(settings.cookie_name)
    existing = current_session(request)
    # Session is gone, so stop running pipelines too: their PBX connection belongs to this session
    stopped = pipeline_registry.stop_for_session(sid) if sid else 0
    dropped = store.drop(sid)
    clear_session_cookie(response)
    logger.info("logout: session dropped=%s pipelines stopped=%s", dropped, stopped)
    audit_log.record(
        "logout",
        actor=existing.username if existing else "-",
        source_ip=client_ip(request),
        summary=f"Logout (stopped {stopped} pipelines)",
        detail={"pipelinesStopped": stopped},
    )
    return {"ok": True, "dropped": dropped, "pipelinesStopped": stopped}
