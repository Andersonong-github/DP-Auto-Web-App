"""Audit log API: query and export."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response

from ..audit import KIND_LABELS, AuditLog
from ..config import settings
from ..security import require_session
from ..sessions import PbxSession

router = APIRouter()

audit = AuditLog(path=settings.audit_file or None, max_entries=settings.audit_max_entries)


@router.get("/entries")
def entries(
    limit: int = Query(200, ge=1, le=2000),
    kind: str = Query("", max_length=40),
    actor: str = Query("", max_length=120),
    _session: PbxSession = Depends(require_session),
) -> dict:
    rows = audit.entries(limit=limit, kind=kind, actor=actor)
    return {
        "total": audit.count(),
        "returned": len(rows),
        "persistent": bool(settings.audit_file),
        "kinds": audit.kinds(),
        "entries": [row.public() for row in rows],
    }


@router.get("/export.csv")
def export_csv(
    limit: int = Query(2000, ge=1, le=10000),
    _session: PbxSession = Depends(require_session),
) -> Response:
    return Response(
        content=audit.to_csv(limit=limit),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dp-audit.csv"'},
    )
