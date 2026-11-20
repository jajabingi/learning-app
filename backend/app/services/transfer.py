"""Import / export. JSON = full backup of the knowledge base; CSV = questions only.

Document importers (PDF, Word, ...) plug in through IMPORTERS: implement `Importer.parse` to turn the file's
bytes into question dicts, register it for its extension, and the /import/questions endpoint picks it up.
"""
import csv
import io
import re
import uuid
from datetime import datetime
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.knowledge import Chapter, Course, Subject, Topic, TopicRelationship
from app.models.learning import UserQuestionProgress
from app.models.note import Note
from app.models.question import Question, QuestionAnswer, QuestionOption
from app.models.user import User
from app.schemas.question import AnswerIn, OptionIn, QuestionCreate
from app.services import learning
from app.services.questions import create_question
from app.services.tags import resolve_tags

FORMAT_VERSION = 1
MAX_IMPORT_ROWS = 20000


# ---------------- JSON ----------------
def export_json(db: Session, user: User) -> dict:
    def s(x):
        return str(x) if x else None

    subjects = list(db.scalars(select(Subject).where(Subject.user_id == user.id).order_by(Subject.position)))
    courses = list(db.scalars(select(Course).where(Course.user_id == user.id).order_by(Course.position)))
    chapters = list(db.scalars(select(Chapter).where(Chapter.user_id == user.id).order_by(Chapter.position)))
    topics = list(db.scalars(select(Topic).where(Topic.user_id == user.id).order_by(Topic.position)))
    questions = list(db.scalars(select(Question).where(Question.user_id == user.id)))
    prog = {p.question_id: p for p in db.scalars(select(UserQuestionProgress).where(UserQuestionProgress.user_id == user.id))}
    notes = list(db.scalars(select(Note).where(Note.user_id == user.id)))
    rels = list(db.scalars(select(TopicRelationship).where(TopicRelationship.user_id == user.id)))
    return {
        "format": "recall-export", "version": FORMAT_VERSION, "exported_at": utcnow().isoformat(),
        "subjects": [{"id": s(x.id), "name": x.name, "description": x.description, "color": x.color, "icon": x.icon,
                      "archived": x.archived_at is not None} for x in subjects],
        "courses": [{"id": s(x.id), "subject_id": s(x.subject_id), "name": x.name, "description": x.description,
                     "archived": x.archived_at is not None} for x in courses],
        "chapters": [{"id": s(x.id), "course_id": s(x.course_id), "name": x.name, "description": x.description,
                      "archived": x.archived_at is not None} for x in chapters],
        "topics": [{"id": s(x.id), "subject_id": s(x.subject_id), "chapter_id": s(x.chapter_id),
                    "parent_id": s(x.parent_id), "name": x.name, "description": x.description, "color": x.color,
                    "icon": x.icon, "tags": [t.name for t in x.tags], "archived": x.archived_at is not None} for x in topics],
        "questions": [{
            "id": s(q.id), "subject_id": s(q.subject_id), "title": q.title, "content": q.content,
            "question_type": q.question_type, "difficulty": q.difficulty, "source": q.source,
            "answer": q.answer.answer if q.answer else "", "explanation": q.answer.explanation if q.answer else "",
            "options": [{"text": o.text, "is_correct": o.is_correct} for o in q.options],
            "topic_ids": [s(t.id) for t in q.topics], "tags": [t.name for t in q.tags],
            "archived": q.archived_at is not None, "created_at": as_utc(q.created_at).isoformat(),
            "progress": None if q.id not in prog or prog[q.id].state == "new" else {
                "state": prog[q.id].state, "stability": prog[q.id].stability, "difficulty": prog[q.id].difficulty,
                "reps": prog[q.id].reps, "lapses": prog[q.id].lapses, "correct_count": prog[q.id].correct_count,
                "last_review_at": as_utc(prog[q.id].last_review_at).isoformat() if prog[q.id].last_review_at else None,
                "due_at": as_utc(prog[q.id].due_at).isoformat() if prog[q.id].due_at else None,
                "suspended": prog[q.id].suspended},
        } for q in questions],
        "notes": [{"id": s(n.id), "title": n.title, "content": n.content, "kind": n.kind,
                   "subject_id": s(n.subject_id), "course_id": s(n.course_id), "chapter_id": s(n.chapter_id),
                   "topic_id": s(n.topic_id), "question_id": s(n.question_id), "tags": [t.name for t in n.tags]} for n in notes],
        "relationships": [{"source_topic_id": s(r.source_topic_id), "target_topic_id": s(r.target_topic_id),
                           "relation_type": r.relation_type, "note": r.note} for r in rels],
    }


