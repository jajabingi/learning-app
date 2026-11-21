import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(Path(_tmp, "uploads"))
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-1234"
os.environ["RATE_LIMIT_AUTH_PER_MIN"] = "0"
os.environ["RATE_LIMIT_AI_PER_MIN"] = "0"  # the in-process limiter is shared by all tests of a run
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
import app.models  # noqa: E402, F401
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def make_user(client, email="a@example.com", password="correct-horse-1"):
    """Public registration: always creates a STUDENT."""
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_staff(client, email, role="teacher", password="correct-horse-1"):
    from app.core.db import SessionLocal
    from app.core.permissions import DEFAULT_TEACHER_PERMISSIONS, set_permissions
    from app.core.security import hash_password
    from app.models.user import User

    db = SessionLocal()
    u = User(email=email, password_hash=hash_password(password), display_name=email.split("@")[0], role=role)
    db.add(u)
    db.flush()
    if role == "teacher":
        set_permissions(db, u, list(DEFAULT_TEACHER_PERMISSIONS))
    db.commit()
    db.close()
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# The original personal-workspace tests run as staff (admin) users.
@pytest.fixture
def auth(client):
    return make_staff(client, "a@example.com", "admin")


@pytest.fixture
def other_auth(client):
    return make_staff(client, "b@example.com", "admin")


@pytest.fixture
def admin_auth(client):
    return make_staff(client, "root@example.com", "admin")


@pytest.fixture
def teacher_auth(client):
    return make_staff(client, "t1@example.com", "teacher")


@pytest.fixture
def teacher2_auth(client):
    return make_staff(client, "t2@example.com", "teacher")


@pytest.fixture
def student_auth(client):
    return make_user(client, "s1@example.com")


@pytest.fixture
def student2_auth(client):
    return make_user(client, "s2@example.com")
