"""Htek / Deltapath IP phone provisioning endpoints (Extras → Htek Provisioning).

All work is delegated to :mod:`backend.app.htek.engine`: a job runs in one
background thread and the page polls its snapshot. Passwords are accepted on the
start request only, are kept in the job's private parameters, and are never
returned by any endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import webbrowser
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..htek import engine
from ..security import client_ip, require_session
from ..sessions import PbxSession
from .audit import audit as audit_log

logger = logging.getLogger("dpauto.htek.api")

router = APIRouter()

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class StartRequest(BaseModel):
    mode: Literal["provision", "scan", "scan_full"] = "provision"
    ips: str = Field(default="", max_length=200_000)
    ipRange: str = Field(default="", max_length=200)
    server: str = Field(default="", max_length=255)
    httpUser: str = Field(default="", max_length=120)
    httpPass: str = Field(default="", max_length=200)
    macPrefix: str = Field(default="001fc1", max_length=40)
    auth1User: str = Field(default="admin", max_length=120)
    auth1Pass: str = Field(default="admin", max_length=200)
    auth2User: str = Field(default="admin", max_length=120)
    auth2Pass: str = Field(default="46709394", max_length=200)
    retryCycles: int = Field(default=20, ge=0, le=999)
    retryDelaySeconds: int = Field(default=15, ge=1, le=300)
    allowRouted: bool = False


class RescanRequest(BaseModel):
    ips: List[str] = Field(default_factory=list, max_length=engine.MAX_TARGETS)
    mode: Literal["", "provision", "scan", "scan_full"] = ""


class OpenRequest(BaseModel):
    ip: str = Field(..., max_length=45)


def _job_or_404(job_id: str, owner: str) -> engine.HtekJob:
    job = engine.manager.get_owned(job_id, owner)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Task not found (it may belong to another session)."},
        )
    return job


@router.get("/info")
def info(_session: PbxSession = Depends(require_session)) -> dict:
    return engine.info()


# ------------------------------------------------------------------ PBX defaults
_PROV_USER_KEYS = ("ftpusername", "ftpuser", "ftpaccount")
_PROV_PASS_KEYS = ("ftppassword", "ftppass", "ftppwd")


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _collect_provisioning_values(node, found: dict) -> None:
    """Flatten a RESTful JSON payload so nested ``data``/``list`` shapes work."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                _collect_provisioning_values(value, found)
                continue
            name = _normalise_key(key)
            if name and value not in (None, ""):
                found.setdefault(name, value)
    elif isinstance(node, list):
        for item in node:
            _collect_provisioning_values(item, found)


def _first_value(found: dict, names: tuple) -> str:
    for name in names:
        value = found.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


@router.get("/pbx-defaults")
def pbx_defaults(session: PbxSession = Depends(require_session)) -> dict:
    """Provisioning defaults from the PBX this session is already logged in to.

    ``server`` is the URL the operator used to reach the PBX (P237).  P1360 and
    P1361 come from ``equipment/provisionsetting`` (``ftp_username`` and
    ``ftp_password``).  A failure is returned as ``ok: false`` with a message so
    the page can keep its manual values; the password is never logged.
    """
    payload = {
        "ok": False,
        "server": str(session.base_url or "").rstrip("/"),
        "httpUser": "",
        "httpPass": "",
        "error": "",
    }
    endpoint = "RESTful/index.php/v1/get/equipment/provisionsetting"
    try:
        response = session.client.get(endpoint, {"_dc": str(int(time.time() * 1000))})
    except Exception as exc:  # noqa: BLE001 - reported to the operator
        payload["error"] = f"PBX request failed: {type(exc).__name__}: {exc}"
        return payload
    if response is None:
        payload["error"] = "PBX returned no response."
        return payload
    if response.status_code != 200:
        payload["error"] = f"PBX returned HTTP {response.status_code}."
        return payload
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - response format is PBX-defined
        payload["error"] = "PBX provisioning-settings response was not JSON."
        return payload

    found: dict = {}
    _collect_provisioning_values(data, found)
    user = _first_value(found, _PROV_USER_KEYS)
    password = _first_value(found, _PROV_PASS_KEYS)
    payload["httpUser"] = user
    payload["httpPass"] = password
    payload["ok"] = bool(user or password)
    if not payload["ok"]:
        payload["error"] = "PBX provisioning settings had no ftp_username / ftp_password."
    return payload


