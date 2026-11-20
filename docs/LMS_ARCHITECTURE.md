# Recall → Teaching & LMS platform: architecture and plan

## 1. Current architecture (before this change)
Single-tenant-per-user app. Every table carries `user_id`; routes resolve rows via `owned()` (404 for other users).
There was **no role concept**: any registered user got the full personal workspace (library, questions, notes, study,
FSRS, analytics, AI, graph, import/export, attachments). Name clash to watch: the library already has a `Course`
(inside a Subject); the LMS course is a different thing, so LMS tables are prefixed `lms_` / classes `Lms*`.

## 2. Target architecture
```
                       ┌──────────── FastAPI /api ────────────┐
 Teacher workspace  ── │ existing routers  (require_staff)     │ ── personal library, questions, notes, AI…
 (ADMIN/TEACHER)    ── │ /teach/*          (require_staff +    │ ── courses, modules, lessons, blocks, preview
                       │                    permission checks)  │
 Admin              ── │ /admin/*          (require_admin)      │ ── users, roles, permissions
 Student portal     ── │ /student/*        (require_student +   │ ── enrolled courses only (Phase 3+)
 (STUDENT)             │                    enrollment checks)  │
 Anyone             ── │ /auth/*, /health                       │
                       └────────────────────────────────────────┘
```
* **Two separate frontends inside one SPA**: `Layout` (teacher) and `StudentLayout` (student) with different
  navigation and design; the router chooses by `user.role`. This is convenience only — the backend enforces everything.
* **Private master question bank stays private.** Course content never references questions through student-readable
  endpoints; students receive only a *rendered projection* of the questions placed in an activity, without answers
  until the activity's policy allows (Phase 4/5).
* **Video is provider-agnostic**: a video block stores a URL; `services/video.py` resolves it against an allow-list
  (YouTube, Vimeo, direct https video/HLS) into an embed descriptor. Large files are never stored on the app server.
  A future uploader/hosting provider only needs to produce a URL (or a signed-URL resolver).

## 3. Database migration plan (Alembic 0002, additive only)
| Change | Detail |
|---|---|
| `users.role` | `student`/`teacher`/`admin`, NOT NULL, server default `student`. **Backfill: every existing user → `admin`** (they are the owner's accounts), so no one loses access to existing data. |
| `user_permissions` | (user_id, permission) fine-grained staff permissions |
| `lms_courses` | owner, slug, metadata, price config (Numeric), status draft/published/archived, access duration, completion rule |
| `lms_modules`, `lms_lessons`, `lms_blocks` | Course → Module → Lesson → ordered content blocks (JSON `data`, validated per type) |
| `lms_enrollments` | student × course, unique pair, status, source, starts/expires, granted_by |
| (attachments) | unchanged; a student may fetch a file only if a *visible block of a course they are enrolled in* references it (Phase 3) |
No existing table is dropped or altered destructively. Verified on a copy of the real DB (see tests/test_migration.py).
Later phases add: quizzes/exams/attempts, assignments/submissions, payments/installments/refunds, progress, announcements, notifications, profiles.

## 4. Authorization model
* **Roles**: `admin` (everything), `teacher` (staff, granted permissions), `student`.
* **Permissions** (checked by `require_permission`; admin bypasses): `courses.manage`, `courses.publish`,
  `students.manage`, `enrollments.manage`, `payments.manage`, `finance.view`, `announcements.manage`. Teachers get all by
  default; an admin can remove/add them per teacher. `users.manage` is admin-only by role.
* **Every request**: authenticate (JWT) → load user from DB (role is never read from the token, so demotion is instant)
  → role/permission dependency → resource ownership (`course.owner_id`) → for students: published course + published
  module/lesson + valid enrollment (`status in active/completed`, not expired, started) — failures return **404**,
  not 403, so ids cannot be probed (IDOR).
* **Default-deny sweep**: all pre-existing routers are mounted with `require_staff`; a test enumerates *every* route
  and asserts a student gets 403 and an anonymous caller 401 except an explicit public/self-service allow-list.
* Public registration only ever creates **students**. Staff accounts are created by an admin (`/admin/users`) or the
  `python -m app.cli create-admin` command.

## 5. Phases
1. **Architecture & security** (done here): roles, permissions, lock-down, schema + migration, access service.
2. **Teacher course management** (done here): dashboard, courses, publish rules, modules, lessons, 16 block types, reorder, duplicate, preview.
3. **Student portal & enrollments** (done): catalog, self-enroll for free courses only, enrolled courses, lesson viewer, explicit progress + time tracking + resume, completion rule, teacher student/enrollment management (suspend/revoke/extend), guarded files. Migration 0003 (`lms_lesson_progress`, `enrollments.completed_at`).
4. Learning content: question/quiz blocks rendered safely, practice sets.
5. Assignments & exams.
6. Payments (manual first, then gateway abstraction + sandbox), balances, financial dashboard.
7. Analytics. 8. End-to-end test matrix (the 17 scenarios in the brief).
