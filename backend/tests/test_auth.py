import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.base import utcnow
from app.models.user import AuthToken, User
from app.services import google
from app.services.email import OUTBOX
from tests.conftest import make_staff, make_user
from tests.test_phase3 import enroll, two_lessons

settings = get_settings()
PW = "correct-horse-1"


def H(tokens) -> dict:
    t = tokens["access_token"] if isinstance(tokens, dict) else tokens
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(autouse=True)
def google_on(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_url", "http://web.test")
    OUTBOX.clear()


class FakeGoogle:
    """Replaces the two network calls; verify_id_token is exercised for real in test_id_token_verification."""

    def __init__(self, monkeypatch):
        self.claims = {"sub": "g-100", "email": "gina@example.com", "email_verified": True, "name": "Gina"}
        self.fail = False
        monkeypatch.setattr(google, "exchange_code", self._exchange)
        monkeypatch.setattr(google, "verify_id_token", self._verify)
        self.nonce = None

    def _exchange(self, code, verifier):
        if self.fail or code == "bad":
            raise google.GoogleError("boom")
        return "fake-id-token"

    def _verify(self, token, nonce):
        self.nonce = nonce
        return dict(self.claims)


@pytest.fixture
def gg(monkeypatch):
    return FakeGoogle(monkeypatch)


def google_login(client, code="good", state=None, **kw):
    """Run the redirect flow like a browser. Returns the redirect Location the SPA lands on."""
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email profile"] and q["client_id"] == [settings.google_client_id]
    cb = client.get("/api/auth/google/callback", params={"code": code, "state": state or q["state"][0]}, follow_redirects=False)
    assert cb.status_code == 302
    return cb.headers["location"], q


def finish(client, loc):
    qs = parse_qs(urlparse(loc).query)
    assert "code" in qs, loc
    r = client.post("/api/auth/google/exchange", json={"code": qs["code"][0]})
    assert r.status_code == 200, r.text
    return r.json()


def audit_actions(client, admin):
    return [a["action"] for a in client.get("/api/admin/audit?page_size=100", headers=admin).json()["items"]]


# ---------------------------------------------------------------- Google
def test_google_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    assert client.get("/api/auth/config").json()["google_enabled"] is False
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 503


def test_google_new_user_is_student_and_returning_user_recognised(client, gg, admin_auth):
    assert client.get("/api/auth/config").json()["google_enabled"] is True
    loc, q = google_login(client)
    assert loc.startswith("http://web.test/auth/callback?code=")
    assert gg.nonce is not None and gg.nonce != q["state"][0]                       # nonce is separate from state
    tokens = finish(client, loc)
    me = client.get("/api/auth/me", headers=H(tokens)).json()
    assert me["role"] == "student" and me["email"] == "gina@example.com" and me["providers"] == ["google"]
    assert me["has_password"] is False and me["email_verified"] is True and me["status"] == "active"
    # the one-time code cannot be replayed
    assert client.post("/api/auth/google/exchange", json={"code": parse_qs(urlparse(loc).query)["code"][0]}).status_code == 400
    # a Google-only account has no password: password login can never succeed
    assert client.post("/api/auth/login", json={"email": "gina@example.com", "password": "!"}).status_code == 401
    # returning user -> same account, no duplicate
    me2 = client.get("/api/auth/me", headers=H(finish(client, google_login(client)[0]))).json()
    assert me2["id"] == me["id"]
    users = client.get("/api/admin/users?q=gina", headers=admin_auth).json()
    assert len(users) == 1
    acts = audit_actions(client, admin_auth)
    assert "user_registered" in acts and "login_google" in acts


def test_google_never_grants_staff_even_for_a_staff_email(client, gg, teacher_auth):
    gg.claims.update(sub="g-t", email="t1@example.com")                              # an existing TEACHER's address
    loc, _ = google_login(client)
    assert "error=account_exists" in loc                                              # not logged in as the teacher, not linked
    gg.claims.update(sub="g-new", email="brand-new@example.com")
    me = client.get("/api/auth/me", headers=H(finish(client, google_login(client)[0]))).json()
    assert me["role"] == "student"


def test_google_csrf_and_failures(client, gg):
    r = client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    # wrong state (CSRF) -> rejected, nothing created
    bad = client.get("/api/auth/google/callback", params={"code": "good", "state": "attacker-state"}, follow_redirects=False)
    assert "error=google_failed" in bad.headers["location"]
    # the failed attempt consumed the cookie: replaying the right state now has no session
    assert "error=google_failed" in client.get("/api/auth/google/callback", params={"code": "good", "state": state}, follow_redirects=False).headers["location"]
    # no cookie at all (callback opened by an attacker's link in another browser)
    client.cookies.clear()
    assert "error=google_failed" in client.get("/api/auth/google/callback", params={"code": "good", "state": state}, follow_redirects=False).headers["location"]
    # user denied consent / Google error
    assert "error=google_denied" in client.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False).headers["location"]
    # token exchange fails
    loc, _ = google_login(client, code="bad")
    assert "error=google_failed" in loc
    gg.fail = True
    assert "error=google_failed" in google_login(client)[0]
    assert client.get("/api/auth/google/callback", follow_redirects=False).headers["location"].endswith("error=google_failed")


