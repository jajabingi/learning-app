from app.services import course_templates as ct


def test_template_list_and_shapes(client, teacher_auth):
    r = client.get("/api/teach/course-templates", headers=teacher_auth)
    assert r.status_code == 200
    ids = {t["id"]: t for t in r.json()}
    assert set(ids) == {"academic", "short", "exam_prep"}
    assert ids["short"]["modules"] == 1 and ids["short"]["lessons"] == 3
    assert ids["academic"]["modules"] == 5 and ids["academic"]["lessons"] == 12 and len(ids["academic"]["outline"]) == 5


def test_every_template_block_is_valid(client, teacher_auth):
    """A template that cannot be created would be a broken product: create each one for real."""
    for t in ct.TEMPLATES:
        r = client.post("/api/teach/courses/from-template", json={"template_id": t["id"], "title": f"קורס {t['id']}"}, headers=teacher_auth)
        assert r.status_code == 201, (t["id"], r.text)


def test_create_from_template_builds_an_unpublished_draft(client, teacher_auth, student_auth):
    r = client.post("/api/teach/courses/from-template", json={"template_id": "short", "title": "NPV בקצרה", "subtitle": "שלושה שיעורים"}, headers=teacher_auth)
    c = r.json()
    assert c["title"] == "NPV בקצרה" and c["status"] == "draft" and c["module_count"] == 1 and c["lesson_count"] == 3
    assert c["published_lesson_count"] == 0 and c["language"] == "עברית"
    full = client.get(f"/api/teach/courses/{c['id']}", headers=teacher_auth).json()
    mod = full["curriculum"][0]
    assert mod["is_published"] is False and [l["title"] for l in mod["lessons"]] == ["שיעור 1: הבסיס", "שיעור 2: העמקה", "שיעור 3: יישום וסיכום"]
    assert mod["lessons"][0]["is_free_preview"] is True and not any(l["is_published"] for l in mod["lessons"])
    lesson = client.get(f"/api/teach/lessons/{mod['lessons'][0]['id']}", headers=teacher_auth).json()
    assert [b["type"] for b in lesson["blocks"]] == ["callout", "text", "formula", "example", "summary"]       # goals, explanation, formula, example, summary
    assert "[להשלמה]" in lesson["blocks"][1]["data"]["markdown"]                                               # placeholders are marked
    # it is the teacher's own draft: students cannot see it, and other teachers cannot touch it
    assert client.get(f"/api/student/courses/{c['id']}", headers=student_auth).status_code == 404


def test_template_validation_and_isolation(client, teacher_auth, teacher2_auth, student_auth):
    ok = client.post("/api/teach/courses/from-template", json={"template_id": "exam_prep", "title": "הכנה"}, headers=teacher_auth).json()
    assert client.post("/api/teach/courses/from-template", json={"template_id": "nope", "title": "x"}, headers=teacher_auth).status_code == 404
    assert client.post("/api/teach/courses/from-template", json={"template_id": "short", "title": ""}, headers=teacher_auth).status_code == 422
    assert client.post("/api/teach/courses/from-template", json={"template_id": "short"}, headers=teacher_auth).status_code == 422
    assert client.get(f"/api/teach/courses/{ok['id']}", headers=teacher2_auth).status_code == 404
    assert client.get("/api/teach/courses", headers=teacher2_auth).json() == []
    assert client.get("/api/teach/course-templates", headers=student_auth).status_code == 403
    assert client.post("/api/teach/courses/from-template", json={"template_id": "short", "title": "x"}, headers=student_auth).status_code == 403
    assert client.get("/api/teach/course-templates").status_code == 401
    assert client.post("/api/teach/courses/from-template", json={"template_id": "short", "title": "x"}).status_code == 401
