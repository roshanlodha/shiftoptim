"""SQLite connection helpers. WAL mode + foreign keys are enabled on every
connection, since SQLite's WAL setting is persistent on the file but
foreign_keys is a per-connection pragma."""

import os
import sqlite3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "data", "shiftoptim.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def get_db(db_path=None):
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if "test_" in os.path.basename(db_path):
        conn.execute("PRAGMA journal_mode=DELETE")
    else:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    # Auto-migration for existing DBs missing preference column
    user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "preference" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN preference TEXT NOT NULL DEFAULT 'frequent'")
    conn.commit()
