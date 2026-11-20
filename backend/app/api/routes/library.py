import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, check_owned_optional, owned, owned_many
from app.models.base import as_utc, utcnow
from app.models.knowledge import Chapter, Course, Subject, Tag, Topic, TopicRelationship
from app.models.learning import QuestionReviewHistory
from app.models.note import Note
from app.models.question import Question, question_topics
from app.schemas.knowledge import (
    ChapterIn, ChapterPatch, CourseIn, CoursePatch, MoveIn, RelationshipIn, RelationshipOut, SubjectIn,
    SubjectPatch, TagIn, TagOut, TopicIn, TopicPatch,
)
from app.services import learning

router = APIRouter(tags=["library"])


# ---------- helpers ----------
def _next_pos(db, model, *conds) -> int:
    m = db.scalar(select(func.max(model.position)).where(*conds))
    return 0 if m is None else m + 1


def _swap(db, model, obj, direction: str, *sibling_conds):
    sibs = list(db.scalars(select(model).where(*sibling_conds).order_by(model.position, model.created_at)))
    for i, s in enumerate(sibs):
        s.position = i
    i = next(i for i, s in enumerate(sibs) if s.id == obj.id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(sibs):
        sibs[i].position, sibs[j].position = sibs[j].position, sibs[i].position
    db.flush()


def _apply_archive(obj, archived):
    if archived is not None:
        obj.archived_at = utcnow() if archived else None


def _simple_out(o, **extra):
    d = {"id": str(o.id), "name": o.name, "description": o.description, "position": o.position,
         "archived": o.archived_at is not None}
    for attr in ("color", "icon"):
        if hasattr(o, attr):
            d[attr] = getattr(o, attr)
    d.update(extra)
    return d


# ---------- tree ----------
@router.get("/library/tree")
def library_tree(db: DB, user: CurrentUser, include_archived: bool = False):
    subjects = list(db.scalars(select(Subject).where(Subject.user_id == user.id).order_by(Subject.position, Subject.created_at)))
    courses = list(db.scalars(select(Course).where(Course.user_id == user.id).order_by(Course.position, Course.created_at)))
    chapters = list(db.scalars(select(Chapter).where(Chapter.user_id == user.id).order_by(Chapter.position, Chapter.created_at)))
    topics = list(db.scalars(select(Topic).where(Topic.user_id == user.id).order_by(Topic.position, Topic.created_at)))
    stats = learning.topic_mastery_map(db, user)

    def vis(o):
        return include_archived or o.archived_at is None

    kids: dict[uuid.UUID | None, list[Topic]] = {}
    for t in topics:
        kids.setdefault(t.parent_id, []).append(t)

    def descendants(tid):
        out, st = set(), [tid]
        while st:
            c = st.pop()
            out.add(c)
            st.extend(k.id for k in kids.get(c, []))
        return out

    def tnode(t: Topic):
        agg = learning.rollup(stats, descendants(t.id))
        return {
            "id": str(t.id), "name": t.name, "color": t.color, "icon": t.icon, "archived": t.archived_at is not None,
            "subject_id": str(t.subject_id), "chapter_id": str(t.chapter_id) if t.chapter_id else None,
            "parent_id": str(t.parent_id) if t.parent_id else None,
            "question_count": agg["questions"], "mastery": round(agg["mastery"], 3), "due": agg["due"],
            "children": [tnode(k) for k in kids.get(t.id, []) if vis(k)],
        }

    by_chapter: dict = {}
    by_subject_root: dict = {}
    for t in topics:
        if t.parent_id is None and vis(t):
            if t.chapter_id:
                by_chapter.setdefault(t.chapter_id, []).append(t)
            else:
                by_subject_root.setdefault(t.subject_id, []).append(t)

    result = []
    for s in subjects:
        if not vis(s):
            continue
        sub_topics = {t.id for t in topics if t.subject_id == s.id}
        agg = learning.rollup(stats, sub_topics)
        sc = []
        for c in (c for c in courses if c.subject_id == s.id and vis(c)):
            chs = [
                {**_simple_out(ch), "topics": [tnode(t) for t in by_chapter.get(ch.id, [])]}
                for ch in chapters if ch.course_id == c.id and vis(ch)
            ]
            sc.append({**_simple_out(c), "chapters": chs})
        result.append({
            **_simple_out(s), "courses": sc, "topics": [tnode(t) for t in by_subject_root.get(s.id, [])],
            "question_count": agg["questions"], "mastery": round(agg["mastery"], 3), "due": agg["due"],
            "topic_count": len(sub_topics),
        })
    return result


# ---------- subjects ----------
@router.post("/subjects", status_code=201)
def create_subject(data: SubjectIn, db: DB, user: CurrentUser):
    s = Subject(user_id=user.id, name=data.name.strip(), description=data.description,
                color=data.color or "#6366f1", icon=data.icon or "book",
                position=_next_pos(db, Subject, Subject.user_id == user.id))
    db.add(s)
    db.flush()
    return _simple_out(s)


@router.get("/subjects/{subject_id}")
def get_subject(subject_id: uuid.UUID, db: DB, user: CurrentUser):
    s = owned(db, Subject, subject_id, user)
    topic_ids = set(db.scalars(select(Topic.id).where(Topic.subject_id == s.id)))
    agg = learning.rollup(learning.topic_mastery_map(db, user), topic_ids)
    qcount = db.scalar(select(func.count()).select_from(Question).where(Question.subject_id == s.id, Question.archived_at.is_(None)))
    return {**_simple_out(s), "topic_count": len(topic_ids), "question_count": qcount, "mastery": round(agg["mastery"], 3),
            "due": agg["due"], "accuracy": agg["accuracy"], "mastered": agg["mastered"]}


@router.patch("/subjects/{subject_id}")
def patch_subject(subject_id: uuid.UUID, data: SubjectPatch, db: DB, user: CurrentUser):
    s = owned(db, Subject, subject_id, user)
    for k, v in data.model_dump(exclude_unset=True, exclude={"archived"}).items():
        if v is not None:
            setattr(s, k, v.strip() if k == "name" else v)
    _apply_archive(s, data.archived)
    return _simple_out(s)


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(subject_id: uuid.UUID, db: DB, user: CurrentUser):
    s = owned(db, Subject, subject_id, user)
    db.delete(s)  # courses/chapters/topics cascade; questions/notes keep existing, unfiled


@router.post("/subjects/{subject_id}/move", status_code=204)
def move_subject(subject_id: uuid.UUID, data: MoveIn, db: DB, user: CurrentUser):
    s = owned(db, Subject, subject_id, user)
    _swap(db, Subject, s, data.direction, Subject.user_id == user.id)


# ---------- courses ----------
@router.post("/courses", status_code=201)
def create_course(data: CourseIn, db: DB, user: CurrentUser):
    owned(db, Subject, data.subject_id, user)
    c = Course(user_id=user.id, subject_id=data.subject_id, name=data.name.strip(), description=data.description,
               position=_next_pos(db, Course, Course.subject_id == data.subject_id))
    db.add(c)
    db.flush()
    return _simple_out(c, subject_id=str(c.subject_id))


@router.get("/courses/{course_id}")
def get_course(course_id: uuid.UUID, db: DB, user: CurrentUser):
    c = owned(db, Course, course_id, user)
    return _simple_out(c, subject_id=str(c.subject_id))


@router.patch("/courses/{course_id}")
def patch_course(course_id: uuid.UUID, data: CoursePatch, db: DB, user: CurrentUser):
    c = owned(db, Course, course_id, user)
    if data.name is not None:
        c.name = data.name.strip()
    if data.description is not None:
        c.description = data.description
    if data.subject_id and data.subject_id != c.subject_id:
        owned(db, Subject, data.subject_id, user)
        c.subject_id = data.subject_id
        c.position = _next_pos(db, Course, Course.subject_id == data.subject_id)
        chapter_ids = list(db.scalars(select(Chapter.id).where(Chapter.course_id == c.id)))
        for t in db.scalars(select(Topic).where(Topic.chapter_id.in_(chapter_ids))) if chapter_ids else []:
            for tid in learning.descendant_topic_ids(db, user, t.id):
                db.get(Topic, tid).subject_id = data.subject_id
    _apply_archive(c, data.archived)
    return _simple_out(c, subject_id=str(c.subject_id))


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Course, course_id, user))  # topics inside move to the subject root


