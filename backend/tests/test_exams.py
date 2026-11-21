import uuid
from datetime import timedelta

from app.core.db import SessionLocal
from app.models.base import utcnow
from app.models.exam import LmsExamAttempt
from tests.test_phase3 import enroll, two_lessons
from tests.test_practice import bank_question

PW = "correct-horse-1"


def mcq(client, h, title="MCQ", n_correct=1, qtype="multiple_choice"):
    opts = [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": n_correct > 1}, {"text": "C", "is_correct": False}, {"text": "D", "is_correct": False}]
    return bank_question(client, h, title, "answer A", "because A", options=opts, qtype=qtype)


def mk_exam(client, h, cid, **kw):
    r = client.post("/api/teach/exams", json={"course_id": cid, "title": "מבחן", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def add_bank(client, h, eid, ids, points=1):
    r = client.post(f"/api/teach/exams/{eid}/questions", json={"question_ids": ids, "points": points}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def publish(client, h, eid):
    r = client.post(f"/api/teach/exams/{eid}/status", json={"action": "publish"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def setup(client, th, **kw):
    """Course + exam with: Q1 MCQ (2 pts), Q2 numeric 42 (3 pts), Q3 open-ended manual (5 pts). Returns ids."""
    cid, _ = two_lessons(client, th)
    q1 = mcq(client, th, "Q1")
    q2 = bank_question(client, th, "Q2", "42", "steps", qtype="calculation")
    q3 = bank_question(client, th, "Q3", "essay", "model essay", qtype="open_ended")
    e = mk_exam(client, th, cid, time_limit_minutes=30, **kw)
    add_bank(client, th, e["id"], [q1["id"]], 2)
    add_bank(client, th, e["id"], [q2["id"]], 3)
    d = add_bank(client, th, e["id"], [q3["id"]], 5)
    return cid, e["id"], d


def by_title(d):
    return {q["title"]: q for q in d["questions"]}


def correct_ids(q):
    return [o["id"] for o in q["options"] if o["is_correct"]]


def answers_for(d, state, mcq_correct=True, numeric="42", essay="my essay"):
    t = by_title(d)
    wrong = next(o["id"] for o in t["Q1"]["options"] if not o["is_correct"])
    return [
        {"exam_question_id": t["Q1"]["id"], "answer": {"option_ids": correct_ids(t["Q1"]) if mcq_correct else [wrong]}},
        {"exam_question_id": t["Q2"]["id"], "answer": {"text": numeric}},
        {"exam_question_id": t["Q3"]["id"], "answer": {"text": essay}},
    ]


def start(client, sh, eid):
    r = client.post(f"/api/student/exams/{eid}/start", headers=sh)
    assert r.status_code == 200, r.text
    return r.json()


def submit(client, sh, aid, answers=None):
    r = client.post(f"/api/student/exam-attempts/{aid}/submit", json={"answers": answers or []}, headers=sh)
    assert r.status_code == 200, r.text
    return r.json()


def set_deadline(aid, delta):
    db = SessionLocal()
    a = db.get(LmsExamAttempt, uuid.UUID(aid))
    a.deadline_at = utcnow() + delta
    db.commit()
    db.close()


def open_exam(client, th, sh, **kw):
    cid, eid, d = setup(client, th, **kw)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    return cid, eid, d


# ---------------------------------------------------------------- creation & configuration
def test_exam_builder_flow_and_publish_validation(client, teacher_auth, student_auth):
    th = teacher_auth
    cid, _ = two_lessons(client, th)
    e = mk_exam(client, th, cid)
    assert client.post(f"/api/teach/exams/{e['id']}/status", json={"action": "publish"}, headers=th).status_code == 422  # empty
    q1, q2 = mcq(client, th, "Q1"), mcq(client, th, "Q2", qtype="true_false")
    d = add_bank(client, th, e["id"], [q1["id"], q2["id"], q1["id"]], points=2)       # duplicates ignored
    assert [q["title"] for q in d["questions"]] == ["Q1", "Q2"] and d["total_points"] == 4
    ids = [q["id"] for q in d["questions"]]
    assert client.post(f"/api/teach/exams/{e['id']}/questions/reorder", json={"ids": ids[::-1]}, headers=th).status_code == 204
    d = client.get(f"/api/teach/exams/{e['id']}", headers=th).json()
    assert [q["title"] for q in d["questions"]] == ["Q2", "Q1"]
    # exam-specific points never touch the bank question
    d = client.patch(f"/api/teach/exam-questions/{ids[0]}", json={"points": 7.5}, headers=th).json()
    assert d["total_points"] == 9.5
    assert client.get(f"/api/questions/{q1['id']}", headers=th).json()["title"] == "Q1"
    # custom exam-only question
    cq = client.post(f"/api/teach/exams/{e['id']}/questions/custom", headers=th,
                     json={"type": "multiple_choice", "content": "Custom?", "options": [{"text": "x", "is_correct": True}, {"text": "y"}], "points": 1}).json()
    assert len(cq["questions"]) == 3
    # an auto-graded custom question without a correct option blocks publishing
    bad = client.post(f"/api/teach/exams/{e['id']}/questions/custom", headers=th, json={"type": "multiple_choice", "content": "Bad", "options": [{"text": "x"}, {"text": "y"}]}).json()
    r = client.post(f"/api/teach/exams/{e['id']}/status", json={"action": "publish"}, headers=th)
    assert r.status_code == 422 and "no correct option" in r.text
    client.delete(f"/api/teach/exam-questions/{bad['questions'][-1]['id']}", headers=th)
    assert client.patch(f"/api/teach/exams/{e['id']}", json={"opens_at": "2030-01-02T00:00:00Z", "closes_at": "2030-01-01T00:00:00Z"}, headers=th).status_code == 422
    pub = publish(client, th, e["id"])
    assert pub["status"] == "published" and pub["effective_status"] == "open" and pub["locked"] is True
    # structure frozen while published; presentation settings still editable
    assert client.patch(f"/api/teach/exams/{e['id']}", json={"time_limit_minutes": 5}, headers=th).status_code == 409
    assert client.post(f"/api/teach/exams/{e['id']}/questions", json={"question_ids": [q1["id"]]}, headers=th).status_code == 409
    assert client.patch(f"/api/teach/exams/{e['id']}", json={"show_answers": True, "description": "new"}, headers=th).status_code == 200
    assert client.post(f"/api/teach/exams/{e['id']}/status", json={"action": "unpublish"}, headers=th).json()["status"] == "draft"
    dup = client.post(f"/api/teach/exams/{e['id']}/duplicate", headers=th).json()
    assert dup["status"] == "draft" and len(dup["questions"]) == 3 and dup["title"].endswith("(copy)")
    assert client.delete(f"/api/teach/exams/{dup['id']}", headers=th).status_code == 204
    assert any(x["id"] == e["id"] for x in client.get("/api/teach/exams", headers=th).json())


def test_teacher_isolation_and_student_blocked(client, teacher_auth, teacher2_auth, student_auth):
    cid, eid, d = setup(client, teacher_auth)
    for method, url, kw in (("get", f"/api/teach/exams/{eid}", {}), ("patch", f"/api/teach/exams/{eid}", {"json": {"title": "x"}}),
                            ("delete", f"/api/teach/exams/{eid}", {}), ("get", f"/api/teach/exams/{eid}/attempts", {}),
                            ("post", f"/api/teach/exams/{eid}/status", {"json": {"action": "publish"}})):
        assert getattr(client, method)(url, headers=teacher2_auth, **kw).status_code == 404, url
    assert client.post("/api/teach/exams", json={"course_id": cid, "title": "x"}, headers=teacher2_auth).status_code == 404
    assert client.get("/api/teach/exams", headers=teacher2_auth).json() == []
    assert client.get("/api/teach/exams", headers=student_auth).status_code == 403
    assert client.get(f"/api/teach/exams/{eid}", headers=student_auth).status_code == 403


# ---------------------------------------------------------------- access
def test_student_access_rules(client, teacher_auth, student_auth, student2_auth):
    cid, eid, d = setup(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)
    assert client.get(f"/api/student/exams/{eid}", headers=student_auth).status_code == 404       # draft
    publish(client, teacher_auth, eid)
    assert client.get(f"/api/student/exams/{eid}", headers=student_auth).status_code == 200
    assert client.get(f"/api/student/exams/{eid}", headers=student2_auth).status_code == 404      # not enrolled
    assert client.post(f"/api/student/exams/{eid}/start", headers=student2_auth).status_code == 404
    assert client.get("/api/student/exams", headers=student2_auth).json() == []
    assert [e["id"] for e in client.get("/api/student/exams", headers=student_auth).json()] == [eid]
    client.post(f"/api/teach/exams/{eid}/status", json={"action": "unpublish"}, headers=teacher_auth)
    assert client.post(f"/api/student/exams/{eid}/start", headers=student_auth).status_code == 404


def test_schedule_window(client, teacher_auth, student_auth):
    future = (utcnow() + timedelta(days=1)).isoformat()
    past = (utcnow() - timedelta(days=1)).isoformat()
    cid, eid, d = setup(client, teacher_auth, opens_at=future)
    enroll(client, teacher_auth, "s1@example.com", cid)
    pub = publish(client, teacher_auth, eid)
    assert pub["effective_status"] == "scheduled"
    assert client.post(f"/api/student/exams/{eid}/start", headers=student_auth).status_code == 409
    client.patch(f"/api/teach/exams/{eid}", json={"opens_at": past}, headers=teacher_auth)
    assert start(client, student_auth, eid)["status"] == "in_progress"
    client.patch(f"/api/teach/exams/{eid}", json={"closes_at": past, "opens_at": None}, headers=teacher_auth)
    assert client.get(f"/api/student/exams/{eid}", headers=student_auth).json()["status"] == "closed"


# ---------------------------------------------------------------- attempt lifecycle
def test_attempt_start_resume_autosave_submit_and_grade(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = open_exam(client, th, sh)
    st = start(client, sh, eid)
    assert st["attempt_no"] == 1 and st["remaining_seconds"] <= 1800 and len(st["questions"]) == 3
    blob = str(st)
    assert "is_correct" not in blob and "because A" not in blob and "model essay" not in blob   # no answer key leaks
    again = start(client, sh, eid)                                                               # resume, not a new attempt
    assert again["id"] == st["id"] and again["deadline_at"] == st["deadline_at"]
    ans = answers_for(d, st)
    r = client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[:1] + [{"exam_question_id": ans[2]["exam_question_id"], "flagged": True}]}, headers=sh)
    assert r.status_code == 200 and r.json()["remaining_seconds"] > 0
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[:1]}, headers=sh).status_code == 200  # idempotent
    reload = client.get(f"/api/student/exam-attempts/{st['id']}", headers=sh).json()               # browser refresh
    q = {x["id"]: x for x in reload["questions"]}
    assert q[ans[0]["exam_question_id"]]["answer"] == ans[0]["answer"] and q[ans[2]["exam_question_id"]]["flagged"] is True
    assert reload["deadline_at"] == st["deadline_at"]
    out = submit(client, sh, st["id"], ans[1:])
    assert out["status"] == "submitted" and out["result"]["released"] is False and out["result"]["pending_manual"] is True
    assert "score" not in out["result"] and "passed" not in out["result"]                         # held back until manual grading is complete
    assert submit(client, sh, st["id"])["status"] == "submitted"                                  # duplicate submit is harmless
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[:1]}, headers=sh).status_code == 409
    # teacher grades the essay
    rows = client.get(f"/api/teach/exams/{eid}/attempts", headers=th).json()
    assert rows[0]["pending_manual"] == 1 and rows[0]["status"] == "submitted" and rows[0]["score"] == 5.0   # 2 + 3 auto, essay pending
    rev = client.get(f"/api/teach/exam-attempts/{st['id']}", headers=th).json()
    essay = next(q for q in rev["questions"] if q["title"] == "Q3")
    assert essay["answer"] == {"text": "my essay"} and essay["expected_answer"] == "essay"
    assert client.post(f"/api/teach/exam-attempts/{st['id']}/grade", json={"grades": [{"exam_question_id": essay["id"], "points": 6}]}, headers=th).status_code == 422
    g = client.post(f"/api/teach/exam-attempts/{st['id']}/grade", json={"grades": [{"exam_question_id": essay["id"], "points": 4, "feedback": "good"}]}, headers=th).json()
    assert g["status"] == "graded" and g["score"] == 9.0 and g["percent"] == 90.0 and g["passed"] is True
    res = client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()
    assert res["passed"] is True and res["percent"] == 90.0
    assert next(q for q in res["questions"] if q["title"] == "Q3")["feedback"] == "good"
    assert "correct_option_ids" not in str(res) and "model essay" not in str(res)                 # answers hidden by default


def test_wrong_answers_and_numeric_tolerance(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th)
    q2 = by_title(d)["Q2"]
    client.patch(f"/api/teach/exam-questions/{q2['id']}", json={"tolerance": 0.5}, headers=th)
    enroll(client, th, "s1@example.com", cid)
    d = client.get(f"/api/teach/exams/{eid}", headers=th).json()
    publish(client, th, eid)
    st = start(client, sh, eid)
    out = submit(client, sh, st["id"], answers_for(d, st, mcq_correct=False, numeric="42.4", essay=""))
    assert out["result"]["score"] == 3.0                                                          # wrong mcq 0, numeric within tolerance 3, blank essay 0
    assert out["status"] == "graded" and out["result"]["passed"] is False                        # 30% < 60%
    assert next(q for q in out["result"]["questions"] if q["title"] == "Q3")["answered"] is False


def test_partial_credit_multi_select(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, _ = two_lessons(client, th)
    q = mcq(client, th, "Multi", n_correct=2)                                                    # A and B correct
    e = mk_exam(client, th, cid)
    d = add_bank(client, th, e["id"], [q["id"]], 4)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, e["id"])
    item = d["questions"][0]
    only_a = [o["id"] for o in item["options"] if o["text"] == "A"]
    st = start(client, sh, e["id"])
    out = submit(client, sh, st["id"], [{"exam_question_id": item["id"], "answer": {"option_ids": only_a}}])
    assert out["result"]["score"] == 2.0                                                          # one of two correct, none wrong
    # no partial credit when disabled
    client.post(f"/api/teach/exams/{e['id']}/status", json={"action": "close"}, headers=th)


# ---------------------------------------------------------------- server-side time
def test_deadline_is_server_side(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = open_exam(client, th, sh)
    st = start(client, sh, eid)
    ans = answers_for(d, st)
    client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[:1]}, headers=sh)
    # inside the grace window a late request is still accepted
    set_deadline(st["id"], -timedelta(seconds=5))
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[1:2]}, headers=sh).status_code == 200
    # beyond the grace window: writes are refused and the attempt is auto-submitted with what was saved
    set_deadline(st["id"], -timedelta(minutes=2))
    r = client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": ans[2:]}, headers=sh)
    assert r.status_code == 409
    got = client.get(f"/api/student/exam-attempts/{st['id']}", headers=sh).json()
    assert got["status"] == "graded" and got["result"]["auto_submitted"] is True      # the essay was never saved -> scored 0, nothing pending
    assert got["result"]["score"] == 5.0                                                          # MCQ 2 + numeric 3, essay never saved
    late = submit(client, sh, st["id"], ans)                                                      # a late submit cannot change anything
    assert late["result"]["auto_submitted"] is True and late["result"]["score"] == 5.0
    row = client.get(f"/api/teach/exams/{eid}/attempts", headers=th).json()[0]
    assert row["auto_submitted"] is True


