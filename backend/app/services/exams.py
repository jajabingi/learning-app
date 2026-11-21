"""Exam engine: snapshots, attempt lifecycle, deadline enforcement, grading and result visibility.

Everything that matters (time, attempt state, grading, what a student may see) is decided here, on the server.
"""
import random
import re
import statistics
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.exam import FINAL_ATTEMPT_STATUSES, LmsExam, LmsExamAnswer, LmsExamAttempt, LmsExamQuestion
from app.models.lms import LmsEnrollment
from app.models.question import Question

GRACE = timedelta(seconds=15)  # tolerance for network latency around the deadline
MAX_TEXT = 20000
NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def D(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


# ---------------------------------------------------------------- question snapshots
def parse_number(text: str) -> Decimal | None:
    s = (text or "").strip().replace(",", "").replace("%", "").replace(" ", "")
    if not NUMBER.fullmatch(s):
        return None
    return Decimal(s)


def snapshot_question(q: Question) -> dict:
    a = q.answer
    return {"type": q.question_type, "title": q.title, "content": q.content,
            "options": [{"id": str(o.id), "text": o.text, "is_correct": bool(o.is_correct)} for o in q.options],
            "answer": a.answer if a else "", "explanation": a.explanation if a else "", "tolerance": 0}


def custom_snapshot(type_: str, content: str, options: list[dict], answer: str, explanation: str, tolerance: float) -> dict:
    return {"type": type_, "title": "", "content": content,
            "options": [{"id": str(uuid.uuid4()), "text": o["text"], "is_correct": bool(o.get("is_correct"))} for o in options],
            "answer": answer, "explanation": explanation, "tolerance": float(tolerance or 0)}


def default_grading(snap: dict) -> str:
    if snap["options"]:
        return "auto"
    if snap["type"] == "calculation" and parse_number(snap["answer"]) is not None:
        return "auto"
    return "manual"


def question_problem(eq: LmsExamQuestion) -> str | None:
    """Why this question cannot be used in a published exam (None = fine)."""
    s = eq.snapshot
    if eq.grading == "auto":
        if s["options"]:
            if not any(o["is_correct"] for o in s["options"]):
                return "no correct option is marked"
        elif parse_number(s["answer"]) is None:
            return "auto grading needs options or a numeric answer"
    return None


# ---------------------------------------------------------------- grading
def normalise_answer(snap: dict, raw: dict | None) -> dict | None:
    """Validate/clean a student's answer against the frozen question. Returns None for 'no answer'."""
    if not raw:
        return None
    if snap["options"]:
        valid = {o["id"] for o in snap["options"]}
        ids = [str(i) for i in (raw.get("option_ids") or [])]
        if not set(ids) <= valid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown option selected")
        single = sum(1 for o in snap["options"] if o["is_correct"]) <= 1
        if single and len(ids) > 1:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select a single option")
        ids = list(dict.fromkeys(ids))
        return {"option_ids": ids} if ids else None
    text = str(raw.get("text") or "")
    if len(text) > MAX_TEXT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Answer is too long")
    return {"text": text} if text.strip() else None


def grade_answer(snap: dict, points: Decimal, grading: str, answer: dict | None, partial: bool) -> tuple[str, Decimal | None, bool | None]:
    """-> (grading_status, points_awarded, is_correct). Deterministic; 'pending' means a teacher must grade it."""
    if answer is None:
        return "auto", D(0), False  # unanswered questions score zero, never wait for a teacher
    if grading == "manual":
        return "pending", None, None
    if snap["options"]:
        correct = {o["id"] for o in snap["options"] if o["is_correct"]}
        chosen = set(answer.get("option_ids") or [])
        if chosen == correct:
            return "auto", D(points), True
        if partial and len(correct) > 1 and chosen:
            frac = max(Decimal(0), Decimal(len(chosen & correct) - len(chosen - correct)) / Decimal(len(correct)))
            return "auto", D(points * frac), False
        return "auto", D(0), False
    expected, given = parse_number(snap["answer"]), parse_number(answer.get("text", ""))
    if expected is None or given is None:
        return "auto", D(0), False
    ok = abs(expected - given) <= Decimal(str(snap.get("tolerance") or 0)) + Decimal("0.0000001")
    return "auto", D(points if ok else 0), ok


# ---------------------------------------------------------------- exam state
def effective_status(exam: LmsExam, now: datetime | None = None) -> str:
    now = now or utcnow()
    if exam.status != "published":
        return exam.status
    if exam.closes_at and now >= as_utc(exam.closes_at):
        return "closed"
    if exam.opens_at and now < as_utc(exam.opens_at):
        return "scheduled"
    return "open"


def total_points(exam: LmsExam) -> Decimal:
    return sum((D(q.points) for q in exam.questions), Decimal(0))


def has_attempts(db: Session, exam_id: uuid.UUID) -> bool:
    return db.scalar(select(LmsExamAttempt.id).where(LmsExamAttempt.exam_id == exam_id).limit(1)) is not None


def publish_problems(exam: LmsExam) -> list[str]:
    out = []
    if not exam.questions:
        out.append("Add at least one question")
    for q in exam.questions:
        p = question_problem(q)
        if p:
            out.append(f"Question {q.position + 1}: {p}")
    if total_points(exam) <= 0:
        out.append("Total points must be greater than zero")
    if exam.opens_at and exam.closes_at and as_utc(exam.closes_at) <= as_utc(exam.opens_at):
        out.append("The closing time must be after the opening time")
    if exam.results_release == "scheduled" and not exam.results_release_at:
        out.append("Choose a result release date")
    return out


# ---------------------------------------------------------------- attempts
SETTINGS_KEYS = ("time_limit_minutes", "passing_score", "partial_credit", "grade_policy", "allow_back",
                 "allow_change_answers", "one_per_page", "title", "instructions")


def attempts_of(db: Session, exam_id: uuid.UUID, student_id: uuid.UUID) -> list[LmsExamAttempt]:
    return list(db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.exam_id == exam_id, LmsExamAttempt.student_id == student_id)
                           .order_by(LmsExamAttempt.attempt_no)))


