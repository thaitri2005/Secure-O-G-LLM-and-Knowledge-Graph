#!/bin/sh
# Nightly backup of PostgreSQL, the one store that holds what cannot be rebuilt: the question log and its feedback
# (backend design §1). Neo4j, the vectors and the chunks are rebuilt from a K1 release by platform/run_release.py.
#
#   sh deploy/backup.sh [folder]          # default folder /srv/kg/backups; keeps the last 7 days
#
# Cron line (crontab -e as the user who runs docker), every night at 02:30 server time:
#   30 2 * * * cd /srv/kg/app && sh deploy/backup.sh /srv/kg/backups >> /srv/kg/backups/backup.log 2>&1
#
# Restore one dump into the running database (it replaces what is there):
#   docker compose -f platform/docker-compose.yml exec -T postgres pg_restore -U kg -d kg --clean --if-exists < <dump>
set -eu

FOLDER="${1:-/srv/kg/backups}"
KEEP_DAYS=7
HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="$HERE/../platform/docker-compose.yml"

mkdir -p "$FOLDER"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$FOLDER/kg-$STAMP.dump"

# Inside the container pg_dump reaches the database over its local socket, so no password is passed around.
# The custom format is compressed and lets pg_restore pick single tables.
docker compose -f "$COMPOSE" exec -T postgres pg_dump -U kg -d kg --format=custom > "$OUT.partial"
mv "$OUT.partial" "$OUT"
echo "$(date -u +%FT%TZ) wrote $OUT ($(wc -c < "$OUT") bytes)"

# Dumps older than KEEP_DAYS days go; a failed night above stops the script before anything is deleted.
find "$FOLDER" -maxdepth 1 -name 'kg-*.dump' -mtime +"$((KEEP_DAYS - 1))" -print -delete
