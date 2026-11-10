# Deltapath Automation · Web Edition

A browser-based bulk provisioning tool for **Deltapath PBX** systems.
It is a rewrite of the original Tkinter desktop tool (`DP Auto API`) as a
**FastAPI backend proxy + plain HTML/JS frontend**, and it can run either

* as a **desktop app** (a native window via PyWebview — one double-click), or
* as a **web service** (Docker / Proxmox container, accessed from any browser).

All PBX traffic is proxied by the backend, so the browser never holds PBX
credentials and never talks to the PBX directly.

---

## Table of contents

1. [Features](#1-features)
2. [Architecture](#2-architecture)
3. [Requirements](#3-requirements)
4. [Install on a machine **without** Python](#4-install-on-a-machine-without-python)
5. [Install and run from source](#5-install-and-run-from-source)
6. [Running the app](#6-running-the-app)
7. [Configuration](#7-configuration)
8. [Docker / Proxmox deployment](#8-docker--proxmox-deployment)
9. [Development and tests](#9-development-and-tests)
10. [Project structure](#10-project-structure)
11. [Security notes](#11-security-notes)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Features

**Pipelines**

* **Standard mode** — the full 13-task pipeline, from Group → Number (Strip Digits),
  for provisioning a customer from scratch.
* **Complex mode** — shares the task order with Standard, plus exclusive option cards:
  Context suffixes, four Permission Group classes with a per-Class context picker,
  ACL groups, User Profile classes + recording, ACL User roles, Username/Email lists,
  and custom API payloads.
* Sequential server-side execution with **live log streaming (SSE)**, per-task status
  lights (grey / yellow / green / red), progress bar and stop button.

**Standalone pages**

| Page | What it does |
|---|---|
| Dashboard | Session info, PBX self-check, recent operations |
| Search & Delete | 20 object types, desktop-parity search then bulk delete |
| SIP Trunk Status | Trunks + online peers, filterable, auto-refresh |
| Name Split Tool | Split full names into First / Last (Excel-ready) |
| **Text to Speech** | Generate MP3 or WAV voice prompts with Microsoft Edge neural voices |
| **Htek Provisioning** | Drives the phone's web UI to apply credentials |
| Audit Log | Login / logout / pipeline / delete history, CSV export |
| Settings | Theme, zoom, session details |

**Other**

* Dark / Light / Auto theme, UI zoom (Ctrl + wheel, 0.5×–3.0×)
* Everything is stored server-side per session; the browser only keeps an opaque
  session cookie
* Optional desktop launcher with **global hotkeys** for Htek credential entry

---

## 2. Architecture

```
┌──────────────────────────────┐
│ Browser (HTML + JS, no build)│
│  HttpOnly cookie: dp_session │
└──────────────┬───────────────┘
               │  same-origin /api/*  (JSON + SSE)
┌──────────────▼───────────────┐
│ FastAPI backend              │
│  · session store (in memory) │
│  · PBX REST proxy            │
│  · pipeline engine           │
└──────────────┬───────────────┘
               │  HTTPS (self-signed cert, TLS relaxed)
┌──────────────▼───────────────┐
│ Deltapath PBX                │
│  /RESTful/index.php/...      │
└──────────────────────────────┘
```

A backend is required because a browser cannot:

* accept the PBX's self-signed certificate / legacy TLS settings,
* send the PBX's `PHPSESSID` cookie cross-site (CORS / SameSite),
* read responses from the PBX (no `Access-Control-Allow-Origin`).

---

## 3. Requirements

| Item | Version | Notes |
|---|---|---|
| Python | **3.10 – 3.14** | 3.12 or 3.13 recommended |
| pip | bundled with Python | |
| Microsoft Edge WebView2 Runtime | any | **Windows only**, needed by the desktop launcher window |
| A Deltapath PBX account | — | with REST API access enabled |

> The launcher window uses PyWebview, which on Windows relies on the
> **WebView2 Runtime**. It ships with Windows 10/11 by default. If the window
> does not open, install it from
> <https://developer.microsoft.com/microsoft-edge/webview2/>.

---

## 4. Install on a machine **without** Python

If Python is not installed yet, install it first.

### Windows

**Option A — Microsoft Store (simplest)**

1. Open **Microsoft Store** → search **Python 3.12** → **Install**.
2. Open a **new** PowerShell window and check:

   ```powershell
   python --version
   ```

**Option B — python.org installer**

1. Go to <https://www.python.org/downloads/windows/> and download
   *Windows installer (64-bit)* for Python 3.12 or newer.
2. Run the installer and **tick “Add python.exe to PATH”** at the bottom of the
   first screen (this is the step people forget).
3. Choose **Install Now**, then open a **new** PowerShell window and verify:

   ```powershell
   python --version
   pip --version
   ```

> If `python` is not recognised, close and reopen the terminal. On some systems
> the command is `py` instead of `python` — use `py --version` to check.

### macOS

```bash
# Homebrew (recommended)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12

python3 --version
```

Or download the macOS installer from <https://www.python.org/downloads/macos/>.

### Linux (Debian / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version
```

On Fedora / RHEL:

```bash
sudo dnf install -y python3 python3-pip
```

---

## 5. Install and run from source

### 5.1 Get the code

```bash
git clone <your-repository-url> "DP Auto Web App"
cd "DP Auto Web App"
```

Or download the ZIP from GitHub → **Code** → **Download ZIP** and extract it.

### 5.2 Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of
your system.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation script with an execution-policy error, run
> this once in the same window and activate again:
>
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

**Windows (cmd.exe)**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

After activation your prompt starts with `(.venv)`.

### 5.3 Install the dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` installs:

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn[standard]` | the web backend |
| `requests` | PBX REST client |
| `pywebview` | the native desktop window (`launcher.py`) |
| `edge-tts`, `miniaudio` | Text to Speech page (MP3 / WAV) |
| `playwright` | Htek Provisioning page |

> **Playwright note:** the project drives the Chrome/Edge already installed on
> the machine, so you do **not** need to download a bundled browser. Do **not**
> run `playwright install` — it is unnecessary and downloads hundreds of MB.

### 5.4 Verify the installation

```bash
python -c "import fastapi, uvicorn, requests; print('dependencies OK')"
```

---

## 6. Running the app

There are two ways to run it. **Most users want option A.**

### Option A — Desktop window (recommended)

```bash
python launcher.py
```

This starts the backend on `http://127.0.0.1:8080` (or the next free port) and
opens a native window. Closing the window stops the backend.

* The launcher writes `launcher.log` and `backend-launch.log` next to the script —
  check these first if the window does not appear.
* If port 8080 is busy, the launcher automatically picks 8081, 8082, …
* Startup timeout is 60 s by default; override with `DP_START_TIMEOUT`.

### Option B — Web service (browser only)

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
```

Then open <http://127.0.0.1:8080>.

Use `--host 0.0.0.0` to allow other machines on the network to connect.

### Option C — one-command dev helper (Windows / Linux)

```powershell
.\scripts\dev.ps1              # real PBX
.\scripts\dev.ps1 -Mock        # UI preview with a fake PBX, no PBX needed
.\scripts\dev.ps1 -Port 8099   # different port
```

```bash
./scripts/dev.sh               # Linux / macOS
./scripts/dev.sh --mock
```

`-Mock` / `--mock` starts a **stateful fake PBX** on port **8098**, so you can
click through the whole UI without a real PBX.

### First login

1. Open the app.
2. Enter the PBX address, username and password
   (for example `suc.example.com` — the scheme is added automatically).
3. Leave **Ignore certificate validation** on if the PBX uses a self-signed
   certificate (common).
4. Press **Sign in and start session**.

---

## 7. Configuration

Everything is optional and read from environment variables prefixed `DP_`.
Copy `.env.example` to `.env` to keep a local set (`.env` is git-ignored).

| Variable | Default | Meaning |
|---|---|---|
| `DP_PORT` | `8080` | port the backend listens on |
| `DP_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `DP_SESSION_IDLE_MINUTES` | `60` | idle timeout |
| `DP_SESSION_ABSOLUTE_MINUTES` | `480` | absolute session lifetime |
| `DP_TLS_VERIFY` | `0` | `1` = verify the PBX certificate |
| `DP_DEFAULT_BASE_URL` | *(empty)* | pre-filled PBX address on the login page |
| `DP_DELETE_PASSWORD` | `871211My` | second password required by delete operations |
| `DP_COOKIE_SECURE` | `0` | set `1` when served over HTTPS only |
| `DP_TRUST_PROXY_HEADERS` | `0` | set `1` behind Nginx / Cloudflare |
| `DP_AUDIT_FILE` | *(empty)* | path to persist the audit log as JSONL |
| `DP_START_TIMEOUT` | `60` | launcher backend-start timeout (seconds) |

PowerShell example:

```powershell
$env:DP_PORT = "8090"
python launcher.py
```

---

## 8. Docker / Proxmox deployment

Build and run with Docker:

```bash
docker build -t dp-auto-web .
docker run -d --name dp-auto-web -p 8080:8080 --env-file .env dp-auto-web
```

Docker Compose:

```bash
cp .env.example .env
docker compose up -d
```

Proxmox (OCI-as-LXC) is documented in
[`deploy/proxmox-oci-lxc.md`](deploy/proxmox-oci-lxc.md).

---

## 9. Development and tests

The end-to-end suites drive a real Chrome through CDP against the fake PBX.

```bash
# 1) start the fake PBX (keep this running)
python scripts/dev_preview.py          # http://127.0.0.1:8098

# 2) run every suite (Windows)
.\scripts\run-e2e.ps1
```

Run a single suite:

```bash
node scripts/e2e_pipeline.mjs http://127.0.0.1:8098 9333 complex
node scripts/e2e_tts.mjs      http://127.0.0.1:8098 9333
```

Backend-only pipeline test:

```bash
python scripts/test_pipeline.py --auto-login --mode complex
```

Suites: `login`, `standard`, `complex`, `pgctx`, `tts`, `ops`.

---

## 10. Project structure

```
DP Auto Web App/
├── launcher.py              # desktop window (PyWebview) + backend supervisor
├── launcher_hotkeys.py      # global hotkeys for Htek credential entry
├── requirements.txt
├── Dockerfile
├── .env.example
├── backend/
│   └── app/
│       ├── main.py          # FastAPI app, static frontend mount, CSP
│       ├── config.py        # DP_* settings
│       ├── security.py      # session cookie, login throttle
│       ├── sessions.py      # in-memory PBX sessions
│       ├── audit.py         # audit log store
│       ├── api/             # auth, system, pipeline, ops, audit, tts, htek
│       ├── pbx/
│       │   ├── rest_client.py   # PBX REST client (desktop port)
│       │   ├── engine.py        # pipeline engine + task definitions
│       │   ├── ext_parser.py    # extension range parsing
│       │   └── tasks/           # standard/ + complex/ task modules
│       └── htek/            # Htek provisioning engine
├── frontend/                # plain HTML/CSS/JS, no build step
│   ├── index.html
│   ├── css/
│   └── js/
│       ├── app.js, router.js, api.js, store.js, ui.js, theme.js, zoom.js
│       └── views/           # one file per page
├── scripts/                 # dev server, fake PBX, e2e suites, deploy helpers
├── deploy/                  # Proxmox OCI-LXC scripts and docs
└── docs/images/             # screenshots used by this README
```

---

## 11. Security notes

* **PBX credentials never reach the browser.** They are sent once to
  `/api/auth/login` and kept only in the server process memory.
* The browser holds a single opaque `HttpOnly` session cookie.
* Login attempts are throttled per source IP (5 failures / 5 minutes by default).
* Delete operations need a second password, validated **server-side**
  (`DP_DELETE_PASSWORD`).
* Passwords are never written to the audit log.
* The API sets a strict CSP, `X-Frame-Options: DENY`, `nosniff` and
  `Cache-Control: no-store`.

**Do not commit** `.env`, `config.json`, `last_session.json`, logs, or any file
containing real PBX credentials — `.gitignore` already excludes them.

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| `python` / `pip` is not recognised | Python is not on `PATH`. Reinstall and tick *Add python.exe to PATH*, or use `py` instead of `python`. |
| PowerShell refuses to activate `.venv` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| `ModuleNotFoundError: fastapi` | The venv is not activated, or dependencies were not installed. Activate `.venv` and run `pip install -r requirements.txt`. |
| The desktop window does not open | Check `launcher.log` and `backend-launch.log`. Install the **WebView2 Runtime** if missing. |
| “backend did not become ready” | A stale process may hold the port. The launcher auto-picks the next free port; check `backend-launch.log` for the real error. |
| Login fails with a TLS error | Set `DP_TLS_VERIFY=0` and keep *Ignore certificate validation* checked. |
| Port 8080 already in use | Use `--port 8090`, or set `DP_PORT`, or just use `launcher.py` which picks a free port. |
| Text to Speech fails | The container/PC needs outbound HTTPS access to `speech.platform.bing.com`. |
| Htek provisioning cannot find a browser | Install Chrome or Edge; the tool uses the already-installed browser. |

---

## Relationship to the desktop version

This project is the browser rewrite of **DP Auto API** (Tkinter). The task
modules (`backend/app/pbx/tasks/**`) are direct ports of the desktop
`modules/**` and `complex_modules/**`, keeping the same REST endpoints and
payloads. The desktop tool remains the reference implementation.
