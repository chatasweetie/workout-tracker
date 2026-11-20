"""Create a verified SQLite snapshot. Run with: python backup.py"""
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Lock

from db import DB_PATH


BACKUP_DIR = Path(__file__).parent / "backups"
_backup_lock = Lock()


def backup_database(db_path=DB_PATH, backup_dir=BACKUP_DIR):
    """Back up committed data without modifying the source or older backups."""
    if not str(backup_dir).strip():
        raise ValueError("WORKOUT_BACKUP_DIR must not be empty.")
    source_path = Path(db_path).expanduser().resolve()
    destination_dir = Path(backup_dir).expanduser().resolve()

    with closing(sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)) as source:
        destination_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with tempfile.NamedTemporaryFile(
            prefix=f"workout-{timestamp}-",
            suffix=".db",
            dir=destination_dir,
            delete=False,
        ) as file:
            destination_path = Path(file.name)

        try:
            with closing(sqlite3.connect(destination_path)) as destination:
                source.backup(destination)
                result = destination.execute("PRAGMA integrity_check").fetchall()
                if result != [("ok",)]:
                    raise sqlite3.DatabaseError(
                        f"Backup integrity check failed: {result}"
                    )
        except (OSError, sqlite3.Error):
            destination_path.unlink(missing_ok=True)
            raise

    return destination_path


def backup_if_due(db_path=DB_PATH, backup_dir=BACKUP_DIR):
    """Create a snapshot unless today's backup already exists on disk."""
    if not str(backup_dir).strip():
        raise ValueError("WORKOUT_BACKUP_DIR must not be empty.")
    destination_dir = Path(backup_dir).expanduser().resolve()
    pattern = f"workout-{datetime.now():%Y%m%d}-*.db"
    with _backup_lock:
        if any(path.is_file() for path in destination_dir.glob(pattern)):
            return None
        return backup_database(db_path, destination_dir)


def main():
    backup_dir = os.environ.get("WORKOUT_BACKUP_DIR", str(BACKUP_DIR))
    try:
        path = backup_database(backup_dir=backup_dir)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1

    print(f"Backup created and integrity checked: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
