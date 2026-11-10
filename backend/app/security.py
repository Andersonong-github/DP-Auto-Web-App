"""Cookie helpers, the authentication dependency, and login throttling."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, Response

from .config import settings
from .sessions import PbxSession, store


def client_ip(request: Request) -> str:
    """Best-effort client address, honouring a reverse proxy when configured."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=sid,
        max_age=settings.session_absolute_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def current_session(request: Request) -> Optional[PbxSession]:
    """Resolve the caller's PBX session, or ``None`` when not signed in."""
    if not settings.cookie_name:
        return None
    return store.get(request.cookies.get(settings.cookie_name))


def require_session(request: Request) -> PbxSession:
    """FastAPI dependency: every protected endpoint goes through this."""
    session = current_session(request)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "unauthenticated",
                "message": "Not signed in or the session expired, please sign in again.",
            },
        )
    return session


class LoginThrottle:
    """Small in-memory failure counter to slow down password guessing."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self._max = max(1, max_failures)
        self._window = max(1, window_seconds)
        self._lock = threading.RLock()
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> Deque[float]:
        bucket = self._failures[key]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            bucket = self._failures[key]
        return bucket

    def retry_after(self, key: str) -> int:
        """Seconds the caller must wait, or ``0`` when not blocked."""
        now = time.time()
        with self._lock:
            bucket = self._trim(key, now)
            if len(bucket) < self._max:
                return 0
            return max(1, int(self._window - (now - bucket[0])) + 1)

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            bucket = self._trim(key, now)
            bucket.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_throttle = LoginThrottle(settings.login_max_failures, settings.login_window_seconds)
