import re
import uuid
from datetime import timedelta

from app.core.db import SessionLocal
from app.main import app
from app.models.base import utcnow
from app.models.lms import LmsEnrollment
from app.models.user import User
from sqlalchemy import select


def course(client, h, **kw):
    r = client.post("/api/teach/courses", json={"title": "Investment Fundamentals", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def module(client, h, cid, title="Intro"):
    r = client.post(f"/api/teach/courses/{cid}/modules", json={"title": title}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def lesson(client, h, mid, title="Understanding Investment"):
    r = client.post(f"/api/teach/modules/{mid}/lessons", json={"title": title}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def block(client, h, lid, type_, data, expect=201):
    r = client.post(f"/api/teach/lessons/{lid}/blocks", json={"type": type_, "data": data}, headers=h)
    assert r.status_code == expect, r.text
    return r.json()


def enroll(student_email, course_id, status="active", **kw):
    db = SessionLocal()
    sid = db.scalar(select(User.id).where(User.email == student_email))
    db.add(LmsEnrollment(student_id=sid, course_id=uuid.UUID(course_id), status=status, source="manual", **kw))
    db.commit()
    db.close()


# ---------------- roles & lock-down ----------------
def test_registration_creates_students_who_cannot_use_teacher_workspace(client, student_auth):
    me = client.get("/api/auth/me", headers=student_auth).json()
    assert me["role"] == "student" and me["permissions"] == []
    for url in ("/api/library/tree", "/api/questions", "/api/notes", "/api/dashboard", "/api/teach/courses",
                "/api/admin/users", "/api/export/json", "/api/ai/status", "/api/review/queue"):
        assert client.get(url, headers=student_auth).status_code == 403, url


def test_every_route_denies_students_and_anonymous(client, student_auth):
    """Default-deny sweep over ALL registered routes: only the allow-list below is open to a student."""
    allowed_for_student = {
        ("GET", "/api/health"), ("POST", "/api/auth/register"), ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"), ("GET", "/api/auth/me"), ("PATCH", "/api/auth/me"),
        ("POST", "/api/auth/change-password"),
        # auth flows: anonymous by design (each is single-use-token / state protected, covered in test_auth.py)
        ("GET", "/api/auth/config"), ("POST", "/api/auth/password/forgot"), ("POST", "/api/auth/password/reset"),
        ("POST", "/api/auth/email/verify"), ("POST", "/api/auth/email/resend"), ("GET", "/api/auth/google/start"),
        ("GET", "/api/auth/google/callback"), ("POST", "/api/auth/google/exchange"), ("POST", "/api/auth/link/confirm"),
        # any signed-in user, student included
        ("POST", "/api/auth/logout"), ("GET", "/api/auth/identities"), ("DELETE", "/api/auth/identities/{identity_id}"),
        ("POST", "/api/auth/google/link/start"),
        ("POST", "/api/payments/webhook/{provider}"),
    }
    sid = str(uuid.uuid4())
    checked = 0
    for path, ops in app.openapi()["paths"].items():  # FastAPI wraps included routers, so use the OpenAPI schema
        url = re.sub(r"\{[^}]+\}", sid, path)
        for method in (m.upper() for m in ops):
            if (method, path) in allowed_for_student or path.startswith("/api/public/"):
                continue   # the public catalog is intentionally anonymous (covered in test_public.py)
            anon = client.request(method, url)
            assert anon.status_code == 401, (method, path, "anonymous", anon.status_code)
            if path.startswith("/api/media/"):  # token-authenticated: a bearer login alone is not accepted
                assert client.request(method, url, headers=student_auth).status_code == 401, path
            elif not path.startswith("/api/student/"):
                r = client.request(method, url, headers=student_auth, json={})
                assert r.status_code == 403, (method, path, "student", r.status_code)
            checked += 1
    assert checked > 100


def test_teacher_cannot_use_admin_routes_and_permissions_are_enforced(client, admin_auth, teacher_auth):
    assert client.get("/api/admin/users", headers=teacher_auth).status_code == 403
    users = client.get("/api/admin/users", headers=admin_auth).json()
    t = next(u for u in users if u["email"] == "t1@example.com")
    assert "courses.manage" in t["permissions"]
    # remove publish permission → can still edit, cannot publish
    r = client.patch(f"/api/admin/users/{t['id']}", json={"permissions": ["courses.manage"]}, headers=admin_auth)
    assert r.json()["permissions"] == ["courses.manage"]
    c = course(client, teacher_auth)
    m = module(client, teacher_auth, c["id"])
    lid = lesson(client, teacher_auth, m["id"])["id"]
    client.patch(f"/api/teach/lessons/{lid}", json={"is_published": True}, headers=teacher_auth)
    client.patch(f"/api/teach/modules/{m['id']}", json={"is_published": True}, headers=teacher_auth)
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=teacher_auth).status_code == 403
    # remove everything → no course management at all
    client.patch(f"/api/admin/users/{t['id']}", json={"permissions": []}, headers=admin_auth)
    assert client.get("/api/teach/courses", headers=teacher_auth).status_code == 403
    assert client.patch(f"/api/admin/users/{t['id']}", json={"permissions": ["nope"]}, headers=admin_auth).status_code == 422


def test_admin_user_management_guards(client, admin_auth):
    r = client.post("/api/admin/users", json={"email": "new@x.com", "password": "longenough1", "role": "teacher"}, headers=admin_auth)
    assert r.status_code == 201 and "courses.publish" in r.json()["permissions"]
    me = client.get("/api/auth/me", headers=admin_auth).json()
    assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "teacher"}, headers=admin_auth).status_code == 409
    assert client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}, headers=admin_auth).status_code == 409
    # deactivated users are locked out immediately
    uid = r.json()["id"]
    login = client.post("/api/auth/login", json={"email": "new@x.com", "password": "longenough1"}).json()
    h = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/teach/courses", headers=h).status_code == 200
    client.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=admin_auth)
    assert client.get("/api/teach/courses", headers=h).status_code == 401
    # suspension revoked that session for good: reactivating does not resurrect the old token
    client.patch(f"/api/admin/users/{uid}", json={"is_active": True, "role": "student"}, headers=admin_auth)
    assert client.get("/api/teach/courses", headers=h).status_code == 401
    fresh = client.post("/api/auth/login", json={"email": "new@x.com", "password": "longenough1"}).json()
    assert client.get("/api/teach/courses", headers={"Authorization": f"Bearer {fresh['access_token']}"}).status_code == 403  # now a student