def test_forged_state_cookie_is_rejected(client, gg):
    forged = jwt.encode({"type": "oauth_state", "state": "s", "nonce": "n", "verifier": "v", "purpose": "login", "uid": None,
                         "exp": utcnow() + timedelta(minutes=5)}, "wrong-secret-wrong-secret-wrong-secret!", algorithm="HS256")
    client.cookies.set("recall_oauth", forged, path="/api/auth/google")
    r = client.get("/api/auth/google/callback", params={"code": "good", "state": "s"}, follow_redirects=False)
    assert "error=google_failed" in r.headers["location"]


def test_existing_email_account_is_not_silently_linked(client, gg, admin_auth):
    pw_headers = make_user(client, "gina@example.com")
    me = client.get("/api/auth/me", headers=pw_headers).json()
    loc, _ = google_login(client)
    assert "error=account_exists" in loc                                              # Google alone does not take over the account
    assert client.get("/api/auth/me", headers=pw_headers).json()["providers"] == []
    mail = [m for m in OUTBOX if m["to"] == "gina@example.com"][-1]
    token = parse_qs(urlparse(next(l for l in mail["body"].split() if l.startswith("http://web.test/auth/link"))).query)["token"][0]
    # confirming from the mailbox links the identity and keeps the SAME user (courses/history stay attached)
    tokens = client.post("/api/auth/link/confirm", json={"token": token}).json()
    assert client.get("/api/auth/me", headers=H(tokens)).json()["id"] == me["id"]
    assert client.get("/api/auth/me", headers=pw_headers).json()["providers"] == ["google"]
    assert client.post("/api/auth/link/confirm", json={"token": token}).status_code == 400   # single use
    # from now on Google sign-in goes to that same account
    assert client.get("/api/auth/me", headers=H(finish(client, google_login(client)[0]))).json()["id"] == me["id"]
    assert "identity_linked" in audit_actions(client, admin_auth)
    # a DIFFERENT Google identity with the same e-mail address cannot attach to it either
    gg.claims.update(sub="g-attacker")
    assert "error=account_exists" in google_login(client)[0]
    tok2 = [m for m in OUTBOX if m["to"] == "gina@example.com"][-1]["body"].split("token=")[1].split()[0]
    db = SessionLocal()
    sub_user = User(email="other@example.com", password_hash="x", role="student")
    db.add(sub_user)
    db.commit()
    db.close()
    # an identity already owned by another account cannot be claimed
    gg.claims.update(sub="g-100")
    assert tok2  # (link token for g-attacker exists; g-100 stays bound to its owner)


