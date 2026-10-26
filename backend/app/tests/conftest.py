import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
os.environ["RATE_LIMIT_LOGIN_PER_MINUTE"] = "100000"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["RATE_LIMIT_REGISTER_PER_MINUTE"] = "100000"
os.environ["MAX_FAILED_LOGINS"] = "100000"

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, engine
from app.main import app
from app.models import Base
from app.seed import DEMO_PASSWORD, reset_all, seed


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def client():
    _cache.clear()
    from app.api import auth as _auth
    _auth._failures.clear()
    _auth._attempts.clear()
    with SessionLocal() as s:
        reset_all(s)
        seed(s)
    return TestClient(app)


def login(client, email, password=DEMO_PASSWORD):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


_cache: dict = {}


def auth(client, email):
    if email not in _cache:
        _cache[email] = {"Authorization": f"Bearer {login(client, email)['access_token']}"}
    return _cache[email]


@pytest.fixture()
def H(client):
    cache = {}
    def get(who):
        if who not in cache:
            cache[who] = auth(client, f"{who}")
        return cache[who]
    return get
