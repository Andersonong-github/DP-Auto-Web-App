"""Run the pipeline once against a local preview or a deployed instance to verify the engine + task modules + SSE.

    .venv\\Scripts\\python.exe scripts\\test_pipeline.py --base http://127.0.0.1:8098 --auto-login
    .venv\\Scripts\\python.exe scripts\\test_pipeline.py --base http://10.10.7.230:8080 \
        --pbx https://pbx.example.com --user 0107 --password '***' --dry

`--auto-login` works only on the local preview server (dev_preview.py).
By default every task except "Htek user creation" is selected; add `--only "Group,Context"` to run a subset.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List

import requests

DEFAULT_PARAMS = {
    "group_name": "DEMO_GROUP",
    "group_code": "DEMO_CODE",
    "unified_limit": "10",
    "host_ip": "192.168.1.10",
    "port": "5060",
    "context_prefix": "DEMO_GROUP",
    "perm_group_prefix": "DEMO_GROUP",
    "inbound_ranges": "60358797500 - 60358797509",
    "user_ext": "0358797500 - 0358797502",
    "htek_model": "uc902g",
}

# Complex-mode-only params (the server validates these; missing ones are rejected with 400)
DEFAULT_COMPLEX_PARAMS = {
    "context_suffixes": ["_Internal", "_Fixed", "_Mobile", "_IDD"],
    "pg_spec": {
        "classes": [
            {"class": n, "source_class": n, "enabled": True, "key": "c_i"} for n in (1, 2, 3, 4)
        ]
    },
    "acl_group_selection": ["Managers", "Users"],
    "profile_classes_selection": ["Class_1", "Class_2", "Class_3", "Class_4"],
    "profile_recording": False,
    "profile_number_context": "",
    # Matches the desktop _sync_acl_user_entries: the first extension goes to Managers, the rest to Users
    "acl_managers": "0358797500",
    "acl_supervisors": "",
    "acl_users": "0358797501,0358797502",
    "usernames": [],
    "emails": [],
}


def login(args, session: requests.Session) -> None:
    if args.auto_login:
        response = session.get(f"{args.base}/api/dev/auto-login", allow_redirects=False, timeout=30)
        if response.status_code not in (302, 200):
            raise SystemExit(f"auto-login failed: HTTP {response.status_code}")
        print("Fake session created via /api/dev/auto-login")
        return

    if not (args.pbx and args.user and args.password):
        raise SystemExit("A real login requires --pbx / --user / --password")
    response = session.post(
        f"{args.base}/api/auth/login",
        json={"base_url": args.pbx, "username": args.user, "password": args.password},
        timeout=180,
    )
    if response.status_code != 200:
        raise SystemExit(f"Login failed: HTTP {response.status_code} {response.text[:400]}")
    print(f"Login succeeded: {response.json().get('baseUrl')} ({response.json().get('loginMode')})")


def pick_tasks(config: Dict[str, Any], mode: str, only: str) -> List[str]:
    tasks = [t["name"] for t in config["tasks"] if t.get(mode)]
    if only:
        wanted = [name.strip() for name in only.split(",") if name.strip()]
        missing = [name for name in wanted if name not in tasks]
        if missing:
            raise SystemExit(f"These tasks are not in {mode} mode: {missing}")
        return wanted
    # Skip Htek user creation by default (mutually exclusive with Mobility user creation)
    return [name for name in tasks if name != "User (Htek Mac based Only)"]


def stream_events(session: requests.Session, base: str, run_id: str, after: int = 0) -> int:
    """Consume SSE, print each log line, and return the last received seq."""
    url = f"{base}/api/pipeline/runs/{run_id}/events?after={after}"
    last = after
    finished = False
    with session.get(url, stream=True, timeout=(10, 600)) as response:
        if response.status_code != 200:
            raise SystemExit(f"SSE connection failed: HTTP {response.status_code}")
        for raw in response.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if not raw.startswith("data: "):
                continue
            event = json.loads(raw[6:])
            last = event.get("seq", last)
            kind = event.get("kind")
            if kind == "log":
                level = event.get("level", "info")
                prefix = {"ok": "  OK ", "err": " ERR ", "warn": "WARN "}.get(level, "     ")
                print(f"{prefix}{event.get('message')}")
            elif kind == "task":
                status = {0: "idle", 1: "running", 2: "success", 3: "error"}.get(event.get("status"))
                print(f"--- task {event.get('name')} -> {status}")
            elif kind == "record":
                print(f"    record {event.get('extension')} / {event.get('login_password')} / {event.get('pin')}")
            elif kind == "customer":
                print(f"    Customer ID = {event.get('customerId')}")
            elif kind == "run_start":
                print(f"=== run start {event.get('mode')}: {len(event.get('tasks', []))} tasks")
            elif kind == "run_end":
                print(f"=== run end: {event.get('status')}, {event.get('records')} records")
                finished = True
            if finished:
                break
    return last


def main() -> int:
    # The Windows console defaults to GBK, so emoji in logs raise UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - old Python versions lack reconfigure
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8098")
    parser.add_argument("--auto-login", action="store_true")
    parser.add_argument("--pbx", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--mode", default="standard", choices=["standard", "complex"])
    parser.add_argument("--only", default="", help="comma-separated task names; all by default (except Htek)")
    parser.add_argument("--params", default="", help="path to a params JSON file")
    parser.add_argument("--dry", action="store_true", help="print what would be submitted without starting it")
    args = parser.parse_args()

    session = requests.Session()
    login(args, session)

    config = session.get(f"{args.base}/api/config", timeout=30).json()
    tasks = pick_tasks(config, args.mode, args.only)

    params = dict(DEFAULT_PARAMS)
    if args.mode == "complex":
        params.update(DEFAULT_COMPLEX_PARAMS)
    if args.params:
        params.update(json.loads(open(args.params, encoding="utf-8").read()))

    payload = {"mode": args.mode, "tasks": tasks, "params": params}
    print(f"mode={args.mode}  tasks={len(tasks)}")
    print("Task order: " + " → ".join(tasks))
    if args.dry:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    started = time.time()
    response = session.post(f"{args.base}/api/pipeline/run", json=payload, timeout=60)
    if response.status_code not in (200, 202):
        print(f"Start failed: HTTP {response.status_code} {response.text[:600]}")
        return 2
    snapshot = response.json()
    run_id = snapshot["id"]
    print(f"run id = {run_id}, progress {snapshot['progress']}")

    stream_events(session, args.base, run_id, after=0)

    final = session.get(f"{args.base}/api/pipeline/runs/{run_id}", timeout=30).json()
    print()
    print("=== Task results ===")
    for state in final["tasks"]:
        mark = {0: "·", 1: "…", 2: "✓", 3: "✗"}.get(state["status"], "?")
        print(f"  {mark} {state['name']}")
    print(f"status={final['status']}  elapsed {round(time.time() - started, 1)}s  "
          f"{len(final['records'])} records  Customer ID={final.get('customerId') or '-'}")
    for record in final["records"]:
        print(f"    {record['extension']}  {record['login_password']}  {record['pin']}")
    return 0 if final["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
