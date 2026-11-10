"""Small utility to run commands / scripts on a Proxmox node (paramiko, password login).

Credentials are read from environment variables only, never written to disk:

    $env:PVE_HOST='192.0.2.10'; $env:PVE_USER='root'; $env:PVE_PASS='***'

Usage:

    # Run commands directly (one argument each)
    python scripts/pve_ssh.py "pveversion" "pct list"

    # Run a local script: SFTP upload to /tmp, then execute with bash (recommended, avoids escaping issues)
    python scripts/pve_ssh.py --script deploy/recon.sh
"""

from __future__ import annotations

import os
import posixpath
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("PVE_HOST", "")
USER = os.environ.get("PVE_USER", "root")
PASSWORD = os.environ.get("PVE_PASS", "")
PORT = int(os.environ.get("PVE_PORT", "22"))
TIMEOUT = int(os.environ.get("PVE_TIMEOUT", "300"))


def connect() -> paramiko.SSHClient:
    if not HOST or not PASSWORD:
        raise SystemExit("Set the environment variables PVE_HOST / PVE_USER / PVE_PASS first")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=HOST,
        port=PORT,
        username=USER,
        password=PASSWORD,
        timeout=20,
        banner_timeout=30,
        auth_timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = TIMEOUT) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def upload(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(local), remote)
    finally:
        sftp.close()


def run_script(client: paramiko.SSHClient, path: Path) -> int:
    remote = posixpath.join("/tmp", f"dsh-{path.name}")
    upload(client, path, remote)
    print(f"$ bash {remote}   (from {path})")
    code, out, err = run(client, f"bash {remote}")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(f"[stderr] {err.rstrip()}")
    print(f"[exit {code}]\n")
    return code


def main() -> int:
    # Windows console defaults to GBK; emoji / BOM in remote output raise UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    args = sys.argv[1:]
    if not args:
        args = ["hostname", "pveversion"]

    client = connect()
    worst = 0
    try:
        if args[0] == "--put":
            # --put <local file> <remote path>
            local, remote = Path(args[1]), args[2]
            upload(client, local, remote)
            code, out, err = run(client, f"ls -l {remote}")
            print(f"Uploaded {local} -> {remote}")
            print(out.strip() or err.strip())
            return code

        if args[0] == "--script":
            for name in args[1:]:
                worst = max(worst, run_script(client, Path(name)))
        else:
            for command in args:
                print(f"$ {command}")
                code, out, err = run(client, command)
                if out.strip():
                    print(out.rstrip())
                if err.strip():
                    print(f"[stderr] {err.rstrip()}")
                if code != 0:
                    print(f"[exit {code}]")
                print()
                worst = max(worst, code)
    finally:
        client.close()
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