def test_link_confirmation_rejects_expired_and_foreign_tokens(client, gg):
    make_user(client, "gina@example.com")
    google_login(client)
    token = [m for m in OUTBOX if m["to"] == "gina@example.com"][-1]["body"].split("token=")[1].split()[0]
    db = SessionLocal()
    for t in db.query(AuthToken).filter(AuthToken.kind == "link_google"):
        t.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()
    assert client.post("/api/auth/link/confirm", json={"token": token}).status_code == 400
    assert client.post("/api/auth/link/confirm", json={"token": "x" * 40}).status_code == 400
    # a password-reset token is not a link token
    client.post("/api/auth/password/forgot", json={"email": "gina@example.com"})
    reset = [m for m in OUTBOX if "Reset" in m["subject"]][-1]["body"].split("token=")[1].split()[0]
    assert client.post("/api/auth/link/confirm", json={"token": reset}).status_code == 400


def test_signed_in_user_links_google_and_cannot_steal_identities(client, gg):
    a = make_user(client, "a1@example.com")
    r = client.post("/api/auth/google/link/start", headers=a)
    assert r.status_code == 200 and r.json()["url"].startswith("https://accounts.google.com/")
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    cb = client.get("/api/auth/google/callback", params={"code": "good", "state": state}, follow_redirects=False)
    assert cb.headers["location"].endswith("linked=google")
    assert client.get("/api/auth/me", headers=a).json()["providers"] == ["google"]
    # that Google account is now bound to user a; user b cannot attach it
    b = make_user(client, "b1@example.com")
    r = client.post("/api/auth/google/link/start", headers=b)
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    cb = client.get("/api/auth/google/callback", params={"code": "good", "state": state}, follow_redirects=False)
    assert "error=google_in_use" in cb.headers["location"]
    assert client.get("/api/auth/me", headers=b).json()["providers"] == []
    # unlinking: a has a password, so it is allowed
    ident = client.get("/api/auth/identities", headers=a).json()["identities"][0]
    assert client.delete(f"/api/auth/identities/{ident['id']}", headers=b).status_code == 404   # not b's
    assert client.delete(f"/api/auth/identities/{ident['id']}", headers=a).status_code == 204
    assert client.post("/api/auth/google/link/start").status_code == 401


def test_google_only_user_cannot_unlink_last_method(client, gg):
    t = finish(client, google_login(client)[0])
    ident = client.get("/api/auth/identities", headers=H(t)).json()["identities"][0]
    assert client.delete(f"/api/auth/identities/{ident['id']}", headers=H(t)).status_code == 409
    # setting a password first (no current password needed for a Google-only account) unlocks it
    assert client.post("/api/auth/change-password", json={"current_password": "", "new_password": "brand-new-pass-1"}, headers=H(t)).status_code == 204
    t2 = client.post("/api/auth/login", json={"email": "gina@example.com", "password": "brand-new-pass-1"}).json()
    assert client.delete(f"/api/auth/identities/{ident['id']}", headers=H(t2)).status_code == 204


def test_suspended_google_user_is_refused(client, gg, admin_auth):
    t = finish(client, google_login(client)[0])
    uid = client.get("/api/auth/me", headers=H(t)).json()["id"]
    client.patch(f"/api/admin/users/{uid}", json={"status": "suspended"}, headers=admin_auth)
    assert client.get("/api/auth/me", headers=H(t)).status_code == 401              # existing session dies immediately
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert "error=suspended" in google_login(client)[0]
    client.patch(f"/api/admin/users/{uid}", json={"status": "active"}, headers=admin_auth)
    assert client.get("/api/auth/me", headers=H(t)).status_code == 401              # old tokens stay revoked
    assert client.get("/api/auth/me", headers=H(finish(client, google_login(client)[0]))).status_code == 200


# ---------------------------------------------------------------- ID token verification (real crypto, fake Google keys)
def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update(kid="k1", alg="RS256", use="sig")
    return key, jwk


