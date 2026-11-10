#!/usr/bin/env bash
# Local dev: create venv, install deps, start the service (Linux / macOS)
#
#   ./scripts/dev.sh              # Normal start (real PBX)
#   ./scripts/dev.sh --mock       # Start with a fake PBX, UI preview only
#   PORT=8099 ./scripts/dev.sh    # Use a different port
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8080}"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "==> Creating .venv"
  python3 -m venv "$ROOT/.venv"
  "$PY" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements.txt"
fi

if [ "${1:-}" = "--mock" ]; then
  echo "==> Starting UI preview (fake PBX, http://127.0.0.1:8098)"
  exec "$PY" "$ROOT/scripts/dev_preview.py"
fi

echo "==> http://127.0.0.1:${PORT}"
exec "$PY" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT" --reload
