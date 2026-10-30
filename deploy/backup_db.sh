#!/bin/sh
# Safe online SQLite backup (works while the app is running). Keeps 14 days.
# crontab -e:  0 3 * * * /home/ubuntu/app/deploy/backup_db.sh
set -e
mkdir -p /home/ubuntu/backups
sqlite3 /home/ubuntu/app/db.sqlite3 ".backup '/home/ubuntu/backups/db-$(date +%F).sqlite3'"
find /home/ubuntu/backups -name 'db-*.sqlite3' -mtime +14 -delete
