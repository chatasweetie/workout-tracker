"""Database setup for the workout tracker."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "workout.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('stretch','strength')),
  focus TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  dose TEXT,
  image_url TEXT,
  equipment TEXT,
  on_floor INTEGER NOT NULL DEFAULT 0,
  seconds INTEGER,
  per_side INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (type, name)
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  day_type TEXT NOT NULL CHECK (day_type IN ('full','flex')),
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS session_items (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  position INTEGER NOT NULL,
  block TEXT NOT NULL,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','done','skipped')),
  note TEXT,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS strength_sets (
  id INTEGER PRIMARY KEY,
  session_item_id INTEGER NOT NULL REFERENCES session_items(id),
  set_number INTEGER NOT NULL,
  reps INTEGER,
  weight REAL
);
"""


def get_connection(db_path=DB_PATH):
    """Open the database. Rows can be read like dicts: row["name"]."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores foreign keys unless asked
    return conn


def init_db(conn):
    """Create the tables if they do not exist yet. Safe to run every time."""
    conn.executescript(SCHEMA)
    conn.commit()