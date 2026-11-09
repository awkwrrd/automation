import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("WMS_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["WMS_SEED_DEMO_DATA"] = "true"
os.environ["WMS_DISPATCHER_ENABLED"] = "false"  # tests drive delivery explicitly
os.environ["WMS_SHOPIFY_SYNC_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin", "admin")


@pytest.fixture(scope="session")
def operator(client):
    return _login(client, "operator", "operator")