def _dt(v) -> datetime | None:
    if not v:
        return None
    try:
        return as_utc(datetime.fromisoformat(v))
    except (ValueError, TypeError):
        return None


def import_json(db: Session, user: User, data: dict) -> dict:
    """Adds the exported content as new rows (ids are remapped; nothing existing is overwritten)."""
    if data.get("format") != "recall-export" or data.get("version") != FORMAT_VERSION:
        raise HTTPException(422, "Not a recognised export file")
    total = sum(len(data.get(k, [])) for k in ("subjects", "courses", "chapters", "topics", "questions", "notes"))
    if total > MAX_IMPORT_ROWS:
        raise HTTPException(413, "Import is too large")
    counts = dict(subjects=0, courses=0, chapters=0, topics=0, questions=0, notes=0, relationships=0)
    smap: dict[str, Subject] = {}
    for i, x in enumerate(data.get("subjects", [])):
        o = Subject(user_id=user.id, name=str(x["name"])[:200], description=str(x.get("description", ""))[:5000],
                    color=str(x.get("color") or "#6366f1")[:16], icon=str(x.get("icon") or "book")[:40], position=i,
                    archived_at=utcnow() if x.get("archived") else None)
        db.add(o)
        smap[x["id"]] = o
        counts["subjects"] += 1
    db.flush()
    cmap: dict[str, Course] = {}
    for i, x in enumerate(data.get("courses", [])):
        if x["subject_id"] not in smap:
            continue
        o = Course(user_id=user.id, subject_id=smap[x["subject_id"]].id, name=str(x["name"])[:200],
                   description=str(x.get("description", ""))[:5000], position=i,
                   archived_at=utcnow() if x.get("archived") else None)
        db.add(o)
        cmap[x["id"]] = o
        counts["courses"] += 1
    db.flush()
    chmap: dict[str, Chapter] = {}
    for i, x in enumerate(data.get("chapters", [])):
        if x["course_id"] not in cmap:
            continue
        o = Chapter(user_id=user.id, course_id=cmap[x["course_id"]].id, name=str(x["name"])[:200],
                    description=str(x.get("description", ""))[:5000], position=i,
                    archived_at=utcnow() if x.get("archived") else None)
        db.add(o)
        chmap[x["id"]] = o
        counts["chapters"] += 1
    db.flush()
    # topics: parents first
    tmap: dict[str, Topic] = {}
    pending = [x for x in data.get("topics", []) if x.get("subject_id") in smap]
    for _ in range(50):
        if not pending:
            break
        rest = []
        for x in pending:
            if x.get("parent_id") and x["parent_id"] not in tmap:
                rest.append(x)
                continue
            o = Topic(user_id=user.id, subject_id=smap[x["subject_id"]].id,
                      chapter_id=chmap[x["chapter_id"]].id if x.get("chapter_id") in chmap else None,
                      parent_id=tmap[x["parent_id"]].id if x.get("parent_id") else None,
                      name=str(x["name"])[:200], description=str(x.get("description", ""))[:20000],
                      color=str(x.get("color", ""))[:16], icon=str(x.get("icon", ""))[:40], position=len(tmap),
                      archived_at=utcnow() if x.get("archived") else None)
            o.tags = resolve_tags(db, user, [str(t) for t in x.get("tags", [])])
            db.add(o)
            db.flush()
            tmap[x["id"]] = o
            counts["topics"] += 1
        if len(rest) == len(pending):
            break
        pending = rest
    qmap: dict[str, Question] = {}
    for x in data.get("questions", []):
        try:
            payload = QuestionCreate(
                title=x.get("title", ""), content=x.get("content", ""), question_type=x.get("question_type", "open_ended"),
                difficulty=x.get("difficulty", "medium"), source=x.get("source", ""),
                answer=AnswerIn(answer=x.get("answer", ""), explanation=x.get("explanation", "")),
                options=[OptionIn(text=o["text"], is_correct=bool(o.get("is_correct"))) for o in x.get("options", [])],
                tags=[str(t) for t in x.get("tags", [])])
        except Exception:
            continue
        q = create_question(db, user, payload)
        q.subject_id = smap[x["subject_id"]].id if x.get("subject_id") in smap else None
        q.topics = [tmap[t] for t in x.get("topic_ids", []) if t in tmap]
        q.archived_at = utcnow() if x.get("archived") else None
        pr = x.get("progress")
        if pr:
            p = learning.get_progress(db, user, q.id)
            p.state = pr.get("state", "review") if pr.get("state") in ("learning", "review", "relearning") else "review"
            p.stability, p.difficulty = float(pr.get("stability", 0)), float(pr.get("difficulty", 0))
            p.reps, p.lapses, p.correct_count = int(pr.get("reps", 0)), int(pr.get("lapses", 0)), int(pr.get("correct_count", 0))
            p.last_review_at, p.due_at, p.suspended = _dt(pr.get("last_review_at")), _dt(pr.get("due_at")), bool(pr.get("suspended"))
            learning.refresh_status(p)
        qmap[x["id"]] = q
        counts["questions"] += 1
    db.flush()
    for x in data.get("notes", []):
        n = Note(user_id=user.id, title=str(x.get("title", ""))[:300], content=str(x.get("content", ""))[:200000],
                 kind=x.get("kind") if x.get("kind") in ("note", "definition", "formula") else "note",
                 subject_id=smap[x["subject_id"]].id if x.get("subject_id") in smap else None,
                 course_id=cmap[x["course_id"]].id if x.get("course_id") in cmap else None,
                 chapter_id=chmap[x["chapter_id"]].id if x.get("chapter_id") in chmap else None,
                 topic_id=tmap[x["topic_id"]].id if x.get("topic_id") in tmap else None,
                 question_id=qmap[x["question_id"]].id if x.get("question_id") in qmap else None)
        n.tags = resolve_tags(db, user, [str(t) for t in x.get("tags", [])])
        db.add(n)
        counts["notes"] += 1
    for x in data.get("relationships", []):
        a, b = tmap.get(x.get("source_topic_id")), tmap.get(x.get("target_topic_id"))
        if a and b and a.id != b.id:
            db.add(TopicRelationship(user_id=user.id, source_topic_id=a.id, target_topic_id=b.id,
                                     relation_type=x.get("relation_type", "related_to"), note=str(x.get("note", ""))[:300]))
            counts["relationships"] += 1
    db.flush()
    return counts