@router.post("/courses/{course_id}/move", status_code=204)
def move_course(course_id: uuid.UUID, data: MoveIn, db: DB, user: CurrentUser):
    c = owned(db, Course, course_id, user)
    _swap(db, Course, c, data.direction, Course.subject_id == c.subject_id)


# ---------- chapters ----------
@router.post("/chapters", status_code=201)
def create_chapter(data: ChapterIn, db: DB, user: CurrentUser):
    owned(db, Course, data.course_id, user)
    ch = Chapter(user_id=user.id, course_id=data.course_id, name=data.name.strip(), description=data.description,
                 position=_next_pos(db, Chapter, Chapter.course_id == data.course_id))
    db.add(ch)
    db.flush()
    return _simple_out(ch, course_id=str(ch.course_id))


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: uuid.UUID, db: DB, user: CurrentUser):
    ch = owned(db, Chapter, chapter_id, user)
    course = db.get(Course, ch.course_id)
    return _simple_out(ch, course_id=str(ch.course_id), subject_id=str(course.subject_id))


@router.patch("/chapters/{chapter_id}")
def patch_chapter(chapter_id: uuid.UUID, data: ChapterPatch, db: DB, user: CurrentUser):
    ch = owned(db, Chapter, chapter_id, user)
    if data.name is not None:
        ch.name = data.name.strip()
    if data.description is not None:
        ch.description = data.description
    if data.course_id and data.course_id != ch.course_id:
        new_course = owned(db, Course, data.course_id, user)
        ch.course_id = new_course.id
        ch.position = _next_pos(db, Chapter, Chapter.course_id == new_course.id)
        for t in db.scalars(select(Topic).where(Topic.chapter_id == ch.id)):
            for tid in learning.descendant_topic_ids(db, user, t.id):
                db.get(Topic, tid).subject_id = new_course.subject_id
    _apply_archive(ch, data.archived)
    return _simple_out(ch, course_id=str(ch.course_id))


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Chapter, chapter_id, user))