def build_attempt(db: Session, exam: LmsExam, student_id: uuid.UUID, attempt_no: int, now: datetime) -> LmsExamAttempt:
    rng = random.Random()
    qs = list(exam.questions)
    if exam.shuffle_questions:
        rng.shuffle(qs)
    frozen = []
    for q in qs:
        snap = {**q.snapshot, "options": list(q.snapshot["options"])}
        if exam.shuffle_options:
            rng.shuffle(snap["options"])
        frozen.append({"id": str(q.id), "points": float(D(q.points)), "grading": q.grading, "snapshot": snap})
    deadline = None
    if exam.time_limit_minutes:
        deadline = now + timedelta(minutes=exam.time_limit_minutes)
    if exam.closes_at:
        closes = as_utc(exam.closes_at)
        deadline = closes if deadline is None else min(deadline, closes)
    att = LmsExamAttempt(
        exam_id=exam.id, student_id=student_id, attempt_no=attempt_no, status="in_progress", started_at=now, deadline_at=deadline,
        settings_snapshot={k: getattr(exam, k) for k in SETTINGS_KEYS}, order_snapshot={"questions": frozen},
        max_score=D(sum(Decimal(str(f["points"])) for f in frozen)))
    db.add(att)
    db.flush()
    return att


def frozen_questions(att: LmsExamAttempt) -> list[dict]:
    return att.order_snapshot["questions"]


def is_expired(att: LmsExamAttempt, now: datetime) -> bool:
    return att.deadline_at is not None and now > as_utc(att.deadline_at) + GRACE


def answer_map(att: LmsExamAttempt) -> dict[str, LmsExamAnswer]:
    return {str(a.exam_question_id): a for a in att.answers}


def finalize(db: Session, att: LmsExamAttempt, now: datetime, auto: bool) -> LmsExamAttempt:
    """Idempotent. Grades every question (unanswered -> 0), stores totals, and leaves manual questions pending."""
    if att.status != "in_progress":
        return att
    submitted = now
    if att.deadline_at and now > as_utc(att.deadline_at):
        submitted = as_utc(att.deadline_at)  # late arrival is stamped with the deadline, never later
    partial = bool(att.settings_snapshot.get("partial_credit"))
    existing = answer_map(att)
    for f in frozen_questions(att):
        a = existing.get(f["id"])
        if a is None:
            a = LmsExamAnswer(attempt_id=att.id, exam_question_id=uuid.UUID(f["id"]), answer=None)
            db.add(a)
            att.answers.append(a)
        gs, pts, ok = grade_answer(f["snapshot"], Decimal(str(f["points"])), f["grading"], a.answer, partial)
        a.grading_status, a.points_awarded, a.is_correct = gs, pts, ok
    att.status = "auto_submitted" if auto else "submitted"
    att.auto_submitted = auto
    att.submitted_at = submitted
    recompute(att, now)
    db.flush()
    return att


def recompute(att: LmsExamAttempt, now: datetime) -> None:
    """Totals from the answer rows; flips to `graded` once nothing is pending."""
    total = sum((D(a.points_awarded) for a in att.answers if a.points_awarded is not None), Decimal(0))
    mx = D(att.max_score or 0)
    att.score = D(total)
    att.percent = D(total / mx * 100) if mx > 0 else D(0)
    pending = any(a.grading_status == "pending" for a in att.answers)
    if att.status in FINAL_ATTEMPT_STATUSES:
        if pending:
            att.passed = None
            if att.status == "graded":
                att.status = "submitted"
        else:
            att.status = "graded"
            att.graded_at = att.graded_at or now
            att.passed = att.percent >= Decimal(att.settings_snapshot["passing_score"])


