"""Htek / Deltapath IP phone auto-provisioning engine.

This is a faithful server-side port of the desktop
``Htek-FTP-Provisioning-Tool`` (``main.py``): ping pre-check, ARP MAC lookup with a
vendor-prefix check, HTTP-authenticated page inspection, and the P237 / P1360 /
P1361 auto-provision form.

Why Playwright
--------------
The desktop tool drives the locally installed Chrome/Edge through Playwright and
fills the phone web UI exactly as a human would. Re-implementing the form POST by
hand was rejected: the Htek pages use JavaScript and a SaveSet -> Autoprovision Now
sequence, so a raw POST can silently save without triggering the reboot. Playwright
is imported lazily, so the app still starts when it is not installed; only the
provisioning browser modes are then marked unavailable.

Everything runs in one background thread per job. Network I/O (ping, ARP, page
navigation) blocks for seconds per phone, which must never run on the event loop.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

try:  # optional dependency: scan-only mode keeps working without it
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - depends on the local installation
    sync_playwright = None

logger = logging.getLogger("dpauto.htek")

MODES: List[dict] = [
    {
        "id": "provision",
        "label": "Full Provision",
        "detail": "Auto-config + HTTP auth: write the provisioning server parameters and reboot the phone.",
        "needsBrowser": True,
    },
    {
        "id": "scan",
        "label": "Scan IP & MAC only",
        "detail": "Ping + ARP only; never logs in and never changes a phone.",
        "needsBrowser": False,
    },
    {
        "id": "scan_full",
        "label": "Scan IP, MAC & phone status",
        "detail": "Adds the registration status and the MAC shown on the phone index page.",
        "needsBrowser": True,
    },
]

DEFAULTS = {
    "mode": "provision",
    "server": "deltapath-cc.maxis.com.my",
    "httpUser": "spip8014",
    "macPrefix": "001fc1",
    "auth1User": "admin",
    "auth1Pass": "admin",
    "auth2User": "admin",
    "auth2Pass": "46709394",
    "retryCycles": 20,
    "retryDelaySeconds": 15,
    "allowRouted": False,
}

MAX_TARGETS = 5000
MAX_ROWS_IN_PAYLOAD = 5000
MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})")
IPV4_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")


class JobBusyError(RuntimeError):
    """Only one Htek job per operator at a time (desktop behaviour)."""


# --------------------------------------------------------------------------- helpers
def find_browser_path() -> Optional[str]:
    """Find an installed Chromium-based browser, exactly like the desktop tool."""
    local = os.environ.get("LOCALAPPDATA") or ""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.join(local, r"Microsoft\Edge\Application\msedge.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


BROWSER_PATH = find_browser_path()


def browser_ready() -> bool:
    return sync_playwright is not None and BROWSER_PATH is not None


def _tcp_probe(ip: str, port: int = 80, timeout: float = 0.9) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def ping_ok(ip: str) -> bool:
    """One ICMP echo with the desktop's 800 ms timeout."""
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", "800", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        # Minimal containers have no ping binary; fall back to a TCP port probe.
        return _tcp_probe(ip)
    except Exception:
        return False


def arp_mac(ip: str) -> Optional[str]:
    """Read the MAC from the ARP/neighbour table and normalise it to 12 hex chars."""
    try:
        if sys.platform == "win32":
            output = subprocess.check_output(
                ["arp", "-a", ip],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=5,
                errors="ignore",
            )
        else:
            output = subprocess.check_output(
                ["ip", "neigh", "show", ip],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=5,
                errors="ignore",
            )
    except Exception:
        return None

    # Prefer a line that actually mentions the target IP, so the local interface
    # MAC in the same arp output cannot be mistaken for the phone.
    match = None
    for line in output.splitlines():
        if ip in line:
            match = MAC_RE.search(line)
            if match:
                break
    if match is None:
        match = MAC_RE.search(output)
    if match is None:
        return None

    mac = re.sub(r"[:-]", "", match.group(1)).lower()
    if mac in {"000000000000", "ffffffffffff"}:
        return None
    return mac