@router.post("/chapters/{chapter_id}/move", status_code=204)
def move_chapter(chapter_id: uuid.UUID, data: MoveIn, db: DB, user: CurrentUser):
    ch = owned(db, Chapter, chapter_id, user)
    _swap(db, Chapter, ch, data.direction, Chapter.course_id == ch.course_id)


# ---------- topics ----------
def _place(db, user, topic: Topic, subject_id, chapter_id, parent_id):
    """Resolve and validate a placement; subtopics inherit subject+chapter from their parent."""
    if parent_id:
        parent = owned(db, Topic, parent_id, user)
        if topic.id and parent.id in learning.descendant_topic_ids(db, user, topic.id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A topic cannot be moved inside itself")
        return parent.subject_id, parent.chapter_id, parent.id
    if chapter_id:
        ch = owned(db, Chapter, chapter_id, user)
        course = db.get(Course, ch.course_id)
        if subject_id and subject_id != course.subject_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chapter belongs to a different subject")
        return course.subject_id, ch.id, None
    if not subject_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "subject_id is required")
    owned(db, Subject, subject_id, user)
    return subject_id, None, None


@router.post("/topics", status_code=201)
def create_topic(data: TopicIn, db: DB, user: CurrentUser):
    t = Topic(user_id=user.id, name=data.name.strip(), description=data.description, color=data.color or "",
              icon=data.icon or "")
    t.subject_id, t.chapter_id, t.parent_id = _place(db, user, t, data.subject_id, data.chapter_id, data.parent_id)
    t.position = _next_pos(db, Topic, Topic.user_id == user.id, Topic.subject_id == t.subject_id,
                           Topic.chapter_id == t.chapter_id if t.chapter_id else Topic.chapter_id.is_(None),
                           Topic.parent_id == t.parent_id if t.parent_id else Topic.parent_id.is_(None))
    t.tags = owned_many(db, Tag, data.tag_ids, user)
    db.add(t)
    db.flush()
    return _topic_brief(t)