# ---------------- course management ----------------
def test_course_crud_validation_and_ownership(client, teacher_auth, teacher2_auth, admin_auth):
    c = course(client, teacher_auth, subtitle="Basics", price_amount="500", discount_amount="400", currency="ILS",
               enrollment_type="paid", objectives=["Understand risk", " "], access_days=365)
    assert c["status"] == "draft" and c["price_amount"] == 500 and c["objectives"] == ["Understand risk"]
    assert client.post("/api/teach/courses", json={"title": "x", "price_amount": "100", "discount_amount": "100"}, headers=teacher_auth).status_code == 422
    assert client.post("/api/teach/courses", json={"title": "x", "enrollment_type": "free", "price_amount": "5"}, headers=teacher_auth).status_code == 422
    assert client.post("/api/teach/courses", json={"title": ""}, headers=teacher_auth).status_code == 422
    # edit
    r = client.patch(f"/api/teach/courses/{c['id']}", json={"title": "IF 101", "discount_amount": None, "access_days": None}, headers=teacher_auth)
    assert r.json()["title"] == "IF 101" and r.json()["discount_amount"] is None and r.json()["access_days"] is None
    # another teacher cannot see, edit, or delete it; admin can
    for method, url, kw in (("get", f"/api/teach/courses/{c['id']}", {}), ("patch", f"/api/teach/courses/{c['id']}", {"json": {"title": "x"}}),
                            ("delete", f"/api/teach/courses/{c['id']}", {}), ("post", f"/api/teach/courses/{c['id']}/modules", {"json": {"title": "m"}})):
        assert getattr(client, method)(url, headers=teacher2_auth, **kw).status_code == 404, url
    assert client.get("/api/teach/courses", headers=teacher2_auth).json() == []
    assert client.get(f"/api/teach/courses/{c['id']}", headers=admin_auth).status_code == 200


