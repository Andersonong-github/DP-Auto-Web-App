"""Pipeline execution API: start / status / event stream (SSE) / stop / record export.

Only callers that are already signed in (holding a server-side PBX session) may
access it, and each session allows only one pipeline at a time (matching the
desktop version's ``pipeline_running`` behavior).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from typing import Generator, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..models import PipelineRunRequest, PipelineRunSnapshot
from ..pbx import engine
from ..pbx.ext_parser import parse_ext_range
from ..security import client_ip, require_session
from ..sessions import PbxSession
from .audit import audit as audit_log

logger = logging.getLogger("dpauto.pipeline")

router = APIRouter()

# Tasks that need an extension range
_EXT_TASKS = (
    "User (Mobility Apps Only)",
    "User (Htek Mac based Only)",
    "Number (Strip Digits)",
    "ACL User",
)


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "bad_request", "message": message})


def _validate(payload: PipelineRunRequest) -> None:
    params = payload.params
    allowed = engine.tasks_for_mode(payload.mode)
    selected = payload.tasks or allowed

    unknown = [name for name in selected if name not in allowed]
    if unknown:
        raise _bad_request(f"These tasks are not available in this mode: {', '.join(unknown)}")

    if all(name in selected for name in engine.MUTUALLY_EXCLUSIVE):
        raise _bad_request("Select only one of \"User (Mobility Apps Only)\" and \"User (Htek Mac based Only)\".")

    if "Group" in selected:
        if not params.group_name.strip():
            raise _bad_request("Enter Group Name.")
        if not params.group_code.strip():
            raise _bad_request("Enter Group Code.")

    limit = (params.unified_limit or "").strip()
    if limit and (not limit.isdigit() or not 1 <= int(limit) <= 300):
        raise _bad_request("Max Concurrent Calls & Reg User must be an integer from 1 to 300.")

    if any(name in selected for name in _EXT_TASKS) and not params.user_ext.strip():
        raise _bad_request("Enter User Extension / Extension Range.")

    if "User (Htek Mac based Only)" in selected:
        exts = parse_ext_range(params.user_ext, strip_six=(payload.mode != "complex"))
        if not exts:
            raise _bad_request("User Extension / Extension Range did not resolve to any valid extension.")
        rows = [row for row in params.htek_mac_data if str(row.get("mac") or "").strip()]
        if len(rows) != len(exts):
            raise _bad_request(f"Htek MAC data needs {len(exts)} rows (one per extension), but got {len(rows)}.")
        if not params.htek_model.strip():
            raise _bad_request("Select the Htek phone model, or choose \"List Provide Model\" and enter the model on each row.")

    # ---- Complex-mode-only checks (mirroring the branches in the desktop start_thread) ----
    if payload.mode == "complex":
        if "Context" in selected and not (params.context_suffixes or []):
            raise _bad_request("Context is selected: check at least one suffix or enter a custom suffix.")

        if "Permission Group" in selected:
            classes = (params.pg_spec or {}).get("classes") or []
            enabled = [item for item in classes if item.get("enabled")]
            if not enabled:
                raise _bad_request("Permission Group is selected: check at least one Class.")
            if any(not str(item.get("key") or "").strip() and not (item.get("ctx") or []) for item in enabled):
                raise _bad_request("Permission Group: every enabled Class needs a Context combination.")

        if "ACL Group" in selected and not (params.acl_group_selection or []):
            raise _bad_request("ACL Group is selected: check at least one of _Managers/_Supervisors/_Users.")

        if "User Profile" in selected and not (params.profile_classes_selection or []):
            raise _bad_request("User Profile is selected: check at least one Class.")

        ext_count = len(parse_ext_range(params.user_ext, strip_six=False)) if params.user_ext.strip() else 0
        for label, values in (("Username", params.usernames), ("Email", params.emails)):
            rows = [value for value in (values or []) if str(value).strip()]
            if rows and ext_count and len(rows) != 1 and len(rows) != ext_count:
                raise _bad_request(
                    f"{label} needs {ext_count} rows (or 1 row shared by all extensions), but got {len(rows)}."
                )


def _get_run(run_id: str, session: PbxSession) -> engine.PipelineRun:
    run = engine.registry.get(run_id)
    if run is None or run.session_id != session.sid:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "Run not found (it may have expired)."})
    return run


def _run_guarded(run: engine.PipelineRun, session: PbxSession) -> None:
    try:
        engine.execute(run, session.client)
    except Exception:  # noqa: BLE001 - must be caught in the thread, or run_end is never sent
        logger.exception("pipeline %s crashed", run.id)
        run.finished_at = run.finished_at or __import__("time").time()
        run.emit("run_end", status="failed", records=len(run.records), customerId=run.customer_id)
    finally:
        ok = sum(1 for state in run.tasks if state.status == engine.STATUS_SUCCESS)
        failed = sum(1 for state in run.tasks if state.status == engine.STATUS_ERROR)
        audit_log.record(
            "pipeline_end",
            actor=session.username,
            source_ip=session.client_ip,
            summary=(
                f"{run.mode} pipeline {_STATUS_CN.get(run.status, run.status)}: "
                f"{ok} succeeded / {failed} failed, {len(run.records)} extension records"
            ),
            detail={
                "runId": run.id,
                "mode": run.mode,
                "status": run.status,
                "success": ok,
                "failed": failed,
                "records": len(run.records),
                "customerId": run.customer_id,
                "groupName": run.params.get("group_name", ""),
            },
            ok=run.status == "success",
        )


_STATUS_CN = {"success": "success", "failed": "failed", "stopped": "stopped", "running": "running"}


@router.post("/run", response_model=PipelineRunSnapshot, status_code=202)
def start_run(
    payload: PipelineRunRequest,
    request: Request,
    session: PbxSession = Depends(require_session),
) -> dict:
    _validate(payload)
    params = payload.params.model_dump()
    params["custom_api_payloads"] = dict(payload.custom_payloads)

    try:
        run = engine.registry.create(session.sid, payload.mode, params, payload.tasks)
    except engine.PipelineBusy as exc:
        raise HTTPException(status_code=409, detail={"code": "pipeline_busy", "message": str(exc)}) from exc
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc

    threading.Thread(target=_run_guarded, args=(run, session), name=f"pipeline-{run.id}", daemon=True).start()
    logger.info(
        "pipeline %s started by %s (mode=%s, tasks=%d)",
        run.id,
        session.username,
        run.mode,
        len(run.tasks),
    )
    audit_log.record(
        "pipeline_start",
        actor=session.username,
        source_ip=client_ip(request),
        summary=f"Started {run.mode} pipeline: {len(run.tasks)} tasks (group {params.get('group_name') or '-'})",
        detail={
            "runId": run.id,
            "mode": run.mode,
            "tasks": [state.name for state in run.tasks],
            "groupName": params.get("group_name", ""),
            "userExt": params.get("user_ext", ""),
        },
    )
    return run.public()


@router.get("/runs", response_model=List[PipelineRunSnapshot])
def list_runs(session: PbxSession = Depends(require_session)) -> list:
    return [run.public() for run in engine.registry.list_for(session.sid)]


@router.get("/runs/{run_id}", response_model=PipelineRunSnapshot)
def get_run(run_id: str, session: PbxSession = Depends(require_session)) -> dict:
    return _get_run(run_id, session).public()


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, session: PbxSession = Depends(require_session)) -> dict:
    run = _get_run(run_id, session)
    engine.registry.stop(run.id)
    logger.info("pipeline %s stop requested by %s", run.id, session.username)
    return {"ok": True, "id": run.id, "status": run.status}


def _sse_payload(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _event_stream(run: engine.PipelineRun, after: int) -> Generator[str, None, None]:
    """Stream a run's events as SSE.

    A reconnect with ``?after=<lastSeq>`` resumes where it left off; even if the
    browser closes, the pipeline itself runs to completion (events stay in
    memory until the next fetch).
    """
    cursor = max(0, after)
    yield ": connected\n\n"

    while True:
        with run.cond:
            pending = [event for event in run.events if event["seq"] > cursor]
            finished = run.finished_at is not None and not pending
            if not pending and not finished:
                run.cond.wait(timeout=1.0)
                pending = [event for event in run.events if event["seq"] > cursor]
                finished = run.finished_at is not None and not pending

        for event in pending:
            cursor = event["seq"]
            yield f"id: {cursor}\ndata: {_sse_payload(event)}\n\n"

        if finished:
            yield f"data: {_sse_payload({'kind': 'stream_end', 'status': run.status, 'lastSeq': cursor})}\n\n"
            return

        if not pending:
            yield ": keepalive\n\n"


@router.get("/runs/{run_id}/events")
def stream_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0, description="Resume events after this seq; used for reconnect continuation"),
    session: PbxSession = Depends(require_session),
) -> StreamingResponse:
    run = _get_run(run_id, session)
    return StreamingResponse(
        _event_stream(run, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            # Keep Nginx from buffering SSE
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/records.csv")
def export_records(run_id: str, session: PbxSession = Depends(require_session)) -> Response:
    run = _get_run(run_id, session)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Extension", "Login Password", "PIN"])
    for record in run.records:
        writer.writerow([record.get("extension", ""), record.get("login_password", ""), record.get("pin", "")])
    # BOM so Excel does not garble it
    body = "\ufeff" + buffer.getvalue()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="dp-records-{run.id}.csv"'},
    )
