import pytest
from webapp.app import create_app
from webapp.db import get_db
from webapp.seed import seed
from webapp.bridge import optimize_block_run


@pytest.fixture
def app():
    import uuid
    import os
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(REPO_ROOT, "data", f"test_pref_{uuid.uuid4().hex}.db")
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except OSError: pass

    app = create_app(db_path=db_path)
    app.config.update({"TESTING": True})

    with app.app_context():
        conn = get_db(db_path)
        seed(conn)
        conn.close()

    yield app

    import gc
    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass


@pytest.fixture
def client(app):
    return app.test_client()


def test_resident_preference_saving(client, app):
    # Login as non-admin PGY-4 resident
    rv = client.post("/login", data={"username": "aaron.damore", "password": "changeme"}, follow_redirects=True)
    assert rv.status_code == 200

    # GET settings page
    rv = client.get("/resident/settings")
    assert b"Frequent Breaks" in rv.data
    assert b"Longer Breaks" in rv.data

    # POST preference = longer
    rv = client.post("/resident/settings", data={"form_type": "preferences", "preference": "longer"}, follow_redirects=True)
    assert b"Preferences saved!" in rv.data

    # Verify DB updated
    db_path = app.config["DB_PATH"]
    conn = get_db(db_path)
    row = conn.execute("SELECT preference FROM users WHERE username = 'aaron.damore'").fetchone()
    assert row["preference"] == "longer"
    conn.close()


def test_admin_block_optimization_route(client, app):
    db_path = app.config["DB_PATH"]
    conn = get_db(db_path)

    # Insert a dummy run and assignments for Block 4
    cur = conn.execute(
        "INSERT INTO runs (pgy_level, block_number, status, min_shifts, time_limit) "
        "VALUES (4, 4, 'draft', 18, 60.0) RETURNING id"
    )
    run_id = cur.fetchone()["id"]

    res1 = conn.execute("SELECT id FROM residents LIMIT 1").fetchone()["id"]
    res2 = conn.execute("SELECT id FROM residents LIMIT 1 OFFSET 1").fetchone()["id"]

    conn.execute("INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, '2026-09-21', 'MGB Day')", (run_id, res1))
    conn.execute("INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, '2026-09-21', 'MGB Night')", (run_id, res2))
    conn.commit()

    # Direct function test
    res = optimize_block_run(conn, run_id)
    assert "swaps_applied" in res

    # Login as admin and trigger optimization route
    client.post("/login", data={"username": "jaba", "password": "thehutt"}, follow_redirects=True)
    rv = client.post(f"/admin/runs/{run_id}/optimize", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Optimization finished" in rv.data
    conn.close()


def test_mgb_nights_exclusion_in_optimizer(client, app):
    db_path = app.config["DB_PATH"]
    conn = get_db(db_path)

    cur = conn.execute(
        "INSERT INTO runs (pgy_level, block_number, status, min_shifts, time_limit) "
        "VALUES (4, 4, 'draft', 18, 60.0) RETURNING id"
    )
    run_id = cur.fetchone()["id"]

    res1 = conn.execute("SELECT id FROM residents LIMIT 1").fetchone()["id"]
    res2 = conn.execute("SELECT id FROM residents LIMIT 1 OFFSET 1").fetchone()["id"]

    # Set res2 rotation to MGB Nights on half block 4a
    hb4a = conn.execute("SELECT id FROM half_blocks WHERE pgy_level = 4 AND block_number = 4 AND half = 'a'").fetchone()["id"]
    conn.execute("UPDATE rotations SET rotation = 'MGB Nights' WHERE resident_id = ? AND half_block_id = ?", (res2, hb4a))
    conn.commit()

    conn.execute("INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, '2026-09-21', 'MGB Day')", (run_id, res1))
    conn.execute("INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, '2026-09-21', 'Acute 11p-8a')", (run_id, res2))
    conn.commit()

    res = optimize_block_run(conn, run_id)
    # res2's shift is locked due to MGB Nights rotation on this half block date
    assert res["swaps_applied"] == 0
    conn.close()