def test_builder_modules_lessons_blocks_reorder_duplicate(client, teacher_auth, teacher2_auth):
    h = teacher_auth
    c = course(client, h)
    m1, m2 = module(client, h, c["id"], "M1"), module(client, h, c["id"], "M2")
    assert client.post(f"/api/teach/courses/{c['id']}/modules/reorder", json={"ids": [m2["id"], m1["id"]]}, headers=h).status_code == 204
    cur = client.get(f"/api/teach/courses/{c['id']}", headers=h).json()["curriculum"]
    assert [m["title"] for m in cur] == ["M2", "M1"]
    assert client.post(f"/api/teach/courses/{c['id']}/modules/reorder", json={"ids": [m1["id"]]}, headers=h).status_code == 422
    l1, l2 = lesson(client, h, m1["id"], "L1")["id"], lesson(client, h, m1["id"], "L2")["id"]
    client.post(f"/api/teach/modules/{m1['id']}/lessons/reorder", json={"ids": [l2, l1]}, headers=h)
    # blocks: insert at position, reorder, duplicate, delete
    b1 = block(client, h, l1, "text", {"markdown": "Hello"})
    b2 = block(client, h, l1, "summary", {"markdown": "Sum"})
    b0 = client.post(f"/api/teach/lessons/{l1}/blocks", json={"type": "callout", "data": {"variant": "tip", "markdown": "t"}, "position": 0}, headers=h).json()
    order = lambda: [b["type"] for b in client.get(f"/api/teach/lessons/{l1}", headers=h).json()["blocks"]]
    assert order() == ["callout", "text", "summary"]
    client.post(f"/api/teach/lessons/{l1}/blocks/reorder", json={"ids": [b2["id"], b0["id"], b1["id"]]}, headers=h)
    assert order() == ["summary", "callout", "text"]
    client.post(f"/api/teach/blocks/{b1['id']}/duplicate", headers=h)
    assert order() == ["summary", "callout", "text", "text"]
    client.delete(f"/api/teach/blocks/{b0['id']}", headers=h)
    assert order() == ["summary", "text", "text"]
    # duplicate lesson copies blocks, unpublished
    d = client.post(f"/api/teach/lessons/{l1}/duplicate", headers=h).json()
    assert d["title"] == "L1 (copy)" and len(d["blocks"]) == 3 and d["is_published"] is False and d["id"] != l1
    # move lesson to another module; cross-course move is rejected
    assert client.patch(f"/api/teach/lessons/{l1}", json={"module_id": m2["id"]}, headers=h).json()["module_id"] == m2["id"]
    other = course(client, h, title="Other")
    om = module(client, h, other["id"])
    assert client.patch(f"/api/teach/lessons/{l1}", json={"module_id": om["id"]}, headers=h).status_code == 422
    # another teacher cannot touch any of these ids
    for method, url, kw in (("get", f"/api/teach/lessons/{l1}", {}), ("patch", f"/api/teach/blocks/{b1['id']}", {"json": {"is_visible": False}}),
                            ("delete", f"/api/teach/modules/{m1['id']}", {}), ("post", f"/api/teach/lessons/{l1}/duplicate", {})):
        assert getattr(client, method)(url, headers=teacher2_auth, **kw).status_code == 404, url
    # deleting a module deletes its lessons and blocks
    assert client.delete(f"/api/teach/modules/{m1['id']}", headers=h).status_code == 204
    assert client.get(f"/api/teach/lessons/{l2}", headers=h).status_code == 404


def test_block_validation_and_video_allowlist(client, teacher_auth):
    h = teacher_auth
    lid = lesson(client, h, module(client, h, course(client, h)["id"])["id"])["id"]
    v = block(client, h, lid, "video", {"url": "https://youtu.be/dQw4w9WgXcQ", "title": "Intro"})
    assert v["data"]["resolved"]["embed_url"] == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    v2 = block(client, h, lid, "video", {"url": "https://vimeo.com/123456789"})
    assert v2["data"]["resolved"]["provider"] == "vimeo"
    assert block(client, h, lid, "video", {"url": "https://cdn.example.com/a.mp4"})["data"]["resolved"]["kind"] == "file"
    for bad in ("http://youtu.be/dQw4w9WgXcQ", "https://evil.example.com/page", "javascript:alert(1)", "https://youtube.com/watch?v=short"):
        block(client, h, lid, "video", {"url": bad}, expect=422)
    block(client, h, lid, "bogus", {}, expect=422)
    block(client, h, lid, "text", {"markdown": "x", "unexpected": 1}, expect=422)
    block(client, h, lid, "external_link", {"url": "javascript:alert(1)"}, expect=422)
    block(client, h, lid, "image", {}, expect=422)
    block(client, h, lid, "formula", {"latex": r"NPV=\sum \frac{CF_t}{(1+r)^t}", "title": "NPV"})


