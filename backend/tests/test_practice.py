import uuid

from tests.test_phase3 import enroll, two_lessons


def bank_question(client, h, title, answer, explanation, options=None, qtype="calculation"):
    body = {"title": title, "content": f"Content of {title}", "question_type": qtype,
            "answer": {"answer": answer, "explanation": explanation}, "options": options or []}
    r = client.post("/api/questions", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def make_set(client, h, cid, qids, publish=True, title="NPV practice"):
    s = client.post(f"/api/teach/courses/{cid}/practice-sets", json={"title": title, "description": "topic"}, headers=h).json()
    r = client.post(f"/api/teach/practice-sets/{s['id']}/items", json={"question_ids": qids}, headers=h)
    assert r.status_code == 201, r.text
    if publish:
        assert client.patch(f"/api/teach/practice-sets/{s['id']}", json={"is_published": True}, headers=h).status_code == 200
    return s["id"]


def test_teacher_builds_sets_ownership_and_rules(client, teacher_auth, teacher2_auth):
    h, h2 = teacher_auth, teacher2_auth
    cid, _ = two_lessons(client, h)
    q1 = bank_question(client, h, "Q1", "42", "step 1\nstep 2")
    q2 = bank_question(client, h, "Q2", "7", "steps")
    s = client.post(f"/api/teach/courses/{cid}/practice-sets", json={"title": "Topic A"}, headers=h).json()
    assert client.patch(f"/api/teach/practice-sets/{s['id']}", json={"is_published": True}, headers=h).status_code == 422   # empty
    out = client.post(f"/api/teach/practice-sets/{s['id']}/items", json={"question_ids": [q1["id"], q2["id"], q1["id"]]}, headers=h).json()
    assert [i["title"] for i in out["items"]] == ["Q1", "Q2"]                                                            # de-duplicated, ordered
    ids = [i["id"] for i in out["items"]]
    assert client.post(f"/api/teach/practice-sets/{s['id']}/items/reorder", json={"ids": ids[::-1]}, headers=h).status_code == 204
    assert [i["title"] for i in client.get(f"/api/teach/courses/{cid}/practice-sets", headers=h).json()[0]["items"]] == ["Q2", "Q1"]
    # another teacher can neither see, edit, nor add their own questions to this course's set, nor use my questions
    q_other = bank_question(client, h2, "Other", "1", "x")
    for method, url, kw in (("get", f"/api/teach/courses/{cid}/practice-sets", {}), ("patch", f"/api/teach/practice-sets/{s['id']}", {"json": {"title": "x"}}),
                            ("delete", f"/api/teach/practice-sets/{s['id']}", {}), ("post", f"/api/teach/practice-sets/{s['id']}/items", {"json": {"question_ids": [q_other["id"]]}})):
        assert getattr(client, method)(url, headers=h2, **kw).status_code == 404, url
    other_cid, _ = two_lessons(client, h2, "T2")
    s2 = client.post(f"/api/teach/courses/{other_cid}/practice-sets", json={"title": "T2 set"}, headers=h2).json()
    assert client.post(f"/api/teach/practice-sets/{s2['id']}/items", json={"question_ids": [q1["id"]]}, headers=h2).status_code == 404  # not their bank
    # removing the last question un-publishes
    client.patch(f"/api/teach/practice-sets/{s['id']}", json={"is_published": True}, headers=h)
    for i in ids:
        client.delete(f"/api/teach/practice-items/{i}", headers=h)
    assert client.get(f"/api/teach/courses/{cid}/practice-sets", headers=h).json()[0]["is_published"] is False


def test_student_never_gets_answers_before_reveal(client, teacher_auth, student_auth):
    h = teacher_auth
    cid, _ = two_lessons(client, h)
    mc = bank_question(client, h, "MC", "T-bill", "Because it is risk free", qtype="multiple_choice",
                       options=[{"text": "T-bill", "is_correct": True}, {"text": "Stock", "is_correct": False}])
    calc = bank_question(client, h, "CALC", "FINAL-ANSWER-123", "STEP-BY-STEP-SOLUTION-456")
    sid = make_set(client, h, cid, [mc["id"], calc["id"]])
    assert client.get("/api/student/practice", headers=student_auth).json() == []          # not enrolled → nothing
    assert client.get(f"/api/student/practice/sets/{sid}", headers=student_auth).status_code == 404
    enroll(client, h, "s1@example.com", cid)
    ov = client.get("/api/student/practice", headers=student_auth).json()
    assert ov[0]["sets"][0]["total"] == 2 and ov[0]["sets"][0]["revealed"] == 0
    data = client.get(f"/api/student/practice/sets/{sid}", headers=student_auth).json()
    text = str(data)
    assert "FINAL-ANSWER-123" not in text and "STEP-BY-STEP-SOLUTION-456" not in text and "is_correct" not in str(data["items"][0]["question"])
    assert all(i["revealed"] is False and i["solution"] is None for i in data["items"])
    # reveal the calculation question: full solution delivered, recorded
    item = next(i for i in data["items"] if i["question"]["title"] == "CALC")
    r = client.post(f"/api/student/practice/items/{item['item_id']}/reveal", json={}, headers=student_auth).json()
    assert r["answer"] == "FINAL-ANSWER-123" and r["explanation"] == "STEP-BY-STEP-SOLUTION-456" and r["is_correct"] is None
    again = client.get(f"/api/student/practice/sets/{sid}", headers=student_auth).json()
    assert next(i for i in again["items"] if i["question"]["title"] == "CALC")["solution"]["explanation"] == "STEP-BY-STEP-SOLUTION-456"
    assert next(i for i in again["items"] if i["question"]["title"] == "MC")["solution"] is None        # others still hidden
    # multiple choice: correctness is computed server-side
    mc_item = next(i for i in data["items"] if i["question"]["title"] == "MC")
    wrong = next(o["id"] for o in mc_item["question"]["options"] if o["text"] == "Stock")
    r = client.post(f"/api/student/practice/items/{mc_item['item_id']}/reveal", json={"selected_option_ids": [wrong]}, headers=student_auth).json()
    assert r["is_correct"] is False and len(r["correct_option_ids"]) == 1
    # a second reveal does not change the recorded selection; reset allows another try
    right = next(o["id"] for o in mc_item["question"]["options"] if o["text"] == "T-bill")
    assert client.post(f"/api/student/practice/items/{mc_item['item_id']}/reveal", json={"selected_option_ids": [right]}, headers=student_auth).json()["is_correct"] is False
    assert client.post(f"/api/student/practice/items/{mc_item['item_id']}/reset", headers=student_auth).status_code == 204
    assert client.post(f"/api/student/practice/items/{mc_item['item_id']}/reveal", json={"selected_option_ids": [right]}, headers=student_auth).json()["is_correct"] is True
    assert client.post(f"/api/student/practice/items/{mc_item['item_id']}/reveal", json={"selected_option_ids": [str(uuid.uuid4())]}, headers=student_auth).status_code in (200, 422)
    ov = client.get("/api/student/practice", headers=student_auth).json()[0]["sets"][0]
    assert ov["revealed"] == 2 and ov["correct"] == 1


def test_practice_access_rules(client, teacher_auth, student_auth, student2_auth):
    h = teacher_auth
    cid, _ = two_lessons(client, h)
    q = bank_question(client, h, "Q", "ans", "steps")
    published = make_set(client, h, cid, [q["id"]], title="Published")
    draft = make_set(client, h, cid, [q["id"]], publish=False, title="Draft")
    enroll(client, h, "s1@example.com", cid)
    S, S2 = student_auth, student2_auth
    assert client.get(f"/api/student/practice/sets/{published}", headers=S).status_code == 200
    assert client.get(f"/api/student/practice/sets/{draft}", headers=S).status_code == 404          # unpublished set
    item = client.get(f"/api/student/practice/sets/{published}", headers=S).json()["items"][0]["item_id"]
    # not enrolled student: no listing, no set, no reveal, no reset (IDOR on item id)
    assert client.get("/api/student/practice", headers=S2).json() == []
    assert client.get(f"/api/student/practice/sets/{published}", headers=S2).status_code == 404
    assert client.post(f"/api/student/practice/items/{item}/reveal", json={}, headers=S2).status_code == 404
    assert client.post(f"/api/student/practice/items/{item}/reset", headers=S2).status_code == 404
    # student 2 enrolled sees their OWN progress only
    client.post(f"/api/student/practice/items/{item}/reveal", json={}, headers=S)
    enroll(client, h, "s2@example.com", cid)
    assert client.get(f"/api/student/practice/sets/{published}", headers=S2).json()["items"][0]["revealed"] is False
    # suspended / archived → access removed immediately, even for an already-revealed item
    e = client.get(f"/api/teach/courses/{cid}/enrollments", headers=h).json()
    mine = next(x for x in e if x["student"]["email"] == "s1@example.com")
    client.patch(f"/api/teach/enrollments/{mine['id']}", json={"status": "suspended"}, headers=h)
    assert client.get(f"/api/student/practice/sets/{published}", headers=S).status_code == 404
    assert client.post(f"/api/student/practice/items/{item}/reveal", json={}, headers=S).status_code == 404
    # unpublishing the set also hides it
    client.patch(f"/api/teach/practice-sets/{published}", json={"is_published": False}, headers=h)
    assert client.get(f"/api/student/practice/sets/{published}", headers=S2).status_code == 404
    assert client.get(f"/api/student/practice/sets/{uuid.uuid4()}", headers=S2).status_code == 404


def test_quiz_block_exposes_practice_set_link_to_students(client, teacher_auth, student_auth):
    from tests.test_lms import block
    h = teacher_auth
    cid, (l1, _) = two_lessons(client, h)
    q = bank_question(client, h, "QZ", "a", "steps")
    sid = make_set(client, h, cid, [q["id"]], title="Module quiz")
    block(client, h, l1, "quiz", {"title": "Quiz", "question_ids": [q["id"]], "practice_set_id": sid})
    enroll(client, h, "s1@example.com", cid)
    blocks = client.get(f"/api/student/lessons/{l1}", headers=student_auth).json()["blocks"]
    quiz = next(b for b in blocks if b["type"] == "quiz")["data"]
    assert quiz["practice_set_id"] == sid and "a" not in [x.get("answer") for x in quiz["questions"]]
    assert client.get(f"/api/student/practice/sets/{sid}", headers=student_auth).status_code == 200
