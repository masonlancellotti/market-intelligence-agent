#!/usr/bin/env bash
# Install/refresh the three MERIDIAN launchd agents on the Mac Mini (PLAN.md §3).
# Templates __MERIDIAN_HOME__ / __HOME__ in the plists, then bootstraps them.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_HOME="${MERIDIAN_HOME:-$HERE}"

AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/meridian"
mkdir -p "$AGENTS" "$LOGS"

UID_NUM="$(id -u)"
for label in daemon watchdog backup; do
  src="$MERIDIAN_HOME/config/launchd/com.meridian.$label.plist"
  dst="$AGENTS/com.meridian.$label.plist"
  sed -e "s#__MERIDIAN_HOME__#$MERIDIAN_HOME#g" -e "s#__HOME__#$HOME#g" "$src" > "$dst"
  echo "installed $dst"
  # reload
  launchctl bootout "gui/$UID_NUM/com.meridian.$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$dst"
  launchctl enable "gui/$UID_NUM/com.meridian.$label"
done

echo
echo "Loaded agents:"
launchctl list | grep meridian || true
echo
echo "Tail logs:  tail -f $LOGS/daemon.err.log"
echo "Kickstart:  launchctl kickstart -k gui/$UID_NUM/com.meridian.daemon"