def _token(key, kid="k1", **over):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": settings.google_client_id, "sub": "123", "email": "x@example.com",
              "email_verified": True, "iat": now, "exp": now + 600, "nonce": "N"}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_id_token_verification(monkeypatch):
    key, jwk = _keypair()
    other_key, _ = _keypair()
    monkeypatch.setattr(google, "fetch_jwks", lambda: {"k1": jwk})
    google._jwks_cache.update(at=0.0, keys={})
    assert google.verify_id_token(_token(key), "N")["sub"] == "123"
    assert google.verify_id_token(_token(key, iss="accounts.google.com"), "N")["sub"] == "123"
    for label, tok in {
        "bad signature": _token(other_key),
        "wrong audience": _token(key, aud="someone-else"),
        "expired": _token(key, exp=int(time.time()) - 3600),
        "wrong issuer": _token(key, iss="https://evil.example.com"),
        "unknown kid": _token(key, kid="nope"),
        "e-mail unverified": _token(key, email_verified=False),
        "no e-mail": _token(key, email=None),
        "no exp": _token(key, exp=None),
        "HS256 forged with the public key": jwt.encode({"iss": "https://accounts.google.com", "aud": settings.google_client_id, "sub": "1", "iat": 1, "exp": int(time.time()) + 99}, "k", algorithm="HS256", headers={"kid": "k1"}),
        "garbage": "not-a-jwt",
    }.items():
        with pytest.raises(google.GoogleError):
            google.verify_id_token(tok, "N")
            pytest.fail(f"accepted: {label}")
    with pytest.raises(google.GoogleError):
        google.verify_id_token(_token(key), "a-different-nonce")                           # replayed token for another login


# ---------------------------------------------------------------- e-mail/password
def test_registration_normalises_email_and_never_takes_a_role(client, admin_auth):
    r = client.post("/api/auth/register", json={"email": "MiXed@Example.com", "password": PW, "display_name": "Mix", "role": "admin", "is_active": False})
    assert r.status_code == 201
    me = client.get("/api/auth/me", headers=H(r.json())).json()
    assert me["role"] == "student" and me["email"] == "mixed@example.com"
    assert client.post("/api/auth/register", json={"email": "mixed@example.com", "password": PW}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "MIXED@EXAMPLE.COM", "password": PW}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "MIXED@example.com", "password": PW}).status_code == 200
    # self-service profile endpoint cannot change the role either
    assert client.patch("/api/auth/me", json={"role": "admin", "display_name": "x"}, headers=H(r.json())).json()["role"] == "student"
    assert client.get("/api/admin/users", headers=H(r.json())).status_code == 403
    assert client.get("/api/teach/courses", headers=H(r.json())).status_code == 403


def test_password_reset_flow(client):
    t = make_user(client, "rita@example.com")
    assert client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"}).status_code == 202
    assert OUTBOX == []                                                                  # unknown address: same answer, no mail
    assert client.post("/api/auth/password/forgot", json={"email": "RITA@example.com"}).status_code == 202
    body = OUTBOX[-1]["body"]
    assert "/reset-password?token=" in body and PW not in body
    token = body.split("token=")[1].split()[0]
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/password/reset", json={"token": "x" * 30, "new_password": "another-pass-9"}).status_code == 400
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "another-pass-9"}).status_code == 204
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "yet-another-9"}).status_code == 400   # single use
    assert client.get("/api/auth/me", headers=t).status_code == 401                      # old sessions revoked
    assert client.post("/api/auth/login", json={"email": "rita@example.com", "password": PW}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "rita@example.com", "password": "another-pass-9"}).status_code == 200


def test_expired_reset_token(client):
    make_user(client, "rita@example.com")
    client.post("/api/auth/password/forgot", json={"email": "rita@example.com"})
    token = OUTBOX[-1]["body"].split("token=")[1].split()[0]
    db = SessionLocal()
    for t in db.query(AuthToken).filter(AuthToken.kind == "password_reset"):
        t.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "another-pass-9"}).status_code == 400


