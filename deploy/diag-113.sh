#!/usr/bin/env bash
# Diagnose why CT 113 will not start: run the app inside the rootfs to surface the real error.
# Run on the node only, read-only (unmount right after mounting).
set -uo pipefail

VMID=113
ROOT=/var/lib/lxc/$VMID/rootfs
PY=/usr/local/bin/python

# `pct mount` writes `lock: mounted` into the CT config. If this script is
# interrupted (Ctrl-C, timeout, ssh drop), the unmount at the bottom never runs and
# the lock survives -- after which every vzdump fails with "CT is locked (mounted)".
# Unmount on ANY exit path so the lock cannot outlive this script.
_cleaned=0
cleanup() {
  [ "$_cleaned" = "1" ] && return
  _cleaned=1
  pct unmount "$VMID" >/dev/null 2>&1 && echo "    unmounted" || echo "    [x] unmount failed"
}
trap cleanup EXIT INT TERM

echo "==> Mount rootfs"
pct mount "$VMID" >/dev/null 2>&1 && echo "    mounted" || echo "    [x] mount failed"

echo
echo "==> App directory"
ls -l "$ROOT/srv/app" 2>&1 | head -8

echo
echo "==> python version (inside chroot)"
chroot "$ROOT" /bin/sh -c 'cd /srv/app && PYTHONDONTWRITEBYTECODE=1 '"$PY"' -c "import sys; print(sys.version)"' 2>&1 | tail -5

echo
echo "==> Import the app directly (key: look for Python exceptions)"
chroot "$ROOT" /bin/sh -c 'cd /srv/app && PYTHONDONTWRITEBYTECODE=1 '"$PY"' -c "import backend.app.main as m; print(\"IMPORT_OK\", m.app.title)"' 2>&1 | tail -40

echo
echo "==> Start uvicorn in the foreground for 5 seconds"
chroot "$ROOT" /bin/sh -c 'cd /srv/app && PYTHONDONTWRITEBYTECODE=1 timeout 5 '"$PY"' -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8081' 2>&1 | tail -25

echo
echo "==> Config syntax check (file by file)"
chroot "$ROOT" /bin/sh -c 'cd /srv/app && for f in backend/app/config.py backend/app/__init__.py backend/app/api/ops.py; do PYTHONDONTWRITEBYTECODE=1 '"$PY"' -c "import ast,sys; ast.parse(open(sys.argv[1],encoding=\"utf-8\").read()); print(\"OK\", sys.argv[1])" "$f" 2>&1 | tail -3; done' 2>&1 | tail -20

echo
echo "==> Unmount"
pct unmount "$VMID" >/dev/null 2>&1 && echo "    unmounted" || echo "    [x] unmount failed"
trap - EXIT INT TERM
