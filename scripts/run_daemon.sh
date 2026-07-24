#!/usr/bin/env bash
# Launch meridiand. Called by com.meridian.daemon.plist (launchd, KeepAlive).
# Path-agnostic: MERIDIAN_HOME defaults to the repo this script lives in.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_HOME="${MERIDIAN_HOME:-$HERE}"
cd "$MERIDIAN_HOME"

# Prefer uv (the locked toolchain, §4); fall back to a local venv.
if command -v uv >/dev/null 2>&1; then
  exec uv run meridiand
elif [ -x ".venv/bin/meridiand" ]; then
  exec .venv/bin/meridiand
elif [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m meridian.app
else
  exec python3 -m meridian.app
fi