def test_attachments_and_question_refs_are_owner_scoped(client, teacher_auth, teacher2_auth):
    h, h2 = teacher_auth, teacher2_auth
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    att = client.post("/api/attachments", files={"file": ("a.png", png, "image/png")}, headers=h)
    assert att.status_code == 201
    q = client.post("/api/questions", json={"title": "Q", "content": "What is NPV?", "answer": {"answer": "secret answer"}}, headers=h).json()
    lid = lesson(client, h, module(client, h, course(client, h)["id"])["id"])["id"]
    block(client, h, lid, "image", {"attachment_id": att.json()["id"], "alt": "x"})
    other_lid = lesson(client, h2, module(client, h2, course(client, h2)["id"])["id"])["id"]
    block(client, h2, other_lid, "image", {"attachment_id": att.json()["id"]}, expect=422)  # someone else's file
    block(client, h2, other_lid, "question", {"question_id": q["id"]}, expect=422)           # someone else's question
    block(client, h2, other_lid, "quiz", {"question_ids": [q["id"]]}, expect=422)
    qb = block(client, h, lid, "question", {"question_id": q["id"]})
    assert qb["data"]["show_answer"] == "after_attempt"
    # the student projection never contains answers or correctness
    pv = client.get(f"/api/teach/lessons/{lid}/preview", headers=h).json()
    text = str(pv)
    assert "secret answer" not in text and "is_correct" not in text and pv["preview"] is True


# ---------------- publishing ----------------
def test_publish_rules_and_preview(client, teacher_auth):
    h = teacher_auth
    c = course(client, h)
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h).status_code == 422
    m = module(client, h, c["id"])
    l = lesson(client, h, m["id"])["id"]
    block(client, h, l, "text", {"markdown": "visible"})
    hidden = client.post(f"/api/teach/lessons/{l}/blocks", json={"type": "text", "data": {"markdown": "teacher only"}, "is_visible": False}, headers=h).json()
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h).status_code == 422  # nothing published yet
    client.patch(f"/api/teach/lessons/{l}", json={"is_published": True}, headers=h)
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h).status_code == 422  # module draft
    client.patch(f"/api/teach/modules/{m['id']}", json={"is_published": True}, headers=h)
    paid = course(client, h, title="Paid", enrollment_type="paid", price_amount="0")
    assert client.post(f"/api/teach/courses/{paid['id']}/status", json={"status": "published"}, headers=h).status_code == 422
    r = client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["published_at"]
    # cannot break a live course
    assert client.patch(f"/api/teach/lessons/{l}", json={"is_published": False}, headers=h).status_code == 409
    assert client.delete(f"/api/teach/lessons/{l}", headers=h).status_code == 409
    # preview shows drafts to the teacher; lesson preview hides hidden blocks
    pv = client.get(f"/api/teach/courses/{c['id']}/preview", headers=h).json()
    assert pv["preview"] and pv["curriculum"][0]["lessons"][0]["id"] == l
    lp = client.get(f"/api/teach/lessons/{l}/preview", headers=h).json()
    assert len(lp["blocks"]) == 1 and hidden["id"] not in str(lp)
    client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "draft"}, headers=h)
    assert client.patch(f"/api/teach/lessons/{l}", json={"is_published": False}, headers=h).status_code == 200


def test_cannot_delete_course_with_enrollments(client, teacher_auth, student_auth):
    c = course(client, teacher_auth)
    enroll("s1@example.com", c["id"])
    assert client.delete(f"/api/teach/courses/{c['id']}", headers=teacher_auth).status_code == 409
    client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "archived"}, headers=teacher_auth)


# ---------------- student access (foundation for phase 3) ----------------
def _published_course(client, h, title="Course A"):
    c = course(client, h, title=title)
    m = module(client, h, c["id"])
    l = lesson(client, h, m["id"])["id"]
    block(client, h, l, "text", {"markdown": "lesson body"})
    client.patch(f"/api/teach/lessons/{l}", json={"is_published": True}, headers=h)
    client.patch(f"/api/teach/modules/{m['id']}", json={"is_published": True}, headers=h)
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h).status_code == 200
    draft = lesson(client, h, m["id"], "Draft lesson")["id"]
    return c["id"], l, draft


