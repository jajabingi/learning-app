import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from fastapi import Depends

from app.api.routes import admin, ai, auth, insights, library, media, notes, public, questions, student, study, teach, teach_ai, teach_institutions, teach_practice, teach_students, teach_exams, student_exams, teach_payments, student_payments, transfer
from app.core.permissions import require_staff
from app.core.config import get_settings
from app.core.db import engine

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("recall")

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_migrate:
        from alembic import command
        from alembic.config import Config

        backend = Path(__file__).resolve().parents[1]
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "migrations"))
        command.upgrade(cfg, "head")
        log.info("database migrated to head")
    yield


app = FastAPI(
    lifespan=lifespan,
    title=f"{settings.app_name} API", version="1.0.0",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None, openapi_url=None if settings.is_production else "/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.exception_handler(RequestValidationError)
async def validation(request: Request, exc: RequestValidationError):
    errs = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": errs[0]["msg"] if errs else "Invalid request", "errors": errs}, status_code=422)


@app.get("/api/health")
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api")  # public + self-service for every role
# Teacher workspace (the original personal-knowledge app): STAFF ONLY, enforced for every route of these routers.
for r in (library.router, questions.router, notes.router, study.router, insights.router, ai.router, transfer.router):
    app.include_router(r, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(teach.router, prefix="/api")      # staff + courses.manage (see router dependencies)
app.include_router(public.router, prefix="/api")          # PUBLIC catalog: no login, rate limited
app.include_router(teach_institutions.router, prefix="/api")
app.include_router(teach_ai.router, prefix="/api")
app.include_router(teach_practice.router, prefix="/api")  # practice sets by topic (staff + courses.manage)
app.include_router(teach_students.router, prefix="/api")  # staff + students/enrollments permissions
app.include_router(media.router, prefix="/api")        # video upload (staff) + signed playback
app.include_router(admin.router, prefix="/api")      # admin only
app.include_router(student.router, prefix="/api")    # student only
app.include_router(teach_exams.router, prefix="/api")    # exams: staff + courses.manage
app.include_router(student_exams.router, prefix="/api")  # exams: student only
app.include_router(teach_payments.router, prefix="/api")  # orders/ledger/finance: staff + payments.manage / finance.view
app.include_router(student_payments.router, prefix="/api")  # my payments: student only
app.include_router(student_payments.webhooks, prefix="/api")  # gateway webhooks: signature-verified
