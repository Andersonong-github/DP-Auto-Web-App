"""Health, runtime config, and PBX connectivity probing."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..models import HealthResponse, ProbeResponse, PublicConfig
from ..pbx.engine import MODE_COMPLEX, MODE_STANDARD, TASK_DEFINITIONS
from ..pbx.rest_client import RestClient
from ..security import require_session
from ..sessions import PbxSession, store

logger = logging.getLogger("dpauto.system")

router = APIRouter()

CONTEXT_LIST_ENDPOINT = "RESTful/index.php/v1/get/numberingplan/context/view/list"

# The PBX silently caps a single list response below the requested ``limit``, so a long
# context list must be read page by page or it looks truncated.
_PAGE_SIZE = 500
_MAX_PAGES = 200


def _context_page(client: RestClient, start: int, limit: int) -> list:
    response = client.get(CONTEXT_LIST_ENDPOINT, {"start": start, "limit": limit})
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={"code": "pbx_error", "message": f"Failed to read contexts: {client.last_error}"},
        )
    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - non-JSON means the session dropped to the login page
        raise HTTPException(
            status_code=502,
            detail={"code": "pbx_error", "message": f"Context list is not JSON (session may have dropped): {exc}"},
        ) from exc
    rows = data.get("list") or data.get("rows") or data.get("data") or []
    return rows if isinstance(rows, list) else []


def _read_context_rows(client: RestClient) -> list:
    """Read the whole context list, following the PBX's ``start``/``limit`` paging."""
    collected: list = []
    seen: set = set()

    # Fast path: try reading all in one request with limit=6000 (standard for Deltapath REST API)
    try:
        response = client.get(CONTEXT_LIST_ENDPOINT, {"start": 0, "limit": 6000})
        if response.status_code == 200:
            data = response.json()
            rows = data.get("list") or data.get("rows") or data.get("data") or []
            if isinstance(rows, list) and len(rows) > 0:
                for row in rows:
                    key = str(row.get("contextID") or row.get("name") or row)
                    if key and key not in seen:
                        seen.add(key)
                        collected.append(row)
                if collected:
                    return collected
    except Exception:
        pass

    start = 0
    for _ in range(_MAX_PAGES):
        page = _context_page(client, start, _PAGE_SIZE)
        if not page:
            break
        fresh = 0
        for row in page:
            key = str(row.get("contextID") or row.get("name") or row)
            if key in seen:
                continue
            seen.add(key)
            collected.append(row)
            fresh += 1
        if fresh == 0:
            break
        start += len(page)
    return collected

# Same probes the desktop tool used to confirm an authenticated session.
PROBES = [
    ("ACL Group list", "configuration/aclgroup", "RESTful/index.php/v1/get/configuration/aclgroup/view/list"),
    ("User Profile list", "user/userprofile", "RESTful/index.php/v1/get/user/userprofile/view/list"),
    ("Customer list", "customer/customer", "RESTful/index.php/v2/get/customer/customer/view/list"),
    ("SIP Trunk list", "siptrunk/siptrunk", "RESTful/index.php/v1/get/siptrunk/siptrunk/view/list"),
]

# Task catalogue is derived straight from the execution engine, so it cannot drift from the real task names.
# No secondary label is emitted: the UI task names are already self-explanatory, and the extra
# grey label only repeated them ("User (Mobility Apps Only) User (Mobility)").

TASKS = [
    {
        "key": module_name,
        "name": ui_name,
        # Kept in the payload for API compatibility, but always empty now: the frontend used
        # to render this as a second grey label after the task name, which read as a duplicate.
        "cn": "",
        "standard": MODE_STANDARD in modes,
        "complex": MODE_COMPLEX in modes,
    }
    for ui_name, module_name, _func, modes in TASK_DEFINITIONS
]


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {
        "status": "ok",
        "name": settings.app_name,
        "version": settings.version,
        "time": time.time(),
        "activeSessions": store.count(),
    }


@router.get("/config", response_model=PublicConfig)
def public_config() -> dict:
    return {
        "appName": settings.app_name,
        "version": settings.version,
        "defaultBaseUrl": settings.default_base_url,
        "sessionIdleMinutes": settings.session_idle_minutes,
        "tlsVerifyDefault": settings.tls_verify,
        "tasks": TASKS,
    }


