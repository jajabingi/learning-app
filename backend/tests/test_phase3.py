import uuid
from datetime import timedelta

from app.core.db import SessionLocal
from app.models.base import utcnow
from app.models.lms import LmsEnrollment
from tests.test_lms import _published_course, block, course, lesson, module
from sqlalchemy import select


def lookup(client, h, email):
    r = client.get("/api/teach/students/lookup", params={"email": email}, headers=h)
    return r


def enroll(client, h, student_email, cid, **kw):
    sid = lookup(client, h, student_email).json()["id"]
    r = client.post("/api/teach/enrollments", json={"student_id": sid, "course_id": cid, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def two_lessons(client, h, title="Course A", rule=None):
    c = course(client, h, title=title, **({"completion_rule": rule} if rule else {}))
    m = module(client, h, c["id"])
    ls = [lesson(client, h, m["id"], f"Lesson {i}")["id"] for i in (1, 2)]
    for l in ls:
        block(client, h, l, "text", {"markdown": "body"})
        client.patch(f"/api/teach/lessons/{l}", json={"is_published": True}, headers=h)
    client.patch(f"/api/teach/modules/{m['id']}", json={"is_published": True}, headers=h)
    assert client.post(f"/api/teach/courses/{c['id']}/status", json={"status": "published"}, headers=h).status_code == 200
    return c["id"], ls


# ---------------- teacher: enrollments & students ----------------
def test_teacher_enrolls_suspends_extends_and_student_access_follows(client, teacher_auth, student_auth):
    cid, (l1, _) = two_lessons(client, teacher_auth)
    assert client.get("/api/student/courses", headers=student_auth).json() == []
    e = enroll(client, teacher_auth, "s1@example.com", cid, notes="paid cash")
    assert e["status"] == "active" and e["source"] == "manual"
    assert len(client.get("/api/student/courses", headers=student_auth).json()) == 1
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 200
    # suspend -> immediately blocked; reactivate; cancel
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "suspended"}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 404
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "active"}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 200
    past = (utcnow() - timedelta(days=1)).isoformat()
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"expires_at": past}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 404
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"expires_at": (utcnow() + timedelta(days=30)).isoformat()}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 200
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "cancelled"}, headers=teacher_auth)
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 404
    # re-enrolling updates the same enrollment (one per student+course)
    e2 = enroll(client, teacher_auth, "s1@example.com", cid)
    assert e2["id"] == e["id"] and e2["status"] == "active"
    # validation
    sid = lookup(client, teacher_auth, "s1@example.com").json()["id"]
    bad = client.post("/api/teach/enrollments", json={"student_id": sid, "course_id": cid, "expires_at": past}, headers=teacher_auth)
    assert bad.status_code == 422
    assert lookup(client, teacher_auth, "nobody@example.com").status_code == 404
    assert lookup(client, teacher_auth, "t1@example.com").status_code == 404   # staff accounts are not enrollable students


def test_access_days_sets_default_expiry(client, teacher_auth, student_auth):
    c = course(client, teacher_auth, access_days=30)
    e = enroll(client, teacher_auth, "s1@example.com", c["id"])
    assert e["expires_at"] is not None


def test_teacher_isolation_for_students_and_enrollments(client, teacher_auth, teacher2_auth, student_auth, student2_auth):
    c1, _ = two_lessons(client, teacher_auth, "T1 course")
    c2, _ = two_lessons(client, teacher2_auth, "T2 course")
    e1 = enroll(client, teacher_auth, "s1@example.com", c1)
    enroll(client, teacher2_auth, "s2@example.com", c2)
    mine = client.get("/api/teach/students", headers=teacher_auth).json()
    assert [s["email"] for s in mine] == ["s1@example.com"]
    s2_id = lookup(client, teacher_auth, "s2@example.com").json()["id"]
    s1_id = mine[0]["id"]
    assert client.get(f"/api/teach/students/{s2_id}", headers=teacher_auth).status_code == 404   # another teacher's student
    assert client.get(f"/api/teach/students/{s1_id}", headers=teacher_auth).status_code == 200
    # cannot enrol into, list, or modify another teacher's course/enrollment
    assert client.post("/api/teach/enrollments", json={"student_id": s1_id, "course_id": c2}, headers=teacher_auth).status_code == 404
    assert client.get(f"/api/teach/courses/{c2}/enrollments", headers=teacher_auth).status_code == 404
    assert client.patch(f"/api/teach/enrollments/{e1['id']}", json={"status": "suspended"}, headers=teacher2_auth).status_code == 404


