"""Create a course from a template: modules, lessons and starter blocks, all as unpublished drafts."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.models.lms import LmsBlock, LmsCourse, LmsLesson, LmsModule
from app.models.user import User
from app.services import course_templates as ct
from app.services import lms
from app.services.lms_blocks import clean_block

router = APIRouter(prefix="/teach", tags=["teacher-templates"], dependencies=[Depends(require_permission(P_COURSES_MANAGE))])
Teacher = Depends(require_permission(P_COURSES_MANAGE))


class FromTemplate(BaseModel):
    template_id: str = Field(max_length=40)
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)


@router.get("/course-templates")
def list_templates():
    return [ct.summary(t) for t in ct.TEMPLATES]


@router.post("/courses/from-template", status_code=201)
def create_from_template(data: FromTemplate, db: DB, user: User = Teacher):
    t = ct.BY_ID.get(data.template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    c = LmsCourse(owner_id=user.id, slug=lms.slugify(data.title), title=data.title, subtitle=data.subtitle, status="draft", language="עברית",
                  difficulty=t["difficulty"], instructor_name=user.display_name, completion_rule={})
    db.add(c)
    db.flush()
    for mi, m in enumerate(t["modules"]):
        mod = LmsModule(course_id=c.id, title=m["title"], position=mi, is_published=False)
        db.add(mod)
        db.flush()
        for li, les in enumerate(m["lessons"]):
            lesson = LmsLesson(course_id=c.id, module_id=mod.id, title=les["title"], position=li, estimated_minutes=les["estimated_minutes"],
                               is_free_preview=les["is_free_preview"], is_published=False)
            db.add(lesson)
            db.flush()
            for bi, b in enumerate(les["blocks"]):
                db.add(LmsBlock(lesson_id=lesson.id, type=b["type"], data=clean_block(db, user.id, b["type"], b["data"]), position=bi, is_visible=True))
    db.flush()
    return lms.course_out(c, lms.course_counts(db, [c.id])[c.id])