@router.get("/pbx/contexts")
def contexts(
    group_name: str = Query(..., min_length=1, max_length=200),
    prefix: str = Query("", max_length=60),
    session: PbxSession = Depends(require_session),
) -> dict:
    """Complex mode's Permission Group / User Profile dropdowns need these context rows.

    Mirrors the desktop ``_refresh_pg_contexts``: find contexts by prefix and
    separate Custom / _Internal / _Fixed / _Mobile / _IDD.

    Besides the prefix-matched set (``all``), the response carries ``groupAll``: **every**
    context that already exists on the server for this Group, whatever its name. The
    Permission Group picker needs that, because a Class may legitimately include a
    pre-existing context whose name does not follow the Context Prefix (for example when
    Task 2 did not create ``_Internal`` and the operator wants an existing one first).
    """
    name = group_name.strip()
    ctx_prefix = (prefix or "").strip() or name
    if ctx_prefix.endswith("_"):
        ctx_prefix = ctx_prefix[:-1]

    client = session.client
    customer_id = client.get_customer_id_by_name(name) or ""
    # One read for the whole context list: it feeds both the prefix-matched set and the
    # Group-wide set, instead of querying the PBX twice. Paged, because the PBX truncates.
    found = [
        {
            "contextID": str(row.get("contextID") or row.get("name") or ""),
            "groupName": str(row.get("groupName") or row.get("group") or ""),
            "customerId": str(row.get("customerId") or row.get("group") or ""),
        }
        for row in _read_context_rows(client)
    ]
    found = [row for row in found if row["contextID"]]
    if not found:
        raise HTTPException(
            status_code=502,
            detail={"code": "pbx_error", "message": f"Failed to read contexts: {client.last_error}"},
        )

    def group_ids(context: dict) -> tuple:
        return (str(context.get("groupName", "")), str(context.get("customerId", "") or ""))

    def belongs_to_group(context: dict) -> bool:
        group_name_value, group_customer_id = group_ids(context)
        if customer_id and (group_customer_id == str(customer_id) or group_name_value == str(customer_id)):
            return True
        return group_name_value == name

    prefix_lower = ctx_prefix.lower()
    group_all = [
        str(context.get("contextID") or "")
        for context in found
        if context.get("contextID") and belongs_to_group(context)
    ]
    group_all = list(dict.fromkeys(group_all))

    matched = [ctx for ctx in group_all if ctx.lower().startswith(prefix_lower)]
    matched_fallback = False
    if not matched:
        matched = [
            str(context.get("contextID") or "")
            for context in found
            if context.get("contextID") and str(context.get("contextID")).lower().startswith(prefix_lower)
        ]
        matched = list(dict.fromkeys(matched))
        matched_fallback = True
    if not group_all:
        # A Group that does not exist yet (Task 1 has not run) still gets the prefix
        # candidates, so the picker is never empty when the prefix is known.
        group_all = list(matched)

    std_suffixes = ["_Internal", "_Fixed", "_Mobile", "_IDD"]
    std_order = {"_Internal": 0, "_Fixed": 1, "_Mobile": 2, "_IDD": 3}

    def suffix_of(full: str) -> str:
        return full[len(ctx_prefix):] if full.startswith(ctx_prefix) else full

    custom_ctx = next((ctx for ctx in matched if suffix_of(ctx) not in std_suffixes), None)
    std_found = sorted(
        (ctx for ctx in matched if suffix_of(ctx) in std_suffixes),
        key=lambda ctx: std_order.get(suffix_of(ctx), 99),
    )
    internal_ctx = next(
        (ctx for ctx in std_found if suffix_of(ctx) == "_Internal"),
        std_found[0] if std_found else None,
    )
    fixed = [ctx for ctx in std_found if ctx != internal_ctx]

    logger.info(
        "contexts for %s: %d prefix-matched, %d in group (fallback=%s)",
        name,
        len(matched),
        len(group_all),
        matched_fallback,
    )
    return {
        "groupName": name,
        "customerId": customer_id,
        "prefix": ctx_prefix,
        "customCtx": custom_ctx,
        "internalCtx": internal_ctx,
        "fixed": fixed,
        "all": matched,
        "groupAll": group_all,
        "fallback": matched_fallback,
    }


@router.get("/pbx/contexts/all")
def all_contexts(session: PbxSession = Depends(require_session)) -> dict:
    """**Every** context on the PBX, across all Groups — no prefix and no Group filter.

    This is the desktop ``_refresh_ctx_dropdowns`` behaviour
    (``search_contexts_by_prefix("")``), used by the User Profile "Number context"
    refresh: the operator must be able to pick any context that exists on the server,
    not only the ones belonging to the Group being provisioned.
    """
    client = session.client
    rows = _read_context_rows(client)
    items = []
    seen = set()
    for row in rows:
        context_id = str(row.get("contextID") or row.get("name") or "").strip()
        if not context_id or context_id in seen:
            continue
        seen.add(context_id)
        items.append(
            {
                "contextID": context_id,
                "contextTitle": str(row.get("contextTitle") or context_id),
                "groupName": str(row.get("groupName") or row.get("group") or ""),
                "customerId": str(row.get("customerId") or row.get("group") or ""),
            }
        )
    items.sort(key=lambda item: item["contextID"].lower())
    logger.info("all contexts: %d entries", len(items))
    return {"total": len(items), "items": items, "contexts": [item["contextID"] for item in items]}


@router.get("/pbx/probe", response_model=ProbeResponse)
def probe(session: PbxSession = Depends(require_session)) -> dict:
    """Round-trip check against the PBX using the stored session."""
    results = []
    for label, _short, endpoint in PROBES:
        started = time.perf_counter()
        entry = {"label": label, "endpoint": endpoint, "ok": False, "detail": ""}
        try:
            response = session.client.get(endpoint, {"start": 0, "limit": 1})
            entry["statusCode"] = response.status_code
            entry["latencyMs"] = int((time.perf_counter() - started) * 1000)
            if response.status_code == 200:
                try:
                    data = response.json()
                    rows = data.get("list") or data.get("rows") or data.get("data") or []
                    entry["rows"] = len(rows) if isinstance(rows, list) else None
                    entry["ok"] = True
                except Exception:
                    entry["detail"] = "Response is not JSON (session may have dropped back to the login page)"
            else:
                entry["detail"] = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator as-is
            entry["latencyMs"] = int((time.perf_counter() - started) * 1000)
            entry["detail"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)

    session.probes = results
    return {
        "baseUrl": session.base_url,
        "ok": all(item["ok"] for item in results),
        "checkedAt": time.time(),
        "results": results,
    }
