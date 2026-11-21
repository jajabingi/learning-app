import pytest

from app import cli
from app.core.db import SessionLocal
from app.models.user import AuditLog, User


@pytest.fixture(autouse=True)
def cli_env(monkeypatch):
    monkeypatch.setenv("RECALL_CLI_SKIP_MIGRATE", "1")  # the test database is created by the fixture
    monkeypatch.setenv("RECALL_PASSWORD", "first-admin-pass-1")


def user(email):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).one_or_none()
    finally:
        db.close()


def test_first_admin_can_sign_in_and_use_admin_area(client):
    assert cli.main(["create-admin", "--email", "Boss@Example.com", "--name", "Boss"]) == 0
    u = user("boss@example.com")
    assert u.role == "admin" and u.status == "active"
    r = client.post("/api/auth/login", json={"email": "boss@example.com", "password": "first-admin-pass-1"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/admin/users/directory", headers=h).json()["total"] == 1
    assert cli.main(["create-admin", "--email", "boss@example.com"]) == 1          # no duplicates


def test_cli_roles_guards_and_audit(client, capsys):
    cli.main(["create-admin", "--email", "boss@example.com"])
    cli.main(["create-teacher", "--email", "t@example.com"])
    assert user("t@example.com").role == "teacher"
    assert cli.main(["set-role", "--email", "boss@example.com", "--role", "student"]) == 1    # last admin is protected
    assert cli.main(["suspend", "--email", "boss@example.com"]) == 1
    assert cli.main(["set-role", "--email", "t@example.com", "--role", "admin"]) == 0
    assert cli.main(["set-role", "--email", "boss@example.com", "--role", "student"]) == 0     # now allowed (another admin exists)
    assert cli.main(["suspend", "--email", "t@example.com"]) == 1                              # t is the last admin
    assert cli.main(["set-role", "--email", "nobody@example.com", "--role", "admin"]) == 1
    old = client.post("/api/auth/login", json={"email": "t@example.com", "password": "first-admin-pass-1"}).json()
    assert cli.main(["reset-password", "--email", "t@example.com"]) == 0
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old['access_token']}"}).status_code == 401   # sessions revoked
    cli.main(["list-users"])
    assert "t@example.com" in capsys.readouterr().out
    db = SessionLocal()
    acts = {a.action for a in db.query(AuditLog)}
    db.close()
    assert {"user_created", "role_changed", "password_changed"} <= acts


def test_short_password_rejected(monkeypatch):
    monkeypatch.setenv("RECALL_PASSWORD", "short")
    assert cli.main(["create-admin", "--email", "x@example.com"]) == 1
    assert user("x@example.com") is None