def _topic_brief(t: Topic):
    return {"id": str(t.id), "name": t.name, "subject_id": str(t.subject_id),
            "chapter_id": str(t.chapter_id) if t.chapter_id else None,
            "parent_id": str(t.parent_id) if t.parent_id else None, "description": t.description,
            "color": t.color, "icon": t.icon, "archived": t.archived_at is not None,
            "tags": [TagOut.model_validate(x).model_dump(mode="json") for x in t.tags]}


@router.get("/topics")
def list_topics(db: DB, user: CurrentUser, subject_id: uuid.UUID | None = None, q: str | None = None,
                include_archived: bool = False):
    """Flat topic list with breadcrumb-ish path, for pickers."""
    stmt = select(Topic).where(Topic.user_id == user.id)
    if subject_id:
        stmt = stmt.where(Topic.subject_id == subject_id)
    if q:
        stmt = stmt.where(Topic.name.ilike(f"%{q}%"))
    if not include_archived:
        stmt = stmt.where(Topic.archived_at.is_(None))
    topics = list(db.scalars(stmt.order_by(Topic.name).limit(2000)))
    names = {t.id: t.name for t in db.scalars(select(Topic).where(Topic.user_id == user.id))}
    subjects = {s.id: s.name for s in db.scalars(select(Subject).where(Subject.user_id == user.id))}
    parents = {t.id: t.parent_id for t in db.scalars(select(Topic).where(Topic.user_id == user.id))}

    def path(t):
        parts, cur, guard = [t.name], parents.get(t.id), 0
        while cur and guard < 20:
            parts.append(names.get(cur, "?"))
            cur, guard = parents.get(cur), guard + 1
        return " › ".join(reversed(parts))

    return [{"id": str(t.id), "name": t.name, "path": path(t), "subject_id": str(t.subject_id),
             "subject_name": subjects.get(t.subject_id, "")} for t in topics]