def finalize_if_expired(db: Session, att: LmsExamAttempt, now: datetime | None = None) -> LmsExamAttempt:
    now = now or utcnow()
    if att.status == "in_progress" and is_expired(att, now):
        finalize(db, att, now, auto=True)
    return att


def save_answers(db: Session, att: LmsExamAttempt, items: list[dict], now: datetime) -> dict:
    """Idempotent upsert of answers/flags. Rejected once the deadline (+grace) has passed."""
    frozen = {f["id"]: f for f in frozen_questions(att)}
    existing = answer_map(att)
    allow_change = bool(att.settings_snapshot.get("allow_change_answers", True))
    for it in items:
        qid = str(it["exam_question_id"])
        f = frozen.get(qid)
        if f is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown question")
        a = existing.get(qid)
        if a is None:
            a = LmsExamAnswer(attempt_id=att.id, exam_question_id=uuid.UUID(qid), answer=None, grading_status="pending")
            db.add(a)
            att.answers.append(a)
            existing[qid] = a
        if "answer" in it:
            new = normalise_answer(f["snapshot"], it["answer"])
            if new != a.answer:
                if a.answer is not None and not allow_change:
                    raise conflict("Answers cannot be changed in this exam")
                a.answer = new
        if it.get("flagged") is not None:
            a.flagged = bool(it["flagged"])
    db.flush()
    return {"saved_at": now, "count": len(items)}


