# Authentication, roles and user management

## Roles and who can do what
| Role | Gets it by | Can |
|---|---|---|
| student | public registration (e-mail or Google) - always | own profile, enrolled courses, own progress/exams/grades |
| teacher | an administrator promotes the user | create/manage **own** courses, question bank, exams; see **own** enrollments/students |
| admin | an administrator promotes the user (or the CLI) | everything above + user directory, roles, suspension, audit log |

The role is never read from a registration or profile payload. Every API route re-checks role, permission and ownership on the server;
hiding buttons in React is only a convenience. Resources that belong to someone else answer **404**, not 403, so ids cannot be probed.

## Account status
`active` | `suspended` | `pending_verification`. Suspension (and logout, password change/reset, role change) bumps the user's
`token_version`, which instantly invalidates every access/refresh token issued earlier. Reactivation restores access to the same data;
old tokens stay dead, so the user signs in again.

## Sign-in flows
* **E-mail + password** - bcrypt, e-mail normalised (trimmed, lower-case), duplicate detection, rate limited.
* **Password reset** - `POST /api/auth/password/forgot` always answers the same way; the e-mailed link carries a single-use token
  (stored only as a SHA-256 hash, 60 min). Resetting revokes all sessions.
* **E-mail verification** - set `REQUIRE_EMAIL_VERIFICATION=true`; registration then returns 202 and the account is
  `pending_verification` until the emailed link is opened.
* **Google** - OAuth 2.0 authorization-code flow with PKCE, completely server side:
  1. `GET /api/auth/google/start` creates `state`, `nonce` and a PKCE verifier, keeps them in a signed httpOnly cookie, redirects to Google.
  2. `GET /api/auth/google/callback` checks `state` against the cookie (CSRF), exchanges the code with the client secret, then verifies the
     ID token: RS256 signature against Google's JWKS, `iss`, `aud` = our client id, `exp`, `nonce`, `email_verified`.
  3. The SPA receives only a **single-use 2-minute code** in the redirect and trades it at `POST /api/auth/google/exchange` for tokens
     (tokens never appear in a URL).
  * Identity key = Google's `sub` (table `user_identities`), not the e-mail.
  * New Google users are created as `student`, with no password.
  * **Linking** never happens just because e-mails match. If a password account already has that address, nothing is linked: an e-mail with a
    confirmation link goes to the account's own mailbox (`POST /api/auth/link/confirm`), or the signed-in user connects Google from
    Settings/Account (`POST /api/auth/google/link/start`). The user id - and with it courses, progress, grades - never changes.
  * A Google identity can belong to one user only; the last sign-in method cannot be removed.

## Google Cloud setup (needed to test Google end-to-end)
1. https://console.cloud.google.com -> create/select a project -> **APIs & Services -> OAuth consent screen** (External, add yourself as test user).
2. **Credentials -> Create credentials -> OAuth client ID -> Web application**.
3. *Authorized redirect URIs*: `http://localhost:8000/api/auth/google/callback` (and your production URL + `/api/auth/google/callback`).
4. Put the client id/secret in `backend/.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (never in the frontend), restart the API.
   The login page shows the Google button only when both are set (`GET /api/auth/config`).
5. Production: serve over HTTPS and set `ENVIRONMENT=production` (cookies become `Secure`).

## Audit log
`GET /api/admin/audit` (admin only). Records role changes, suspensions/reactivations, user creation, profile/permission edits, registration,
Google sign-in, linking/unlinking, password change/reset and e-mail verification: actor, target, action, time, metadata. Keys that look like
secrets (`password`, `token`, `secret`, `code`, `hash`, ...) are dropped before storing.

## Admin API
`GET /api/admin/users/directory?q=&role=&status=&sort=&order=&page=&page_size=` - `GET /api/admin/users/{id}` - `PATCH /api/admin/users/{id}`
(`role`, `status`, `display_name`, `permissions`) - `GET /api/admin/users/summary` - `GET /api/admin/audit`.
Guards: the last active admin cannot be demoted or suspended; nobody can demote or suspend themselves.