def test_enrollment_permissions(client, admin_auth, teacher_auth, student_auth):
    t = next(u for u in client.get("/api/admin/users", headers=admin_auth).json() if u["email"] == "t1@example.com")
    cid, _ = two_lessons(client, teacher_auth)
    client.patch(f"/api/admin/users/{t['id']}", json={"permissions": ["courses.manage", "courses.publish", "students.manage"]}, headers=admin_auth)
    assert lookup(client, teacher_auth, "s1@example.com").status_code == 403       # needs enrollments.manage
    assert client.get("/api/teach/students", headers=teacher_auth).status_code == 200


# ---------------- student: progress ----------------
def test_progress_is_explicit_and_completion_follows_rule(client, teacher_auth, student_auth):
    cid, (l1, l2) = two_lessons(client, teacher_auth)
    e = enroll(client, teacher_auth, "s1@example.com", cid)
    H = student_auth
    # opening a lesson does not complete it
    assert client.post(f"/api/student/lessons/{l1}/progress", json={"seconds": 40}, headers=H).json()["time_spent_seconds"] == 40
    client.post(f"/api/student/lessons/{l1}/progress", json={"seconds": 20}, headers=H)
    assert client.post(f"/api/student/lessons/{l1}/progress", json={"seconds": 100000}, headers=H).status_code == 422   # cannot inflate time
    c = client.get(f"/api/student/courses/{cid}", headers=H).json()
    assert c["progress"]["percent"] == 0 and c["progress"]["time_spent_seconds"] == 60 and c["progress"]["resume_lesson_id"] == l1
    assert client.get(f"/api/student/lessons/{l1}", headers=H).json()["completed"] is False
    # complete lesson 1 -> 50%, course not complete
    r = client.post(f"/api/student/lessons/{l1}/complete", json={}, headers=H).json()
    assert r["course_percent"] == 50 and r["course_completed"] is False and r["next_lesson_id"] == l2
    assert client.get(f"/api/student/courses/{cid}", headers=H).json()["curriculum"][0]["lessons"][0]["completed"] is True
    # complete lesson 2 -> course completed, access continues
    r = client.post(f"/api/student/lessons/{l2}/complete", json={}, headers=H).json()
    assert r["course_percent"] == 100 and r["course_completed"] is True
    assert client.get(f"/api/student/lessons/{l1}", headers=H).status_code == 200
    me = client.get(f"/api/teach/courses/{cid}/enrollments", headers=teacher_auth).json()[0]
    assert me["status"] == "completed" and me["completed_at"] and me["progress"]["percent"] == 100
    # un-completing reverts the status
    client.post(f"/api/student/lessons/{l2}/complete", json={"completed": False}, headers=H)
    assert client.get(f"/api/teach/courses/{cid}/enrollments", headers=teacher_auth).json()[0]["status"] == "active"
    # a suspended enrollment is never flipped by progress
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "suspended"}, headers=teacher_auth)
    assert client.post(f"/api/student/lessons/{l2}/complete", json={}, headers=H).status_code == 404


def test_completion_rule_threshold(client, teacher_auth, student_auth):
    cid, (l1, l2) = two_lessons(client, teacher_auth, rule={"min_lesson_percent": 50, "require_quizzes": False})
    enroll(client, teacher_auth, "s1@example.com", cid)
    r = client.post(f"/api/student/lessons/{l1}/complete", json={}, headers=student_auth).json()
    assert r["course_completed"] is True


def test_progress_is_private_and_access_checked(client, teacher_auth, student_auth, student2_auth):
    cid, (l1, _) = two_lessons(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)
    client.post(f"/api/student/lessons/{l1}/complete", json={}, headers=student_auth)
    # student 2 (not enrolled) cannot read or write progress on that lesson
    assert client.post(f"/api/student/lessons/{l1}/complete", json={}, headers=student2_auth).status_code == 404
    assert client.post(f"/api/student/lessons/{l1}/progress", json={"seconds": 5}, headers=student2_auth).status_code == 404
    enroll(client, teacher_auth, "s2@example.com", cid)
    assert client.get(f"/api/student/courses/{cid}", headers=student2_auth).json()["progress"]["completed_lessons"] == 0   # own progress only
    # a student cannot supply a student id anywhere: the API has no such parameter, and teacher endpoints are forbidden
    s1_id = lookup(client, teacher_auth, "s1@example.com").json()["id"]
    assert client.get(f"/api/teach/students/{s1_id}", headers=student2_auth).status_code == 403
    prof = client.get(f"/api/teach/students/{s1_id}", headers=teacher_auth).json()
    assert prof["enrollments"][0]["progress"]["completed_lessons"] == 1 and prof["activity"][0]["lesson_title"] == "Lesson 1"


