import io
import json

from app.services.ai.provider import set_provider_override


def mk_subject(client, auth, name="Finance"):
    r = client.post("/api/subjects", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def mk_topic(client, auth, subject_id, name="Risk", **kw):
    r = client.post("/api/topics", json={"subject_id": subject_id, "name": name, **kw}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def mk_question(client, auth, **kw):
    body = {"title": "What is variance?", "content": "Define variance.", "answer": {"answer": "E[(X-mu)^2]"}, **kw}
    r = client.post("/api/questions", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- auth ----------
def test_auth_flow(client):
    assert client.get("/api/auth/me").status_code == 401
    h = {"Authorization": "Bearer nope"}
    assert client.get("/api/auth/me", headers=h).status_code == 401
    r = client.post("/api/auth/register", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"email": "x@example.com", "password": "longenough1"})
    tokens = r.json()
    assert client.post("/api/auth/register", json={"email": "X@example.com", "password": "longenough1"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-password"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "x@example.com", "password": "longenough1"})
    assert ok.status_code == 200
    # refresh token must not work as an access token, and vice versa
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert "password_hash" not in me and me["email"] == "x@example.com"


# ---------- ownership ----------
def test_users_cannot_touch_each_others_data(client, auth, other_auth):
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"])
    q = mk_question(client, auth, topic_ids=[t["id"]])
    n = client.post("/api/notes", json={"title": "n", "topic_id": t["id"]}, headers=auth).json()
    for method, url in [("get", f"/api/subjects/{s['id']}"), ("get", f"/api/topics/{t['id']}"),
                        ("get", f"/api/questions/{q['id']}"), ("delete", f"/api/questions/{q['id']}"),
                        ("get", f"/api/notes/{n['id']}"), ("patch", f"/api/subjects/{s['id']}")]:
        r = getattr(client, method)(url, headers=other_auth, **({"json": {}} if method == "patch" else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    # cannot attach own question to someone else's topic / subject
    r = client.post("/api/questions", json={"title": "x", "topic_ids": [t["id"]]}, headers=other_auth)
    assert r.status_code == 404
    r = client.post("/api/topics", json={"subject_id": s["id"], "name": "hack"}, headers=other_auth)
    assert r.status_code == 404
    assert client.get("/api/questions", headers=other_auth).json()["total"] == 0
    assert client.get("/api/search", params={"q": "variance"}, headers=other_auth).json()["results"] == []


# ---------- library ----------
def test_library_hierarchy_move_and_tree(client, auth):
    s = mk_subject(client, auth)
    c = client.post("/api/courses", json={"subject_id": s["id"], "name": "Portfolio theory"}, headers=auth).json()
    ch = client.post("/api/chapters", json={"course_id": c["id"], "name": "Risk"}, headers=auth).json()
    t = mk_topic(client, auth, s["id"], "Variance", chapter_id=ch["id"])
    sub = mk_topic(client, auth, s["id"], "Sample variance", parent_id=t["id"])
    assert sub["chapter_id"] == ch["id"]
    tree = client.get("/api/library/tree", headers=auth).json()
    topic_node = tree[0]["courses"][0]["chapters"][0]["topics"][0]
    assert topic_node["name"] == "Variance" and topic_node["children"][0]["name"] == "Sample variance"
    # cannot move a topic inside its own subtree
    r = client.patch(f"/api/topics/{t['id']}", json={"move": True, "parent_id": sub["id"], "subject_id": s["id"]}, headers=auth)
    assert r.status_code == 422
    # move subtopic to subject root
    r = client.patch(f"/api/topics/{sub['id']}", json={"move": True, "subject_id": s["id"]}, headers=auth)
    assert r.json()["parent_id"] is None and r.json()["chapter_id"] is None
    # reorder
    a = mk_topic(client, auth, s["id"], "A")
    b = mk_topic(client, auth, s["id"], "B")
    assert client.post(f"/api/topics/{b['id']}/move", json={"direction": "up"}, headers=auth).status_code == 204
    names = [x["name"] for x in client.get("/api/library/tree", headers=auth).json()[0]["topics"]]
    assert names.index("B") < names.index("A")
    # deleting a chapter keeps the topics (moved to the subject root)
    assert client.delete(f"/api/chapters/{ch['id']}", headers=auth).status_code == 204
    detail = client.get(f"/api/topics/{t['id']}", headers=auth).json()
    assert detail["chapter_id"] is None
    # archive hides from tree
    client.patch(f"/api/topics/{a['id']}", json={"archived": True}, headers=auth)
    names = [x["name"] for x in client.get("/api/library/tree", headers=auth).json()[0]["topics"]]
    assert "A" not in names


# ---------- questions ----------
def test_question_crud_filters_bulk(client, auth):
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"])
    q1 = mk_question(client, auth, topic_ids=[t["id"]], tags=["Stats", "core"], difficulty="hard")
    q2 = mk_question(client, auth, title="Pick one", content="Which?", question_type="multiple_choice",
                     options=[{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}])
    assert q1["subject_id"] == s["id"] and {x["name"] for x in q1["tags"]} == {"stats", "core"}
    assert client.post("/api/questions", json={"title": "", "content": ""}, headers=auth).status_code == 422
    bad = client.post("/api/questions", json={"title": "x", "question_type": "multiple_choice",
                                              "options": [{"text": "A"}, {"text": "B"}]}, headers=auth)
    assert bad.status_code == 422  # no correct option
    lst = client.get("/api/questions", params={"topic_id": t["id"]}, headers=auth).json()
    assert lst["total"] == 1
    assert client.get("/api/questions", params={"tag": "stats"}, headers=auth).json()["total"] == 1
    assert client.get("/api/questions", params={"difficulty": "hard"}, headers=auth).json()["total"] == 1
    assert client.get("/api/questions", params={"q": "which"}, headers=auth).json()["total"] == 1
    assert client.get("/api/questions", params={"q": "mu)^2"}, ).status_code == 401
    assert client.get("/api/questions", params={"q": "mu)^2"}, headers=auth).json()["total"] == 2  # answer search
    assert client.get("/api/questions", params={"status": "new"}, headers=auth).json()["total"] == 2
    # update + options replace
    r = client.patch(f"/api/questions/{q2['id']}", json={"options": [{"text": "X", "is_correct": True}], "difficulty": "easy"}, headers=auth)
    assert [o["text"] for o in r.json()["options"]] == ["X"] and r.json()["difficulty"] == "easy"
    # duplicate
    d = client.post(f"/api/questions/{q1['id']}/duplicate", headers=auth).json()
    assert d["title"].endswith("(copy)") and d["id"] != q1["id"] and len(d["tags"]) == 2
    # bulk
    ids = [q1["id"], q2["id"], d["id"]]
    assert client.post("/api/questions/bulk/apply", json={"ids": ids, "action": "add_tags", "tags": ["bulk"]}, headers=auth).json()["affected"] == 3
    assert client.get("/api/questions", params={"tag": "bulk"}, headers=auth).json()["total"] == 3
    client.post("/api/questions/bulk/apply", json={"ids": ids, "action": "archive"}, headers=auth)
    assert client.get("/api/questions", headers=auth).json()["total"] == 0
    assert client.get("/api/questions", params={"archived": True}, headers=auth).json()["total"] == 3
    client.post("/api/questions/bulk/apply", json={"ids": ids, "action": "delete"}, headers=auth)
    assert client.get("/api/questions", params={"archived": True}, headers=auth).json()["total"] == 0


# ---------- study + SRS ----------
def test_study_session_updates_schedule(client, auth):
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"])
    qs = [mk_question(client, auth, title=f"Q{i}", topic_ids=[t["id"]]) for i in range(3)]
    assert client.post("/api/study/sessions", json={"mode": "weakness", "selection": "weak"}, headers=auth).status_code == 422
    r = client.post("/api/study/sessions", json={"mode": "topic", "topic_id": t["id"], "count": 10}, headers=auth)
    sid = r.json()["id"]
    assert r.json()["total"] == 3
    sess = client.get(f"/api/study/sessions/{sid}", headers=auth).json()
    assert len(sess["items"]) == 3 and set(sess["items"][0]["intervals"]) == {"1", "2", "3", "4"}
    ids = [i["question"]["id"] for i in sess["items"]]
    # rate: good, again, easy
    res = client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": ids[0], "rating": 3, "time_ms": 4000}, headers=auth).json()
    assert res["progress"]["state"] == "review" and res["scheduled_days"] >= 1
    res = client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": ids[1], "rating": 1}, headers=auth).json()
    assert res["progress"]["state"] == "learning" and res["remaining"] == 2  # Q3 + the re-queued failed card
    # answering the same question twice without a pending slot is rejected
    assert client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": ids[0], "rating": 3}, headers=auth).status_code == 409
    # pause / resume
    assert client.post(f"/api/study/sessions/{sid}/pause", headers=auth).json()["status"] == "paused"
    assert client.get("/api/study/sessions", headers=auth).json()[0]["id"] == sid
    assert client.post(f"/api/study/sessions/{sid}/resume", headers=auth).json()["status"] == "active"
    # finish everything: failed question was re-queued once
    for _ in range(5):
        sess = client.get(f"/api/study/sessions/{sid}", headers=auth).json()
        pending = [i for i in sess["items"] if not i["answered"]]
        if not pending:
            break
        client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": pending[0]["question"]["id"], "rating": 4}, headers=auth)
    summ = client.get(f"/api/study/sessions/{sid}/summary", headers=auth).json()
    assert summ["status"] == "completed" and summ["reviews"] == 4 and summ["accuracy"] == 0.75
    q = client.get(f"/api/questions/{ids[0]}", headers=auth).json()
    assert q["progress"]["reps"] == 1 and q["progress"]["due_at"] is not None
    # queue: nothing due right now, upcoming has the reviews
    queue = client.get("/api/review/queue", headers=auth).json()
    assert queue["due_now"] == 0 or queue["due_now"] == 1  # the Again'd card may be re-due after 10 min only
    assert sum(u["count"] for u in queue["upcoming"]) >= 2
    hist = client.get(f"/api/questions/{ids[0]}/history", headers=auth).json()
    assert len(hist) == 1 and hist[0]["rating"] == 3


def test_multiple_choice_wrong_answer_is_forced_lapse(client, auth):
    q = mk_question(client, auth, title="mc", question_type="multiple_choice",
                    options=[{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}])
    sid = client.post("/api/study/sessions", json={"mode": "multiple_choice", "selection": "all"}, headers=auth).json()["id"]
    wrong = [o["id"] for o in q["options"] if not o["is_correct"]]
    res = client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": q["id"], "rating": 4, "selected_option_ids": wrong}, headers=auth).json()
    assert res["rating"] == 1 and res["correct"] is False


def test_due_queue_and_dashboard_use_real_data(client, auth):
    from datetime import timedelta
    from app.core.db import SessionLocal
    from app.models.learning import UserQuestionProgress
    from app.models.base import utcnow
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"])
    q = mk_question(client, auth, topic_ids=[t["id"]])
    sid = client.post("/api/study/sessions", json={"selection": "all"}, headers=auth).json()["id"]
    client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": q["id"], "rating": 3}, headers=auth)
    db = SessionLocal()
    p = db.query(UserQuestionProgress).one()
    p.due_at = utcnow() - timedelta(days=3)
    p.last_review_at = utcnow() - timedelta(days=10)
    db.commit()
    db.close()
    queue = client.get("/api/review/queue", headers=auth).json()
    assert queue["due_now"] == 1 and queue["overdue"] == 1 and queue["items"][0]["overdue_days"] >= 3
    dash = client.get("/api/dashboard", headers=auth).json()
    assert dash["totals"]["questions"] == 1 and dash["totals"]["due_today"] == 1 and dash["totals"]["streak"] == 1
    assert dash["totals"]["subjects"] == 1 and dash["totals"]["topics"] == 1
    assert dash["continue_learning"][0]["name"] == "Risk"
    an = client.get("/api/analytics", headers=auth).json()
    assert an["summary"]["reviews"] == 1 and an["summary"]["accuracy"] == 1.0
    assert "retention" in an["definitions"]
    # session in due-only mode now picks it up
    due = client.post("/api/study/sessions", json={"selection": "due"}, headers=auth)
    assert due.status_code == 201 and due.json()["total"] == 1


def test_weak_areas_detected(client, auth):
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"], "Hard stuff")
    q = mk_question(client, auth, topic_ids=[t["id"]])
    for _ in range(6):
        sid = client.post("/api/study/sessions", json={"selection": "all"}, headers=auth).json()["id"]
        client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": q["id"], "rating": 1}, headers=auth)
    weak = client.get("/api/dashboard", headers=auth).json()["weak_areas"]
    assert weak and weak[0]["name"] == "Hard stuff" and "low_accuracy" in weak[0]["reasons"]
    assert client.get("/api/analytics", headers=auth).json()["most_forgotten"][0]["lapses"] >= 5


# ---------- notes / graph / search ----------
def test_notes_links_graph_search(client, auth):
    s = mk_subject(client, auth)
    a = mk_topic(client, auth, s["id"], "Variance")
    b = mk_topic(client, auth, s["id"], "Covariance")
    n1 = client.post("/api/notes", json={"title": "Variance basics", "content": "x", "topic_id": a["id"], "kind": "definition"}, headers=auth).json()
    n2 = client.post("/api/notes", json={"title": "Cov", "content": "See [[Variance basics]] for more"}, headers=auth).json()
    assert n2["links_to"][0]["id"] == n1["id"]
    assert client.get(f"/api/notes/{n1['id']}/backlinks", headers=auth).json()[0]["id"] == n2["id"]
    assert len(client.get("/api/notes", params={"topic_id": a["id"], "kind": "definition"}, headers=auth).json()) == 1
    # relationships
    r = client.post("/api/relationships", json={"source_topic_id": a["id"], "target_topic_id": b["id"], "relation_type": "prerequisite_for"}, headers=auth)
    assert r.status_code == 201
    assert client.post("/api/relationships", json={"source_topic_id": a["id"], "target_topic_id": a["id"]}, headers=auth).status_code == 422
    g = client.get("/api/graph", headers=auth).json()
    assert len(g["nodes"]) == 2 and g["edges"][0]["relation_type"] == "prerequisite_for"
    assert client.get(f"/api/topics/{a['id']}", headers=auth).json()["related"][0]["topic"]["name"] == "Covariance"
    assert client.delete(f"/api/relationships/{r.json()['id']}", headers=auth).status_code == 204
    # search
    mk_question(client, auth, title="Explain covariance", content="cov")
    types = {x["type"] for x in client.get("/api/search", params={"q": "covariance"}, headers=auth).json()["results"]}
    assert {"topic", "question"} <= types


# ---------- import / export ----------
def test_json_roundtrip_and_csv(client, auth, other_auth):
    s = mk_subject(client, auth, "Math")
    t = mk_topic(client, auth, s["id"], "Algebra")
    mk_question(client, auth, topic_ids=[t["id"]], tags=["x"])
    client.post("/api/notes", json={"title": "N", "topic_id": t["id"]}, headers=auth)
    sid = client.post("/api/study/sessions", json={"selection": "all"}, headers=auth).json()["id"]
    qid = client.get("/api/questions", headers=auth).json()["items"][0]["id"]
    client.post(f"/api/study/sessions/{sid}/answer", json={"question_id": qid, "rating": 3}, headers=auth)
    exp = client.get("/api/export/json", headers=auth)
    assert exp.status_code == 200
    data = exp.json()
    assert data["questions"][0]["progress"]["state"] == "review"
    r = client.post("/api/import/json", files={"file": ("e.json", json.dumps(data), "application/json")}, headers=other_auth)
    assert r.json()["questions"] == 1 and r.json()["topics"] == 1 and r.json()["notes"] == 1
    imported = client.get("/api/questions", headers=other_auth).json()["items"][0]
    assert imported["topics"][0]["name"] == "Algebra" and imported["progress"]["reps"] == 1
    assert client.post("/api/import/json", files={"file": ("e.json", b'{"x":1}', "application/json")}, headers=auth).status_code == 422
    # csv
    csv_text = client.get("/api/export/questions.csv", headers=auth).text
    assert csv_text.splitlines()[0].startswith("title,content")
    csv_in = ("title,content,question_type,difficulty,answer,subject,topics,tags,options\n"
              "Capital?,Capital of France?,multiple_choice,easy,Paris,Geo,Europe,a;b,*Paris|Rome\n"
              "=cmd|' /C calc'!A0,bad row,open_ended,bogus,,,,,\n")
    r = client.post("/api/import/questions", files={"file": ("q.csv", csv_in, "text/csv")}, headers=auth).json()
    assert r["created"] == 1 and r["error_count"] == 1 and r["errors"][0]["row"] == 3
    got = client.get("/api/questions", params={"q": "France"}, headers=auth).json()["items"][0]
    assert got["subject_id"] and got["options"][0]["is_correct"] and got["topics"][0]["name"] == "Europe"
    assert client.post("/api/import/questions", files={"file": ("q.pdf", b"%PDF", "application/pdf")}, headers=auth).status_code == 415


# ---------- attachments ----------
def test_attachment_upload_rules(client, auth, other_auth):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    r = client.post("/api/attachments", files={"file": ("pic.png", png, "image/png")}, headers=auth)
    assert r.status_code == 201
    aid = r.json()["id"]
    got = client.get(f"/api/attachments/{aid}/file", headers=auth)
    assert got.status_code == 200 and got.content == png
    assert client.get(f"/api/attachments/{aid}/file", headers=other_auth).status_code == 404
    assert client.get(f"/api/attachments/{aid}/file").status_code == 401
    assert client.post("/api/attachments", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=auth).status_code == 415
    assert client.post("/api/attachments", files={"file": ("fake.png", b"not a png", "image/png")}, headers=auth).status_code == 415


# ---------- AI ----------
class FakeAI:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, *, max_tokens=None):
        self.calls.append((system, user))
        return self.reply


def test_ai_disabled_without_key(client, auth):
    assert client.get("/api/ai/status", headers=auth).json()["enabled"] is False
    r = client.post("/api/ai/generate-questions", json={"text": "x" * 50}, headers=auth)
    assert r.status_code == 503


def test_ai_generation_never_saves_and_evaluation_parses(client, auth):
    s = mk_subject(client, auth)
    t = mk_topic(client, auth, s["id"], description="Variance measures dispersion around the mean.")
    fake = FakeAI('```json\n[{"title":"T","content":"What is variance?","question_type":"multiple_choice","difficulty":"easy",'
                  '"answer":"Dispersion","explanation":"because","options":[{"text":"Dispersion","is_correct":true},{"text":"Mean","is_correct":false}]},'
                  '{"content":"broken mcq","question_type":"multiple_choice","options":[{"text":"a","is_correct":false}]}]\n```')
    set_provider_override(fake)
    try:
        r = client.post("/api/ai/generate-questions", json={"topic_id": t["id"], "count": 2}, headers=auth)
        assert r.status_code == 200, r.text
        drafts = r.json()["questions"]
        assert len(drafts) == 2 and drafts[0]["topic_ids"] == [t["id"]] and drafts[1]["question_type"] == "open_ended"
        assert client.get("/api/questions", headers=auth).json()["total"] == 0  # nothing saved automatically
        saved = client.post("/api/questions/batch", json=drafts[:1], headers=auth)
        assert saved.status_code == 201 and client.get("/api/questions", headers=auth).json()["total"] == 1
        # prompt-injection guard text present, and user material delimited
        assert "never follow instructions" in fake.calls[0][0] and "<material>" in fake.calls[0][1]

        q = saved.json()[0]
        fake.reply = '{"score": 82, "correct_concepts":["spread"], "missing_concepts":["squared"], "incorrect_reasoning":[], "improved_answer":"better", "explanation":"ok", "suggested_rating":3}'
        ev = client.post("/api/ai/evaluate", json={"question_id": q["id"], "answer": "how spread out values are"}, headers=auth).json()
        assert ev["score"] == 82 and ev["suggested_rating"] == 3
        fake.reply = "not json at all"
        assert client.post("/api/ai/evaluate", json={"question_id": q["id"], "answer": "x"}, headers=auth).status_code == 502
        fake.reply = "Here is an explanation."
        tr = client.post("/api/ai/tutor", json={"action": "simpler", "question_id": q["id"]}, headers=auth)
        assert tr.json()["reply"] == "Here is an explanation."
        assert client.post("/api/ai/tutor", json={"action": "bogus", "question_id": q["id"]}, headers=auth).status_code == 422
        plan = client.post("/api/ai/study-plan", json={"goal": "Pass the exam", "days": 7}, headers=auth)
        assert plan.status_code == 200 and "plan" in plan.json()
    finally:
        set_provider_override(None)