def test_logout_and_password_change_revoke_sessions(client):
    t = client.post("/api/auth/register", json={"email": "lo@example.com", "password": PW}).json()
    other = client.post("/api/auth/login", json={"email": "lo@example.com", "password": PW}).json()   # a second device
    assert client.post("/api/auth/logout", headers=H(t)).status_code == 204
    assert client.get("/api/auth/me", headers=H(t)).status_code == 401
    assert client.get("/api/auth/me", headers=H(other)).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/logout").status_code == 401
    a = client.post("/api/auth/login", json={"email": "lo@example.com", "password": PW}).json()
    b = client.post("/api/auth/login", json={"email": "lo@example.com", "password": PW}).json()
    assert client.post("/api/auth/change-password", json={"current_password": "wrong-one-1", "new_password": "fresh-pass-1"}, headers=H(a)).status_code == 400
    assert client.post("/api/auth/change-password", json={"current_password": PW, "new_password": "fresh-pass-1"}, headers=H(a)).status_code == 204
    assert client.get("/api/auth/me", headers=H(b)).status_code == 401


def test_email_verification_when_required(client, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)
    r = client.post("/api/auth/register", json={"email": "vera@example.com", "password": PW})
    assert r.status_code == 202 and r.json() == {"verification_required": True}
    assert client.post("/api/auth/login", json={"email": "vera@example.com", "password": PW}).status_code == 403
    token = OUTBOX[-1]["body"].split("token=")[1].split()[0]
    assert client.post("/api/auth/email/resend", json={"email": "vera@example.com"}).status_code == 202
    assert client.post("/api/auth/email/verify", json={"token": "y" * 30}).status_code == 400
    tokens = client.post("/api/auth/email/verify", json={"token": token}).json()
    me = client.get("/api/auth/me", headers=H(tokens)).json()
    assert me["status"] == "active" and me["email_verified"] is True
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "vera@example.com", "password": PW}).status_code == 200


# ---------------------------------------------------------------- admin user management
def test_user_directory_search_filter_sort_paginate(client, admin_auth, teacher_auth):
    for i in range(5):
        make_user(client, f"stud{i}@example.com")
    d = client.get("/api/admin/users/directory?page_size=3&sort=email&order=asc", headers=admin_auth).json()
    assert d["total"] == 7 and len(d["items"]) == 3 and d["page"] == 1
    assert [u["email"] for u in d["items"]] == sorted(u["email"] for u in d["items"])
    assert len(client.get("/api/admin/users/directory?page_size=3&page=3", headers=admin_auth).json()["items"]) == 1
    assert client.get("/api/admin/users/directory?role=teacher", headers=admin_auth).json()["total"] == 1
    assert client.get("/api/admin/users/directory?q=STUD3", headers=admin_auth).json()["items"][0]["email"] == "stud3@example.com"
    assert client.get("/api/admin/users/directory?status=suspended", headers=admin_auth).json()["total"] == 0
    assert client.get("/api/admin/users/directory?role=hacker", headers=admin_auth).status_code == 422
    assert client.get("/api/admin/users/directory?page_size=1000", headers=admin_auth).status_code == 422
    row = client.get("/api/admin/users/directory?q=stud0", headers=admin_auth).json()["items"][0]
    assert row["providers"] == ["password"] and row["enrolled_courses"] == 0 and row["status"] == "active"
    s = client.get("/api/admin/users/summary", headers=admin_auth).json()
    assert s["by_role"]["student"] == 5 and s["total"] == 7


