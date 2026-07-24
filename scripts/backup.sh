#!/usr/bin/env bash
# Nightly backup (PLAN.md §3). sqlite3 .backup + Parquet rsync to a second location.
# Retention: 14 dailies, 8 weeklies. Called by com.meridian.backup.plist at 02:30.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_HOME="${MERIDIAN_HOME:-$HERE}"
cd "$MERIDIAN_HOME"

DEST="${MERIDIAN_BACKUP_DIR:-$MERIDIAN_HOME/data/backups}"
STAMP="$(date +%Y-%m-%d)"
DOW="$(date +%u)"   # 1=Mon..7=Sun
mkdir -p "$DEST/daily" "$DEST/weekly"

DB="$MERIDIAN_HOME/data/meridian.db"
if [ -f "$DB" ]; then
  # online, consistent backup — safe while the daemon holds the WAL
  sqlite3 "$DB" ".backup '$DEST/daily/meridian-$STAMP.db'"
  gzip -f "$DEST/daily/meridian-$STAMP.db"
fi

# Parquet mirror (delta)
rsync -a --delete "$MERIDIAN_HOME/data/parquet/" "$DEST/parquet/" 2>/dev/null || \
  cp -R "$MERIDIAN_HOME/data/parquet/." "$DEST/parquet/" 2>/dev/null || true

# Sunday snapshot -> weekly
if [ "$DOW" = "7" ] && [ -f "$DEST/daily/meridian-$STAMP.db.gz" ]; then
  cp "$DEST/daily/meridian-$STAMP.db.gz" "$DEST/weekly/meridian-$STAMP.db.gz"
fi

# retention: keep 14 dailies, 8 weeklies
ls -1t "$DEST/daily"/meridian-*.db.gz 2>/dev/null  | tail -n +15 | xargs -r rm -f
ls -1t "$DEST/weekly"/meridian-*.db.gz 2>/dev/null | tail -n +9  | xargs -r rm -f
echo "backup complete: $DEST/daily/meridian-$STAMP.db.gz"