def test_student_access_requires_valid_enrollment(client, teacher_auth, student_auth, student2_auth):
    cid, lid, draft = _published_course(client, teacher_auth)
    # account alone grants nothing
    assert client.get("/api/student/courses", headers=student_auth).json() == []
    for url in (f"/api/student/courses/{cid}", f"/api/student/lessons/{lid}"):
        assert client.get(url, headers=student_auth).status_code == 404
    enroll("s1@example.com", cid)
    assert [c["id"] for c in client.get("/api/student/courses", headers=student_auth).json()] == [cid]
    detail = client.get(f"/api/student/courses/{cid}", headers=student_auth).json()
    lessons = detail["curriculum"][0]["lessons"]
    assert [x["id"] for x in lessons] == [lid]  # the draft lesson is not listed
    assert "owner_id" not in detail and "price_amount" in detail
    body = client.get(f"/api/student/lessons/{lid}", headers=student_auth).json()
    assert body["blocks"][0]["data"]["markdown"] == "lesson body"
    assert client.get(f"/api/student/lessons/{draft}", headers=student_auth).status_code == 404   # unpublished
    # another student, enrolled nowhere, gets nothing (IDOR)
    assert client.get(f"/api/student/courses/{cid}", headers=student2_auth).status_code == 404
    assert client.get(f"/api/student/lessons/{lid}", headers=student2_auth).status_code == 404
    # random ids look identical to forbidden ones
    assert client.get(f"/api/student/lessons/{uuid.uuid4()}", headers=student_auth).status_code == 404