def test_dashboard_continue_and_resume(client, teacher_auth, student_auth):
    cid, (l1, l2) = two_lessons(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)
    d = client.get("/api/student/dashboard", headers=student_auth).json()
    assert d["continue_learning"]["lesson_id"] == l1 and d["totals"]["courses"] == 1   # nothing started: first lesson
    client.post(f"/api/student/lessons/{l1}/complete", json={}, headers=student_auth)
    client.post(f"/api/student/lessons/{l2}/progress", json={"seconds": 10}, headers=student_auth)
    d = client.get("/api/student/dashboard", headers=student_auth).json()
    assert d["continue_learning"]["lesson_id"] == l2 and d["continue_learning"]["percent"] == 50
    assert d["totals"]["lessons_completed"] == 1 and d["totals"]["time_spent_seconds"] == 10


# ---------------- catalog & self enrollment ----------------
def test_catalog_hides_unpublished_and_content(client, teacher_auth, student_auth):
    cid, (l1, _) = two_lessons(client, teacher_auth, "Published one")
    draft = course(client, teacher_auth, title="Draft one")
    cat = client.get("/api/student/catalog", headers=student_auth).json()
    assert [c["title"] for c in cat] == ["Published one"]
    assert client.get(f"/api/student/catalog/{draft['id']}", headers=student_auth).status_code == 404
    d = client.get(f"/api/student/catalog/{cid}", headers=student_auth).json()
    assert d["has_access"] is False and d["can_self_enroll"] is False   # manual course
    text = str(d)
    assert "body" not in text and "blocks" not in text and "owner_id" not in text                 # outline only
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 404     # catalog is not access


def test_self_enroll_only_for_free_courses(client, teacher_auth, student_auth):
    free_id, (fl, _) = two_lessons(client, teacher_auth, "Free course")
    client.patch(f"/api/teach/courses/{free_id}", json={"enrollment_type": "free", "price_amount": "0"}, headers=teacher_auth)
    paid_id, _ = two_lessons(client, teacher_auth, "Paid course")
    client.patch(f"/api/teach/courses/{paid_id}", json={"enrollment_type": "paid", "price_amount": "100"}, headers=teacher_auth)
    manual_id, _ = two_lessons(client, teacher_auth, "Manual course")
    H = student_auth
    for cid in (paid_id, manual_id):
        assert client.post(f"/api/student/courses/{cid}/enroll", headers=H).status_code == 403
    assert client.post(f"/api/student/courses/{uuid.uuid4()}/enroll", headers=H).status_code == 404
    assert client.get(f"/api/student/lessons/{fl}", headers=H).status_code == 404
    assert client.post(f"/api/student/courses/{free_id}/enroll", headers=H).status_code == 201
    assert client.post(f"/api/student/courses/{free_id}/enroll", headers=H).status_code == 201   # idempotent
    assert client.get(f"/api/student/lessons/{fl}", headers=H).status_code == 200
    # a teacher-suspended student cannot re-enrol themselves
    e = client.get(f"/api/teach/courses/{free_id}/enrollments", headers=teacher_auth).json()[0]
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "suspended"}, headers=teacher_auth)
    assert client.post(f"/api/student/courses/{free_id}/enroll", headers=H).status_code == 409
    assert client.get(f"/api/student/lessons/{fl}", headers=H).status_code == 404


def test_free_preview_lessons(client, teacher_auth, student_auth):
    cid, (l1, l2) = two_lessons(client, teacher_auth)
    client.patch(f"/api/teach/lessons/{l1}", json={"is_free_preview": True}, headers=teacher_auth)
    assert client.get(f"/api/student/catalog/{cid}/preview/{l1}", headers=student_auth).status_code == 200
    assert client.get(f"/api/student/catalog/{cid}/preview/{l2}", headers=student_auth).status_code == 404   # not flagged
    client.patch(f"/api/teach/lessons/{l1}", json={"is_published": False}, headers=teacher_auth)
    assert client.get(f"/api/student/catalog/{cid}/preview/{l1}", headers=student_auth).status_code == 404
    other, (ol, _) = two_lessons(client, teacher_auth, "Other")
    assert client.get(f"/api/student/catalog/{other}/preview/{l2}", headers=student_auth).status_code == 404   # lesson of another course
