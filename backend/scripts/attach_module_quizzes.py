"""Turns each module-quiz block of the seeded course into a real, startable practice set (kind=exam) WITHOUT reseeding,
so enrolled students keep their progress.   Usage (from backend/):  .venv/Scripts/python scripts/attach_module_quizzes.py"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.lms import LmsBlock, LmsCourse, LmsLesson, LmsModule, LmsPracticeItem, LmsPracticeSet  # noqa: E402


def main():
    db = SessionLocal()
    try:
        made = 0
        for course in db.scalars(select(LmsCourse)):
            for mod in db.scalars(select(LmsModule).where(LmsModule.course_id == course.id).order_by(LmsModule.position)):
                for les in db.scalars(select(LmsLesson).where(LmsLesson.module_id == mod.id)):
                    for b in db.scalars(select(LmsBlock).where(LmsBlock.lesson_id == les.id, LmsBlock.type == "quiz")):
                        if (b.data or {}).get("practice_set_id") or not b.data.get("question_ids"):
                            continue
                        ps = LmsPracticeSet(course_id=course.id, title=b.data.get("title") or f"בוחן — {mod.title}", kind="exam",
                                            description="בוחן סיכום למודול. נסו לפתור לפני שמציגים את הפתרון המלא.",
                                            position=100 + mod.position, is_published=True)
                        db.add(ps)
                        db.flush()
                        for i, qid in enumerate(b.data["question_ids"]):
                            db.add(LmsPracticeItem(set_id=ps.id, question_id=uuid.UUID(qid), position=i))
                        b.data = {**b.data, "practice_set_id": str(ps.id)}
                        flag_modified(b, "data")
                        made += 1
        db.commit()
        print(f"linked {made} module quizzes to practice sets")
    finally:
        db.close()


if __name__ == "__main__":
    main()
