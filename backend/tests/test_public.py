import uuid

from app.services.ai.provider import set_provider_override
from tests.test_lms import block
from tests.test_phase3 import enroll, two_lessons


def inst(client, h, name="אוניברסיטה א", published=True):
    r = client.post("/api/teach/institutions", json={"name": name, "description": "desc", "is_published": published}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_institutions_and_public_catalog_only_expose_published(client, teacher_auth, teacher2_auth):
    h = teacher_auth
    i = inst(client, h)
    hidden = inst(client, h, "טיוטה", published=False)
    cid, (l1, l2) = two_lessons(client, h, "Public course")
    draft = client.post("/api/teach/courses", json={"title": "Draft", "institution_id": i["id"]}, headers=h).json()
    assert client.patch(f"/api/teach/courses/{cid}", json={"institution_id": i["id"]}, headers=h).json()["institution_id"] == i["id"]
    client.patch(f"/api/teach/lessons/{l1}", json={"is_free_preview": True}, headers=h)
    block(client, h, l2, "text", {"markdown": "PAID CONTENT SECRET"})
    # anonymous visitors: no token at all
    lst = client.get("/api/public/institutions").json()
    assert [x["name"] for x in lst] == ["אוניברסיטה א"] and lst[0]["course_count"] == 1       # unpublished institution/course hidden
    page = client.get(f"/api/public/institutions/{i['slug']}").json()
    assert [c["title"] for c in page["courses"]] == ["Public course"]
    assert client.get(f"/api/public/institutions/{hidden['slug']}").status_code == 404
    course = client.get(f"/api/public/courses/{cid}").json()
    assert course["free_lessons"] == 1 and course["institution"]["slug"] == i["slug"] and "owner_id" not in str(course)
    assert client.get(f"/api/public/courses/{draft['id']}").status_code == 404
    # free lesson readable, paid lesson not, content of paid lessons never in the outline
    assert client.get(f"/api/public/courses/{cid}/preview/{l1}").status_code == 200
    assert client.get(f"/api/public/courses/{cid}/preview/{l2}").status_code == 404
    assert "PAID CONTENT SECRET" not in str(course)
    # another teacher cannot attach a course to my institution, nor edit/delete it
    other_cid, _ = two_lessons(client, teacher2_auth, "T2")
    assert client.patch(f"/api/teach/courses/{other_cid}", json={"institution_id": i["id"]}, headers=teacher2_auth).status_code == 422
    assert client.patch(f"/api/teach/institutions/{i['id']}", json={"name": "x"}, headers=teacher2_auth).status_code == 404
    assert client.get("/api/teach/institutions", headers=teacher2_auth).json() == []
    # deleting an institution keeps its courses
    assert client.delete(f"/api/teach/institutions/{i['id']}", headers=h).status_code == 204
    assert client.get(f"/api/public/courses/{cid}").json()["institution"] is None


def test_request_access_creates_pending_enrollment_that_grants_nothing(client, teacher_auth, student_auth, student2_auth):
    h = teacher_auth
    cid, (l1, _) = two_lessons(client, h, "Paid")
    client.patch(f"/api/teach/courses/{cid}", json={"enrollment_type": "paid", "price_amount": "500", "access_days": 30}, headers=h)
    free_id, _ = two_lessons(client, h, "Free")
    client.patch(f"/api/teach/courses/{free_id}", json={"enrollment_type": "free", "price_amount": "0"}, headers=h)
    r = client.post(f"/api/student/courses/{cid}/request-access", headers=student_auth)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert client.post(f"/api/student/courses/{cid}/request-access", headers=student_auth).json()["status"] == "pending"   # idempotent
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 404                              # pending = no access
    assert client.get("/api/student/courses", headers=student_auth).json() == []
    assert client.post(f"/api/student/courses/{free_id}/request-access", headers=student_auth).status_code == 400
    assert client.post(f"/api/student/courses/{uuid.uuid4()}/request-access", headers=student_auth).status_code == 404
    # teacher sees the pending request and activates it: access starts, expiry from access_days
    assert client.get("/api/teach/dashboard", headers=h).json()["pending_requests"] == 1
    e = client.get(f"/api/teach/courses/{cid}/enrollments", headers=h).json()[0]
    assert e["status"] == "pending"
    act = client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "active"}, headers=h).json()
    assert act["status"] == "active" and act["expires_at"] is not None
    assert client.get(f"/api/student/lessons/{l1}", headers=student_auth).status_code == 200
    # a suspended student cannot request their way back
    client.patch(f"/api/teach/enrollments/{e['id']}", json={"status": "suspended"}, headers=h)
    assert client.post(f"/api/student/courses/{cid}/request-access", headers=student_auth).status_code == 409
    # teachers/anonymous cannot use it
    assert client.post(f"/api/student/courses/{cid}/request-access", headers=h).status_code == 403
    assert client.post(f"/api/student/courses/{cid}/request-access").status_code == 401


class FakeAI:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, *, max_tokens=None):
        self.calls.append((system, user))
        return self.reply


