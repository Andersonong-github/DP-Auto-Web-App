"""Pipeline execution engine (ported from ``execute_pipeline`` in the desktop ``main.py``).

The task modules are verbatim copies of the desktop ``standard_modules/*.py`` and keep
the ``f(log_func, shared_data) -> bool`` interface, so this module only has to:

* run the selected tasks in order, stopping when one fails (unless several Groups are configured);
* turn task status, logs and extension records into a subscribable event stream that SSE pushes to the browser;
* support interruption at any time.
"""

from __future__ import annotations

import importlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .rest_client import RestClient

MODE_STANDARD = "standard"
MODE_COMPLEX = "complex"

# Status light values, same as the desktop version: gray / yellow / green / red
STATUS_IDLE = 0
STATUS_RUNNING = 1
STATUS_SUCCESS = 2
STATUS_ERROR = 3

# (UI name, module name, entry function, applicable modes) -- order is execution order
TASK_DEFINITIONS = [
    ("Group", "task1_group", "run_group_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("Context", "task2_context", "run_context_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("Permission Group", "task3_perm", "run_perm_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("SIP Trunk", "task4_sip_trunk", "run_sip_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("Outbound Routing", "task5_outbound_routing", "run_outbound_task", (MODE_STANDARD, MODE_COMPLEX)),
    # Complex-only alternative to the 10 default rules: one hand-picked number + context.
    # It reuses Task 5's module; the ``custom_routing_mode`` flag switches the module to a single rule.
    ("Custom Outbound Routing", "task5_outbound_routing", "run_outbound_task", (MODE_COMPLEX,)),
    ("Inbound Routing", "task6_inbound_routing", "run_inbound_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("Caller ID Manipulation", "task7_caller_id_manipulation", "run_caller_id_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("ACL Group", "task8_acl_group", "run_acl_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("User Profile", "task9_user_profile", "run_profile_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("User (Mobility Apps Only)", "task10_user", "run_user_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("User (Htek Mac based Only)", "task10b_user_htek", "run_user_htek_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("ACL User", "task11_acl_user", "run_acl_user_task", (MODE_STANDARD, MODE_COMPLEX)),
    ("Number (Strip Digits)", "task12_number_strip", "run_number_strip_task", (MODE_STANDARD,)),
]

# The two "create user" tasks are mutually exclusive
MUTUALLY_EXCLUSIVE = ("User (Mobility Apps Only)", "User (Htek Mac based Only)")

MAX_EVENTS = 6000


def tasks_for_mode(mode: str) -> List[str]:
    return [name for name, _m, _f, modes in TASK_DEFINITIONS if mode in modes]


def definition_for(name: str):
    for entry in TASK_DEFINITIONS:
        if entry[0] == name:
            return entry
    raise KeyError(name)


def _infer_level(message: str) -> str:
    text = str(message or "").lstrip()
    if text.startswith("❌") or text.startswith("[x]"):
        return "err"
    if text.startswith("⚠️") or text.startswith("ℹ️"):
        return "warn"
    if text.startswith("✅"):
        return "ok"
    return "info"


@dataclass
class TaskState:
    name: str
    status: int = STATUS_IDLE
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def public(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


@dataclass
class PipelineRun:
    id: str
    mode: str
    params: Dict[str, Any]
    tasks: List[TaskState]
    session_id: str
    created_at: float = field(default_factory=time.time)
    status: str = "running"  # running | success | failed | stopped
    events: List[dict] = field(default_factory=list)
    records: List[dict] = field(default_factory=list)
    customer_id: str = ""
    finished_at: Optional[float] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    cond: threading.Condition = field(default_factory=threading.Condition)
    seq: int = 0
    dropped_events: int = 0

    # ---------------------------------------------------------------- events
    def emit(self, kind: str, **payload: Any) -> None:
        with self.cond:
            self.seq += 1
            event = {"seq": self.seq, "t": time.time(), "kind": kind}
            event.update(payload)
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                overflow = len(self.events) - MAX_EVENTS
                del self.events[:overflow]
                self.dropped_events += overflow
            self.cond.notify_all()

    def log(self, message: str, level: Optional[str] = None) -> None:
        self.emit("log", level=level or _infer_level(message), message=str(message))

    def append_record(self, extension: str, login_password: str, pin: str) -> None:
        record = {"extension": extension, "login_password": login_password, "pin": pin}
        self.records.append(record)
        self.emit("record", **record)

    def set_customer_id(self, customer_id: Any) -> None:
        self.customer_id = str(customer_id or "")
        self.emit("customer", customerId=self.customer_id)

    # -------------------------------------------------------------- snapshot
    def running_task(self) -> Optional[str]:
        for state in self.tasks:
            if state.status == STATUS_RUNNING:
                return state.name
        return None

    def public(self) -> dict:
        done = sum(1 for s in self.tasks if s.status in (STATUS_SUCCESS, STATUS_ERROR))
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "createdAt": self.created_at,
            "finishedAt": self.finished_at,
            "customerId": self.customer_id,
            "tasks": [s.public() for s in self.tasks],
            "records": list(self.records),
            "progress": {
                "total": len(self.tasks),
                "done": done,
                "success": sum(1 for s in self.tasks if s.status == STATUS_SUCCESS),
                "error": sum(1 for s in self.tasks if s.status == STATUS_ERROR),
                "current": self.running_task(),
            },
            "lastSeq": self.seq,
            "droppedEvents": self.dropped_events,
        }


class PipelineBusy(RuntimeError):
    """A pipeline is already running for this PBX session."""


class RunRegistry:
    """In-process run registry (single-worker deployment, no database needed)."""

    def __init__(self, max_runs_per_session: int = 20, keep_seconds: int = 7200) -> None:
        self._lock = threading.RLock()
        self._runs: Dict[str, PipelineRun] = {}
        self._active: Dict[str, str] = {}  # session_id -> run_id
        self._max_runs = max_runs_per_session
        self._keep_seconds = keep_seconds

    def create(self, session_id: str, mode: str, params: Dict[str, Any], selected: List[str]) -> PipelineRun:
        with self._lock:
            self._purge_locked()
            active_id = self._active.get(session_id)
            active = self._runs.get(active_id) if active_id else None
            if active is not None and active.status == "running":
                raise PipelineBusy(f"A pipeline is already running ({active.id}); stop it or wait for it to finish.")

            allowed = tasks_for_mode(mode)
            chosen = [name for name in allowed if name in selected] if selected else list(allowed)
            if not chosen:
                raise ValueError("No runnable tasks; select at least one task.")

            run = PipelineRun(
                id=uuid.uuid4().hex[:12],
                mode=mode,
                params=params,
                tasks=[TaskState(name=name) for name in chosen],
                session_id=session_id,
            )
            self._runs[run.id] = run
            self._active[session_id] = run.id
            return run

    def get(self, run_id: str) -> Optional[PipelineRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list_for(self, session_id: str) -> List[PipelineRun]:
        with self._lock:
            runs = [r for r in self._runs.values() if r.session_id == session_id]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            run_id = self._active.get(session_id)
            run = self._runs.get(run_id) if run_id else None
            return bool(run and run.status == "running")

    def stop(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None:
            return False
        run.stop_event.set()
        run.log("Stop requested; it will abort once the current task finishes.", level="warn")
        return True

    def stop_for_session(self, session_id: str) -> int:
        count = 0
        for run in self.list_for(session_id):
            if run.status == "running":
                run.stop_event.set()
                count += 1
        return count

    def _purge_locked(self) -> None:
        now = time.time()
        by_session: Dict[str, List[PipelineRun]] = {}
        for run in list(self._runs.values()):
            expired = run.finished_at is not None and now - run.finished_at > self._keep_seconds
            if expired:
                self._runs.pop(run.id, None)
                continue
            by_session.setdefault(run.session_id, []).append(run)

        for session_id, runs in by_session.items():
            runs.sort(key=lambda r: r.created_at, reverse=True)
            for stale in runs[self._max_runs:]:
                if stale.status == "running":
                    continue
                self._runs.pop(stale.id, None)


registry = RunRegistry()


# ------------------------------------------------------------------- execute
def execute(run: PipelineRun, client: RestClient) -> None:
    """Run the tasks sequentially in a background thread, reporting progress through ``run.emit``."""
    params = dict(run.params)
    shared: Dict[str, Any] = dict(params)
    shared["rest_client"] = client
    shared["user_records"] = run.records
    shared["append_user_record"] = run.append_record
    shared["set_customer_id"] = run.set_customer_id
    shared["custom_api_payloads"] = params.get("custom_api_payloads") or {}

    limit = str(params.get("unified_limit") or "10")
    shared.setdefault("max_concurrent", limit)
    shared.setdefault("max_reg_user", limit)

    # Multiple Groups: run the first comma-separated one directly, the rest after the Group task
    group_names = [name.strip() for name in str(params.get("group_name") or "").split(",") if name.strip()]
    if len(group_names) > 1:
        shared["original_group_name"] = params.get("group_name")
        shared["group_name"] = group_names[0]
        shared["additional_groups"] = group_names[1:]
    else:
        shared["additional_groups"] = []

    run.emit("run_start", mode=run.mode, tasks=[t.name for t in run.tasks], params=_public_params(params))
    run.log(f"Starting {run.mode} pipeline with {len(run.tasks)} task(s).", level="info")

    all_ok = True
    aborted = False
    try:
        for state in run.tasks:
            if run.stop_event.is_set():
                run.log(f"User interrupted; skipping the remaining tasks ({state.name} and later).", level="warn")
                aborted = True
                break

            ui_name = state.name
            _task_name, module_name, func_name, _modes = definition_for(ui_name)
            state.status = STATUS_RUNNING
            state.started_at = time.time()
            run.emit("task", name=ui_name, status=STATUS_RUNNING)
            run.log(f"Running: {ui_name}")

            ok = False
            try:
                module = importlib.import_module(f"{__package__}.tasks.{run.mode}.{module_name}")
                func = getattr(module, func_name)
                ok = bool(func(run.log, shared))
            except Exception as exc:  # noqa: BLE001 - an exception in one task must not crash the whole pipeline
                run.log(f"{ui_name} raised an exception: {type(exc).__name__}: {exc}", level="err")
                ok = False

            state.status = STATUS_SUCCESS if ok else STATUS_ERROR
            state.finished_at = time.time()
            run.emit("task", name=ui_name, status=state.status)
            if not ok:
                all_ok = False
                run.log(f"{ui_name} failed", level="err")
                if not shared.get("additional_groups"):
                    run.log("Pipeline stopped at the task that failed.", level="err")
                    break

            # After the Group task succeeds, create the additional groups too
            if ui_name == "Group" and shared.get("additional_groups"):
                for extra in list(shared["additional_groups"]):
                    if run.stop_event.is_set():
                        aborted = True
                        break
                    run.log(f"Running: Group for {extra}", level="info")
                    try:
                        module = importlib.import_module(f"{__package__}.tasks.{run.mode}.{module_name}")
                        func = getattr(module, func_name)
                        temp = dict(shared)
                        temp["group_name"] = extra
                        if func(run.log, temp):
                            run.log(f"Group created: {extra}", level="ok")
                        else:
                            run.log(f"Group creation failed: {extra}", level="err")
                            all_ok = False
                    except Exception as exc:  # noqa: BLE001
                        run.log(f"Extra Group {extra} raised an exception: {exc}", level="err")
                        all_ok = False

        if run.stop_event.is_set() or aborted:
            run.status = "stopped"
            run.log("Task execution was stopped by the user." if run.stop_event.is_set() else "Task execution aborted.", level="warn")
        elif all_ok:
            run.status = "success"
            run.log("All tasks completed!", level="ok")
        else:
            run.status = "failed"
    except Exception as exc:  # noqa: BLE001 - safety net, ensure run_end is always emitted
        run.status = "failed"
        run.log(f"Fatal error: {type(exc).__name__}: {exc}", level="err")
    finally:
        run.finished_at = time.time()
        run.emit(
            "run_end",
            status=run.status,
            records=len(run.records),
            customerId=run.customer_id,
        )


def _public_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Parameters echoed back to the frontend, with anything that must not be sent removed."""
    hidden = {"custom_api_payloads", "pg_server_data", "usernames", "emails", "htek_mac_data"}
    return {k: v for k, v in params.items() if k not in hidden}
