"""Local UI preview server: stands in a **stateful fake PBX** for the real device.

    .venv\\Scripts\\python.exe scripts\\dev_preview.py        # http://127.0.0.1:8098

Besides making the UI viewable, it also lets the **entire standard pipeline (13 tasks) really run once locally**:
the fake PBX remembers the Group / User Profile it created and returns the fields the task code expects
(`success` / `id` / `status_id` / `profileId` / `pin`), so the status lights, the SSE log and the
extension records are all produced for real.

Use it only for local development:
  * the container image starts with ``uvicorn backend.app.main:app``, so this file is never loaded;
  * the ``/api/dev/auto-login`` route is also registered only in the preview process.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import uvicorn
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.pbx.rest_client import RestClient  # noqa: E402
from backend.app.security import set_session_cookie  # noqa: E402
from backend.app.sessions import store  # noqa: E402

# The fake PBX "database"
STATE: dict = {"customers": [], "profiles": [], "acl_groups": [], "numbers": [], "contexts": [], "acl_user_updates": [], "next_id": 5000}


def _next_id() -> int:
    STATE["next_id"] += 1
    return STATE["next_id"]


class FakeResponse:
    def __init__(self, payload=None, status: int = 200, text: str | None = None) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.text = text if text is not None else json.dumps(payload or {}, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError("response is not JSON")
        return self._payload


def fake_login(self, username, password):  # noqa: ANN001
    self.authenticated = True
    self.login_mode = "restful"
    self.last_error = ""
    return True


# Sample data for the remaining optional task entities (Search & Delete page).
# Rows follow the *current* demo group so the desktop-style prefix matching works.
def entity_samples(name: str, cid: str) -> dict:
    return {
        "user/huntgroup/view/list": [
            {"id": 3001, "title": f"{name}_HUNT", "name": f"{name}_HUNT", "huntmode": "ringall", "group": cid}
        ],
        "callpickupgroup/view/list": [
            {"id": 3002, "groupID": 3002, "groupTitle": f"{name}_PICKUP", "group": cid}
        ],
        "callcentre/queue/view/list": [{"id": 3003, "name": f"{name}_QUEUE", "group": cid}],
        "ivr/route/view/list": [{"id": f"{name}_IVR", "name": f"{name}_IVR", "group": cid}],
        "configuration/voiceprompt/view/list": [
            {"id": 3005, "prompt_name": f"{name}_PROMPT", "name": f"{name}_PROMPT", "group": cid}
        ],
        "numbercallforward/view/list": [
            {"number": "0358797500", "call_forward": "0358797501", "group": cid}
        ],
        "callcentre/agent/view/list": [
            {"id": 3007, "agentid": f"{name}_AG1", "name": f"{name}_AG1", "firstname": name, "group": cid}
        ],
        "callcentre/agentgroup/view/list": [{"id": 3008, "name": f"{name}_AG", "group": cid}],
        "numberingplan/number/view/list": [
            {
                "id": 3009,
                "number": "0358797500",
                "number_name": f"{name} Number",
                "context": f"{name}_Internal",
                "group": cid,
            }
        ],
        "calleridmanipulation/view/list": [
            {
                # matched by group name so the row is found whichever duplicate
                # customer id a repeated demo run happens to resolve to
                "peerID": name,
                "manipulation_id": 4001,
                "manipulation_type": "default",
                "internal_exten_range_begin": "6400",
                "internal_exten_range_end": "6499",
                "callerid_strip": "",
                "callerid_prepend": "6032856",
                "resolved_range_begin": "60328566400",
                "resolved_range_end": "60328566499",
            }
        ],
    }


def fake_get(self, endpoint, params=None):  # noqa: ANN001
    params = params or {}

    # ---- Number lookup: the three-step v1 RESTful chain (matches the implementation in ops.py) ----
    if endpoint.endswith("/numberingplan/numberstatus/view/list"):
        return FakeResponse(
            {
                "success": True,
                "list": [
                    {
                        "number": "0358797500",
                        "id": "8001",
                        "number_id": "3009",
                        "status_name": "Strip Digit",
                        "status_desc": "demo status",
                        "status_type": "simple",
                        "status_owner_display": "0358797500 - Demo",
                    }
                ],
            }
        )

    if "/numberstatus/" in endpoint:
        return FakeResponse(
            {
                "id": "8001",
                "number_id": "3009",
                "status_name": "Strip Digit",
                "status_type": "simple",
                "type": "Number",
                "status_owner": "0358797500 - Demo",
                "steps": [
                    {
                        "step": 1,
                        "step_type": "goto_context",
                        "app": "Goto",
                        "parameter": "03383,,DEMO_GROUP_Internal",
                        "display_parameter": "",
                    }
                ],
            }
        )

    if re.search(r"numberingplan/number/\d+$", endpoint):
        return FakeResponse(
            {
                "id": "3009",
                "number": "0358797500",
                "number_name": "DEMO Number",
                "group": "1001",
                "context": "DEMO_GROUP_Internal",
                "type": "Number",
            }
        )

    # ---- Search & Delete (desktop parity): detail + list endpoints ----
    def _demo_group():
        row = STATE["customers"][-1] if STATE["customers"] else {"engName": "DEMO CUSTOMER", "customerId": "1001"}
        return row.get("engName") or "DEMO_GROUP", str(row.get("customerId") or "1001")

    if re.search(r"numberingplan/permissiongroup/view/list$", endpoint):
        name, cid = _demo_group()
        rows = [
            {"contextTitle": f"{name}_Class_{n}", "groupName": name, "contextInclude_value": ""}
            for n in (1, 2, 3, 4)
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if re.search(r"numberingplan/permissiongroup/(.+)$", endpoint):
        name, cid = _demo_group()
        title = endpoint.rstrip("/").split("/")[-1]
        # The real PBX wraps details in {"data": {...}} (RestClient.get_permgroup_detail)
        return FakeResponse({"data": {"contextTitle": title, "group": cid, "contextInclude_value": "", "groupName": name}})

    if re.search(r"numberingplan/context/([^/]+)$", endpoint):
        name, cid = _demo_group()
        context_id = endpoint.rstrip("/").split("/")[-1]
        # The real PBX wraps details in {"data": {...}} (RestClient.get_context_detail)
        return FakeResponse(
            {
                "data": {
                    "id": context_id,
                    "contextID": context_id,
                    "contextTitle": context_id,
                    "contextDesc": "",
                    "group": cid,
                    "groupName": name,
                }
            }
        )

    if re.search(r"user/user/view/list$", endpoint):
        name, cid = _demo_group()
        rows = [
            {"id": 4001, "username": "0358797500", "ext": "0358797500", "group": cid, "firstname": "Demo", "lastname": "Manager"},
            {"id": 4002, "username": "0358797501", "ext": "0358797501", "group": cid, "firstname": "Demo", "lastname": "User 1"},
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if re.search(r"user/user/([^/]+)$", endpoint):
        name, cid = _demo_group()
        user_id = endpoint.rstrip("/").split("/")[-1]
        return FakeResponse(
            {"id": user_id, "username": user_id, "ext": user_id, "group": cid, "firstname": "Demo", "lastname": "User"}
        )

    for fragment, rows in entity_samples(*_demo_group()).items():
        if fragment in endpoint:
            return FakeResponse({"list": rows, "total": len(rows)})
    if "customer/customer/view/list" in endpoint:
        # Preview parity with the real PBX: a single response is capped at 100 rows
        # (it silently returns fewer than the requested ``limit``), so the backend
        # must page through with ``start`` to see every Group.
        rows = STATE["customers"] or [
            {"customerId": "1001", "engName": "DEMO CUSTOMER", "code": "DEMO"}
        ]
        start = int(params.get("start", 0) or 0)
        requested = int(params.get("limit", 100) or 100)
        page_size = min(requested, 100)
        page = rows[start:start + page_size]
        return FakeResponse({"list": page, "total": len(rows)})

    if "userprofile/view/list" in endpoint:
        rows = STATE["profiles"] or [
            {"id": 900, "profile_name": "DEMO_Class_3", "group": "1001"}
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if "numberingplan/context/view/list" in endpoint:
        # The real PBX returns every context of every Group; the backend filters by Group.
        # Replay whatever Task 2 / /api/dev/seed-contexts created, and fall back to the four
        # standard rows of the current demo group when nothing has been created yet.
        if STATE["contexts"]:
            name_by_cid = {row.get("customerId"): row.get("engName") for row in STATE["customers"]}
            rows = [
                {
                    "id": index,
                    "contextID": ctx["contextID"],
                    "contextTitle": ctx.get("contextTitle") or ctx["contextID"],
                    "groupName": name_by_cid.get(ctx.get("group"), ""),
                    "group": ctx.get("group") or "",
                    "customerId": ctx.get("group") or "",
                }
                for index, ctx in enumerate(STATE["contexts"], start=1)
            ]
            return FakeResponse({"list": rows, "total": len(rows)})
        row = STATE["customers"][-1] if STATE["customers"] else {"engName": "DEMO_GROUP", "customerId": "1001"}
        name, cid = row.get("engName") or "DEMO_GROUP", row.get("customerId") or "1001"
        rows = [
            {
                "id": index,
                "contextID": f"{name}{suffix}",
                "contextTitle": f"{name}{suffix}",
                "groupName": name,
                "group": cid,
                "customerId": cid,
            }
            for index, suffix in enumerate(("_Internal", "_Fixed", "_Mobile", "_IDD"), start=1)
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if "aclgroup/view/list" in endpoint:
        # task9 finds the ACL group via <group name>_Users, so the groups created by task8 must be replayed here
        rows = STATE["acl_groups"] or [
            {"id": 1, "acl_group_id": 1, "name": "DEMO-ACL", "customer_id": "1001"}
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if "acluser/view/list" in endpoint:
        name, cid = _demo_group()
        rows = [
            {"id": 5001, "username": f"{name}_U1", "groupname": name, "group": cid, "privileges": "manager"},
            {"id": 5002, "username": f"{name}_U2", "groupname": name, "group": cid, "privileges": "limited"},
        ]
        return FakeResponse({"list": rows, "total": len(rows)})

    if "acluser/" in endpoint:
        # The real PBX returns a **flat** user object here (the task code uses it directly as a dict)
        ext = endpoint.rstrip("/").split("/")[-1]
        return FakeResponse(
            {
                "id": ext,
                "username": ext,
                "firstname": "Demo",
                "lastname": "User",
                "group": "1001",
                "email": "",
            }
        )

    if "activepeer" in endpoint:
        # SIP trunk status page: report two "online peers" (names must line up with
        # the siptrunk rows above, which follow the current demo group)
        name = _demo_group()[0]
        return FakeResponse(
            {
                "list": [
                    {"name": f"{name}_PEER", "host": "192.168.1.10", "port": "5060", "status": "registered"},
                    {"name": f"{name}_PEER2", "host": "192.168.1.11", "port": "5060", "status": "unreachable"},
                ]
            }
        )

    if "siptrunk" in endpoint:
        return FakeResponse(
            {
                "list": [
                    {"peerID": f"{_demo_group()[0]}_PEER", "host": "192.168.1.10", "port": "5060", "group": _demo_group()[1]},
                    {"peerID": f"{_demo_group()[0]}_PEER2", "host": "192.168.1.11", "port": "5060", "group": _demo_group()[1]},
                ]
            }
        )

    # All other lookups (outbound/inbound/caller ID manipulation/context...) return an empty list, so the tasks take the "create" branch
    return FakeResponse({"list": [], "total": 0})


def fake_post(self, endpoint, json_data=None):  # noqa: ANN001
    payload = json_data or {}

    if "post/numberingplan/context" in endpoint:
        context_id = payload.get("contextID") or payload.get("contextTitle") or ""
        STATE["contexts"].append(
            {
                "contextID": context_id,
                "contextTitle": payload.get("contextTitle") or context_id,
                "group": str(payload.get("group") or ""),
            }
        )
        return FakeResponse({"success": True, "id": _next_id()})

    if "post/customer/customer" in endpoint:
        row = {
            "customerId": str(_next_id()),
            "engName": payload.get("engName") or payload.get("name") or "",
            "code": payload.get("code") or "",
        }
        STATE["customers"].append(row)
        return FakeResponse({"success": True, "id": row["customerId"], "data": row})

    if "post/user/userprofile" in endpoint:
        profile_id = _next_id()
        STATE["profiles"].append(
            {
                "id": profile_id,
                "profile_name": payload.get("profile_name") or f"PROFILE_{profile_id}",
                "group": payload.get("group") or "",
                # Kept so the E2E suite can prove the chosen number context reaches the PBX.
                "number_context": payload.get("number_context") or "",
                "user_context": payload.get("user_context") or "",
            }
        )
        return FakeResponse({"success": True, "profileId": profile_id})

    if "numberingplan/number" in endpoint and "set/status" not in endpoint:
        number_id = _next_id()
        STATE["numbers"].append(
            {
                "id": number_id,
                "number": payload.get("number") or "",
                "number_name": payload.get("number_name") or "",
                "number_desc": payload.get("number_desc") or "",
                "group": payload.get("group") or "",
                "context": payload.get("context") or "",
                "action": payload.get("action") or "",
            }
        )
        return FakeResponse({"success": True, "id": number_id})

    if "post/user/user" in endpoint:
        return FakeResponse(
            {
                "success": True,
                "id": _next_id(),
                "pin": {
                    "login_pw": f"lp{int(time.time()) % 100000}",
                    "user_pin": f"{int(time.time()) % 10000:04d}",
                },
            }
        )

    return FakeResponse({"success": True, "id": _next_id()})


def fake_post_form(self, endpoint, data):  # noqa: ANN001
    payload = data or {}
    if "numberstatus" in endpoint:
        return FakeResponse({"success": True, "status_id": _next_id()})
    if "number/set/status/mode" in endpoint:
        # POST 3 of "Number (Create Dial to Number)": enable simple status mode
        return FakeResponse({"success": True, "mode": payload.get("mode") or "simple"})
    if "post/configuration/aclgroup" in endpoint:
        group_id = _next_id()
        STATE["acl_groups"].append(
            {
                "id": group_id,
                "acl_group_id": group_id,
                "name": payload.get("name") or f"ACL_{group_id}",
                "customer_id": str(payload.get("group") or payload.get("customer_id") or ""),
            }
        )
        return FakeResponse({"success": True, "id": group_id, "acl_group_id": group_id})
    if "/put/configuration/acluser/" in endpoint:
        # Keep what Task 11 sent so the E2E suite can prove every role really receives the
        # four manager_allow capabilities (not just the first extension of each group).
        STATE["acl_user_updates"].append(
            {
                "id": endpoint.rstrip("/").split("/")[-1],
                "username": payload.get("username") or "",
                "aclgroup": str(payload.get("aclgroup") or ""),
                "privileges": payload.get("privileges") or "",
                "features": payload.get("features") or "[]",
            }
        )
        return FakeResponse({"success": True, "id": payload.get("id") or ""})
    return FakeResponse({"success": True, "id": _next_id()})


def fake_delete(self, endpoint, params=None):  # noqa: ANN001
    """Delete endpoint (used by Search & Delete): the fake PBX always returns success."""
    return FakeResponse({"success": True, "deleted": endpoint})


RestClient.login = fake_login        # type: ignore[method-assign]
RestClient.get = fake_get            # type: ignore[method-assign]
RestClient.post = fake_post          # type: ignore[method-assign]
RestClient.post_form = fake_post_form  # type: ignore[method-assign]
RestClient.delete = fake_delete      # type: ignore[method-assign]

from backend.app.main import app  # noqa: E402


def auto_login(_request) -> RedirectResponse:
    """Preview only: create a fake session right away and redirect back to the home page."""
    client = RestClient("https://pbx.demo.local", verify=False)
    client.login("demo", "demo")
    session = store.create(client, client.base_url, "demo", "restful", "127.0.0.1")
    response = RedirectResponse(url="/", status_code=302)
    set_session_cookie(response, session.sid)
    return response


def reset_demo(_request):
    """Preview only: clear the fake PBX data so the demo can be repeated."""
    STATE["customers"].clear()
    STATE["profiles"].clear()
    STATE["acl_groups"].clear()
    STATE["numbers"].clear()
    STATE["contexts"].clear()
    STATE["acl_user_updates"].clear()
    return RedirectResponse(url="/#/dashboard", status_code=302)


def seed_contexts(request):
    """Preview only: create a Group that has contexts but **no ``_Internal``**.

    ``/api/dev/seed-contexts`` — the scenario the Permission Group picker must handle:
    Task 2 skipped ``_Internal``, yet the operator wants an already-existing context to
    sit ahead of the standard ones in a Class.

    Query params: ``group`` (default ``CTX_GROUP``), ``contexts`` (comma-separated names).
    """
    group = request.query_params.get("group", "CTX_GROUP")
    raw = request.query_params.get("contexts", "")
    names = [part.strip() for part in raw.split(",") if part.strip()] or [
        f"{group}_SALES",
        f"{group}_SUPPORT",
        f"{group}_Fixed",
    ]
    customer_id = ""
    for row in STATE["customers"]:
        if row.get("engName") == group:
            customer_id = row.get("customerId") or ""
            break
    if not customer_id:
        customer_id = str(_next_id())
        STATE["customers"].append({"customerId": customer_id, "engName": group, "code": group})
    STATE["contexts"] = [ctx for ctx in STATE["contexts"] if ctx.get("group") != customer_id]
    for name in names:
        STATE["contexts"].append({"contextID": name, "contextTitle": name, "group": customer_id})
    return JSONResponse({"group": group, "customerId": customer_id, "contexts": names})


def debug_profiles(_request):
    """Preview only: what the fake PBX recorded for each created User Profile."""
    return JSONResponse({"profiles": STATE["profiles"]})


def debug_acl_users(_request):
    """Preview only: what Task 11 sent for each ACL user update."""
    return JSONResponse({"updates": STATE["acl_user_updates"]})


def seed_groups(request):
    """Preview only: fill the fake PBX with N customer groups to exercise long lists.

    ``/api/dev/seed-groups?count=250`` -- useful for reproducing the "Group list is
    truncated" bug, because the fake customer list caps one response at 100 rows.
    """
    count = int(request.query_params.get("count", "250") or 250)
    STATE["customers"].clear()
    for index in range(1, count + 1):
        STATE["customers"].append(
            {
                "customerId": str(1000 + index),
                "engName": f"DEMO_GROUP_{index:03d}",
                "code": f"DG{index:03d}",
                "maxConcurrentCalls": 10,
                "registerUserCount": 10,
            }
        )
    return RedirectResponse(url="/#/search-delete", status_code=302)


# The static directory is mounted at "/" and would swallow routes appended after it, so these two must go first.
app.router.routes.insert(0, Route("/api/dev/debug-profiles", debug_profiles, methods=["GET"]))
app.router.routes.insert(0, Route("/api/dev/debug-acl-users", debug_acl_users, methods=["GET"]))
app.router.routes.insert(0, Route("/api/dev/seed-contexts", seed_contexts, methods=["GET", "POST"]))
app.router.routes.insert(0, Route("/api/dev/seed-groups", seed_groups, methods=["GET", "POST"]))
app.router.routes.insert(0, Route("/api/dev/reset", reset_demo, methods=["GET", "POST"]))
app.router.routes.insert(0, Route("/api/dev/auto-login", auto_login, methods=["GET"]))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8098, log_level="info")