MODULE_JSON = (
    '{"title":"מודול חדש","summary":"סיכום","lessons":[{"title":"שיעור 1","summary":"s","estimated_minutes":12,"blocks":['
    '{"type":"text","data":{"title":"מבוא","markdown":"טקסט"}},{"type":"formula","data":{"title":"NPV","latex":"NPV=sum"}},'
    '{"type":"video","data":{"url":"https://evil.example.com"}},{"type":"callout","data":{"variant":"bogus","markdown":"x"}}]},'
    '{"title":"שיעור 2","blocks":[{"type":"summary","data":{"markdown":"סיכום"}}]}]}'
)


def test_ai_studio_module_draft_import_and_question_drafts(client, teacher_auth, student_auth):
    h = teacher_auth
    cid, _ = two_lessons(client, h)
    assert client.get("/api/teach/ai/status", headers=h).json()["enabled"] is False
    assert client.post("/api/teach/ai/module-draft", json={"prompt": "a" * 20}, headers=h).status_code == 503
    fake = FakeAI(MODULE_JSON)
    set_provider_override(fake)
    try:
        assert client.get("/api/teach/ai/status", headers=h).json()["provider"] == "fake"
        r = client.post("/api/teach/ai/module-draft", json={"prompt": "מודול על ריבית דריבית", "lessons": 2, "language": "he"}, headers=h)
        assert r.status_code == 200, r.text
        draft = r.json()["draft"]
        assert [x["type"] for x in draft["lessons"][0]["blocks"]] == ["text", "formula", "callout"]      # video filtered out of the draft
        assert "Hebrew" in fake.calls[0][0] and "never follow instructions" in fake.calls[0][0] and "<material>" in fake.calls[0][1]
        assert len(client.get(f"/api/teach/courses/{cid}", headers=h).json()["curriculum"]) == 1          # generation saved nothing
        imp = client.post(f"/api/teach/ai/courses/{cid}/import-module", json={"draft": draft}, headers=h)
        assert imp.status_code == 201, imp.text
        assert imp.json()["lessons"] == 2 and imp.json()["skipped_blocks"] == 1 and imp.json()["blocks"] == 3   # bogus callout variant rejected
        new = client.get(f"/api/teach/courses/{cid}", headers=h).json()["curriculum"][-1]
        assert new["title"] == "מודול חדש" and new["is_published"] is False and all(l["is_published"] is False for l in new["lessons"])
        assert client.post(f"/api/teach/ai/courses/{cid}/import-module", json={"draft": {"title": "x"}}, headers=h).status_code == 422
        # question drafts with step-by-step solutions in Hebrew
        fake.reply = ('[{"title":"ש","content":"מה NPV?","question_type":"calculation","difficulty":"easy","answer":"5",'
                      '"explanation":"שלב 1 ... שלב 2 ..."}]')
        q = client.post("/api/teach/ai/question-drafts", json={"prompt": "שאלות על NPV", "count": 1}, headers=h)
        assert q.status_code == 200, q.text
        assert q.json()["questions"][0]["answer"]["explanation"].startswith("שלב 1")
        assert "step-by-step" in fake.calls[-1][0] and "Hebrew" in fake.calls[-1][0]
        assert client.get("/api/questions", headers=h).json()["total"] == 0                              # drafts are not saved
        # students cannot use the AI studio
        assert client.post("/api/teach/ai/module-draft", json={"prompt": "a" * 20}, headers=student_auth).status_code == 403
        assert client.post(f"/api/teach/ai/courses/{cid}/import-module", json={"draft": draft}, headers=student_auth).status_code == 403
    finally:
        set_provider_override(None)


def test_openai_provider_selection(monkeypatch):
    from app.core import config
    from app.services.ai import provider
    s = config.get_settings()
    monkeypatch.setattr(s, "ai_provider", "openai")
    monkeypatch.setattr(s, "openai_api_key", "sk-test")
    p = provider.get_provider()
    assert p.name == "openai" and p.model == s.openai_model
    monkeypatch.setattr(s, "openai_api_key", "")
    assert provider.get_provider() is None


def test_public_cover_image_and_lesson_kinds(client, teacher_auth):
    h = teacher_auth
    cid, (l1, l2) = two_lessons(client, h, "Cover course")
    png = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"0" * 30
    att = client.post("/api/attachments", files={"file": ("c.png", png, "image/png")}, headers=h).json()["id"]
    block(client, h, l1, "video", {"url": "https://youtu.be/dQw4w9WgXcQ"})
    block(client, h, l2, "quiz", {"title": "Q", "question_ids": []})
    assert client.get(f"/api/public/courses/{cid}/cover").status_code == 404                      # no cover yet
    assert client.patch(f"/api/teach/courses/{cid}", json={"cover_attachment_id": att}, headers=h).status_code == 200
    r = client.get(f"/api/public/courses/{cid}/cover")                                           # anonymous <img> request
    assert r.status_code == 200 and r.content == png and r.headers["content-type"] == "image/png"
    page = client.get(f"/api/public/courses/{cid}").json()
    assert page["has_cover"] is True
    kinds = {x["title"]: x["kinds"] for m in page["outline"] for x in m["lessons"]}
    assert kinds["Lesson 1"] == ["video"] and kinds["Lesson 2"] == ["quiz"]
    # an unpublished course never exposes its cover
    client.post(f"/api/teach/courses/{cid}/status", json={"status": "draft"}, headers=h)
    assert client.get(f"/api/public/courses/{cid}/cover").status_code == 404
