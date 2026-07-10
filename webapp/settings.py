"""Admin-editable solver settings stored in SQLite."""

import json

from schedulebuilder.pgy4.config import BALANCE_WEIGHTS

BALANCE_WEIGHTS_KEY = "balance_weights"
CATEGORY_ORDER = ("Weekend", "Morning", "Swing", "Night", "MGH", "BWH", "Pedi", "FT")


def default_balance_weights():
    return dict(BALANCE_WEIGHTS)


def load_balance_weights(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (BALANCE_WEIGHTS_KEY,)
    ).fetchone()
    if row is None:
        return default_balance_weights()
    stored = json.loads(row["value"])
    weights = default_balance_weights()
    weights.update({k: int(v) for k, v in stored.items() if k in weights})
    return weights


def save_balance_weights(conn, weights):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    cleaned = {k: int(weights[k]) for k in CATEGORY_ORDER}
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (BALANCE_WEIGHTS_KEY, json.dumps(cleaned)),
    )
    conn.commit()
