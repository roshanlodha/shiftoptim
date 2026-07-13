import pytest
from webapp.app import create_app
from webapp.db import get_db, init_db
from webapp.seed import seed


@pytest.fixture
def app():
    # Use a unique test db path to prevent collisions/locks
    import uuid
    import os
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(REPO_ROOT, "data", f"test_shiftoptim_{uuid.uuid4().hex}.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass
    if os.path.exists(db_path + "-wal"):
        try:
            os.remove(db_path + "-wal")
        except OSError:
            pass
    if os.path.exists(db_path + "-shm"):
        try:
            os.remove(db_path + "-shm")
        except OSError:
            pass
            
    app = create_app(db_path=db_path)
    app.config.update({
        "TESTING": True,
    })
    
    with app.app_context():
        conn = get_db(db_path)
        seed(conn)
        conn.close()

    yield app

    # Cleanup after test
    import gc
    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError as e:
                print(f"Teardown cleanup failed to remove {p}: {e}")


@pytest.fixture
def client(app):
    return app.test_client()


def test_admin_flow_pgy1(client):
    # 1. Login
    rv = client.post("/login", data={
        "username": "jaba",
        "password": "thehutt"
    }, follow_redirects=True)
    assert b"ED Schedule Builder" in rv.data, "Login failed or did not show admin dashboard"
    
    # 2. Toggle PGY to 1
    rv = client.get("/admin/toggle_pgy/1", follow_redirects=True)
    assert b"PGY-1" in rv.data, "Failed to toggle PGY to 1"
    
    # 3. Run solver for Block 4
    rv = client.post("/admin/blocks/4/run", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Draft" in rv.data, "Solver run did not successfully produce a draft schedule"
    
    # 4. Verify review page has grid cells with PGY-1 shift name
    assert b"MGH Jr. - AC PGY1 7a-4p" in rv.data or b"BWH Jr.  - Exe Jr 8a-4p" in rv.data


def test_admin_flow_pgy1_with_off_service(client):
    # 1. Login
    client.post("/login", data={
        "username": "jaba",
        "password": "thehutt"
    }, follow_redirects=True)
    
    # 2. Toggle PGY to 1
    client.get("/admin/toggle_pgy/1", follow_redirects=True)
    
    # 3. Post solver run with off-service parameters
    rv = client.post("/admin/blocks/4/run", data={
        "off_service_name[]": ["Off Service 1", "Off Service 2"],
        "off_service_site[]": ["MGH", "BWH"],
        "off_service_half_a[]": ["1", "1"],
        "off_service_half_b[]": ["1", "0"]
    }, follow_redirects=True)
    
    assert rv.status_code == 200
    assert b"Draft" in rv.data
    assert b"Off Service 1" in rv.data or b"Off Service 2" in rv.data