# ---------------- CSV ----------------
CSV_COLUMNS = ["title", "content", "question_type", "difficulty", "answer", "explanation", "subject", "topics",
               "tags", "source", "options"]
_FORMULA = re.compile(r"^[=+\-@\t\r]")


def _safe(v: str) -> str:
    """Neutralise spreadsheet formula injection: prefix a quote when a cell would start a formula."""
    return "'" + v if _FORMULA.match(v) else v


def _unsafe(v: str) -> str:
    return v[1:] if len(v) > 1 and v[0] == "'" and _FORMULA.match(v[1:]) else v


def export_csv(db: Session, user: User) -> str:
    subjects = {s.id: s.name for s in db.scalars(select(Subject).where(Subject.user_id == user.id))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for q in db.scalars(select(Question).where(Question.user_id == user.id).order_by(Question.created_at)):
        opts = "|".join(("*" if o.is_correct else "") + o.text.replace("|", "/") for o in q.options)
        row = [q.title, q.content, q.question_type, q.difficulty, q.answer.answer if q.answer else "",
               q.answer.explanation if q.answer else "", subjects.get(q.subject_id, ""),
               ";".join(t.name for t in q.topics), ";".join(t.name for t in q.tags), q.source, opts]
        w.writerow([_safe(str(c)) for c in row])
    return buf.getvalue()


class Importer(Protocol):
    extensions: tuple[str, ...]

    def parse(self, raw: bytes) -> tuple[list[dict], list[dict]]:
        """Return (rows, errors). Each row uses the CSV_COLUMNS keys."""


class CsvImporter:
    extensions = (".csv",)

    def parse(self, raw: bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "CSV must be UTF-8 encoded")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not ({"content", "title"} & {f.strip().lower() for f in reader.fieldnames}):
            raise HTTPException(422, "CSV needs a header row with at least a 'title' or 'content' column")
        rows, errors = [], []
        for i, r in enumerate(reader, start=2):
            if i > MAX_IMPORT_ROWS:
                raise HTTPException(413, "Import is too large")
            rows.append({k.strip().lower(): _unsafe((v or "").strip()) if k else "" for k, v in r.items() if k})
        return rows, errors


IMPORTERS: dict[str, Importer] = {ext: imp for imp in (CsvImporter(),) for ext in imp.extensions}


def import_question_rows(db: Session, user: User, rows: list[dict]) -> dict:
    created, errors = 0, []
    subjects = {s.name.lower(): s for s in db.scalars(select(Subject).where(Subject.user_id == user.id))}
    topics: dict[tuple, Topic] = {(t.subject_id, t.name.lower()): t for t in db.scalars(select(Topic).where(Topic.user_id == user.id))}
    for i, r in enumerate(rows, start=2):
        try:
            subject = None
            if r.get("subject"):
                subject = subjects.get(r["subject"].lower())
                if subject is None:
                    subject = Subject(user_id=user.id, name=r["subject"][:200], position=len(subjects))
                    db.add(subject)
                    db.flush()
                    subjects[subject.name.lower()] = subject
            tlist = []
            for name in [t.strip() for t in r.get("topics", "").split(";") if t.strip()]:
                if subject is None:
                    raise ValueError("topics given without a subject")
                t = topics.get((subject.id, name.lower()))
                if t is None:
                    t = Topic(user_id=user.id, subject_id=subject.id, name=name[:200])
                    db.add(t)
                    db.flush()
                    topics[(subject.id, name.lower())] = t
                tlist.append(t.id)
            options = []
            for part in [p for p in r.get("options", "").split("|") if p.strip()]:
                options.append(OptionIn(text=part.lstrip("*").strip(), is_correct=part.startswith("*")))
            qtype = r.get("question_type") or ("multiple_choice" if options else "open_ended")
            payload = QuestionCreate(
                title=r.get("title", ""), content=r.get("content", ""), question_type=qtype,
                difficulty=r.get("difficulty") or "medium", source=r.get("source", ""),
                subject_id=subject.id if subject else None, topic_ids=tlist,
                tags=[t for t in r.get("tags", "").split(";") if t.strip()],
                answer=AnswerIn(answer=r.get("answer", ""), explanation=r.get("explanation", "")), options=options)
            create_question(db, user, payload)
            created += 1
        except Exception as e:  # report per-row problems instead of failing the whole file
            msg = e.errors()[0]["msg"] if hasattr(e, "errors") and e.errors() else str(e)
            errors.append({"row": i, "message": msg})
    return {"created": created, "errors": errors[:100], "error_count": len(errors)}
