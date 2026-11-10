"""Optional task endpoints: Search & Delete and SIP trunk status.

* Search & Delete: search by object type + keyword, then delete in bulk. Delete endpoints follow
  ``RESTful/index.php/v1/delete/<area>/<entity>/<id[,id...]>`` (the form used in the opt_*.py modules).
  The desktop app hardcodes the delete password in the client (``871211My``) -- here it becomes an
  explicit **server-side check**, with the password read from ``DP_DELETE_PASSWORD``: the client never sees it.
* SIP trunk status: merge the siptrunk list with the systemstatus/activepeer data,
  matching the fetch logic of the desktop opt_siptrunkstatus.py.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..pbx import optional
from ..security import client_ip, require_session
from ..sessions import PbxSession
from .audit import audit as audit_log

logger = logging.getLogger("dpauto.ops")

router = APIRouter()

# The desktop app hardcodes 871211My; here it can be overridden via DP_DELETE_PASSWORD
DELETE_PASSWORD = settings.delete_password

# List / delete endpoints and field names per entity (from modules_optional/opt_*.py)
ENTITY_SPECS: Dict[str, Dict[str, Any]] = {
    "group": {
        "label": "Group / Customer",
        "list": "RESTful/index.php/v2/get/customer/customer/view/list",
        "delete": "RESTful/index.php/v1/delete/customer/customer",
        "nameFields": ["engName", "name", "customerName"],
        "idFields": ["customerId", "id", "ID"],
        "extraFields": ["code", "maxConcurrentCalls", "registerUserCount"],
        "groupFields": [],
    },
    "siptrunk": {
        "label": "SIP Trunk",
        "list": "RESTful/index.php/v1/get/siptrunk/siptrunk/view/list",
        "delete": "RESTful/index.php/v1/delete/siptrunk/siptrunk",
        "nameFields": ["peerID", "peerid", "name"],
        "idFields": ["peerID", "id", "ID"],
        "extraFields": ["host", "port", "group"],
        "groupFields": ["group", "customer_id"],
    },
    "context": {
        "label": "Number Context",
        "list": "RESTful/index.php/v1/get/numberingplan/context/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/context",
        "nameFields": ["contextID", "contextTitle", "name"],
        "idFields": ["id", "ID"],
        "extraFields": ["contextTitle", "group", "contextDesc"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "permissiongroup": {
        "label": "Permission Group",
        "list": "RESTful/index.php/v1/get/numberingplan/permissiongroup/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/permissiongroup",
        "nameFields": ["contextTitle", "title", "name"],
        "idFields": ["id", "ID"],
        "extraFields": ["group", "contextInclude_value"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "outboundrouting": {
        "label": "Outbound Routing",
        "list": "RESTful/index.php/v1/get/numberingplan/outboundrouting/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/outboundrouting",
        "nameFields": ["number", "sippeer_value", "peerID", "name"],
        "idFields": ["routing_id", "routingId", "id", "ID"],
        "extraFields": ["number", "sippeer_value", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "inboundrouting": {
        "label": "Inbound Routing",
        "list": "RESTful/index.php/v1/get/numberingplan/inboundnumber/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/inboundnumber",
        "nameFields": ["number", "range_begin", "peerID_value", "peerID"],
        "idFields": ["id", "ID", "routing_id"],
        "rangeFields": ["range_begin", "range_end"],
        "extraFields": ["range_begin", "range_end", "number", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "calleridmanipulation": {
        "label": "Caller ID Manipulation",
        "list": "RESTful/index.php/numberingplan/calleridmanipulation/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/calleridmanipulation",
        "nameFields": ["internal_exten_range_begin", "peerID_value", "peerID", "name"],
        "idFields": ["id", "ID", "manipulation_id"],
        "rangeFields": ["internal_exten_range_begin", "internal_exten_range_end"],
        "extraFields": ["internal_exten_range_begin", "internal_exten_range_end", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "aclgroup": {
        "label": "ACL Group",
        "list": "RESTful/index.php/v1/get/configuration/aclgroup/view/list",
        "delete": "RESTful/index.php/v1/delete/configuration/aclgroup",
        "nameFields": ["name"],
        "idFields": ["acl_group_id", "group_id", "id", "ID"],
        "extraFields": ["description", "group_privilege", "customer_id"],
        "groupFields": ["customer_id", "customerId", "group"],
    },
    "userprofile": {
        "label": "User Profile",
        "list": "RESTful/index.php/v1/get/user/userprofile/view/list",
        "delete": "RESTful/index.php/v1/delete/user/userprofile",
        "nameFields": ["profile_name", "name"],
        "idFields": ["id", "ID", "profile_id"],
        "extraFields": ["profile_name", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "user": {
        "label": "User / Extension",
        "list": "RESTful/index.php/v1/get/user/user/view/list",
        "delete": "RESTful/index.php/v1/delete/user/user",
        "nameFields": ["username", "name", "ext", "firstname", "lastname"],
        "idFields": ["id", "ID"],
        "extraFields": ["username", "firstname", "lastname", "groupTitle", "groupCode"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    # ---- The following come from the delete() implementations in the other opt_*.py ----
    "huntgroup": {
        "label": "Hunt Group",
        "list": "RESTful/index.php/v1/get/user/huntgroup/view/list",
        "delete": "RESTful/index.php/v1/delete/user/huntgroup",
        "deleteMethod": "post",
        "nameFields": ["name", "description", "groupTitle"],
        "idFields": ["id", "ID", "huntgroup_id"],
        "extraFields": ["description", "group", "groupTitle"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "callpickup": {
        "label": "Call Pickup Group",
        "list": "RESTful/index.php/v1/get/user/callpickupgroup/view/list",
        "delete": "RESTful/index.php/v1/delete/user/callpickupgroup",
        "deleteMethod": "post",
        "nameFields": ["name", "description"],
        "idFields": ["id", "ID", "group_id"],
        "extraFields": ["description", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "queue": {
        "label": "Call Queue",
        "list": "RESTful/index.php/callcentre/queue/view/list",
        "delete": "RESTful/index.php/v1/callcentre/queue",
        "nameFields": ["name", "queue_name", "title"],
        "idFields": ["id", "ID", "queue_id"],
        "extraFields": ["description", "group", "number"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "ivr": {
        "label": "IVR Menu",
        "list": "RESTful/index.php/ivr/route/view/list",
        "delete": "RESTful/index.php/v1/ivr/route/menu",
        "nameFields": ["name", "ivr_name", "title"],
        "idFields": ["id", "ID", "ivr_name"],
        "extraFields": ["description", "group", "number"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "voiceprompt": {
        "label": "Voice Prompt",
        "list": "RESTful/index.php/configuration/voiceprompt/view/list",
        "delete": "RESTful/index.php/v1/configuration/voiceprompt",
        "nameFields": ["name", "title", "description"],
        "idFields": ["id", "ID", "voiceprompt_id"],
        "extraFields": ["description", "group", "type"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "callforward": {
        "label": "Call Forward",
        "list": "RESTful/index.php/v1/get/numberingplan/numbercallforward/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/numbercallforward",
        # The desktop app deletes by "number", so the row id is the number itself
        "nameFields": ["number", "call_forward"],
        "idFields": ["number"],
        "extraFields": ["number", "call_forward", "type"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "agent": {
        "label": "Agent",
        "list": "RESTful/index.php/get/callcentre/agent/view/list",
        "delete": "RESTful/index.php/v1/callcentre/agent",
        "nameFields": ["name", "username", "agent_name"],
        "idFields": ["id", "ID", "agent_id"],
        "extraFields": ["username", "group", "type"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "agentgroup": {
        "label": "Agent Group",
        "list": "RESTful/index.php/get/callcentre/agentgroup/view/list",
        "delete": "RESTful/index.php/v1/callcentre/agentgroup",
        "nameFields": ["name", "title", "description"],
        "idFields": ["id", "ID", "agentgroup_id"],
        "extraFields": ["description", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
    "number": {
        "label": "Number",
        "list": "RESTful/index.php/v1/get/numberingplan/number/view/list",
        "delete": "RESTful/index.php/v1/delete/numberingplan/number",
        "nameFields": ["number", "number_name", "name"],
        "idFields": ["id", "ID"],
        "extraFields": ["number", "number_name", "context", "group"],
        "groupFields": ["group", "customerId", "customer_id"],
    },
}

# Nodes with underscores in the complex schema; the frontend only sends the key
ENTITY_ORDER = [
    "group",
    "siptrunk",
    "context",
    "permissiongroup",
    "outboundrouting",
    "inboundrouting",
    "calleridmanipulation",
    "aclgroup",
    "userprofile",
    "user",
    "huntgroup",
    "callpickup",
    "queue",
    "ivr",
    "voiceprompt",
    "callforward",
    "agent",
    "agentgroup",
    "number",
]


# Group / Customer list endpoint (mirrors the desktop ``_populate_group_combo``)
GROUP_LIST_ENDPOINT = ENTITY_SPECS["group"]["list"]


class SearchRequest(BaseModel):
    entity: str = Field(default="", max_length=40)
    entities: List[str] = Field(default_factory=list, max_length=60)
    keyword: str = Field(default="", max_length=200)
    customer_id: str = Field(default="", max_length=40)
    limit: int = Field(default=6000, ge=1, le=20000)


class SearchRow(BaseModel):
    id: str
    name: str
    extra: Dict[str, Any] = Field(default_factory=dict)


class SearchGroupResult(BaseModel):
    entity: str
    label: str
    total: int
    rows: List[SearchRow] = Field(default_factory=list)
    error: str = ""


class SearchResponse(BaseModel):
    keyword: str
    customerId: str = ""
    total: int
    groups: List[SearchGroupResult] = Field(default_factory=list)


class DeleteRequest(BaseModel):
    entity: str = Field(..., min_length=1, max_length=40)
    ids: List[str] = Field(..., min_length=1, max_length=500)
    password: str = Field(..., min_length=1, max_length=200)


class DeleteResponse(BaseModel):
    entity: str
    requested: int
    deleted: int
    failed: int
    results: List[dict]


def _spec(entity: str) -> Dict[str, Any]:
    spec = ENTITY_SPECS.get(entity)
    if spec is None:
        raise HTTPException(status_code=400, detail={"code": "bad_entity", "message": f"Unsupported entity type: {entity}"})
    return spec


def _rows(response) -> List[dict]:
    if response.status_code != 200:
        return []
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - non-JSON means the session dropped to the login page
        return []
    rows = data.get("list") or data.get("rows") or data.get("data") or data.get("peers") or []
    if isinstance(rows, dict):
        rows = rows.get("list") or rows.get("rows") or rows.get("data") or rows.get("peers") or []
    return [row for row in rows if isinstance(row, dict)]


def _first(row: dict, fields: List[str]) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def _display_name(spec: Dict[str, Any], row: dict) -> str:
    """Compose the row label shown in Search & Delete.

    Range-based objects (Inbound Routing / Caller ID Manipulation) are displayed as
    ``<begin>-<end>`` (matching the desktop opt_*.py list), falling back to the single
    value when the end of the range is empty.
    """
    range_fields = spec.get("rangeFields")
    if range_fields:
        begin = _first(row, [range_fields[0]])
        end = _first(row, [range_fields[1]])
        if begin and end:
            return f"{begin}-{end}"
        if begin or end:
            return begin or end
        fallback = _first(row, [field for field in spec.get("nameFields") or [] if field not in range_fields])
        return fallback
    return _first(row, spec.get("nameFields") or [])


# The PBX caps a single list response (it silently returns fewer rows than the
# requested ``limit``), so asking for 6000 in one shot only ever sees the first
# page -- that is why long Group lists looked truncated. Read page by page until
# the server stops handing out new rows.
_PAGE_SIZE = 500
_MAX_PAGES = 200  # hard stop: 200 * 500 = 100k rows, far beyond any real PBX


def _list_rows(client, endpoint: str, limit: int) -> List[dict]:
    """Read one list endpoint completely, following the PBX's ``start``/``limit`` paging.

    Stops when a page comes back empty, when the server repeats rows it already sent
    (some controllers ignore ``start``), or when ``limit`` is reached. A non-200 page
    that yields no rows at all raises 502 like the previous single-shot version.

    Note: a short page is *not* treated as the end -- the PBX caps a page below the
    requested ``limit``, which is exactly what used to truncate long Group lists.
    """
    page_size = min(_PAGE_SIZE, max(1, limit))
    collected: List[dict] = []
    seen: set = set()
    start = 0

    for _ in range(_MAX_PAGES):
        response = client.get(endpoint, {"start": start, "limit": page_size})
        page = _rows(response)

        if not page:
            if not collected and response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "pbx_error",
                        "message": f"Failed to read list (HTTP {response.status_code}): {client.last_error}",
                    },
                )
            break

        # Dedupe defensively: a controller that ignores ``start`` would otherwise
        # loop forever appending the same first page.
        fresh = 0
        for row in page:
            key = json.dumps(row, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            collected.append(row)
            fresh += 1
            if len(collected) >= limit:
                return collected

        if fresh == 0:
            break
        start += len(page)

    return collected


def _resolve_group(client, keyword: str, customer_id: str):
    """Resolve Group -> ``(keyword used for matching, customer_id, set of Group identifiers)``.

    Matches desktop: digits resolve by Group ID, text resolves exactly by engName; on a hit the
    ID / name / code all count as identifiers of that Group, so its objects are filtered in too.
    """
    spec = ENTITY_SPECS["group"]
    group_keys: set = set()
    match_keyword = keyword
    group_id = customer_id
    cache: List[Optional[dict]] = []

    def load() -> List[dict]:
        if not cache:
            try:
                cache.append(_list_rows(client, GROUP_LIST_ENDPOINT, 6000))
            except Exception:  # noqa: BLE001
                cache.append([])
        return cache[0] or []

    row = None
    if customer_id:
        row = next((r for r in load() if _first(r, spec["idFields"]) == customer_id), None)
    elif keyword and keyword.isdigit():
        row = next((r for r in load() if _first(r, spec["idFields"]) == keyword), None)
    elif keyword:
        target = keyword.lower()
        row = next((r for r in load() if _first(r, spec["nameFields"]).lower() == target), None)

    if row:
        gid = _first(row, spec["idFields"])
        gname = _first(row, spec["nameFields"])
        gcode = _first(row, ["code", "customerCode"])
        group_id = group_id or gid
        group_keys.update(value.lower() for value in (gid, gname, gcode) if value)
        if keyword.isdigit() and gname:
            match_keyword = gname
    return match_keyword, group_id, group_keys


def _search_entity(client, spec: Dict[str, Any], keyword: str, group_keys: set, limit: int) -> List[dict]:
    """List one object type, keeping rows where the keyword hits or the row belongs to the selected Group (matches desktop opt_*.search)."""
    rows = _list_rows(client, spec["list"], limit)
    keyword_lower = keyword.lower()
    match_all = not keyword and not group_keys
    matched: List[dict] = []
    for row in rows:
        if match_all:
            matched.append(row)
            continue
        name_hit = False
        if keyword:
            names = [str(row.get(field) or "").lower() for field in spec["nameFields"]]
            ids = [_first(row, spec["idFields"])]
            if keyword_lower.isdigit():
                name_hit = keyword in ids
            else:
                name_hit = any(name.startswith(keyword_lower) or keyword_lower in name for name in names if name)
        group_hit = False
        if group_keys:
            row_group = _first(row, spec.get("groupFields") or [])
            group_hit = bool(row_group) and row_group.lower() in group_keys
        if name_hit or group_hit:
            matched.append(row)

    result_rows = []
    for row in matched[:500]:
        extra = {}
        for field in spec.get("extraFields") or []:
            value = row.get(field)
            if value not in (None, ""):
                extra[field] = value
        name = _display_name(spec, row)
        result_rows.append({"id": _first(row, spec["idFields"]), "name": name, "extra": extra})
    return result_rows


@router.get("/entities")
def entities(_session: PbxSession = Depends(require_session)) -> List[dict]:
    """Catalog of optional object types (for the frontend checkbox list)."""
    return [{"key": key, "label": ENTITY_SPECS[key]["label"]} for key in ENTITY_ORDER]


@router.get("/groups")
def groups(session: PbxSession = Depends(require_session)) -> List[dict]:
    """Group / Customer catalog (for the frontend Group dropdown, matching desktop _populate_group_combo)."""
    spec = ENTITY_SPECS["group"]
    items = []
    for row in _list_rows(session.client, GROUP_LIST_ENDPOINT, 6000):
        name = _first(row, spec["nameFields"])
        cid = _first(row, spec["idFields"])
        if name and cid:
            items.append({"id": cid, "name": name, "code": _first(row, ["code", "customerCode"])})
    items.sort(key=lambda item: item["name"].lower())
    logger.info("groups list: %d entries", len(items))
    return items


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, session: PbxSession = Depends(require_session)) -> dict:
    client = session.client

    keys: List[str] = []
    for key in [*(payload.entities or []), payload.entity]:
        if key and key not in keys:
            keys.append(key)
    if not keys:
        raise HTTPException(status_code=400, detail={"code": "empty", "message": "Select at least one object type to search."})

    keyword = payload.keyword.strip()
    customer_id = payload.customer_id.strip()
    if not keyword and not customer_id:
        raise HTTPException(status_code=400, detail={"code": "empty", "message": "Type a keyword or pick a Group first."})

    match_keyword, group_id, group_keys = _resolve_group(client, keyword, customer_id)

    group_results = []
    total = 0
    for key in keys:
        spec = ENTITY_SPECS.get(key)
        if spec is None:
            logger.warning("search skipped unknown entity %r", key)
            group_results.append({"entity": key, "label": key, "total": 0, "rows": [], "error": "Unsupported object type"})
            continue
        try:
            rows = _search_entity(client, spec, match_keyword, group_keys, payload.limit)
        except HTTPException as exc:  # one failing type must not break the whole search
            logger.warning("search %s failed: %s", key, exc.detail)
            group_results.append({"entity": key, "label": spec["label"], "total": 0, "rows": [], "error": str(exc.detail)})
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("search %s error: %s", key, exc)
            group_results.append({"entity": key, "label": spec["label"], "total": 0, "rows": [], "error": str(exc)})
            continue
        group_results.append({"entity": key, "label": spec["label"], "total": len(rows), "rows": rows})
        total += len(rows)

    logger.info(
        "search entities=%s keyword=%r customer=%r -> %d matches",
        keys, match_keyword, group_id, total,
    )
    return {
        "keyword": match_keyword,
        "customerId": group_id,
        "total": total,
        "groups": group_results,
    }


def _delete_one(client, endpoint: str, entity_id: str, method: str = "delete") -> dict:
    """Same as the opt_*.py modules: try DELETE first, fall back to a POST form;
    some entities (hunt group / call pickup group) use POST directly in the desktop app.
    """
    url = f"{endpoint}/{entity_id}"
    detail = ""

    if method != "post":
        try:
            response = client.delete(url)
            ok = response.status_code == 200
            try:
                body = response.json()
                detail = str(body.get("message") or body.get("msg") or body)[:200]
                if body.get("success") is False:
                    ok = False
            except Exception:  # noqa: BLE001
                detail = (response.text or "")[:200]
            if ok:
                return {"id": entity_id, "ok": True, "detail": detail}
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"

    for body in ({"id": entity_id}, {"customerId": entity_id}, {"customer_id": entity_id}):
        try:
            response = client.post_form(url, body)
            if response.status_code == 200:
                return {"id": entity_id, "ok": True, "detail": f"POST {list(body.keys())[0]}"}
        except Exception:  # noqa: BLE001
            continue
    return {"id": entity_id, "ok": False, "detail": detail or "Delete failed"}


@router.post("/delete", response_model=DeleteResponse)
def delete(payload: DeleteRequest, request: Request, session: PbxSession = Depends(require_session)) -> dict:
    if payload.password != DELETE_PASSWORD:
        logger.warning("delete rejected: wrong password (%s, %d ids)", payload.entity, len(payload.ids))
        audit_log.record(
            "delete",
            actor=session.username,
            source_ip=client_ip(request),
            summary=f"Delete rejected (wrong password): {spec_label(payload.entity)} x {len(payload.ids)}",
            detail={"entity": payload.entity, "ids": payload.ids[:50], "reason": "bad_password"},
            ok=False,
        )
        raise HTTPException(status_code=403, detail={"code": "bad_password", "message": "Incorrect delete password."})

    spec = _spec(payload.entity)
    client = session.client
    method = spec.get("deleteMethod", "delete")
    results = [_delete_one(client, spec["delete"], entity_id, method) for entity_id in payload.ids]
    deleted = sum(1 for item in results if item["ok"])
    logger.warning(
        "delete %s: %d/%d ok by %s", payload.entity, deleted, len(results), session.username
    )
    audit_log.record(
        "delete",
        actor=session.username,
        source_ip=client_ip(request),
        summary=f"Delete {spec_label(payload.entity)}: {deleted} succeeded / {len(results) - deleted} failed",
        detail={
            "entity": payload.entity,
            "requested": len(results),
            "deleted": deleted,
            "failed": len(results) - deleted,
            "ids": payload.ids[:50],
            "failedIds": [item["id"] for item in results if not item["ok"]][:20],
        },
        ok=deleted == len(results),
    )
    return {
        "entity": payload.entity,
        "requested": len(results),
        "deleted": deleted,
        "failed": len(results) - deleted,
        "results": results,
    }


def spec_label(entity: str) -> str:
    spec = ENTITY_SPECS.get(entity)
    return (spec or {}).get("label", entity)


class OptionalSearchRequest(BaseModel):
    keyword: str = Field(default="", max_length=200)
    entities: List[str] = Field(default_factory=list, max_length=40)


class OptionalDeleteRequest(BaseModel):
    entities: List[str] = Field(default_factory=list, max_length=40)
    password: str = Field(..., min_length=1, max_length=200)


# Per-session "last search" state, mirroring the desktop modules' found_items:
# delete removes exactly what the previous search found, never client-supplied ids.
_LAST_SEARCH: Dict[str, Dict[str, List[dict]]] = {}


@router.get("/optional/entities")
def optional_entities(_session: PbxSession = Depends(require_session)) -> dict:
    """The 20 task types of the desktop 'Search & Delete' page, in desktop order."""
    return {"entities": optional.entity_catalog()}


@router.post("/optional/search")
def optional_search(
    payload: OptionalSearchRequest,
    request: Request,
    session: PbxSession = Depends(require_session),
) -> dict:
    keyword = payload.keyword.strip()
    if not keyword:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Enter a group name or customer ID."},
        )

    keys = optional.entity_catalog_order(payload.entities)
    if not keys:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Select at least one task."},
        )

    client = session.client
    resolved, customer_id = optional.resolve_keyword(client, keyword)
    results = []
    found: Dict[str, List[dict]] = {}
    for key in keys:
        result = optional.search_entity(client, key, resolved, customer_id)
        found[key] = result.get("items", [])
        results.append({name: value for name, value in result.items() if name != "items"} | {"itemCount": len(result.get("items", []))})

    _LAST_SEARCH[session.sid] = found
    total = sum(item["itemCount"] for item in results)
    logger.info("optional search by %s: '%s' -> %d item(s) in %d type(s)", session.username, keyword, total, len(results))
    audit_log.record(
        "optional_search",
        actor=session.username,
        source_ip=client_ip(request),
        summary=f"Search & Delete: '{keyword}' -> {total} item(s) in {len(results)} type(s)",
        detail={"keyword": keyword, "resolved": resolved, "customerId": customer_id, "entities": keys},
    )
    return {
        "keyword": keyword,
        "resolvedKeyword": resolved,
        "customerId": customer_id,
        "results": results,
    }


@router.post("/optional/delete")
def optional_delete(
    payload: OptionalDeleteRequest,
    request: Request,
    session: PbxSession = Depends(require_session),
) -> dict:
    if payload.password != DELETE_PASSWORD:
        logger.warning("optional delete rejected: wrong password (%d types)", len(payload.entities))
        audit_log.record(
            "delete",
            actor=session.username,
            source_ip=client_ip(request),
            summary=f"Optional delete rejected (bad password): {len(payload.entities)} type(s)",
            detail={"entities": payload.entities, "reason": "bad_password"},
            ok=False,
        )
        raise HTTPException(status_code=403, detail={"code": "bad_password", "message": "Incorrect delete password."})

    keys = optional.entity_catalog_order(payload.entities)
    if not keys:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Select at least one task."},
        )

    found = _LAST_SEARCH.get(session.sid, {})
    client = session.client
    results = []
    # Desktop walks the module list in reverse when deleting ("bottom-to-top").
    for key in reversed(keys):
        results.append(optional.delete_entity(client, key, found.get(key, [])))
        found[key] = []

    deleted = sum(item["deleted"] for item in results)
    failed = sum(item["failed"] for item in results)
    audit_log.record(
        "delete",
        actor=session.username,
        source_ip=client_ip(request),
        summary=f"Optional delete: {deleted} deleted / {failed} failed across {len(results)} type(s)",
        detail={"entities": keys, "deleted": deleted, "failed": failed},
        ok=failed == 0,
    )
    return {"deleted": deleted, "failed": failed, "results": results}


@router.get("/pbx/siptrunk/status")
def siptrunk_status(session: PbxSession = Depends(require_session)) -> dict:
    """SIP trunk status: siptrunk list merged with live activepeer state."""
    client = session.client

    trunk_rows = _rows(client.get("RESTful/index.php/v1/get/siptrunk/siptrunk/view/list", {"start": 0, "limit": 1000}))
    peer_ids = sorted({str(row.get("peerID") or row.get("peerid") or "").strip() for row in trunk_rows} - {""})
    trunk_by_peer = {
        str(row.get("peerID") or row.get("peerid") or "").strip(): row for row in trunk_rows if row.get("peerID") or row.get("peerid")
    }

    status_response = client.get(
        "RESTful/index.php/v1/get/systemstatus/activepeer/view/list",
        {"_dc": str(int(time.time() * 1000))},
    )
    status_rows = _rows(status_response)
    if status_response.status_code != 200:
        logger.warning("activepeer list HTTP %s", status_response.status_code)

    known = set(peer_ids)
    results = []
    for row in status_rows:
        name = str(row.get("name") or row.get("peerid") or row.get("peerID") or "").strip()
        if known and name not in known:
            continue
        trunk = trunk_by_peer.get(name) or {}
        results.append(
            {
                "name": name,
                "host": str(row.get("host") or trunk.get("host") or ""),
                "port": str(row.get("port") or trunk.get("port") or ""),
                "status": str(row.get("status") or row.get("state") or ""),
                "group": str(trunk.get("group") or ""),
            }
        )

    return {
        "checkedAt": time.time(),
        "endpoint": "RESTful/index.php/v1/get/systemstatus/activepeer/view/list",
        "peerIds": peer_ids,
        "rows": results,
        "trunkCount": len(trunk_rows),
    }
