#!/usr/bin/env bash
# Watchdog (PLAN.md §3). Runs every 5 min via com.meridian.watchdog.plist.
# curls /api/health; on 3 consecutive failures fires a P0 via the standalone notifier
# CLI path (works even when the daemon is down). State persists in data/.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_HOME="${MERIDIAN_HOME:-$HERE}"
cd "$MERIDIAN_HOME"

PORT="${MERIDIAN_PORT:-8788}"
STATE="$MERIDIAN_HOME/data/.watchdog_fails"
THRESHOLD=3

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://localhost:${PORT}/api/health" || echo 000)"

notify() {
  if command -v uv >/dev/null 2>&1; then
    uv run meridian-notify "$1" -p P0 --title "Meridian watchdog" --path /system --force
  elif [ -x ".venv/bin/python" ]; then
    .venv/bin/python -m meridian.notify "$1" -p P0 --title "Meridian watchdog" --path /system --force
  else
    python3 -m meridian.notify "$1" -p P0 --title "Meridian watchdog" --path /system --force
  fi
}

if [ "$code" = "200" ]; then
  echo 0 > "$STATE"
  exit 0
fi

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
echo "watchdog: health HTTP $code (consecutive failures: $fails)"

if [ "$fails" -ge "$THRESHOLD" ]; then
  notify "meridiand unreachable (HTTP $code) for ${fails} checks — is the daemon alive?"
  echo 0 > "$STATE"   # reset so we don't spam every 5 min; re-fires after 3 more
fi
