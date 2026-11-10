"""Server-side store for authenticated Deltapath PBX sessions.

The browser only ever receives an opaque random session id in an HttpOnly
cookie.  The PBX's own PHP session (cookies, TLS settings) never leaves the
server, which is what makes this app work at all: a browser cannot talk to a
Deltapath PBX directly (self-signed certificate, TLS 1.0 / SECLEVEL=0,
``PHPSESSID`` cookie, no CORS headers).
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import settings
from .pbx.rest_client import RestClient


@dataclass
class PbxSession:
    sid: str
    client: RestClient
    base_url: str
    username: str
    login_mode: str
    created_at: float
    last_seen: float
    client_ip: str = ""
    probes: List[dict] = field(default_factory=list)

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.created_at)

    @property
    def idle_seconds(self) -> int:
        return int(time.time() - self.last_seen)

    def public(self) -> dict:
        """Session view safe to hand to the browser (never the password)."""
        return {
            "authenticated": True,
            "baseUrl": self.base_url,
            "username": self.username,
            "loginMode": self.login_mode,
            "createdAt": self.created_at,
            "lastSeen": self.last_seen,
            "ageSeconds": self.age_seconds,
            "idleSeconds": self.idle_seconds,
            "idleTimeoutSeconds": settings.session_idle_minutes * 60,
            "absoluteTimeoutSeconds": settings.session_absolute_minutes * 60,
        }


class SessionStore:
    """Thread-safe, in-memory session table.

    The app is deployed with a single uvicorn worker (see the Dockerfile), so
    an in-process table is sufficient and avoids a database dependency.
    """

    def __init__(self, idle_minutes: int, absolute_minutes: int) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, PbxSession] = {}
        self._idle_seconds = max(1, idle_minutes) * 60
        self._absolute_seconds = max(1, absolute_minutes) * 60

    def create(
        self,
        client: RestClient,
        base_url: str,
        username: str,
        login_mode: str,
        client_ip: str = "",
    ) -> PbxSession:
        now = time.time()
        session = PbxSession(
            sid=secrets.token_urlsafe(32),
            client=client,
            base_url=base_url,
            username=username,
            login_mode=login_mode,
            created_at=now,
            last_seen=now,
            client_ip=client_ip,
        )
        with self._lock:
            self.purge_locked()
            self._sessions[session.sid] = session
        return session

    def get(self, sid: Optional[str]) -> Optional[PbxSession]:
        if not sid:
            return None
        with self._lock:
            self.purge_locked()
            session = self._sessions.get(sid)
            if session is None:
                return None
            session.last_seen = time.time()
            return session

    def peek(self, sid: Optional[str]) -> Optional[PbxSession]:
        """Like :meth:`get` but does not refresh the idle timer."""
        if not sid:
            return None
        with self._lock:
            return self._sessions.get(sid)

    def drop(self, sid: Optional[str]) -> bool:
        if not sid:
            return False
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    def purge_locked(self) -> int:
        """Evict expired sessions. Caller must hold the lock."""
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_seen > self._idle_seconds
            or now - session.created_at > self._absolute_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        return len(expired)

    def purge(self) -> int:
        with self._lock:
            return self.purge_locked()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


store = SessionStore(settings.session_idle_minutes, settings.session_absolute_minutes)