@router.get("/hotkey-event")
def hotkey_event(_session: PbxSession = Depends(require_session)) -> dict:
    """Last credential copy made by the desktop launcher's global shortcut.

    The launcher runs as a separate process from this backend, so it records
    the event in a small JSON file and the Htek page polls it for the toast.
    Only an index is exposed, never the credentials.
    """
    path = os.environ.get("DP_HTEK_EVENT_FILE") or os.path.join(
        tempfile.gettempdir(), "dp_auto_web_htek_hotkey.json"
    )
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "seq": int(data.get("seq") or 0),
            "index": int(data.get("index", -1)),
        }
    except Exception:  # noqa: BLE001 - no launcher has copied anything yet
        return {"seq": 0, "index": -1}


@router.get("/jobs/current")
def current_job(session: PbxSession = Depends(require_session)) -> dict:
    job = engine.manager.latest(session.sid)
    return {"job": job.snapshot() if job else None}


@router.post("/jobs")
def start_job(
    payload: StartRequest,
    request: Request,
    session: PbxSession = Depends(require_session),
) -> dict:
    try:
        job = engine.manager.start(session.sid, payload.model_dump())
    except engine.JobBusyError as exc:
        raise HTTPException(status_code=409, detail={"code": "busy", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "htek_unavailable", "message": str(exc)}) from exc

    summary = f"Htek {payload.mode} on {job.counts()['total']} target(s): {payload.ipRange or 'list'}"
    audit_log.record(
        "htek_start",
        actor=session.username,
        source_ip=client_ip(request),
        summary=summary,
        detail={"jobId": job.id, "mode": payload.mode, "server": payload.server, "targets": job.counts()["total"]},
    )
    return job.snapshot()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: PbxSession = Depends(require_session)) -> dict:
    return _job_or_404(job_id, session.sid).snapshot()


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str, request: Request, session: PbxSession = Depends(require_session)) -> dict:
    job = _job_or_404(job_id, session.sid)
    engine.manager.stop(job_id, session.sid)
    audit_log.record(
        "htek_stop",
        actor=session.username,
        source_ip=client_ip(request),
        summary=f"Htek task {job_id} stop requested",
        detail={"jobId": job_id},
    )
    return job.snapshot()


@router.post("/jobs/{job_id}/rescan")
def rescan_job(
    job_id: str,
    payload: RescanRequest,
    session: PbxSession = Depends(require_session),
) -> dict:
    source = _job_or_404(job_id, session.sid)
    ips = [item.strip() for item in payload.ips if item.strip()]
    if not ips:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Select at least one checked IP to rescan."},
        )

    params = dict(source.params)
    params.pop("_truncated", None)
    params["ips"] = "\n".join(ips)
    params["ipRange"] = ""
    if payload.mode:
        params["mode"] = payload.mode
    try:
        job = engine.manager.start(session.sid, params)
    except engine.JobBusyError as exc:
        raise HTTPException(status_code=409, detail={"code": "busy", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "htek_unavailable", "message": str(exc)}) from exc
    return job.snapshot()


@router.post("/jobs/{job_id}/clear")
def clear_rows(job_id: str, session: PbxSession = Depends(require_session)) -> dict:
    job = _job_or_404(job_id, session.sid)
    if job.state == "running":
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "Stop the running task before clearing the table."},
        )
    job.clear_rows()
    return job.snapshot()


@router.delete("/jobs/{job_id}/rows/{ip}")
def delete_row(job_id: str, ip: str, session: PbxSession = Depends(require_session)) -> dict:
    job = _job_or_404(job_id, session.sid)
    if not job.delete_row(ip):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"{ip} is no longer in this result table."},
        )
    return job.snapshot()


@router.post("/jobs/{job_id}/open")
def open_phone(
    job_id: str,
    payload: OpenRequest,
    request: Request,
    session: PbxSession = Depends(require_session),
) -> dict:
    """Open a phone's web UI in the operator's browser (desktop double-click parity).

    Only available when the app is used through the local launcher: a browser page
    cannot open a LAN URL on the client machine, and a container must not open
    windows on the server.
    """
    _job_or_404(job_id, session.sid)
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_only",
                "message": "Open-phone is only available from the local launcher on the operator PC.",
            },
        )
    if not engine.IPV4_RE.match(payload.ip):
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": "Invalid IPv4 address."})
    url = f"http://{payload.ip}/"
    try:
        opened = webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "open_failed", "message": f"Could not open the browser: {exc}"},
        ) from exc
    return {"ok": bool(opened), "url": url}


@router.get("/jobs/{job_id}/export.csv")
def export_job(job_id: str, session: PbxSession = Depends(require_session)) -> Response:
    job = _job_or_404(job_id, session.sid)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(job.started_at))
    return Response(
        content=job.to_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="htek_results_{stamp}.csv"'},
    )