def test_enrollment_status_dates_and_course_status_gate_access(client, teacher_auth, student_auth):
    cid, lid, _ = _published_course(client, teacher_auth)
    db = SessionLocal()
    sid = db.scalar(select(User.id).where(User.email == "s1@example.com"))
    db.close()
    cases = {"pending": {}, "suspended": {}, "cancelled": {}, "expired": {},
             "active-expired-date": {"expires_at": utcnow() - timedelta(days=1)},
             "active-future-start": {"starts_at": utcnow() + timedelta(days=1)}}
    for name, extra in cases.items():
        db = SessionLocal()
        for e in db.scalars(select(LmsEnrollment)):
            db.delete(e)
        db.commit()
        db.add(LmsEnrollment(student_id=sid, course_id=uuid.UUID(cid), source="manual",
                             status="active" if name.startswith("active") else name, **extra))
        db.commit()
        db.close()
        assert client.get(f"/api/student/lessons/{lid}", headers=student_auth).status_code == 404, name
        assert client.get("/api/student/courses", headers=student_auth).json() == [], name
    for name, status_, extra in (("active", "active", {}), ("completed", "completed", {}), ("future expiry", "active", {"expires_at": utcnow() + timedelta(days=5)})):
        db = SessionLocal()
        for e in db.scalars(select(LmsEnrollment)):
            db.delete(e)
        db.commit()
        db.add(LmsEnrollment(student_id=sid, course_id=uuid.UUID(cid), source="manual", status=status_, **extra))
        db.commit()
        db.close()
        assert client.get(f"/api/student/lessons/{lid}", headers=student_auth).status_code == 200, name
    # unpublishing the course (or archiving) removes access immediately, enrollment untouched
    client.post(f"/api/teach/courses/{cid}/status", json={"status": "archived"}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{lid}", headers=student_auth).status_code == 404
    assert client.get("/api/student/courses", headers=student_auth).json() == []


def test_teacher_cannot_use_student_routes_and_students_cannot_preview(client, teacher_auth, student_auth):
    cid, lid, _ = _published_course(client, teacher_auth)
    assert client.get("/api/student/courses", headers=teacher_auth).status_code == 403
    assert client.get(f"/api/teach/courses/{cid}/preview", headers=student_auth).status_code == 403
    assert client.get(f"/api/teach/lessons/{lid}/preview", headers=student_auth).status_code == 403


def test_student_file_access_is_bound_to_enrollment(client, teacher_auth, student_auth, student2_auth):
    h = teacher_auth
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 30
    att = client.post("/api/attachments", files={"file": ("a.png", png, "image/png")}, headers=h).json()["id"]
    secret = client.post("/api/attachments", files={"file": ("b.png", png, "image/png")}, headers=h).json()["id"]
    cid, lid, draft = _published_course(client, h)
    block(client, h, lid, "image", {"attachment_id": att})
    block(client, h, draft, "image", {"attachment_id": secret})                      # only in an unpublished lesson
    block(client, h, lid, "text", {"markdown": f"![x](/api/attachments/{att}/file)"})  # markdown reference
    enroll("s1@example.com", cid)
    ok = client.get(f"/api/student/files/{att}", headers=student_auth)
    assert ok.status_code == 200 and ok.content == png
    assert client.get(f"/api/student/files/{secret}", headers=student_auth).status_code == 404   # draft lesson
    assert client.get(f"/api/student/files/{att}", headers=student2_auth).status_code == 404     # not enrolled
    assert client.get(f"/api/attachments/{att}/file", headers=student_auth).status_code == 403   # teacher endpoint
    assert client.get(f"/api/student/files/{uuid.uuid4()}", headers=student_auth).status_code == 404


# ---------------- uploaded videos ----------------
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8 + bytes(range(256)) * 40   # 10 KB, valid 'ftyp' header


def test_video_upload_signed_playback_and_range(client, teacher_auth, teacher2_auth, student_auth, student2_auth):
    h = teacher_auth
    up = client.post("/api/teach/videos", files={"file": ("lecture.mp4", MP4, "video/mp4")}, headers=h)
    assert up.status_code == 201, up.text
    vid = up.json()["id"]
    # validation: type, content, auth, ownership
    assert client.post("/api/teach/videos", files={"file": ("x.avi", MP4, "video/x-msvideo")}, headers=h).status_code == 415
    assert client.post("/api/teach/videos", files={"file": ("fake.mp4", b"not a video at all", "video/mp4")}, headers=h).status_code == 415
    assert client.post("/api/teach/videos", files={"file": ("a.mp4", MP4, "video/mp4")}, headers=student_auth).status_code == 403
    cid, lid, _ = _published_course(client, h)
    other = lesson(client, teacher2_auth, module(client, teacher2_auth, course(client, teacher2_auth)["id"])["id"])["id"]
    block(client, teacher2_auth, other, "video", {"attachment_id": vid}, expect=422)           # someone else's video
    block(client, h, lid, "video", {}, expect=422)                                             # nothing provided
    b = block(client, h, lid, "video", {"attachment_id": vid, "title": "Lecture"})
    assert b["data"]["resolved"]["kind"] == "upload" and "playback_url" in b["data"]
    # editing round-trips the decorated data without error (derived fields are ignored)
    assert client.patch(f"/api/teach/blocks/{b['id']}", json={"data": b["data"]}, headers=h).status_code == 200
    # a student gets a playback URL only once enrolled
    assert client.get(f"/api/student/lessons/{lid}", headers=student_auth).status_code == 404
    enroll("s1@example.com", cid)
    blocks = client.get(f"/api/student/lessons/{lid}", headers=student_auth).json()["blocks"]
    url = next(x["data"]["playback_url"] for x in blocks if x["type"] == "video")
    # playback works without any bearer header, supports ranges, and rejects bad/mismatched tokens
    full = client.get(url)
    assert full.status_code == 200 and full.content == MP4 and full.headers["accept-ranges"] == "bytes"
    part = client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == MP4[100:200] and part.headers["content-range"] == f"bytes 100-199/{len(MP4)}"
    assert client.get(url, headers={"Range": "bytes=-50"}).content == MP4[-50:]
    assert client.get(url, headers={"Range": "bytes=999999-"}).status_code == 416
    assert client.get(f"/api/media/video/{vid}?t=garbage").status_code == 401
    assert client.get(f"/api/media/video/{vid}").status_code == 401
    other_vid = client.post("/api/teach/videos", files={"file": ("b.webm", b"\x1aE\xdf\xa3" + b"\x00" * 50, "video/webm")}, headers=h).json()["id"]
    assert client.get(f"/api/media/video/{other_vid}?t={url.split('t=')[1]}").status_code == 401   # token bound to its attachment
    # a student who is not enrolled never receives a token
    assert client.get(f"/api/student/lessons/{lid}", headers=student2_auth).status_code == 404
