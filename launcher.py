"""DP Auto Web — local desktop launcher (PyWebview).

Starts the FastAPI backend (uvicorn) as a child process, waits for the health
endpoint to be ready, then opens a native PyWebview window that loads the
browser UI. Closing the window shuts the backend down.

Run:
    python launcher.py

Diagnostics
-----------
The previous version discarded the backend's stdout/stderr, so a failed start
only produced "backend did not become ready in time" after 30 s. That is why a
stale process holding port 8080 (or a slow cold start) looked like "the app does
not open". This version:

* writes the backend console to ``backend-launch.log``;
* probes the health endpoint with ``http.client`` (no proxy surprises);
* if the configured port is occupied by a non-health process, picks the next
  free port automatically instead of timing out;
* waits up to ``DP_START_TIMEOUT`` seconds (default 60), shows a native error
  box with the reason, and still shuts the child down cleanly.
"""

import http.client
import os
import shutil
import socket
import subprocess
import sys
import time

import webview

from launcher_hotkeys import GlobalHtekHotkeys

HOST = "127.0.0.1"
START_PORT = int(os.environ.get("DP_PORT", "8080"))
START_TIMEOUT = int(os.environ.get("DP_START_TIMEOUT", "60"))

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOG = os.path.join(_HERE, "launcher.log")
_BACKEND_LOG = os.path.join(_HERE, "backend-launch.log")
_proc = None
_port = START_PORT
_base = f"http://{HOST}:{START_PORT}"


def _log(msg):
    with open(_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def _health_ok(port):
    conn = None
    try:
        conn = http.client.HTTPConnection(HOST, port, timeout=2)
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        response.read()
        return response.status == 200
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _port_free(port):
    # On Windows SO_REUSEADDR lets a second socket bind a port that is already
    # listening (the opposite of POSIX), so it must NOT be used for a free-port
    # probe: it reported a hung server as free and uvicorn then died with
    # WinError 10048. Probe with a real connect first, then a plain bind.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect((HOST, port))
            return False  # something is listening (even if it never answers)
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def _pick_port(start):
    """Return (port, already_running).

    A healthy server on the requested port is reused (a second window attaches to
    it). Otherwise walk upward until a free port is found, so a leftover process
    that no longer answers /api/health cannot make the launcher fail.
    """
    for port in range(start, start + 20):
        if _health_ok(port):
            return port, True
        if _port_free(port):
            return port, False
    return start, False


def _wait_ready(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health_ok(port):
            return True
        if _proc is not None and _proc.poll() is not None:
            return False  # backend exited; no point waiting
        time.sleep(0.3)
    return False


def _tail(path, lines=40):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:]).strip()
    except Exception:
        return ""


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _has_backend_deps(python):
    """True when this interpreter can import the backend runtime."""
    try:
        probe = subprocess.run(
            [python, "-c", "import uvicorn, fastapi"],
            capture_output=True,
            timeout=20,
            creationflags=_no_window(),
        )
        return probe.returncode == 0
    except Exception:
        return False


def _candidate_pythons():
    """Interpreters to try for the backend, in order of preference.

    The launcher window itself may be started by a Python that only has
    pywebview (for example a small venv, or a file association). The backend
    needs uvicorn/fastapi, so never assume sys.executable has them.
    """
    seen = set()

    def add(path):
        if not path:
            return None
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return None
        key = os.path.normcase(path)
        if key in seen:
            return None
        seen.add(key)
        return path

    for path in (
        os.environ.get("DP_PYTHON"),
        sys.executable,
        os.path.join(_HERE, ".venv", "Scripts", "python.exe"),
        os.path.join(os.path.dirname(_HERE), "venv", "Scripts", "python.exe"),
        os.path.join(_HERE, "venv", "Scripts", "python.exe"),
        shutil.which("python"),
        shutil.which("python3"),
    ):
        resolved = add(path)
        if resolved:
            yield resolved


def _backend_python():
    for python in _candidate_pythons():
        if _has_backend_deps(python):
            _log(f"backend interpreter: {python}")
            return python
    return None


def _fatal(message):
    _log(message)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "DP Auto Web - launcher", 0x10)
    except Exception:
        pass


class LauncherApi:
    """Small JS bridge used by the Htek page for Windows-wide shortcuts."""

    def __init__(self, hotkeys: GlobalHtekHotkeys) -> None:
        self._hotkeys = hotkeys

    def set_htek_hotkeys(self, entries):
        """Receive the page's current combos + credentials and register them."""
        return self._hotkeys.update(entries)

    def htek_hotkey_status(self):
        return self._hotkeys.status()


def main():
    global _proc, _port, _base

    _log("launcher start")
    _port, already_running = _pick_port(START_PORT)
    _base = f"http://{HOST}:{_port}"

    if already_running:
        _log(f"attached to a running backend at {_base}")
    else:
        if _port != START_PORT:
            _log(f"port {START_PORT} is busy and not answering /api/health; using {_port} instead")

        backend_python = _backend_python()
        if not backend_python:
            requirements = os.path.join(_HERE, "requirements.txt")
            _fatal(
                "The backend Python is missing its dependencies (uvicorn/fastapi).\n\n"
                f"Launcher Python:\n{sys.executable}\n\n"
                "Install them once with:\n"
                f'"{sys.executable}" -m pip install -r "{requirements}"\n\n'
                "Or point DP_PYTHON at a Python that already has them."
            )
            sys.exit(1)

        cmd = [
            backend_python,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            HOST,
            "--port",
            str(_port),
            "--log-level",
            "info",
        ]
        backend_log = open(_BACKEND_LOG, "a", encoding="utf-8")
        backend_log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting on port {_port} ===\n")
        backend_log.flush()
        _proc = subprocess.Popen(
            cmd,
            cwd=_HERE,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        backend_log.close()
        _log(f"backend starting (pid {_proc.pid}) on {_base}")

        if not _wait_ready(_port, START_TIMEOUT):
            exit_code = _proc.poll()
            detail = _tail(_BACKEND_LOG)
            if _proc and exit_code is None:
                try:
                    _proc.terminate()
                except Exception:
                    pass
            reason = (
                f"The backend did not become ready on {_base} within {START_TIMEOUT}s."
                if exit_code is None
                else f"The backend exited with code {exit_code} before becoming ready."
            )
            _fatal(
                f"{reason}\n\nSee:\n{_BACKEND_LOG}\n\nLast output:\n"
                f"{detail[-1800:] if detail else '(no output captured)'}"
            )
            sys.exit(1)

    _log(f"backend ready at {_base}")

    hotkeys = GlobalHtekHotkeys(log=_log)
    api = LauncherApi(hotkeys)
    window = webview.create_window(
        "DP Auto Web - Local",
        _base,
        width=1280,
        height=820,
        min_size=(960, 640),
        js_api=api,
    )
    if hotkeys.supported():
        _log("global Htek shortcuts: ready (registered when the page loads)")
    else:
        _log("global Htek shortcuts: unavailable on this host or already owned")
    try:
        webview.start()
    except Exception as e:
        _log(f"webview error: {e}")
        _fatal(f"The window could not be opened.\n\n{type(e).__name__}: {e}")
        raise
    finally:
        hotkeys.stop()
        _shutdown()


def _shutdown():
    global _proc
    _log("shutting down backend")
    if _proc is not None:
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(_proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                _log(f"taskkill error: {e}")
        else:
            try:
                _proc.terminate()
            except Exception as e:
                _log(f"terminate error: {e}")
        _proc = None


if __name__ == "__main__":
    main()
