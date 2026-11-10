"""Operation log (audit).

Records **state-changing or security-related** actions: login success/failure,
logout, pipeline start and end, delete operations. Read-only queries (number
lookup, search, probe) are deliberately not recorded, otherwise the log would be
flooded.

In memory by default (consistent with this project's sessions: stateless, cleared
on restart). Set ``DP_AUDIT_FILE`` to a persistent path (for example a volume
mounted into the container) to append JSONL and replay it at startup.

**Passwords are never recorded** - failed logins record only the username and an
error summary.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dpauto.audit")

KIND_LABELS = {
    "login": "Login OK",
    "login_failed": "Login failed",
    "logout": "Logout",
    "pipeline_start": "Pipeline started",
    "pipeline_end": "Pipeline ended",
    "delete": "Object deleted",
    "htek_start": "Htek task started",
    "htek_stop": "Htek task stopped",
}


@dataclass
class AuditEntry:
    id: str
    ts: float
    kind: str
    actor: str
    source_ip: str
    summary: str
    ok: bool = True
    detail: Dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind,
            "kindLabel": KIND_LABELS.get(self.kind, self.kind),
            "actor": self.actor,
            "sourceIp": self.source_ip,
            "summary": self.summary,
            "ok": self.ok,
            "detail": self.detail,
        }


class AuditLog:
    def __init__(self, path: Optional[str] = None, max_entries: int = 2000) -> None:
        self._lock = threading.RLock()
        self._entries: List[AuditEntry] = []
        self._max = max(50, max_entries)
        self._path = path or ""
        if self._path:
            self._load()

    # ------------------------------------------------------------------ write
    def record(
        self,
        kind: str,
        actor: str = "",
        source_ip: str = "",
        summary: str = "",
        detail: Optional[Dict[str, Any]] = None,
        ok: bool = True,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=uuid.uuid4().hex[:12],
            ts=time.time(),
            kind=kind,
            actor=actor or "-",
            source_ip=source_ip or "-",
            summary=summary,
            ok=ok,
            detail=detail or {},
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max:
                del self._entries[: len(self._entries) - self._max]
        self._persist(entry)
        logger.info("audit %s by %s: %s", kind, entry.actor, summary)
        return entry

    # ------------------------------------------------------------------ read
    def entries(self, limit: int = 200, kind: str = "", actor: str = "") -> List[AuditEntry]:
        with self._lock:
            rows = list(self._entries)
        if kind:
            rows = [row for row in rows if row.kind == kind]
        if actor:
            needle = actor.lower()
            rows = [row for row in rows if needle in row.actor.lower()]
        rows.reverse()  # newest first
        return rows[: max(1, limit)]

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def kinds(self) -> List[dict]:
        return [{"key": key, "label": label} for key, label in KIND_LABELS.items()]

    def to_csv(self, limit: int = 2000) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        # Times use the container's local timezone (the deploy script injects TZ,
        # default Asia/Kuala_Lumpur); the column names say "local" so they are not
        # confused with UTC.
        writer.writerow(["Time (local)", "Type", "Operator", "Source IP", "Result", "Summary", "Detail"])
        for row in self.entries(limit=limit):
            writer.writerow(
                [
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row.ts)),
                    KIND_LABELS.get(row.kind, row.kind),
                    row.actor,
                    row.source_ip,
                    "Succeeded" if row.ok else "Failed",
                    row.summary,
                    json.dumps(row.detail, ensure_ascii=False) if row.detail else "",
                ]
            )
        return "\ufeff" + buffer.getvalue()

    # ---------------------------------------------------------------- persistence
    def _persist(self, entry: AuditEntry) -> None:
        if not self._path:
            return
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 - an audit write failure must not affect business logic
            logger.warning("audit persist failed: %s", exc)

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as handle:
                lines = handle.readlines()[-self._max :]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self._entries.append(
                    AuditEntry(
                        id=str(data.get("id") or uuid.uuid4().hex[:12]),
                        ts=float(data.get("ts") or time.time()),
                        kind=str(data.get("kind") or "unknown"),
                        actor=str(data.get("actor") or "-"),
                        source_ip=str(data.get("source_ip") or "-"),
                        summary=str(data.get("summary") or ""),
                        ok=bool(data.get("ok", True)),
                        detail=data.get("detail") or {},
                    )
                )
            logger.info("audit loaded %d entries from %s", len(self._entries), self._path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audit load failed: %s", exc)
