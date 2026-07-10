"""Assert-based smoke test: seed a temp DB, verify roster derivation matches
config.ini, history aggregation matches history.json, and role gating works.
Run with: python webapp/tests/test_app.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from schedulebuilder.pgy4.inputs import load_block as ini_load_block
from schedulebuilder.pgy4.inputs import load_timeoff as ini_load_timeoff
from webapp import bridge, db as dbmod
from webapp.app import create_app
from webapp.seed import seed, HISTORY_JSON


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = dbmod.get_db(path)
    seed(conn)
    return path, conn


# config.ini predates the full-name migration and still keys Kira Chandran by
# her first name; the DB (and history.json) use her last name, "Chandran".
NAME_FIXUPS = {"Kira": "Chandran"}


def _fixup(name):
    return NAME_FIXUPS.get(name, name)


def test_roster_derivation_matches_config_ini():
    path, conn = _temp_db()
    try:
        ini_dates, ini_residents, ini_role_on, ini_active_halves = ini_load_block("4")
        db_dates, db_residents, db_role_on, db_active_halves = bridge.load_block_from_db(conn, 4, 4)

        assert ini_dates == db_dates, "dates for block 4 should match config.ini"
        assert {_fixup(n) for n in ini_residents} == set(db_residents), "roster for block 4 should match config.ini"
        assert {_fixup(n): v for n, v in ini_active_halves.items()} == db_active_halves, \
            "active-half counts should match config.ini"
        for (name, date), role in ini_role_on.items():
            assert db_role_on.get((_fixup(name), date)) == role, f"{name} on {date} role mismatch"
    finally:
        conn.close()
        os.remove(path)


def test_time_off_matches_config_ini():
    path, conn = _temp_db()
    try:
        ini_timeoff = ini_load_timeoff()
        db_timeoff = bridge.load_timeoff_from_db(conn)
        for name, ranges in ini_timeoff.items():
            db_name = _fixup(name)
            assert sorted(db_timeoff.get(db_name, [])) == sorted(ranges), f"time off mismatch for {name}"
    finally:
        conn.close()
        os.remove(path)


def test_history_baseline_matches_history_json():
    path, conn = _temp_db()
    try:
        with open(HISTORY_JSON) as f:
            raw = json.load(f)
        history = bridge.load_history_from_db(conn, 4)
        for name, entry in raw.items():
            last_name = _fixup(name)
            db_entry = history[last_name]
            assert db_entry["half_blocks_worked"] == entry.get("half_blocks_worked", 0)
            assert db_entry["weekend"] == entry.get("weekend", 0)
            for shift_name, count in entry.get("shifts", {}).items():
                assert db_entry["shifts"][shift_name] == count, f"{last_name} {shift_name} mismatch"
    finally:
        conn.close()
        os.remove(path)


def test_auth_role_gating():
    path, conn = _temp_db()
    conn.close()
    try:
        app = create_app(db_path=path)
        app.config["TESTING"] = True
        client = app.test_client()

        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code == 302, "unauthenticated admin access should redirect to login"

        client.post("/login", data={"username": "jaba", "password": "thehutt"})
        resp = client.get("/admin")
        assert resp.status_code == 200, "admin should reach the dashboard"
        client.get("/logout")

        client.post("/login", data={"username": "chiaka.anyaso", "password": "changeme"})
        resp = client.get("/admin")
        assert resp.status_code == 403, "resident should be forbidden from admin routes"
        resp = client.get("/schedule")
        assert resp.status_code == 200, "resident should reach their schedule page"
    finally:
        os.remove(path)


def main():
    test_roster_derivation_matches_config_ini()
    test_time_off_matches_config_ini()
    test_history_baseline_matches_history_json()
    test_auth_role_gating()
    print("All webapp smoke tests passed.")


if __name__ == "__main__":
    main()