def normalise_mac(value: str) -> Optional[str]:
    """Return a MAC as 12 lowercase hex chars, or None if the text has no MAC."""
    text = str(value or "")
    match = MAC_RE.search(text)
    if match is None:
        # Some phone pages print the MAC without separators.
        match = re.search(r"\b([0-9a-fA-F]{12})\b", text)
    if match is None:
        return None
    mac = re.sub(r"[:-]", "", match.group(1)).lower()
    if mac in {"000000000000", "ffffffffffff"}:
        return None
    return mac


def parse_ip_range(spec: str) -> List[str]:
    """Expand ``192.0.2.1-254`` (and the full ``192.0.2.1-192.0.2.254`` form)."""
    text = (spec or "").strip()
    if not text or "-" not in text:
        return []
    base, end_part = text.rsplit("-", 1)
    base = base.strip()
    end_part = end_part.strip()
    if "." not in base:
        return []

    prefix, start_part = base.rsplit(".", 1)
    try:
        start_num = int(start_part)
    except ValueError:
        return []

    if "." in end_part:
        end_prefix, end_last = end_part.rsplit(".", 1)
        if end_prefix != prefix:
            return []
        try:
            end_num = int(end_last)
        except ValueError:
            return []
    else:
        try:
            end_num = int(end_part)
        except ValueError:
            return []

    if not (0 <= start_num <= 255 and 0 <= end_num <= 255) or end_num < start_num:
        return []
    return [f"{prefix}.{number}" for number in range(start_num, end_num + 1)]


def build_targets(ips_text: str, range_text: str) -> Tuple[List[str], bool]:
    """Desktop rule: a non-empty IP range wins over the list. Returns (targets, truncated)."""
    raw: List[str] = []
    if (range_text or "").strip():
        raw = parse_ip_range(range_text)
    else:
        for line in (ips_text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw.append(line)

    targets: List[str] = []
    seen = set()
    truncated = False
    for item in raw:
        # Accept a comma separated list on one line as a convenience.
        for candidate in re.split(r"[\s,;]+", item):
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            if not IPV4_RE.match(candidate):
                continue
            seen.add(candidate)
            targets.append(candidate)
            if len(targets) >= MAX_TARGETS:
                truncated = True
                return targets, truncated
    return targets, truncated


# --------------------------------------------------------------------------- job model
@dataclass
class Row:
    ip: str
    mac: str = "N/A"
    status: str = "QUEUED"
    detail: str = "Queued"
    phase: str = "queued"  # queued | running | done | retry
    attempts: int = 0
    first_seen: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "status": self.status,
            "detail": self.detail,
            "phase": self.phase,
            "attempts": self.attempts,
            "updatedAt": self.updated_at,
        }


def _is_bad_detail(detail: str) -> bool:
    return any(marker in detail for marker in ("OFFLINE", "MAC MISMATCH", "IP CONFLICT", "FAIL"))


