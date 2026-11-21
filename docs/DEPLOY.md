# Deploying Recall (Docker + PostgreSQL)

Verified: `docker compose up --build` brings up PostgreSQL 16, the API (all 7 migrations run on an empty database) and the web
container; an end-to-end smoke run (admin, teacher, student, course, exam, grading, suspension) passes through the nginx front door.

## What you need
* A Linux server with Docker + the compose plugin (any VPS with 2 GB RAM is enough to start), a domain name pointing at it.
* HTTPS in front of the `web` container (Caddy is the easiest, see below). Google sign-in and the secure session cookie need HTTPS.
* Optional: Google OAuth credentials (`docs/AUTH.md`), an SMTP account (password-reset / verification mail), an AI key.

## 1. Get the code and configure
```bash
git clone https://github.com/jajabingi/learning-app.git && cd learning-app/knowledge-platform   # branch: main once merged
cp .env.example .env && nano .env
```
Set at least:
```
POSTGRES_PASSWORD=<long random>
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
FRONTEND_URL=https://learn.example.com
CORS_ORIGINS=https://learn.example.com
GOOGLE_CLIENT_ID=...            # optional
GOOGLE_CLIENT_SECRET=...        # optional
GOOGLE_REDIRECT_URI=https://learn.example.com/api/auth/google/callback
SMTP_HOST=smtp.example.com      # optional but needed for password reset e-mails
SMTP_USER=...  SMTP_PASSWORD=...  EMAIL_FROM="Recall <no-reply@learn.example.com>"
ANTHROPIC_API_KEY=...           # optional (AI studio / tutor)
WEB_PORT=8080
```
Keep `.env` private (it is git-ignored). Never reuse `SECRET_KEY` from another environment.

## 2. Start
```bash
docker compose up -d --build
docker compose ps            # db healthy, api + web up
curl -s localhost:8080/api/health
```
The API container runs `alembic upgrade head` on every start, so upgrades are: `git pull && docker compose up -d --build`.

## 3. First administrator
```bash
docker compose exec api python -m app.cli create-admin --email you@example.com --name "Your Name"
```
Then sign in at `https://learn.example.com/teachers`. From there create teachers (Admin -> Users -> New user). See `docs/USERS.md`.

## 4. HTTPS with Caddy (example)
Install Caddy on the host and point it at the web container:
```
learn.example.com {
    reverse_proxy localhost:8080
    request_body { max_size 1100MB }
}
```
Caddy obtains and renews the certificate automatically. Only ports 80/443 should be open to the internet (the database is not published).

## 5. Backups and restore
```bash
./scripts/backup.sh /srv/recall-backups        # database dump + uploads archive; keeps the newest 14 of each
# cron (daily 03:00):   0 3 * * *  cd /path/to/knowledge-platform && ./scripts/backup.sh /srv/recall-backups
```
**Copy the backup folder off the server** (another machine or object storage): a backup on the same disk does not survive a lost server.

Restore (tested: the restored database had identical data):
```bash
docker compose exec -T db psql -U recall -d postgres -c "DROP DATABASE recall" -c "CREATE DATABASE recall"
docker compose exec -T db pg_restore -U recall -d recall --no-owner < recall-db-YYYYMMDD-HHMMSS.dump
docker compose exec -T api tar -C /data -xzf - < recall-uploads-YYYYMMDD-HHMMSS.tar.gz
docker compose restart api
```

## 6. Operating notes
* Logs: `docker compose logs -f api`. Health check: `GET /api/health`.
* Behind nginx the API trusts `X-Forwarded-For` (set in the Dockerfile), so rate limits apply per real client IP, not per proxy.
  Sign-in is limited to 30 attempts per minute per IP so a classroom sharing one Wi-Fi is fine.
* Uploaded videos live in the `uploads` volume (max 1 GB each). For many or large videos, host them on YouTube/Vimeo and paste the link.
* Single server only: the rate limiter is in-process. Running several API replicas would need Redis for it.
* Updating: back up first, then `git pull && docker compose up -d --build`.

## Pre-launch checklist
- [ ] HTTPS works, `FRONTEND_URL`/`CORS_ORIGINS` use the https domain
- [ ] First admin created, a teacher created, a test student registered and enrolled
- [ ] Password-reset e-mail arrives (SMTP configured) and the link works
- [ ] Google button appears and signs in (if enabled)
- [ ] A backup was taken AND restored on another machine at least once
- [ ] Terms of use and a privacy policy page exist (you collect e-mails and grades)
