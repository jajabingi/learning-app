# Recall — teaching platform + personal knowledge workspace

Teacher workspace (courses, curriculum builder, lesson content blocks, preview, plus the original personal library/questions/
notes/FSRS/graph/AI tools) and a separate student portal. See `docs/LMS_ARCHITECTURE.md` for the architecture, migration
plan, authorization model and phases. **Status:** Phases 1–3 done (roles/permissions, course builder, student portal with
catalog/progress, teacher enrollment & student management); quizzes, assignments, payments, notifications, analytics are next.

## Original description: personal knowledge & learning platform

Knowledge library + question bank + notes + knowledge graph + FSRS spaced repetition + AI helpers.
React/TypeScript/Vite/Tailwind frontend, FastAPI/SQLAlchemy backend, PostgreSQL (SQLite for quick local dev).

## Run locally (no Docker)

```bash
# backend (http://localhost:8000, docs at /api/docs)
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --reload                        # auto-migrates a local SQLite file

# frontend (http://localhost:5173, proxies /api to :8000)
cd frontend && npm install && npm run dev
```

**Roles.** Public registration creates **student** accounts only. Staff (teacher/admin) accounts are created by an
admin (Teaching → *Team & permissions*) or on the command line:
```bash
cd backend && .venv/Scripts/python -m app.cli create-admin --email you@example.com   # prompts for a password
# Docker: docker compose exec api python -m app.cli create-admin --email you@example.com
```
Accounts that existed before the teaching platform was added were automatically promoted to admin (migration 0002).
Tests: `cd backend && .venv/Scripts/python -m pytest`.

## Run with Docker (PostgreSQL)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD and SECRET_KEY (and optionally ANTHROPIC_API_KEY)
docker compose up --build   # http://localhost:8080
```
The API container runs `alembic upgrade head` on start. Uploads and the DB live in named volumes.

## Architecture

```
backend/app
  core/      config, DB session (one transaction per request), JWT + bcrypt, rate limiter
  models/    SQLAlchemy tables (user, knowledge, question, learning, note)
  schemas/   Pydantic request/response models (all input validated here)
  services/  business logic: fsrs.py, learning.py (queues, mastery), analytics.py, transfer.py (import/export),
             storage.py (uploads), ai/ (provider abstraction + prompts)
  api/routes HTTP layer: auth, library, questions, notes, study, insights, ai, transfer
backend/migrations   Alembic (0001 = full schema)     backend/tests   pytest (FSRS unit + API workflows)
frontend/src
  api/ client with token refresh · components/ UI + feature components · contexts/ auth, theme, toasts
  hooks/ shared queries · pages/ one file per screen · lib/ formatting
```

### Database
Users → Subjects → Courses → Chapters → Topics (self-referencing `parent_id` = subtopics). A topic always has a
`subject_id`; `chapter_id` and `parent_id` are optional, so topics can sit anywhere and be moved freely.
Questions belong to a user, optionally a subject, and link to many topics (`question_topics`) and tags
(`question_tags`); `question_answers`, `question_options`, `attachments` hang off them. Learning data:
`user_question_progress` (FSRS state, one row per user+question), `study_sessions`, `study_session_questions`,
`question_review_history` (append-only log). Also `notes` (+`note_links`, `note_tags`), `tags`, `topic_relationships`.
Every table carries `user_id`; every route resolves objects through `owned()` which returns 404 for other users' rows.
Deleting a subject cascades to its courses/topics; questions and notes are kept (unfiled). Deleting a chapter/course
moves topics to the subject root.

### Spaced repetition
FSRS-4.5 with default weights (`services/fsrs.py`): stability, difficulty, retrievability, ratings Again/Hard/Good/Easy,
target retention configurable in Settings. "Again" re-queues the card at the end of the current session and schedules it
10 min out. Status: New / Learning / Reviewing / Mastered / Suspended. **Mastered is derived, not stored**: stability ≥ 21 d
and current recall ≥ 85%, so neglected questions fall back to Reviewing.

### Analytics definitions
Accuracy (answers not rated Again) · Retention (accuracy on already-learned cards) · Mastery (recall × maturity over *all*
questions, unstudied = 0) · Completion (due reviews actually done) · Activity (volume, streak, time). Shown separately in the UI.

### AI
`services/ai/provider.py` is the only code that knows the vendor or key. Set `ANTHROPIC_API_KEY` (server env). Features:
question generation (returns drafts only; saved via `POST /questions/batch` after you confirm), answer evaluation,
tutor actions, study plan. Without a key, AI endpoints return 503 and the UI explains why. Add a provider by implementing
`AIProvider.complete`.

### Import / export
JSON full backup (incl. FSRS state) and CSV questions. `services/transfer.py:IMPORTERS` maps file extensions to parsers —
add PDF/Word by registering an importer.

## Feature status

| Area | Status |
|---|---|
| Auth (register/login/refresh, bcrypt, JWT, rate-limited) | Done, tested |
| Library hierarchy: create/edit/archive/delete/reorder/move, tags, colors | Done, tested (drag-and-drop reorder not implemented; up/down + Move dialog) |
| Question bank: 11 types, editor (Markdown/LaTeX/code/tables/images), filters, bulk, duplicate, CSV/JSON | Done, tested |
| Study modes (8), sessions, pause/resume, FSRS, review queue | Done, tested |
| Dashboard, analytics, weak areas | Done, tested (real data) |
| Notes (Markdown, `[[links]]`, backlinks, note→question, definitions/formulas) | Done |
| Knowledge graph (React Flow, prerequisites, weak highlighting, create/delete edges) | Done; browser-smoke-tested |
| AI generation / evaluation / tutor / plan | Implemented and tested against a fake provider; **not run against the live API** |
| Docker / PostgreSQL | Files written; **not run here** (Docker daemon unavailable). Schema/migration verified on SQLite only |

## Known limitations
- Dates/streaks use UTC days (the `timezone` field is stored but unused).
- Rich text is a Markdown editor with toolbar + preview, not WYSIWYG.
- Search is `ILIKE`-based (fine for personal scale; add Postgres full-text/pg_trgm for very large libraries).
- Deleting a question leaves its uploaded files on disk. Rate limiting is in-process (use Redis for multi-replica).
- FSRS uses default parameters; no per-user optimisation yet. PDF/Word import not built.


## AI studio (generate modules and questions from a prompt)
Teaching -> a course -> **AI studio** (new module) or a practice set -> **Generate questions with AI** (questions with step-by-step
solutions). Output is always a draft that you review before importing. Keys stay on the server, set in `backend/.env`:
```
# Claude (default)
ANTHROPIC_API_KEY=...
# or ChatGPT / any OpenAI-compatible API
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o            # use any chat model your account supports
OPENAI_BASE_URL=https://api.openai.com/v1
```
Restart the API after changing `.env`. Endpoints: `POST /api/teach/ai/module-draft`, `.../courses/{id}/import-module`, `.../question-drafts`.
Tested with a fake provider only; not yet run against a live key.

## Public pages, institutions and the paywall
Visitors see a Hebrew landing page (`/`) listing published **institutions** (Teaching -> Institutions), then the institution's courses,
then a public course page. Lessons marked *free preview* are readable without an account; any other lesson opens a purchase dialog.
Non-free courses: the student sends a purchase request (a **pending** enrollment that grants nothing); the teacher activates it in the
course's Students tab after receiving payment. Online card payment is not built yet.
UI strings live in `frontend/src/i18n/he.ts`; to add English, create `en.ts` with the same keys.
