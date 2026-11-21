# CI/CD: how a change reaches production

```
branch -> Pull Request -> CI (tests, build, Postgres migrations, Docker) -> merge to main -> Render + Vercel deploy -> post-deploy check
```

## What runs automatically
| Where | When | What |
|---|---|---|
| GitHub Actions `CI` (`.github/workflows/ci.yml`) | every Pull Request and push to `main` | backend tests, frontend typecheck + build, migrations on a real PostgreSQL (with a provider-style `postgresql://` URL), both Docker images build |
| Vercel | every PR (preview URL) and push to `main` (production) | builds `frontend/` and serves it |
| Render | push to `main` | rebuilds the backend Docker image and restarts it (`alembic upgrade head` runs on start) |
| GitHub Actions `Post-deploy check` | push to `main` | waits for production `/api/health`, checks public endpoints (and the website proxy if `PROD_SITE_URL` is set) |

## One-time setup in the web consoles (about 5 minutes)
1. **GitHub -> Settings -> Branches -> Add rule for `main`**: require a pull request, and require the status checks
   *Backend tests*, *Frontend typecheck and build*, *Migrations on PostgreSQL*, *Docker images build*. A broken change then cannot be merged.
2. **GitHub -> Settings -> Secrets and variables -> Actions -> Variables**: add `PROD_SITE_URL` = your Vercel URL
   (and `PROD_API_URL` if the Render URL changes).
3. **Render -> service -> Settings -> Build & Deploy -> Auto-Deploy**: choose *After CI checks pass* so Render only deploys a green `main`.
4. **Vercel -> Settings -> Git**: Production Branch = `main`; Root Directory = `frontend`.

## Everyday workflow
```bash
git checkout -b feat/my-change      # work, commit
git push -u origin feat/my-change   # open the Pull Request on GitHub; wait for green checks; Merge
```
Production updates by itself a few minutes later. Database changes are migrations (`alembic revision --autogenerate`); they run on the
next Render start. Always take a backup before a risky migration (`docs/DEPLOY.md`).

## If something goes wrong
* A red check: open the failed job in the PR, fix, push again.
* A bad deploy: revert the merge on GitHub (the *Revert* button on the merged PR) - Render and Vercel redeploy the previous code.
  Vercel also lets you "Promote" an older deployment instantly.
