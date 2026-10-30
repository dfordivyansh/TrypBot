"""Safe online backup of db.sqlite3 (works while the app is running).

Usage: python backup_db.py <db_path> <backup_dir> [keep_days]
Writes <backup_dir>/db-YYYY-MM-DD_HHMM.sqlite3, verifies it, deletes copies older than keep_days.
"""
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

db_path, backup_dir = Path(sys.argv[1]), Path(sys.argv[2])
keep_days = int(sys.argv[3]) if len(sys.argv) > 3 else 14
backup_dir.mkdir(parents=True, exist_ok=True)

target = backup_dir / f"db-{datetime.now():%Y-%m-%d_%H%M}.sqlite3"
src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
dst = sqlite3.connect(target)
try:
    src.backup(dst)
except Exception as exc:
    # e.g. disk full: don't leave a half-written copy taking up space.
    dst.close()
    src.close()
    target.unlink(missing_ok=True)
    sys.exit(f"Backup failed: {exc}")
src.close()

result = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close()
if result != "ok":
    target.rename(target.with_suffix(".CORRUPT"))
    sys.exit(f"Backup integrity check failed: {result}")

cutoff = time.time() - keep_days * 86400
for old in [*backup_dir.glob("db-*.sqlite3"), *backup_dir.glob("db-*.CORRUPT")]:
    if old.stat().st_mtime < cutoff:
        old.unlink()
print(f"Backup OK: {target}")