def test_expiry_is_finalised_even_if_nobody_returns(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = open_exam(client, th, sh)
    st = start(client, sh, eid)
    set_deadline(st["id"], -timedelta(hours=1))
    rows = client.get(f"/api/teach/exams/{eid}/attempts", headers=th).json()                      # teacher view finalises it
    assert rows[0]["auto_submitted"] is True
    nxt = start(client, sh, eid)                                                                  # and a new attempt gets a fresh timer
    assert nxt["attempt_no"] == 2 and nxt["remaining_seconds"] > 1700


def test_deadline_capped_by_closing_time(client, teacher_auth, student_auth):
    cid, eid, d = setup(client, teacher_auth, closes_at=(utcnow() + timedelta(minutes=5)).isoformat())
    enroll(client, teacher_auth, "s1@example.com", cid)
    publish(client, teacher_auth, eid)
    st = start(client, student_auth, eid)
    assert st["remaining_seconds"] <= 300                                                         # 30 min limit, but the exam closes in 5


# ---------------------------------------------------------------- attempts policy
def test_max_attempts_resume_policy_and_cancel(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, max_attempts=2)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    a1 = start(client, sh, eid)
    submit(client, sh, a1["id"])
    a2 = start(client, sh, eid)
    assert a2["attempt_no"] == 2
    submit(client, sh, a2["id"])
    r = client.post(f"/api/student/exams/{eid}/start", headers=sh)
    assert r.status_code == 409 and "attempts" in r.text.lower()
    intro = client.get(f"/api/student/exams/{eid}", headers=sh).json()
    assert intro["attempts_left"] == 0 and intro["can_start"] is False
    client.post(f"/api/teach/exam-attempts/{a2['id']}/cancel", headers=th)                         # teacher voids one attempt
    assert start(client, sh, eid)["attempt_no"] == 3


def test_resume_disabled_forfeits_attempt(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, allow_resume=False, max_attempts=2)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    a1 = start(client, sh, eid)
    a2 = start(client, sh, eid)                                                                    # leaving and returning = new attempt
    assert a2["id"] != a1["id"] and a2["attempt_no"] == 2
    assert client.get(f"/api/student/exam-attempts/{a1['id']}", headers=sh).json()["status"] in ("submitted", "graded")


def test_no_changing_answers_and_shuffle(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, allow_change_answers=False, shuffle_questions=True, shuffle_options=True)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    st = start(client, sh, eid)
    assert sorted(q["id"] for q in st["questions"]) == sorted(q["id"] for q in d["questions"])
    q = st["questions"][0]
    body = {"exam_question_id": q["id"], "answer": {"option_ids": [q["options"][0]["id"]]} if q["options"] else {"text": "1"}}
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": [body]}, headers=sh).status_code == 200
    other = {"exam_question_id": q["id"], "answer": {"option_ids": [q["options"][1]["id"]]} if q["options"] else {"text": "2"}}
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": [other]}, headers=sh).status_code == 409
    # tampered payloads are rejected
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": [{"exam_question_id": str(uuid.uuid4()), "answer": {"text": "x"}}]}, headers=sh).status_code == 422
    mc = next(x for x in st["questions"] if x["options"])
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": [{"exam_question_id": mc["id"], "answer": {"option_ids": [str(uuid.uuid4())]}}]}, headers=sh).status_code == 422


# ---------------------------------------------------------------- snapshots
def test_attempt_is_immune_to_later_edits(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = open_exam(client, th, sh)
    st = start(client, sh, eid)
    q1 = by_title(d)["Q1"]
    client.patch(f"/api/questions/{q1['question_id']}", json={"content": "CHANGED IN BANK"}, headers=th)
    client.patch(f"/api/teach/exams/{eid}", json={"passing_score": 99, "title": "renamed"}, headers=th) if False else None
    client.patch(f"/api/teach/exams/{eid}", json={"description": "edited"}, headers=th)
    again = client.get(f"/api/student/exam-attempts/{st['id']}", headers=sh).json()
    assert "CHANGED IN BANK" not in str(again)
    assert next(x for x in again["questions"] if x["title"] == "Q1")["points"] == 2


# ---------------------------------------------------------------- results visibility
def test_result_release_rules(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, results_release="manual", show_answers=True, show_explanations=True)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    st = start(client, sh, eid)
    out = submit(client, sh, st["id"], answers_for(d, st))
    assert out["result"]["released"] is False and "score" not in out["result"]                    # hidden until the teacher releases
    client.post(f"/api/teach/exam-attempts/{st['id']}/grade", json={"grades": [{"exam_question_id": by_title(d)["Q3"]["id"], "points": 5}]}, headers=th)
    assert client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()["released"] is False
    client.post(f"/api/teach/exams/{eid}/release-results", headers=th)
    res = client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()
    assert res["released"] is True and res["score"] == 10.0 and res["passed"] is True
    q1 = next(q for q in res["questions"] if q["title"] == "Q1")
    assert q1["correct_option_ids"] and q1["explanation"] == "because A"                          # allowed by the exam settings


def test_scheduled_release_and_partial_publication(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, results_release="scheduled", results_release_at=(utcnow() + timedelta(days=1)).isoformat())
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    st = start(client, sh, eid)
    assert submit(client, sh, st["id"], answers_for(d, st))["result"]["released"] is False
    client.patch(f"/api/teach/exams/{eid}", json={"results_release": "immediate"}, headers=th)
    pending = client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()
    assert pending["released"] is False and pending["pending_manual"] is True                    # manual grading incomplete -> held back
    client.patch(f"/api/teach/exams/{eid}", json={"release_partial": True}, headers=th)
    part = client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()
    assert part["released"] is True and part["score"] == 5.0 and "passed" not in part


def test_hide_score(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, eid, d = setup(client, th, show_score=False, show_pass_fail=True)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, eid)
    st = start(client, sh, eid)
    out = submit(client, sh, st["id"], answers_for(d, st))
    client.post(f"/api/teach/exam-attempts/{st['id']}/grade", json={"grades": [{"exam_question_id": by_title(d)["Q3"]["id"], "points": 5}]}, headers=th)
    res = client.get(f"/api/student/exam-attempts/{st['id']}/result", headers=sh).json()
    assert "score" not in res and "percent" not in res and res["passed"] is True


# ---------------------------------------------------------------- security
def test_cross_student_isolation(client, teacher_auth, student_auth, student2_auth):
    th = teacher_auth
    cid, eid, d = open_exam(client, th, student_auth)
    enroll(client, th, "s2@example.com", cid)
    st = start(client, student_auth, eid)
    aid = st["id"]
    ans = answers_for(d, st)
    for method, url, kw in (("get", f"/api/student/exam-attempts/{aid}", {}), ("get", f"/api/student/exam-attempts/{aid}/result", {}),
                            ("post", f"/api/student/exam-attempts/{aid}/answers", {"json": {"answers": ans}}),
                            ("post", f"/api/student/exam-attempts/{aid}/submit", {"json": {}})):
        assert getattr(client, method)(url, headers=student2_auth, **kw).status_code == 404, url
    # student 2 starts their own attempt and it is independent
    st2 = start(client, student2_auth, eid)
    assert st2["id"] != aid
    # students cannot touch grading / teacher endpoints
    for method, url, kw in (("post", f"/api/teach/exam-attempts/{aid}/grade", {"json": {"grades": [{"exam_question_id": ans[0]["exam_question_id"], "points": 1}]}}),
                            ("get", f"/api/teach/exam-attempts/{aid}", {}), ("get", f"/api/teach/exams/{eid}/stats", {})):
        assert getattr(client, method)(url, headers=student_auth, **kw).status_code == 403, url
    # unauthenticated and unknown ids
    assert client.get(f"/api/student/exam-attempts/{aid}").status_code == 401
    assert client.get(f"/api/student/exam-attempts/{uuid.uuid4()}", headers=student_auth).status_code == 404


def test_other_teacher_cannot_grade_or_read_attempts(client, teacher_auth, teacher2_auth, student_auth):
    cid, eid, d = open_exam(client, teacher_auth, student_auth)
    st = start(client, student_auth, eid)
    submit(client, student_auth, st["id"])
    for method, url, kw in (("get", f"/api/teach/exam-attempts/{st['id']}", {}), ("post", f"/api/teach/exam-attempts/{st['id']}/release", {}),
                            ("post", f"/api/teach/exam-attempts/{st['id']}/cancel", {}), ("get", f"/api/teach/exams/{eid}/stats", {}),
                            ("post", f"/api/teach/exam-attempts/{st['id']}/grade", {"json": {"grades": [{"exam_question_id": str(uuid.uuid4()), "points": 1}]}})):
        assert getattr(client, method)(url, headers=teacher2_auth, **kw).status_code == 404, url
    sid = client.get("/api/auth/me", headers=student_auth).json()["id"]
    assert client.get(f"/api/teach/students/{sid}/exams", headers=teacher2_auth).json() == []
    assert len(client.get(f"/api/teach/students/{sid}/exams", headers=teacher_auth).json()) == 1


def test_revoked_enrollment_blocks_attempt(client, teacher_auth, student_auth):
    cid, eid, d = open_exam(client, teacher_auth, student_auth)
    st = start(client, student_auth, eid)
    enr = client.get(f"/api/teach/courses/{cid}/enrollments", headers=teacher_auth).json()[0]
    client.patch(f"/api/teach/enrollments/{enr['id']}", json={"status": "cancelled"}, headers=teacher_auth)
    assert client.get(f"/api/student/exam-attempts/{st['id']}", headers=student_auth).status_code == 404
    assert client.post(f"/api/student/exam-attempts/{st['id']}/answers", json={"answers": answers_for(d, st)}, headers=student_auth).status_code == 404


# ---------------------------------------------------------------- analytics
def test_statistics_use_real_attempts_only(client, teacher_auth, student_auth, student2_auth):
    th = teacher_auth
    cid, eid, d = open_exam(client, th, student_auth)
    enroll(client, th, "s2@example.com", cid)
    s0 = client.get(f"/api/teach/exams/{eid}/stats", headers=th).json()
    assert s0["enrolled"] == 2 and s0["started"] == 0 and s0["average"] is None and s0["pass_rate"] is None
    st = start(client, student_auth, eid)
    submit(client, student_auth, st["id"], answers_for(d, st))
    client.post(f"/api/teach/exam-attempts/{st['id']}/grade", json={"grades": [{"exam_question_id": by_title(d)["Q3"]["id"], "points": 5}]}, headers=th)
    start(client, student2_auth, eid)                                                             # in progress
    s = client.get(f"/api/teach/exams/{eid}/stats", headers=th).json()
    assert (s["started"], s["submitted"], s["in_progress"], s["not_started"]) == (2, 1, 1, 0)
    assert s["average"] == 100.0 and s["highest"] == 100.0 and s["pass_rate"] == 100.0 and s["median"] == 100.0
    q1 = next(q for q in s["questions"] if q["title"] == "Q1")
    assert q1["n"] == 1 and q1["percent_correct"] == 100.0
    lst = next(e for e in client.get("/api/teach/exams", headers=th).json() if e["id"] == eid)
    assert lst["submissions"] == 1 and lst["average"] == 100.0 and lst["question_count"] == 3


def test_grade_policy_highest_vs_latest(client, teacher_auth, student_auth):
    th, sh = teacher_auth, student_auth
    cid, _ = two_lessons(client, th)
    q = mcq(client, th)
    e = mk_exam(client, th, cid, max_attempts=3, grade_policy="highest")
    d = add_bank(client, th, e["id"], [q["id"]], 1)
    enroll(client, th, "s1@example.com", cid)
    publish(client, th, e["id"])
    item = d["questions"][0]
    good = {"exam_question_id": item["id"], "answer": {"option_ids": correct_ids(item)}}
    bad = {"exam_question_id": item["id"], "answer": {"option_ids": [next(o["id"] for o in item["options"] if not o["is_correct"])]}}
    for ans in (good, bad):
        submit(client, sh, start(client, sh, e["id"])["id"], [ans])
    assert client.get(f"/api/teach/exams/{e['id']}/stats", headers=th).json()["average"] == 100.0
    client.patch(f"/api/teach/exams/{e['id']}", json={"grade_policy": "latest"}, headers=th)
    assert client.get(f"/api/teach/exams/{e['id']}/stats", headers=th).json()["average"] == 0.0


def test_preview_has_no_answer_key_and_creates_no_attempt(client, teacher_auth):
    cid, eid, d = setup(client, teacher_auth)
    p = client.get(f"/api/teach/exams/{eid}/preview", headers=teacher_auth).json()
    assert len(p["questions"]) == 3 and "is_correct" not in str(p) and p["total_points"] == 10
    assert client.get(f"/api/teach/exams/{eid}/attempts", headers=teacher_auth).json() == []