class HtekJob:
    def __init__(self, owner: str, params: dict, targets: Sequence[str]) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.owner = owner
        self.params = dict(params)
        self.mode = self.params["mode"]
        self.created_at = time.time()
        self.started_at = self.created_at
        self.finished_at: Optional[float] = None
        self.state = "running"  # running | finished | stopped | error
        self.error = ""
        self.cycle = 0
        self.current_ip = ""
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.rows: Dict[str, Row] = {ip: Row(ip) for ip in targets}
        self.order: List[str] = list(targets)
        self.truncated = bool(self.params.get("_truncated"))
        self.logs: List[dict] = []
        self.provisioned: set = set()
        self.locked_macs: Dict[str, str] = {}

        self.server = str(self.params.get("server") or "").strip()
        self.http_user = str(self.params.get("httpUser") or "").strip()
        self.http_pass = str(self.params.get("httpPass") or "")
        self.mac_prefix = str(self.params.get("macPrefix") or "").strip().lower()
        self.retry_cycles = int(self.params.get("retryCycles") or 0)
        self.retry_delay = max(1, int(self.params.get("retryDelaySeconds") or 15))
        # Routed/cross-subnet phones have no ARP entry on this PC. When enabled,
        # continue with HTTP and read the MAC from the phone page instead.
        self.allow_routed = bool(self.params.get("allowRouted"))

        pairs = [
            ("account 2", str(self.params.get("auth2User") or ""), str(self.params.get("auth2Pass") or "")),
            ("account 1", str(self.params.get("auth1User") or ""), str(self.params.get("auth1Pass") or "")),
        ]
        self.credentials = [(label, user, password) for label, user, password in pairs if user or password]

    # ------------------------------------------------------------------ logging
    def log(self, level: str, message: str) -> None:
        entry = {"t": time.time(), "level": level, "message": str(message)}
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > 500:
                del self.logs[: len(self.logs) - 500]
        logger.info("htek %s: %s", self.id, message)

    # ------------------------------------------------------------------- rows
    def update_row(self, ip: str, mac: str, status: str, detail: str, phase: str) -> None:
        with self.lock:
            row = self.rows.get(ip)
            if row is None:
                row = Row(ip)
                self.rows[ip] = row
                self.order.append(ip)
            row.mac = mac
            row.status = status
            row.detail = detail
            row.phase = phase
            row.attempts += 1
            row.updated_at = time.time()

    def set_phase(self, ip: str, phase: str) -> None:
        with self.lock:
            row = self.rows.get(ip)
            if row:
                row.phase = phase
                row.updated_at = time.time()

    def delete_row(self, ip: str) -> bool:
        with self.lock:
            if ip not in self.rows:
                return False
            del self.rows[ip]
            if ip in self.order:
                self.order.remove(ip)
            return True

    def clear_rows(self) -> None:
        with self.lock:
            self.rows.clear()
            self.order.clear()

    # --------------------------------------------------------------- snapshot
    def counts(self) -> dict:
        with self.lock:
            rows = list(self.rows.values())
        done = sum(1 for row in rows if row.phase == "done")
        retry = sum(1 for row in rows if row.phase == "retry")
        processed = sum(1 for row in rows if row.status != "QUEUED")
        ok = sum(1 for row in rows if row.status == "DONE" and not _is_bad_detail(row.detail))
        fail = sum(1 for row in rows if row.status == "DONE" and _is_bad_detail(row.detail))
        return {
            "total": len(rows),
            "processed": processed,
            "done": done,
            "retry": retry,
            "ok": ok,
            "fail": fail,
            "pending": len(rows) - done,
        }

    def snapshot(self, include_logs: bool = True) -> dict:
        with self.lock:
            rows = [self.rows[ip].public() for ip in self.order if ip in self.rows]
            logs = list(self.logs) if include_logs else []
            state = self.state
            finished_at = self.finished_at
            current_ip = self.current_ip
            cycle = self.cycle
            error = self.error
            truncated = self.truncated
        return {
            "id": self.id,
            "mode": self.mode,
            "state": state,
            "cycle": cycle,
            "currentIp": current_ip,
            "startedAt": self.started_at,
            "finishedAt": finished_at,
            "error": error,
            "truncated": truncated,
            "counts": self.counts(),
            "rows": rows,
            "logs": logs,
            "config": {
                "server": self.server,
                "httpUser": self.http_user,
                "macPrefix": self.mac_prefix,
                "auth1User": str(self.params.get("auth1User") or ""),
                "auth2User": str(self.params.get("auth2User") or ""),
                "retryCycles": self.retry_cycles,
                "retryDelaySeconds": self.retry_delay,
            },
        }

    def to_csv(self) -> str:
        with self.lock:
            rows = [self.rows[ip] for ip in self.order if ip in self.rows]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["IP Address", "MAC Address", "Status", "Detail"])
        for row in rows:
            writer.writerow([row.ip, row.mac, row.status, row.detail])
        return "\ufeff" + buffer.getvalue()


# --------------------------------------------------------------------------- browser work
_STATUS_XPATHS = [
    "//td[contains(text(), 'Account 1')]/following-sibling::td[1]",
    "//td[text()='Account 1']/following-sibling::td[1]",
]

