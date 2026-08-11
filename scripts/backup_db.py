"""Daily SQLite backup for the bot's database.

Copies the live DB to backups/db_<date>.sqlite using sqlite3's online
backup API — safe even while the bot process has the database open for
writes, unlike a plain file copy, which could land mid-transaction and
produce a corrupt backup. After each run, only the most recent KEEP_COUNT
dated copies are kept; older ones are deleted.

Meant to run once a day from cron — see DEPLOYMENT.md for the crontab
line. Deliberately doesn't import config.py (which requires BOT_TOKEN and
ANTHROPIC_API_KEY to be set): a DB backup has nothing to do with Telegram
or Claude credentials, so it reads DB_PATH from .env directly instead.

Usage: python scripts/backup_db.py [db_path] [backup_dir]
Both are optional: db_path defaults to $DB_PATH (same variable the bot
itself reads) or ./bot.db, backup_dir defaults to ./backups.
"""
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEEP_COUNT = 7

load_dotenv(PROJECT_ROOT / ".env")


def backup(db_path: Path, backup_dir: Path) -> Path:
    if not db_path.is_file():
        raise SystemExit(f"backup_db.py: database not found at {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"db_{date.today().isoformat()}.sqlite"

    source = sqlite3.connect(str(db_path))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            source.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source.close()

    return dest


def rotate(backup_dir: Path, keep: int = KEEP_COUNT) -> list[Path]:
    """Keeps only the `keep` most recent dated backups (sorted by the
    date in the filename, which sorts correctly as plain text since it's
    ISO YYYY-MM-DD) and deletes the rest.
    """
    existing = sorted(backup_dir.glob("db_*.sqlite"))
    to_delete = existing[:-keep] if len(existing) > keep else []
    for f in to_delete:
        f.unlink()
    return to_delete


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.getenv("DB_PATH", PROJECT_ROOT / "bot.db"))
    backup_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / "backups"

    dest = backup(db_path, backup_dir)
    print(f"backup_db.py: wrote {dest}")

    for removed in rotate(backup_dir):
        print(f"backup_db.py: removed old backup {removed}")


if __name__ == "__main__":
    main()