@router.get("/topics/{topic_id}")
def get_topic(topic_id: uuid.UUID, db: DB, user: CurrentUser):
    t = owned(db, Topic, topic_id, user)
    now = utcnow()
    subject = db.get(Subject, t.subject_id)
    chapter = db.get(Chapter, t.chapter_id) if t.chapter_id else None
    course = db.get(Course, chapter.course_id) if chapter else None
    trail, cur, guard = [], t.parent_id, 0
    while cur and guard < 30:
        p = db.get(Topic, cur)
        trail.append({"id": str(p.id), "name": p.name})
        cur, guard = p.parent_id, guard + 1
    trail.reverse()

    subtree = learning.descendant_topic_ids(db, user, t.id)
    stats = learning.topic_mastery_map(db, user, now)
    own, total = learning.rollup(stats, {t.id}), learning.rollup(stats, subtree)
    children = list(db.scalars(select(Topic).where(Topic.parent_id == t.id).order_by(Topic.position, Topic.created_at)))

    rels = list(db.scalars(select(TopicRelationship).where(
        TopicRelationship.user_id == user.id,
        (TopicRelationship.source_topic_id == t.id) | (TopicRelationship.target_topic_id == t.id))))
    other_ids = {r.target_topic_id if r.source_topic_id == t.id else r.source_topic_id for r in rels}
    others = {o.id: o for o in db.scalars(select(Topic).where(Topic.id.in_(other_ids)))} if other_ids else {}
    related = [{"id": str(r.id), "relation_type": r.relation_type, "direction": "out" if r.source_topic_id == t.id else "in",
                "topic": {"id": str(others[oid].id), "name": others[oid].name}}
               for r in rels for oid in [r.target_topic_id if r.source_topic_id == t.id else r.source_topic_id] if oid in others]

    # study history: reviews of this topic's questions
    qids = select(question_topics.c.question_id).where(question_topics.c.topic_id.in_(subtree))
    since = now - timedelta(days=30)
    hist_rows = db.execute(
        select(QuestionReviewHistory, Question.title).join(Question, Question.id == QuestionReviewHistory.question_id)
        .where(QuestionReviewHistory.user_id == user.id, QuestionReviewHistory.question_id.in_(qids))
        .order_by(QuestionReviewHistory.reviewed_at.desc()).limit(200)
    ).all()
    per_day: dict[str, dict] = {}
    for h, _ in hist_rows:
        if as_utc(h.reviewed_at) >= since:
            d = per_day.setdefault(as_utc(h.reviewed_at).date().isoformat(), {"reviews": 0, "correct": 0})
            d["reviews"] += 1
            d["correct"] += int(h.correct)
    note_counts = db.execute(select(Note.kind, func.count()).where(Note.user_id == user.id, Note.topic_id == t.id)
                             .group_by(Note.kind)).all()
    return {
        **_topic_brief(t),
        "breadcrumb": {"subject": {"id": str(subject.id), "name": subject.name},
                       "course": {"id": str(course.id), "name": course.name} if course else None,
                       "chapter": {"id": str(chapter.id), "name": chapter.name} if chapter else None,
                       "ancestors": trail},
        "children": [_topic_brief(c) for c in children if c.archived_at is None],
        "related": related,
        "progress": {"direct_questions": own["questions"], "questions": total["questions"], "mastery": round(total["mastery"], 3),
                     "accuracy": total["accuracy"], "due": total["due"], "mastered": total["mastered"],
                     "new": total["new"], "lapses": total["lapses"], "reviews": total["reps"]},
        "history": {"per_day": [{"date": k, **v} for k, v in sorted(per_day.items())],
                    "recent": [{"question_id": str(h.question_id), "title": title, "rating": h.rating,
                                "correct": h.correct, "reviewed_at": as_utc(h.reviewed_at).isoformat(),
                                "study_mode": h.study_mode} for h, title in hist_rows[:25]]},
        "note_counts": {k: v for k, v in note_counts},
    }


@router.patch("/topics/{topic_id}")
def patch_topic(topic_id: uuid.UUID, data: TopicPatch, db: DB, user: CurrentUser):
    t = owned(db, Topic, topic_id, user)
    if data.name is not None:
        t.name = data.name.strip()
    for f in ("description", "color", "icon"):
        v = getattr(data, f)
        if v is not None:
            setattr(t, f, v)
    if data.tag_ids is not None:
        t.tags = owned_many(db, Tag, data.tag_ids, user)
    _apply_archive(t, data.archived)
    if data.move:
        subject_id, chapter_id, parent_id = _place(db, user, t, data.subject_id, data.chapter_id, data.parent_id)
        t.subject_id, t.chapter_id, t.parent_id = subject_id, chapter_id, parent_id
        t.position = _next_pos(db, Topic, Topic.user_id == user.id, Topic.subject_id == subject_id)
        for tid in learning.descendant_topic_ids(db, user, t.id) - {t.id}:
            d = db.get(Topic, tid)
            d.subject_id, d.chapter_id = subject_id, chapter_id
    db.flush()
    return _topic_brief(t)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Topic, topic_id, user))  # subtopics cascade; questions are kept (unlinked from the topic)


