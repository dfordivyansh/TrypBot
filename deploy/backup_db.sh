#!/bin/sh
# Daily SQLite backup, safe while the app runs (SQLite backup API), gzipped.
# Keeps the newest 3 and skips the run when the disk is low: on 12 Nov 2026
# uncleaned backups filled the disk and the CRM failed with "disk I/O error".
#
# crontab -e:  30 3 * * * sh /home/ubuntu/app/deploy/backup_db.sh >> /home/ubuntu/backups/backup.log 2>&1
set -e
APP=/home/ubuntu/app
DIR=/home/ubuntu/backups
KEEP=3
mkdir -p "$DIR"

# Free space must cover the database twice (raw copy + gzip) plus 500 MB spare.
DB_KB=$(du -k "$APP/db.sqlite3" | cut -f1)
FREE_KB=$(df --output=avail -k "$DIR" | tail -1)
if [ "$FREE_KB" -lt $((DB_KB * 2 + 512000)) ]; then
    echo "$(date '+%F %T') SKIPPED: only $((FREE_KB / 1024)) MB free"
    exit 1
fi

OUT="$DIR/db-daily-$(date +%F).sqlite3"
"$APP/.venv/bin/python" -c "import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
    "$APP/db.sqlite3" "$OUT"
gzip -f "$OUT"

# Only the newest $KEEP daily backups stay.
ls -t "$DIR"/db-daily-*.sqlite3.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date '+%F %T') OK: $(du -h "$OUT.gz" | cut -f1) $OUT.gz"
