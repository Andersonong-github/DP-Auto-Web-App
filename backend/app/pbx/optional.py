"""Faithful port of the desktop app's "Optional Task - Search & Delete" page.

Mirrors ``DP Auto API/modules_optional/opt_*.py``:

* 20 entity types, in the same order (17 main + 3 under "Cinch Contact Center");
* one keyword (group name or customer ID) searched across **every checked type**;
* each type reports its own status line, exactly like the desktop result label
  (``Found 3: a, b, c`` / ``Not found`` / ``Error``);
* delete removes what each checked type found, walking the list **in reverse**
  (desktop behaviour: "deleting checked optional tasks bottom-to-top").

The actual matching is done by the same ``RestClient`` helpers the desktop
modules call (``search_contexts_by_prefix``, ``search_siptrunks_by_peerid`` …),
so the semantics stay identical.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dpauto.optional")

MAIN = "main"
CINCH = "cinch"

# Practically "no limit": every DID/range must be visible in the result line.
MAX_LABELS = 500


@dataclass(frozen=True)
class OptionalEntity:
    key: str
    label: str
    group: str = MAIN
    # list + filter family
    list_endpoint: str = ""
    limit: int = 6000
    group_fields: Tuple[str, ...] = ()
    name_fields: Tuple[str, ...] = ()
    id_field: str = "id"
    label_fields: Tuple[str, ...] = ()
    label_template: str = "{value}"
    # delete
    delete_endpoint: str = ""
    delete_mode: str = "per_item"  # per_item | joined | first
    delete_method: str = "delete"  # delete | post
    delete_key: str = "id"


# Order and labels mirror main.py's self.opt_modules list. ``label_fields`` mirror
# the desktop ``_names`` expression of each module (that is what the desktop shows
# in its per-row result box), so e.g. Inbound Routing shows the DID ``number``.
OPTIONAL_ENTITIES: List[OptionalEntity] = [
    OptionalEntity("group", "Group", MAIN, delete_endpoint="RESTful/index.php/v1/delete/customer/customer", delete_mode="first", delete_key="id"),
    OptionalEntity("context", "Context", MAIN, label_fields=("contextID",),
                   delete_endpoint="RESTful/index.php/v1/delete/numberingplan/context", delete_mode="joined", delete_method="post", delete_key="contextID"),
    OptionalEntity("permgroup", "Permission Group", MAIN, label_fields=("contextTitle",),
                   delete_endpoint="RESTful/index.php/v1/delete/numberingplan/permissiongroup", delete_mode="joined", delete_method="post", delete_key="contextTitle"),
    OptionalEntity("siptrunk", "SIP Trunk", MAIN, label_fields=("peerID", "port"), label_template="{a} (Port: {b})",
                   delete_endpoint="RESTful/index.php/v1/delete/siptrunk/siptrunk", delete_mode="joined", delete_method="post", delete_key="peerID"),
    OptionalEntity("outboundrouting", "Outbound Routing", MAIN, label_fields=("number",),
                   delete_endpoint="RESTful/index.php/v1/delete/numberingplan/outboundrouting", delete_method="post_form", delete_key="routing_id"),
    OptionalEntity("inboundrouting", "Inbound Routing", MAIN, label_fields=("number",),
                   delete_endpoint="RESTful/index.php/v1/delete/numberingplan/inboundnumber", delete_method="post_form", delete_key="id"),
    OptionalEntity("calleridmanipulation", "Caller ID Manipulation", MAIN,
                   label_fields=("resolved_range_begin", "resolved_range_end"), label_template="{a}-{b}",
                   delete_endpoint="RESTful/index.php/v1/delete/numberingplan/calleridmanipulation", delete_method="post_form", delete_key="id"),
    OptionalEntity("aclgroup", "ACL Group", MAIN, label_fields=("name",),
                   delete_endpoint="RESTful/index.php/delete/configuration/aclgroup", delete_method="post", delete_key="group_id"),
    OptionalEntity("userprofile", "User Profile", MAIN, label_fields=("profile_name",),
                   delete_endpoint="RESTful/index.php/v1/delete/user/userprofile", delete_method="post", delete_key="id"),
    OptionalEntity("user", "User", MAIN, delete_endpoint="RESTful/index.php/v1/delete/user/user", delete_method="post", delete_key="id"),
    OptionalEntity("acluser", "ACL User", MAIN, list_endpoint="RESTful/index.php/v1/get/configuration/acluser/view/list",
                   group_fields=("_group",), name_fields=("groupname", "username"), id_field="username",
                   label_fields=("username",), delete_endpoint="RESTful/index.php/v1/delete/user/user", delete_method="post", delete_key="username"),
    OptionalEntity("numberstrip", "Number (Strip Digits)", MAIN, list_endpoint="RESTful/index.php/v1/get/numberingplan/number/view/list",
                   group_fields=("group", "groupname"), name_fields=("number", "number_name"), id_field="id",
                   label_fields=("number",), delete_endpoint="RESTful/index.php/v1/delete/numberingplan/number", delete_method="post", delete_key="id"),
    OptionalEntity("callforward", "Call Forward", MAIN, list_endpoint="RESTful/index.php/v1/get/numberingplan/numbercallforward/view/list",
                   group_fields=("group",), name_fields=("number",), id_field="number",
                   label_fields=("number", "call_forward"), label_template="{a}->{b}", delete_endpoint="RESTful/index.php/v1/delete/numberingplan/numbercallforward", delete_key="number"),
    OptionalEntity("callpickup", "Call Pickup", MAIN, list_endpoint="RESTful/index.php/v1/get/user/callpickupgroup/view/list",
                   group_fields=("group",), name_fields=("groupTitle",), id_field="groupID", label_fields=("groupTitle",),
                   delete_endpoint="RESTful/index.php/v1/delete/user/callpickupgroup", delete_method="post", delete_key="groupID"),
    OptionalEntity("huntgroup", "Hunt Group", MAIN, list_endpoint="RESTful/index.php/v1/get/user/huntgroup/view/list",
                   group_fields=("group",), name_fields=("title",), id_field="id", label_fields=("title", "huntmode"),
                   label_template="{a} ({b})", delete_endpoint="RESTful/index.php/v1/delete/user/huntgroup", delete_method="post", delete_key="id"),
    OptionalEntity("voiceprompt", "Voice Prompt", MAIN, list_endpoint="RESTful/index.php/configuration/voiceprompt/view/list",
                   group_fields=("group",), name_fields=("prompt_name",), id_field="id", label_fields=("prompt_name",),
                   delete_endpoint="RESTful/index.php/v1/configuration/voiceprompt", delete_key="id"),
    OptionalEntity("ivr", "IVR", MAIN, list_endpoint="RESTful/index.php/ivr/route/view/list",
                   group_fields=("group",), name_fields=("name",), id_field="id", label_fields=("name",),
                   delete_endpoint="RESTful/index.php/v1/ivr/route/menu", delete_key="id"),
    OptionalEntity("agents", "Agents", CINCH, list_endpoint="RESTful/index.php/get/callcentre/agent/view/list",
                   group_fields=("group",), name_fields=("agentid", "firstname", "lastname"), id_field="id",
                   label_fields=("agentid",), delete_endpoint="RESTful/index.php/v1/callcentre/agent", delete_key="id"),
    OptionalEntity("agentgroups", "Agent Groups", CINCH, list_endpoint="RESTful/index.php/get/callcentre/agentgroup/view/list",
                   group_fields=("group",), name_fields=("name",), id_field="id", label_fields=("name",),
                   delete_endpoint="RESTful/index.php/v1/callcentre/agentgroup", delete_key="id"),
    OptionalEntity("queue", "Queue", CINCH, list_endpoint="RESTful/index.php/callcentre/queue/view/list",
                   group_fields=("group",), name_fields=("name",), id_field="id", label_fields=("name",),
                   delete_endpoint="RESTful/index.php/v1/callcentre/queue", delete_key="id"),
]

BY_KEY: Dict[str, OptionalEntity] = {entity.key: entity for entity in OPTIONAL_ENTITIES}

# The 10 types whose search is delegated to a named RestClient helper, mirroring
# the desktop module of the same name.
HELPER_ENTITIES = {
    "context",
    "permgroup",
    "siptrunk",
    "outboundrouting",
    "inboundrouting",
    "calleridmanipulation",
    "aclgroup",
    "userprofile",
    "user",
}


def entity_catalog() -> List[dict]:
    return [
        {"key": entity.key, "label": entity.label, "group": entity.group}
        for entity in OPTIONAL_ENTITIES
    ]


def entity_catalog_order(keys: List[str]) -> List[str]:
    """Order the requested keys the way the desktop module list is ordered."""
    wanted = set(keys)
    return [entity.key for entity in OPTIONAL_ENTITIES if entity.key in wanted]


def resolve_keyword(client, keyword: str) -> Tuple[str, str]:
    """Mirror main.py::_opt_run_search: numeric/【id】 keywords resolve to a name."""
    query = (keyword or "").strip()
    customer_id = ""
    if not query:
        return query, customer_id
    if query.isdigit():
        resolved = client.get_group_name_by_id(query)
        if resolved:
            logger.info("resolved id %s -> %s", query, resolved)
            customer_id = query
            query = resolved
        return query, customer_id

    match = re.search(r"[【\[](\d+)[】\]]", query)
    if match:
        customer_id = match.group(1)
        name_part = query[: match.start()].strip() or query
        resolved = client.get_group_name_by_id(customer_id) or name_part
        query = resolved
    return query, customer_id


def _rows(response) -> List[dict]:
    if response is None or response.status_code != 200:
        return []
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        return []
    rows = data if isinstance(data, list) else (data.get("list") or data.get("rows") or data.get("data") or [])
    if isinstance(rows, dict):
        rows = rows.get("list") or rows.get("rows") or rows.get("data") or []
    return [row for row in (rows or []) if isinstance(row, dict)]


def _inbound_label(item: dict) -> str:
    """Inbound Routing result: the DID (a block of DIDs renders as a range).

    The real PBX returns no ``number`` field for inbound routes, only
    ``range_begin``/``range_end`` (e.g. ``60323020100``..``60323020199``), and the
    RestClient helper copies that pair into ``number``. Prefer the explicit range
    fields, then ``number``, so a DID block is shown as ``start-end``.
    """
    return _pair_label(
        item,
        [
            ("range_begin", "range_end"),
            ("resolved_range_begin", "resolved_range_end"),
            ("internal_exten_range_begin", "internal_exten_range_end"),
        ],
        ("number", "id"),
    )


def _pair_label(item: dict, pairs: List[Tuple[str, str]], fallback_fields: Tuple[str, ...]) -> str:
    """Return the first complete ``begin-end`` range among ``pairs``.

    Mirrors the desktop opt_*.py result line (``begin-end`` per hit): a pair only
    counts when both ends are present, so a lone ``begin`` never renders as a bare
    DID. When no complete pair exists, the first non-empty fallback value wins.
    """
    def clean(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text in {"-", "--", "None", "null"} else text

    lone: str = ""
    for begin_field, end_field in pairs:
        begin = clean(item.get(begin_field))
        end = clean(item.get(end_field))
        if begin and end:
            return begin if begin == end else f"{begin}-{end}"
        if not lone:
            lone = begin or end
    if lone:
        return lone
    for field in fallback_fields:
        value = clean(item.get(field))
        if value:
            return value
    return ""


def _callerid_label(item: dict) -> str:
    """Caller ID Manipulation result: the **DID** (range shown as a range).

    A real PBX row is e.g.
    ``{"internal_exten_range_begin": "6400", "internal_exten_range_end": "6499",
       "callerid_prepend": "6032856", "resolved_range_begin": "60328566400",
       "resolved_range_end": "60328566499"}``
    so the number an operator cares about is ``resolved_range_*``; a single DID
    renders as itself, a block of DIDs renders as ``start-end``. The internal
    extension range is only a fallback (the desktop page showed just that).
    """
    return _pair_label(
        item,
        [
            ("resolved_range_begin", "resolved_range_end"),
            ("range_begin", "range_end"),
            ("internal_exten_range_begin", "internal_exten_range_end"),
        ],
        ("number", "id"),
    )


def _label_value(item: dict, entity: OptionalEntity) -> str:
    """First non-empty value from the entity's label fields (with sane fallbacks)."""
    if entity.key == "inboundrouting":
        return _inbound_label(item)
    if entity.key == "outboundrouting":
        return _outbound_label(item)
    if entity.key == "calleridmanipulation":
        return _callerid_label(item)
    fields = entity.label_fields or (
        "name",
        "contextTitle",
        "profile_name",
        "peerID",
        "contextID",
        "username",
        "number",
        "title",
        "id",
    )
    values = [str(item.get(field) or "") for field in fields]
    values = [value for value in values if value and value not in {"-", "--"}]
    if "{b}" in entity.label_template and len(values) >= 2:
        return entity.label_template.format(a=values[0], b=values[1])
    return values[0] if values else ""


