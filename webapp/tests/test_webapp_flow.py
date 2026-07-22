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


def test_admin_flow_pgy4(client):
    # 1. Login
    rv = client.post("/login", data={
        "username": "jaba",
        "password": "thehutt"
    }, follow_redirects=True)
    assert b"ED Schedule Builder" in rv.data, "Login failed or did not show admin dashboard"
    
    # 2. Toggle PGY to 4
    rv = client.get("/admin/toggle_pgy/4", follow_redirects=True)
    assert b"PGY-4" in rv.data, "Failed to toggle PGY to 4"
    
    # 3. Run solver for Block 4
    rv = client.post("/admin/blocks/4/run", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Draft" in rv.data, "Solver run did not successfully produce a draft schedule"
