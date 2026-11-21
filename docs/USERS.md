# Users: who signs in where, and how accounts are created

| Who | Sign-in page | How the account is created | Lands on |
|---|---|---|---|
| Student | `/login` (or "Continue with Google") | Registers themselves at `/register`; always a student | `/my` |
| Teacher | `/teachers` (`/login` also works) | **Never self-service.** An admin creates it (Admin -> Users -> New user, or Teaching -> Team & permissions), or promotes an existing student | `/teach` |
| Admin | `/teachers` | The first admin is created on the server with the CLI; later admins are promoted by an admin | `/admin` |

## First administrator (once, on a new install)
```bash
cd backend && .venv/Scripts/python -m app.cli create-admin --email you@example.com --name "Your Name"
# Docker:
docker compose exec api python -m app.cli create-admin --email you@example.com
```
It asks for the password twice (set `RECALL_PASSWORD` for scripts). Other commands: `create-teacher`, `set-role`, `reset-password`,
`suspend`, `activate`, `list-users`. The last active admin can never be demoted or suspended.

## Day to day (as admin, in the browser)
* **Admin -> Users**: search, filter by role/status, sort, page; **New user** (student/teacher/admin with a temporary password).
* Open a user: change role (confirmation dialog), **Promote to teacher**, **Suspend / Reactivate**, **Send password reset email**,
  see enrollments and the activity history. Everything is written to the audit log (Admin -> Users -> Audit log).
* A suspended user is signed out everywhere at once and cannot sign in; their data stays.

## Students getting into courses
Registration only creates the account. Access to a course is separate: free courses can be joined by the student; paid courses are
requested by the student and approved by the teacher (course -> Students), or the teacher enrolls the student by e-mail.

## Google
Enabled only when `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set (see `docs/AUTH.md`). New Google users are students. If an account with
that e-mail already exists, it is **not** linked automatically: a confirmation link goes to that mailbox, or the user connects Google from
Settings / My account while signed in.