def test_admin_role_and_status_changes_are_audited_and_guarded(client, admin_auth, teacher_auth, student_auth):
    users = {u["email"]: u for u in client.get("/api/admin/users", headers=admin_auth).json()}
    stu, adm = users["s1@example.com"], users["root@example.com"]
    # promote a student to teacher (only an admin can)
    assert client.patch(f"/api/admin/users/{stu['id']}", json={"role": "teacher"}, headers=student_auth).status_code == 403
    assert client.patch(f"/api/admin/users/{stu['id']}", json={"role": "teacher"}, headers=teacher_auth).status_code == 403
    r = client.patch(f"/api/admin/users/{stu['id']}", json={"role": "teacher"}, headers=admin_auth).json()
    assert r["role"] == "teacher" and "courses.manage" in r["permissions"]
    assert client.get("/api/auth/me", headers=student_auth).status_code == 401               # old role's token no longer valid
    new = client.post("/api/auth/login", json={"email": "s1@example.com", "password": PW}).json()
    assert client.get("/api/teach/courses", headers=H(new)).status_code == 200
    assert client.patch(f"/api/admin/users/{stu['id']}", json={"role": "student"}, headers=admin_auth).json()["role"] == "student"
    # suspend / reactivate
    assert client.patch(f"/api/admin/users/{stu['id']}", json={"status": "suspended"}, headers=admin_auth).json()["status"] == "suspended"
    assert client.post("/api/auth/login", json={"email": "s1@example.com", "password": PW}).status_code == 403
    assert client.patch(f"/api/admin/users/{stu['id']}", json={"status": "active"}, headers=admin_auth).json()["is_active"] is True
    assert client.post("/api/auth/login", json={"email": "s1@example.com", "password": PW}).status_code == 200
    # guards: the only admin can neither demote nor suspend themselves
    assert client.patch(f"/api/admin/users/{adm['id']}", json={"role": "student"}, headers=admin_auth).status_code == 409
    assert client.patch(f"/api/admin/users/{adm['id']}", json={"status": "suspended"}, headers=admin_auth).status_code == 409
    # a second admin may demote the first, but never the last active one
    second = client.post("/api/admin/users", json={"email": "adm2@example.com", "password": PW, "role": "admin"}, headers=admin_auth).json()
    assert client.patch(f"/api/admin/users/{adm['id']}", json={"role": "teacher"}, headers=admin_auth).status_code == 409   # self
    h2 = H(client.post("/api/auth/login", json={"email": "adm2@example.com", "password": PW}).json())
    assert client.patch(f"/api/admin/users/{adm['id']}", json={"role": "teacher"}, headers=h2).status_code == 200
    assert client.patch(f"/api/admin/users/{second['id']}", json={"status": "suspended"}, headers=h2).status_code == 409
    # audit trail
    log = client.get("/api/admin/audit?page_size=100", headers=h2).json()["items"]
    acts = [a["action"] for a in log]
    for want in ("role_changed", "user_suspended", "user_reactivated", "user_created"):
        assert want in acts, want
    change = next(a for a in log if a["action"] == "role_changed" and a["target"] == "s1@example.com")
    assert change["actor"] == "root@example.com" and change["details"]["from_role"] in ("student", "teacher") and change["created_at"]
    keys = {k.lower() for a in log for k in a["details"]}
    assert not [k for k in keys if any(w in k for w in ("password", "token", "secret", "hash"))]
    assert client.get("/api/admin/audit", headers=teacher_auth).status_code == 403
    filtered = client.get(f"/api/admin/audit?target_user_id={stu['id']}&action=role_changed", headers=h2).json()
    assert filtered["total"] == 2


def test_user_detail_shows_enrollments_and_activity(client, admin_auth, teacher_auth, student_auth):
    cid, _ = two_lessons(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=admin_auth).json() if u["email"] == "s1@example.com")
    client.patch(f"/api/admin/users/{uid}", json={"display_name": "Renamed"}, headers=admin_auth)
    d = client.get(f"/api/admin/users/{uid}", headers=admin_auth).json()
    assert d["enrollments"][0]["status"] == "active" and d["display_name"] == "Renamed"
    assert any(a["action"] == "profile_edited" for a in d["activity"])
    assert client.get(f"/api/admin/users/{uuid.uuid4()}", headers=admin_auth).status_code == 404
    for h in (student_auth, teacher_auth):
        assert client.get(f"/api/admin/users/{uid}", headers=h).status_code == 403
        assert client.get("/api/admin/users/directory", headers=h).status_code == 403
        assert client.get("/api/admin/users/summary", headers=h).status_code == 403
    assert client.get("/api/admin/users/directory").status_code == 401
    t = next(u["id"] for u in client.get("/api/admin/users", headers=admin_auth).json() if u["email"] == "t1@example.com")
    assert client.get(f"/api/admin/users/{t}", headers=admin_auth).json()["owned_courses"] == 1