_MAC_XPATHS = [
    "//td[contains(text(), 'MAC Address')]/following-sibling::td[1]",
    "//td[@width='280' and contains(text(), ':')]",
    "//td[contains(text(), 'MAC')]/following-sibling::td",
]


def _status_info(page, ip: str) -> Tuple[str, str]:
    """Replicates the desktop ``get_status_info`` xpath scraping."""
    reg_status = "Unknown"
    mac_addr = "N/A"
    try:
        page.goto(f"http://{ip}/index.htm", timeout=8000)
        page.wait_for_load_state("networkidle")
        for xpath in _STATUS_XPATHS:
            try:
                text = page.locator(f"xpath={xpath}").inner_text(timeout=2000).strip()
                if text:
                    reg_status = text.replace("\n", " ")
                    break
            except Exception:
                continue
        for xpath in _MAC_XPATHS:
            try:
                text = page.locator(f"xpath={xpath}").inner_text(timeout=2000).strip()
                candidate = normalise_mac(text)
                if candidate:
                    mac_addr = candidate
                    break
            except Exception:
                continue
    except Exception:
        pass
    return reg_status, mac_addr


def _close_quietly(resource) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        pass


def _process_ip(job: HtekJob, browser, ip: str) -> Tuple[str, str, str]:
    """One pass over one phone; mirrors ``run_one_phone`` in the desktop tool."""
    reachable = ping_ok(ip)
    if not reachable and job.allow_routed and _tcp_probe(ip, 80):
        # Some routed phone VLANs block ICMP but still serve the web UI.
        reachable = True
        job.log("info", f"{ip}: ping failed but TCP 80 answered (routed host)")
    current_mac = arp_mac(ip)

    if job.mode == "scan":
        if not reachable:
            return "DONE", "OFFLINE (No Device Found)", "N/A"
        if not current_mac:
            if job.allow_routed:
                return "DONE", "REACHABLE (routed; MAC not in ARP table)", "N/A"
            return "DONE", "FAIL (ARP MAC not found)", "N/A"
        if job.mac_prefix and not current_mac.startswith(job.mac_prefix):
            return "DONE", f"MAC MISMATCH (Prefix should be {job.mac_prefix})", current_mac
        return "DONE", "Found (Scan Only)", current_mac

    if not reachable:
        return "DONE", "OFFLINE (No Device Found)", "N/A"
    if not current_mac:
        if not job.allow_routed:
            return "DONE", "FAIL (ARP MAC not found)", "N/A"
        # A phone behind another gateway/static route has no ARP entry on this
        # PC; keep going over HTTP and validate the MAC shown by the phone.
        job.log("info", f"{ip}: no ARP entry (routed host); MAC will be read from the phone page")
    elif job.mac_prefix and not current_mac.startswith(job.mac_prefix):
        return "DONE", f"MAC MISMATCH (Prefix should be {job.mac_prefix})", current_mac

    if current_mac:
        job.locked_macs[ip] = current_mac

    for label, user, password in job.credentials:
        if job.stop_event.is_set():
            return "STOP", "Aborted", "N/A"
        context = None
        try:
            context = browser.new_context(
                http_credentials={"username": user, "password": password},
                ignore_https_errors=True,
            )
            page = context.new_page()
            response = page.goto(f"http://{ip}/index.htm", timeout=10000)
            if response is not None and response.status == 401:
                job.log("warn", f"{ip}: HTTP auth failed for {label} ({user or 'empty user'})")
                continue

            info, page_mac = _status_info(page, ip)
            effective_mac = current_mac or (page_mac if page_mac and page_mac != "N/A" else None)
            if not current_mac and effective_mac:
                job.log("info", f"{ip}: MAC from phone page: {effective_mac}")

            if job.mode == "scan_full":
                if (
                    not current_mac
                    and job.mac_prefix
                    and effective_mac
                    and not effective_mac.startswith(job.mac_prefix)
                ):
                    return "DONE", f"MAC MISMATCH (Prefix should be {job.mac_prefix})", effective_mac
                return (
                    "DONE",
                    f"Status: {info} | MAC: {effective_mac or 'N/A'}",
                    effective_mac or "N/A",
                )

            # Full provision: on a routed phone, validate the MAC from the index
            # page before writing anything, then keep using it for the result row.
            if (
                not current_mac
                and job.mac_prefix
                and effective_mac
                and not effective_mac.startswith(job.mac_prefix)
            ):
                return "DONE", f"MAC MISMATCH (Prefix should be {job.mac_prefix})", effective_mac
            if not effective_mac:
                job.log(
                    "warn",
                    f"{ip}: MAC unavailable (no ARP entry and phone page did not show one); continuing",
                )

            # A phone that was already provisioned by this job and has since
            # registered is finished; no need to send the form again.
            if info != "Unknown" and "Registered" in info and ip in job.provisioned:
                return "DONE", info, effective_mac or "N/A"

            page.goto(f"http://{ip}/auto_provision.htm", timeout=10000)
            page.fill('input[name="P237"]', job.server)
            page.fill('input[name="P1360"]', job.http_user)
            page.evaluate('document.querySelector(\'input[name="P1361"]\').removeAttribute("readonly")')
            page.fill('input[name="P1361"]', job.http_pass)
            page.click('input[value="SaveSet"]', force=True)
            page.wait_for_timeout(500)
            page.click('input[value="Autoprovision Now"]', force=True)
            job.provisioned.add(ip)
            return "RETRY", "Provision Sent -> Rebooting", effective_mac or "N/A"
        except Exception as exc:  # noqa: BLE001 - one bad phone must not stop the batch
            job.log("warn", f"{ip}: {label} attempt failed ({type(exc).__name__}: {exc})")
            continue
        finally:
            _close_quietly(context)

    return "RETRY", "Waiting Login / Auth Fail", current_mac or "N/A"


