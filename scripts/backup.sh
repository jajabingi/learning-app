#!/usr/bin/env bash
# Backs up the PostgreSQL database and the uploads volume of a running Docker deployment.
#   ./scripts/backup.sh [backup_dir]            (default ./backups)
# Restore:  see docs/DEPLOY.md ("Backups and restore").  Run daily from cron and copy the files off the server.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:-./backups}"; STAMP="$(date +%Y%m%d-%H%M%S)"; PROJECT="${COMPOSE_PROJECT_NAME:-}"
mkdir -p "$DIR"
C=(docker compose ${PROJECT:+-p "$PROJECT"})
"${C[@]}" exec -T db pg_dump -U recall -d recall --format=custom > "$DIR/recall-db-$STAMP.dump"
"${C[@]}" exec -T api tar -C /data -czf - uploads > "$DIR/recall-uploads-$STAMP.tar.gz" 2>/dev/null || echo "(no uploads yet)"
# keep the 14 newest of each kind
for kind in db uploads; do ls -1t "$DIR"/recall-$kind-* 2>/dev/null | tail -n +15 | xargs -r rm -f; done
echo "Backup written to $DIR ($STAMP)"