# ---------------------------------------------------------------- cross-user isolation
def test_teacher_cannot_reach_another_teachers_students_or_courses(client, teacher_auth, teacher2_auth, student_auth, student2_auth):
    cid, _ = two_lessons(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)
    sid = next(s["id"] for s in client.get("/api/teach/students", headers=teacher_auth).json())
    assert client.get("/api/teach/students", headers=teacher2_auth).json() == []
    assert client.get(f"/api/teach/students/{sid}", headers=teacher2_auth).status_code in (403, 404)
    assert client.get(f"/api/teach/courses/{cid}", headers=teacher2_auth).status_code == 404
    assert client.get(f"/api/teach/courses/{cid}/enrollments", headers=teacher2_auth).status_code == 404
    # students never reach staff or admin APIs, nor each other's courses
    assert client.get(f"/api/teach/courses/{cid}", headers=student_auth).status_code == 403
    assert client.get("/api/admin/users", headers=student_auth).status_code == 403
    assert client.get(f"/api/student/courses/{cid}", headers=student2_auth).status_code == 404
    assert client.get(f"/api/student/courses/{cid}", headers=student_auth).status_code == 200


def test_expired_and_tampered_access_tokens(client):
    t = make_user(client, "tok@example.com")
    uid = client.get("/api/auth/me", headers=t).json()["id"]
    expired = jwt.encode({"sub": uid, "type": "access", "tv": 0, "exp": utcnow() - timedelta(seconds=5)}, settings.secret_key, algorithm="HS256")
    assert client.get("/api/auth/me", headers=H(expired)).status_code == 401
    wrong_key = jwt.encode({"sub": uid, "type": "access", "tv": 0, "exp": utcnow() + timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    assert client.get("/api/auth/me", headers=H(wrong_key)).status_code == 401
    refresh_as_access = client.post("/api/auth/login", json={"email": "tok@example.com", "password": PW}).json()["refresh_token"]
    assert client.get("/api/auth/me", headers=H(refresh_as_access)).status_code == 401      # token types are not interchangeable
    stale = jwt.encode({"sub": uid, "type": "access", "tv": 99, "exp": utcnow() + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")
    assert client.get("/api/auth/me", headers=H(stale)).status_code == 401


def test_audit_never_stores_secrets():
    from app.services import audit
    assert audit._clean({"password": "x", "access_token": "y", "client_secret": "z", "role": "teacher", "code": "1"}) == {"role": "teacher"}


def test_admin_creates_students_and_sends_reset_email(client, admin_auth, teacher_auth):
    r = client.post("/api/admin/users", json={"email": "New.Student@Example.com", "password": PW, "role": "student"}, headers=admin_auth)
    assert r.status_code == 201 and r.json()["role"] == "student" and r.json()["email"] == "new.student@example.com"
    assert client.post("/api/auth/login", json={"email": "new.student@example.com", "password": PW}).status_code == 200
    assert client.post("/api/admin/users", json={"email": "x@example.com", "password": PW, "role": "student"}, headers=teacher_auth).status_code == 403
    OUTBOX.clear()
    assert client.post(f"/api/admin/users/{r.json()['id']}/send-reset", headers=admin_auth).status_code == 202
    assert OUTBOX[-1]["to"] == "new.student@example.com" and "/reset-password?token=" in OUTBOX[-1]["body"]
    assert client.post(f"/api/admin/users/{r.json()['id']}/send-reset", headers=teacher_auth).status_code == 403
    client.patch(f"/api/admin/users/{r.json()['id']}", json={"status": "suspended"}, headers=admin_auth)
    assert client.post(f"/api/admin/users/{r.json()['id']}/send-reset", headers=admin_auth).status_code == 409