def grade_manually(db: Session, att: LmsExamAttempt, grades: list[dict], teacher_id: uuid.UUID, now: datetime) -> None:
    if att.status == "in_progress" or att.status == "cancelled":
        raise conflict("The attempt has not been submitted")
    frozen = {f["id"]: f for f in frozen_questions(att)}
    existing = answer_map(att)
    for g in grades:
        qid = str(g["exam_question_id"])
        f, a = frozen.get(qid), existing.get(qid)
        if f is None or a is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown question")
        pts = D(g["points"])
        if pts < 0 or pts > D(f["points"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Points must be between 0 and {f['points']}")
        a.points_awarded, a.feedback = pts, g.get("feedback", "")
        a.grading_status, a.graded_by = "graded", teacher_id
        a.is_correct = pts >= D(f["points"])
    recompute(att, now)
    db.flush()


# ---------------------------------------------------------------- views
def iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


def student_question(f: dict, a: LmsExamAnswer | None) -> dict:
    s = f["snapshot"]
    multi = sum(1 for o in s["options"] if o["is_correct"]) > 1
    return {"id": f["id"], "type": s["type"], "title": s["title"], "content": s["content"], "points": f["points"],
            "options": [{"id": o["id"], "text": o["text"]} for o in s["options"]],  # NEVER is_correct
            "multiple": multi, "answer": a.answer if a else None, "flagged": bool(a.flagged) if a else False}


def attempt_state(att: LmsExamAttempt, now: datetime) -> dict:
    """What the student's browser needs to run the exam. Contains no answer key."""
    am = answer_map(att)
    st = att.settings_snapshot
    return {
        "id": str(att.id), "exam_id": str(att.exam_id), "attempt_no": att.attempt_no, "status": att.status,
        "server_now": iso(now), "started_at": iso(att.started_at), "deadline_at": iso(att.deadline_at),
        "remaining_seconds": max(0, int((as_utc(att.deadline_at) - now).total_seconds())) if att.deadline_at else None,
        "title": st["title"], "instructions": st["instructions"], "one_per_page": st["one_per_page"], "allow_back": st["allow_back"],
        "allow_change_answers": st["allow_change_answers"], "time_limit_minutes": st["time_limit_minutes"],
        "questions": [student_question(f, am.get(f["id"])) for f in frozen_questions(att)],
    }


def release_state(exam: LmsExam, att: LmsExamAttempt, now: datetime) -> bool:
    if exam.results_release == "immediate":
        return True
    if exam.results_release == "manual":
        return bool(att.released_at or exam.results_released_at)
    return bool(exam.results_release_at and now >= as_utc(exam.results_release_at))


def student_result(exam: LmsExam, att: LmsExamAttempt, now: datetime) -> dict:
    """Respects every visibility setting; correct answers / explanations only when the teacher allows them."""
    base = {"id": str(att.id), "exam_id": str(exam.id), "title": exam.title, "attempt_no": att.attempt_no, "status": att.status,
            "submitted_at": iso(att.submitted_at), "auto_submitted": att.auto_submitted, "released": False, "pending_manual": att.status != "graded"}
    if att.status not in FINAL_ATTEMPT_STATUSES:
        return base
    complete = att.status == "graded"
    if not release_state(exam, att, now) or (not complete and not exam.release_partial):
        return base
    out = {**base, "released": True}
    if exam.show_score:
        out.update(score=float(att.score), max_score=float(att.max_score), percent=float(att.percent))
    if exam.show_pass_fail and complete:
        out["passed"] = att.passed
        out["passing_score"] = att.settings_snapshot["passing_score"]
    am = answer_map(att)
    qs = []
    for i, f in enumerate(frozen_questions(att), 1):
        s, a = f["snapshot"], am.get(f["id"])
        row = {"id": f["id"], "number": i, "type": s["type"], "content": s["content"], "title": s["title"],
               "options": [{"id": o["id"], "text": o["text"]} for o in s["options"]], "your_answer": a.answer if a else None,
               "answered": bool(a and a.answer), "grading_status": a.grading_status if a else "auto"}
        if exam.show_score:
            row.update(points=f["points"], points_awarded=float(a.points_awarded) if a and a.points_awarded is not None else None)
        if exam.show_pass_fail or exam.show_score:
            row["is_correct"] = a.is_correct if a else False
        if a and a.feedback and a.grading_status == "graded":
            row["feedback"] = a.feedback
        if exam.show_answers:
            row["correct_option_ids"] = [o["id"] for o in s["options"] if o["is_correct"]]
            row["correct_answer"] = s["answer"]
        if exam.show_explanations:
            row["explanation"] = s["explanation"]
        qs.append(row)
    out["questions"] = qs
    return out


def final_attempt(attempts: list[LmsExamAttempt], policy: str) -> LmsExamAttempt | None:
    done = [a for a in attempts if a.status == "graded"]
    if not done:
        return None
    return max(done, key=lambda a: (a.percent, a.attempt_no)) if policy == "highest" else max(done, key=lambda a: a.attempt_no)


def active_students(db: Session, course_id: uuid.UUID) -> list[uuid.UUID]:
    from app.services.access import enrollment_grants_access
    now = utcnow()
    return [e.student_id for e in db.scalars(select(LmsEnrollment).where(LmsEnrollment.course_id == course_id)) if enrollment_grants_access(e, now)]


def exam_stats(db: Session, exam: LmsExam) -> dict:
    attempts = list(db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.exam_id == exam.id, LmsExamAttempt.status != "cancelled")))
    by_student: dict[uuid.UUID, list[LmsExamAttempt]] = {}
    for a in attempts:
        by_student.setdefault(a.student_id, []).append(a)
    enrolled = set(active_students(db, exam.course_id))
    started = set(by_student)
    in_progress = {s for s, al in by_student.items() if any(a.status == "in_progress" for a in al)}
    submitted = {s for s, al in by_student.items() if any(a.status in FINAL_ATTEMPT_STATUSES for a in al)}
    finals = [fa for al in by_student.values() if (fa := final_attempt(al, exam.grade_policy))]
    pcts = [float(a.percent) for a in finals]
    graded_final = [a for a in finals]
    out = {
        "enrolled": len(enrolled), "started": len(started), "in_progress": len(in_progress), "submitted": len(submitted),
        "not_started": len(enrolled - started), "graded": len(finals),
        "average": round(statistics.mean(pcts), 1) if pcts else None, "median": round(statistics.median(pcts), 1) if pcts else None,
        "highest": max(pcts) if pcts else None, "lowest": min(pcts) if pcts else None,
        "pass_rate": round(100 * sum(1 for a in graded_final if a.passed) / len(graded_final), 1) if graded_final else None,
    }
    # per-question analytics, from real submitted attempts only (frozen snapshots keyed by the exam question id)
    per: dict[str, dict] = {}
    for a in attempts:
        if a.status not in FINAL_ATTEMPT_STATUSES:
            continue
        am = answer_map(a)
        for f in frozen_questions(a):
            row = per.setdefault(f["id"], {"id": f["id"], "title": (f["snapshot"]["title"] or f["snapshot"]["content"])[:80],
                                           "n": 0, "correct": 0, "incorrect": 0, "unanswered": 0, "pending": 0})
            ans = am.get(f["id"])
            row["n"] += 1
            if not ans or not ans.answer:
                row["unanswered"] += 1
            elif ans.grading_status == "pending":
                row["pending"] += 1
            elif ans.is_correct:
                row["correct"] += 1
            else:
                row["incorrect"] += 1
    qa = []
    for r in per.values():
        n = r["n"] or 1
        qa.append({**r, "percent_correct": round(100 * r["correct"] / n, 1), "percent_incorrect": round(100 * r["incorrect"] / n, 1),
                   "percent_unanswered": round(100 * r["unanswered"] / n, 1), "difficult": r["n"] >= 3 and r["correct"] / n < 0.4})
    out["questions"] = qa
    return out