def _run_job(job: HtekJob) -> None:
    playwright_ctx = None
    browser = None
    try:
        if job.mode != "scan":
            if not browser_ready():
                raise RuntimeError(
                    "Playwright or a Chromium browser is not available on this host; "
                    "only the SCAN mode can run."
                )
            job.log("info", f"Launching headless browser: {BROWSER_PATH}")
            playwright_ctx = sync_playwright().start()
            browser = playwright_ctx.chromium.launch(headless=True, executable_path=BROWSER_PATH)
            job.log("ok", "Browser ready")

        pending = list(job.order)
        while pending and not job.stop_event.is_set():
            job.cycle += 1
            job.log("info", f"Cycle {job.cycle}: {len(pending)} IP(s) pending")
            for ip in list(pending):
                if job.stop_event.is_set():
                    break
                job.current_ip = ip
                job.set_phase(ip, "running")
                job.log("info", f"Scanning & working on {ip}")
                status, detail, mac = _process_ip(job, browser, ip)
                job.update_row(ip, mac, status, detail, "done" if status == "DONE" else "retry")
                job.log(
                    "ok" if status == "DONE" and not _is_bad_detail(detail) else "warn",
                    f"{ip}: {status} - {detail}",
                )
                if status == "DONE" and ip in pending:
                    pending.remove(ip)

            if not pending or job.stop_event.is_set():
                break
            if job.mode in ("scan", "scan_full"):
                break
            if job.retry_cycles and job.cycle >= job.retry_cycles:
                for ip in pending:
                    row = job.rows.get(ip)
                    job.update_row(
                        ip,
                        row.mac if row else "N/A",
                        "STOP",
                        f"Retry limit reached ({job.retry_cycles} cycles)",
                        "done",
                    )
                job.log("warn", f"Retry limit reached after {job.retry_cycles} cycles")
                break

            job.log("info", f"Cycle finished. Waiting {job.retry_delay}s before the next attempt...")
            if job.stop_event.wait(job.retry_delay):
                break
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator in the page
        job.error = f"{type(exc).__name__}: {exc}"
        job.log("err", f"Job failed: {job.error}")
        with job.lock:
            job.state = "error"
    finally:
        job.current_ip = ""
        _close_quietly(browser)
        if playwright_ctx is not None:
            try:
                playwright_ctx.stop()
            except Exception:
                pass
        with job.lock:
            if job.state != "error":
                job.state = "stopped" if job.stop_event.is_set() else "finished"
            job.finished_at = time.time()
        counts = job.counts()
        if job.state == "finished":
            job.log("ok", f"Job finished: {counts['ok']} success, {counts['fail']} failed")
        elif job.state == "stopped":
            job.log("warn", "Job stopped by the operator")


