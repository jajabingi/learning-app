import pytest

from app.bootstrap import ensure_first_admin
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.models.user import User

settings = get_settings()


@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@h:5432/d", "postgresql+psycopg2://u:p@h:5432/d"),
    ("postgresql://u:p@h/d?sslmode=require", "postgresql+psycopg2://u:p@h/d?sslmode=require"),
    ("postgresql+psycopg2://u:p@h/d", "postgresql+psycopg2://u:p@h/d"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_database_url_is_normalised(raw, expected):
    assert Settings(database_url=raw, secret_key="k" * 40).database_url == expected


def test_bootstrap_creates_admin_once_and_never_overwrites(client, monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", " Boss@Example.com ")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "first-admin-pass-1")
    assert ensure_first_admin() is True
    assert ensure_first_admin() is False                                  # an admin exists now
    r = client.post("/api/auth/login", json={"email": "boss@example.com", "password": "first-admin-pass-1"})
    assert r.status_code == 200
    db = SessionLocal()
    assert db.query(User).filter(User.role == "admin").count() == 1
    db.close()
    monkeypatch.setattr(settings, "bootstrap_admin_password", "a-different-pass-2")
    assert ensure_first_admin() is False
    assert client.post("/api/auth/login", json={"email": "boss@example.com", "password": "first-admin-pass-1"}).status_code == 200


def test_bootstrap_ignores_missing_or_weak_settings(client, monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "first-admin-pass-1")
    assert ensure_first_admin() is False
    monkeypatch.setattr(settings, "bootstrap_admin_email", "boss@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "short")
    assert ensure_first_admin() is False