@router.post("/topics/{topic_id}/move", status_code=204)
def reorder_topic(topic_id: uuid.UUID, data: MoveIn, db: DB, user: CurrentUser):
    t = owned(db, Topic, topic_id, user)
    _swap(db, Topic, t, data.direction, Topic.user_id == user.id, Topic.subject_id == t.subject_id,
          Topic.chapter_id == t.chapter_id if t.chapter_id else Topic.chapter_id.is_(None),
          Topic.parent_id == t.parent_id if t.parent_id else Topic.parent_id.is_(None))


# ---------- tags ----------
@router.get("/tags")
def list_tags(db: DB, user: CurrentUser):
    from app.models.question import question_tags
    counts = dict(db.execute(select(question_tags.c.tag_id, func.count()).group_by(question_tags.c.tag_id)).all())
    return [{**TagOut.model_validate(t).model_dump(mode="json"), "question_count": counts.get(t.id, 0)}
            for t in db.scalars(select(Tag).where(Tag.user_id == user.id).order_by(Tag.name))]


@router.patch("/tags/{tag_id}")
def patch_tag(tag_id: uuid.UUID, data: TagIn, db: DB, user: CurrentUser):
    from app.services.tags import normalize
    t = owned(db, Tag, tag_id, user)
    name = normalize(data.name)
    clash = db.scalar(select(Tag).where(Tag.user_id == user.id, Tag.name == name, Tag.id != t.id))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tag with that name exists")
    t.name, t.color = name, data.color or t.color
    return TagOut.model_validate(t)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Tag, tag_id, user))


# ---------- relationships / graph ----------
@router.get("/graph")
def graph(db: DB, user: CurrentUser, subject_id: uuid.UUID | None = None):
    stmt = select(Topic).where(Topic.user_id == user.id, Topic.archived_at.is_(None))
    if subject_id:
        stmt = stmt.where(Topic.subject_id == subject_id)
    topics = list(db.scalars(stmt))
    stats = learning.topic_mastery_map(db, user)
    subjects = {s.id: s for s in db.scalars(select(Subject).where(Subject.user_id == user.id))}
    ids = {t.id for t in topics}
    rels = [r for r in db.scalars(select(TopicRelationship).where(TopicRelationship.user_id == user.id))
            if r.source_topic_id in ids and r.target_topic_id in ids]
    nodes = []
    for t in topics:
        s = learning.rollup(stats, {t.id})
        nodes.append({"id": str(t.id), "name": t.name, "subject_id": str(t.subject_id),
                      "subject_name": subjects[t.subject_id].name if t.subject_id in subjects else "",
                      "color": subjects[t.subject_id].color if t.subject_id in subjects else "#6366f1",
                      "questions": s["questions"], "mastery": round(s["mastery"], 3), "accuracy": s["accuracy"],
                      "due": s["due"]})
    return {"nodes": nodes, "edges": [RelationshipOut.model_validate(r).model_dump(mode="json") for r in rels]}


@router.post("/relationships", response_model=RelationshipOut, status_code=201)
def create_relationship(data: RelationshipIn, db: DB, user: CurrentUser):
    if data.source_topic_id == data.target_topic_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A topic cannot relate to itself")
    owned(db, Topic, data.source_topic_id, user)
    owned(db, Topic, data.target_topic_id, user)
    dup = db.scalar(select(TopicRelationship).where(
        TopicRelationship.source_topic_id == data.source_topic_id,
        TopicRelationship.target_topic_id == data.target_topic_id,
        TopicRelationship.relation_type == data.relation_type))
    if dup:
        return dup
    r = TopicRelationship(user_id=user.id, **data.model_dump())
    db.add(r)
    db.flush()
    return r


@router.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, TopicRelationship, rel_id, user))