# --------------------------------------------------------------------------- manager
class HtekManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, HtekJob] = {}
        self._latest: Dict[str, str] = {}

    def start(self, owner: str, params: dict) -> HtekJob:
        with self._lock:
            current = self._jobs.get(self._latest.get(owner, ""))
            if current is not None and current.state == "running":
                raise JobBusyError("A task is already running. Stop it before starting another one.")

        targets, truncated = build_targets(
            str(params.get("ips") or ""),
            str(params.get("ipRange") or ""),
        )
        if not targets:
            raise ValueError(
                "No valid IPv4 target. Enter at least one address or an IP range such as 192.0.2.1-254."
            )

        mode = str(params.get("mode") or "provision")
        if mode not in {item["id"] for item in MODES}:
            raise ValueError(f"Unknown execution mode '{mode}'.")
        if mode != "scan" and not browser_ready():
            raise RuntimeError(
                "Playwright with a local Chrome/Edge is required for this mode. "
                "Install it with: pip install playwright   (no browser download is needed)."
            )
        if mode in ("provision", "scan_full") and not any(
            str(params.get(key) or "").strip() for key in ("auth1User", "auth2User")
        ):
            raise ValueError("At least one HTTP login account is required for this mode.")

        safe_params = dict(params)
        safe_params["mode"] = mode
        safe_params["_truncated"] = truncated
        job = HtekJob(owner, safe_params, targets)

        with self._lock:
            self._jobs[job.id] = job
            self._latest[owner] = job.id
            self._prune_locked(owner)

        job.log("info", f"Task accepted: {mode}, {len(targets)} target(s)")
        thread = threading.Thread(target=_run_job, args=(job,), name=f"htek-{job.id}", daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Optional[HtekJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_owned(self, job_id: str, owner: str) -> Optional[HtekJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.owner != owner:
                return None
            return job

    def latest(self, owner: str) -> Optional[HtekJob]:
        with self._lock:
            job = self._jobs.get(self._latest.get(owner, ""))
            return job

    def stop(self, job_id: str, owner: str) -> Optional[HtekJob]:
        job = self.get_owned(job_id, owner)
        if job is None:
            return None
        job.stop_event.set()
        job.log("warn", "Stop requested...")
        return job

    def _prune_locked(self, owner: str) -> None:
        owned = [(job_id, job) for job_id, job in self._jobs.items() if job.owner == owner]
        if len(owned) <= 25:
            return
        owned.sort(key=lambda item: item[1].created_at)
        for job_id, job in owned[: len(owned) - 25]:
            if job.state != "running":
                self._jobs.pop(job_id, None)


manager = HtekManager()


def info() -> dict:
    """Capabilities + safe defaults for the page."""
    return {
        "modes": MODES,
        "defaults": DEFAULTS,
        "capabilities": {
            "playwright": sync_playwright is not None,
            "browser": BROWSER_PATH is not None,
            "browserPath": BROWSER_PATH or "",
            "ready": browser_ready(),
            "platform": sys.platform,
            "ping": True,
            "arp": True,
            "maxTargets": MAX_TARGETS,
        },
        "hotkeyNote": (
            "Alt+1 / Alt+2 are configurable: click a shortcut key here and press a new "
            "combination. Shortcuts work while this page is focused and copy that account's "
            "credentials. A browser page cannot send keystrokes into other applications, so "
            "the desktop tool keeps its global hotkeys (it is untouched)."
        ),
    }