def _outbound_label(item: dict) -> str:
    """Outbound Routing result: the dial pattern (``number``), else the route id."""
    def clean(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text in {"-", "--", "None", "null"} else text

    return clean(item.get("number")) or clean(item.get("dial_pattern")) or clean(item.get("id"))


def _status(entity: OptionalEntity, items: List[dict]) -> str:
    """``Found N: <label>, <label>, …`` listing **every** hit (ranges shown as ranges).

    The desktop label box only showed the first few and the web row used to clip the
    rest, so an operator could not see all DIDs; only a pathological payload is
    capped here (MAX_LABELS) and the overflow is reported explicitly.
    """
    if not items:
        return "Not found"
    names = [_label_value(item, entity) for item in items[:MAX_LABELS]]
    names = [name for name in names if name]
    suffix = "" if len(items) <= MAX_LABELS else f" (+{len(items) - MAX_LABELS} more)"
    return f"Found {len(items)}: {', '.join(names)}{suffix}"


def _result(entity: OptionalEntity, items: List[dict], status: Optional[str] = None, error: str = "") -> dict:
    return {
        "key": entity.key,
        "label": entity.label,
        "group": entity.group,
        "ok": bool(items) and not error,
        "count": len(items),
        "status": status if status is not None else _status(entity, items),
        "error": error,
        "items": items,
    }


# --------------------------------------------------------------------- search
def _search_group(client, keyword: str, customer_id: str) -> dict:
    entity = BY_KEY["group"]
    row = client.get_customer_by_name(keyword)
    if not row:
        return _result(entity, [], status="Not found")
    cid = row.get("customerId") or row.get("id")
    item = {
        "id": cid,
        "name": keyword,
        "maxConcurrentCalls": row.get("maxConcurrentCalls", ""),
        "registerUserCount": row.get("registerUserCount", ""),
    }
    status = (
        f"ID: {cid} ({keyword}) | MaxCalls: {item['maxConcurrentCalls']} "
        f"| RegUsers: {item['registerUserCount']}"
    )
    return _result(entity, [item], status=status)


def _search_context(client, keyword: str, customer_id: str) -> dict:
    entity = BY_KEY["context"]
    resolved_name = keyword
    resolved_id = customer_id
    if not resolved_id:
        if keyword.isdigit():
            resolved_name = client.get_group_name_by_id(keyword) or keyword
            resolved_id = keyword
        else:
            resolved_id = client.get_customer_id_by_name(keyword) or ""
    if not resolved_id or not resolved_name:
        return _result(entity, [], status="Not found")

    fetched: List[dict] = []
    for row in client.search_contexts_by_prefix("") or []:
        context_id = row.get("contextID", "")
        if not context_id:
            continue
        if str(row.get("groupName", "") or "") != resolved_name:
            continue
        detail = client.get_context_detail(context_id)
        if detail and str(detail.get("group", "") or "") == str(resolved_id):
            fetched.append(detail)
    return _result(entity, fetched)


def _search_permgroup(client, keyword: str, customer_id: str) -> dict:
    entity = BY_KEY["permgroup"]
    resolved_name = keyword
    resolved_id = customer_id
    if not resolved_id:
        if keyword.isdigit():
            resolved_name = client.get_group_name_by_id(keyword) or keyword
            resolved_id = keyword
        else:
            resolved_id = client.get_customer_id_by_name(keyword) or ""
    if not resolved_id or not resolved_name:
        return _result(entity, [], status="Not found")

    fetched: List[dict] = []
    for row in client.search_permgroups_by_prefix("") or []:
        title = row.get("contextTitle", "") or row.get("title", "") or ""
        if not title:
            continue
        gn = str(row.get("groupName", "") or row.get("group", "") or "").strip()
        matched = False
        if resolved_id and gn.lower() == str(resolved_id).lower():
            matched = True
        elif resolved_name and gn.lower() == resolved_name.lower():
            matched = True
        if not matched:
            continue
        detail = client.get_permgroup_detail(title)
        if detail and str(detail.get("group", "") or "") == str(resolved_id):
            fetched.append(detail)
    return _result(entity, fetched)


def _resolve_group(client, keyword: str, customer_id: str) -> Tuple[str, str, str]:
    """(name, id, code) — mirrors the resolve block the desktop modules repeat."""
    resolved_name = keyword
    resolved_id = customer_id
    code = ""
    if resolved_id:
        resolved_name = client.get_group_name_by_id(resolved_id) or resolved_name
        code = client.get_customer_code_by_name(resolved_name) or ""
    else:
        resolved_name = client.get_group_name_by_id(keyword) or keyword
        resolved_id = client.get_customer_id_by_name(keyword) or ""
        code = client.get_customer_code_by_name(keyword) or ""
    return resolved_name, resolved_id, code


def _search_siptrunk(client, keyword: str, customer_id: str) -> dict:
    name, cid, code = _resolve_group(client, keyword, customer_id)
    results = client.search_siptrunks_by_peerid(name, cid, group_name=name, code=code) or []
    return _result(BY_KEY["siptrunk"], results)


def _search_by_peer(client, key: str, keyword: str, customer_id: str) -> dict:
    entity = BY_KEY[key]
    name, cid, code = _resolve_group(client, keyword, customer_id)
    trunks = client.search_siptrunks_by_peerid(name, cid, group_name=name, code=code) or []
    peer_ids = [trunk.get("peerID") for trunk in trunks if trunk.get("peerID")]
    searcher = {
        "outboundrouting": client.search_outboundroutings_by_sippeer,
        "inboundrouting": client.search_inboundroutings_by_peer,
        "calleridmanipulation": client.search_calleridmanipulations_by_peer,
    }[key]
    results = searcher(name, cid, group_name=name, code=code, peer_ids=peer_ids) or []
    return _result(entity, results)


def _search_aclgroup(client, keyword: str, customer_id: str) -> dict:
    name, cid, code = _resolve_group(client, keyword, customer_id)
    results = client.search_acl_groups_by_name(name, cid, code=code) or []
    return _result(BY_KEY["aclgroup"], results)


def _search_userprofile(client, keyword: str, customer_id: str) -> dict:
    name, cid, code = _resolve_group(client, keyword, customer_id)
    results = client.search_user_profiles_by_name(name, cid, code=code) or []
    return _result(BY_KEY["userprofile"], results)


def _search_user(client, keyword: str, customer_id: str) -> dict:
    entity = BY_KEY["user"]
    code = client.get_customer_code_by_name(keyword) or ""
    results = client.search_users_by_ext(keyword, customer_id=customer_id, code=code) or []
    detailed: List[dict] = []
    logged: List[dict] = []
    for row in results:
        detail = client.get_user_detail(row.get("id", "") or row.get("ext", ""))
        target = detail or row
        detailed.append(target)
        logged.append({"id": target.get("id") or row.get("id"), "username": target.get("username") or row.get("ext")})
    if detailed:
        names = ", ".join(str(item.get("username") or item.get("ext") or "") for item in logged)
        return _result(entity, detailed, status=f"Found {len(detailed)}: {names}")
    return _result(entity, [], status="Not found")


def _list_rows_paged(client, endpoint: str, limit: int) -> List[dict]:
    """Read a list endpoint completely, following the PBX's ``start``/``limit`` paging.

    The PBX caps how many rows one response carries, so a single ``limit=6000``
    request only returns the first page. Page through until it stops yielding new
    rows (or the cap is hit), otherwise long lists silently look truncated.
    """
    page_size = min(500, max(1, limit))
    collected: List[dict] = []
    seen: set = set()
    start = 0

    for _ in range(200):
        page = _rows(client.get(endpoint, {"start": start, "limit": page_size}))
        if not page:
            break
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


def _search_list_filter(client, entity: OptionalEntity, keyword: str, customer_id: str) -> dict:
    """The 10 modules that GET a list and filter it themselves."""
    name, cid, code = _resolve_group(client, keyword, customer_id)
    prefix = name.lower()
    cid_lower = str(cid or "").lower()
    code_lower = (code or "").lower()
    kw_lower = keyword.lower()

    rows = _list_rows_paged(client, entity.list_endpoint, entity.limit)

    results: List[dict] = []
    for row in rows:
        group_value = str(row.get(entity.group_fields[0], "") or "").lower() if entity.group_fields else ""
        group_name_value = ""
        if "_group" in entity.group_fields:
            group_name_value = str(client._extract_group(row) or "").lower()

        group_ok = False
        if cid_lower and (group_value == cid_lower or group_name_value == cid_lower):
            group_ok = True
        elif code_lower and group_value == code_lower:
            group_ok = True
        elif prefix and (group_value.startswith(prefix) or group_name_value.startswith(prefix)):
            group_ok = True

        name_ok = False
        for field in entity.name_fields:
            value = str(row.get(field, "") or "").lower()
            if value and (value.startswith(prefix) or value.startswith(kw_lower)):
                name_ok = True
                break

        # Desktop rule: when the group resolved, a group match is enough;
        # otherwise fall back to matching the name/number prefix.
        if cid_lower or code_lower:
            if not (group_ok or name_ok):
                continue
        elif not (group_ok or name_ok):
            continue

        item: Dict[str, Any] = {}
        for field in entity.label_fields:
            item[field] = row.get(field, "")
        item[entity.id_field] = row.get(entity.id_field, "") or row.get("ID", "")
        for extra in ("number", "number_name", "groupname", "group_id", "call_forward", "huntmode", "privileges", "groupTitle", "prompt_name", "name"):
            if extra in row and extra not in item:
                item[extra] = row.get(extra, "")
        results.append(item)

    return _result(entity, results)


SEARCHERS = {
    "group": _search_group,
    "context": _search_context,
    "permgroup": _search_permgroup,
    "siptrunk": _search_siptrunk,
    "outboundrouting": lambda c, k, cid: _search_by_peer(c, "outboundrouting", k, cid),
    "inboundrouting": lambda c, k, cid: _search_by_peer(c, "inboundrouting", k, cid),
    "calleridmanipulation": lambda c, k, cid: _search_by_peer(c, "calleridmanipulation", k, cid),
    "aclgroup": _search_aclgroup,
    "userprofile": _search_userprofile,
    "user": _search_user,
}


def search_entity(client, key: str, keyword: str, customer_id: str = "") -> dict:
    entity = BY_KEY.get(key)
    if entity is None:
        raise KeyError(key)
    started = time.perf_counter()
    try:
        searcher = SEARCHERS.get(key)
        result = searcher(client, keyword, customer_id) if searcher else _search_list_filter(client, entity, keyword, customer_id)
    except Exception as exc:  # noqa: BLE001 - one bad type must not kill the whole search
        logger.warning("optional search %s failed: %s", key, exc)
        result = _result(entity, [], status="Error", error=f"{type(exc).__name__}: {exc}")
    result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
    logger.info("optional search %s -> %s", key, result["status"][:120])
    return result


# --------------------------------------------------------------------- delete
def _extract_target_id(item: dict, entity: OptionalEntity) -> str:
    target = str(item.get(entity.delete_key, "") or "").strip()
    if target:
        return target
    if entity.key == "aclgroup":
        return str(item.get("group_id", "") or item.get("acl_group_id", "") or item.get("id", "") or item.get("ID", "") or "").strip()
    if entity.key in ("inboundrouting", "outboundrouting"):
        return str(item.get("id", "") or item.get("routing_id", "") or item.get("routingId", "") or item.get("ID", "") or "").strip()
    if entity.key == "calleridmanipulation":
        return str(item.get("id", "") or item.get("manipulation_id", "") or item.get("ID", "") or "").strip()
    if entity.key == "callpickup":
        return str(item.get("groupID", "") or item.get("group_id", "") or item.get("id", "") or "").strip()
    if entity.key == "permgroup":
        return str(item.get("contextTitle", "") or item.get("title", "") or item.get("name", "") or "").strip()
    if entity.key == "context":
        return str(item.get("contextID", "") or item.get("id", "") or "").strip()
    if entity.key == "siptrunk":
        return str(item.get("peerID", "") or item.get("peerid", "") or item.get("name", "") or "").strip()
    if entity.key in ("user", "acluser"):
        return str(item.get("username", "") or item.get("id", "") or "").strip()
    return str(item.get("id", "") or item.get("ID", "") or item.get("name", "") or "").strip()


def _delete_call(client, endpoint: str, method: str, body: Optional[dict] = None) -> Tuple[bool, str]:
    detail = ""
    try:
        if method == "post_form":
            response = client.post_form(endpoint, body or {})
        elif method == "post":
            response = client.post(endpoint)
        else:
            response = client.delete(endpoint)
        try:
            body_json = response.json()
            detail = str(body_json.get("message") or body_json.get("msg") or body_json.get("error") or body_json)[:200]
            if isinstance(body_json, dict) and body_json.get("success") is False:
                return False, detail
        except Exception:  # noqa: BLE001
            detail = (response.text or "")[:200]
        return response.status_code == 200, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def delete_entity(client, key: str, items: List[dict]) -> dict:
    entity = BY_KEY.get(key)
    if entity is None:
        raise KeyError(key)
    if not items:
        return {"key": key, "label": entity.label, "deleted": 0, "failed": 0, "results": [], "status": "nothing to delete"}

    results: List[dict] = []

    if entity.delete_mode == "first":
        target = _extract_target_id(items[0], entity)
        if not target:
            return {"key": key, "label": entity.label, "deleted": 0, "failed": 1, "results": [], "status": "no id"}
        ok, detail = _delete_call(client, f"{entity.delete_endpoint}/{target}", "delete")
        if not ok:  # desktop falls back to POST form with id / customerId / customer_id
            for b in ({"id": target}, {"customerId": target}, {"customer_id": target}):
                try:
                    response = client.post_form(f"{entity.delete_endpoint}/{target}", b)
                    if response.status_code == 200:
                        ok, detail = True, f"POST {list(b.keys())[0]}"
                        break
                except Exception:  # noqa: BLE001
                    continue
        results.append({"id": target, "ok": ok, "detail": detail})

    elif entity.delete_mode == "joined":
        keys = [_extract_target_id(item, entity) for item in items]
        keys = [value for value in keys if value]
        if not keys:
            return {"key": key, "label": entity.label, "deleted": 0, "failed": 1, "results": [], "status": "no ids"}
        joined = ",".join(keys)
        ok, detail = _delete_call(client, f"{entity.delete_endpoint}/{joined}", entity.delete_method)
        results.append({"id": joined, "ok": ok, "detail": detail, "count": len(keys)})

    else:
        for item in items:
            target = _extract_target_id(item, entity)
            if not target:
                results.append({"id": "", "ok": False, "detail": "missing key"})
                continue
            body = {entity.delete_key: target} if entity.delete_method == "post_form" else None
            ok, detail = _delete_call(client, f"{entity.delete_endpoint}/{target}", entity.delete_method, body=body)
            # Desktop fallback: if DELETE method failed, try post_form with common body fields
            if not ok and entity.delete_method == "delete":
                for b in ({"id": target}, {"customerId": target}, {"customer_id": target}):
                    try:
                        resp = client.post_form(f"{entity.delete_endpoint}/{target}", b)
                        if resp.status_code == 200:
                            ok, detail = True, f"POST {list(b.keys())[0]}"
                            break
                    except Exception:
                        pass
            results.append({"id": target, "ok": ok, "detail": detail})

    deleted = sum(1 for row in results if row["ok"])
    failed = len(results) - deleted
    logger.warning("optional delete %s: %s ok / %s failed", key, deleted, failed)
    return {
        "key": key,
        "label": entity.label,
        "deleted": deleted,
        "failed": failed,
        "results": results,
        "status": f"Deleted {deleted}/{len(results)}",
    }
