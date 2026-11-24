#!/usr/bin/env bash
# Nightly PostgreSQL backup for the shared server (plan task B1). Keeps the last 7 days.
#
#   platform/server/backup.sh                         # writes /srv/backups/kg-<UTC time>.dump
#   15 3 * * * /srv/kg/repo/platform/server/backup.sh >> /srv/backups/backup.log 2>&1      # crontab -e, as kg
#
# A dump in PostgreSQL's custom format (pg_dump -Fc); restore with pg_restore. Neo4j is not backed up: it is derived
# from files in the repository and the K1 release (D-06), and the loaders rebuild it.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
OUT="${OUT:-/srv/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"

stamp="$(date -u +%Y%m%dT%H%MZ)"
file="$OUT/kg-$stamp.dump"
docker compose -f "$REPO/platform/docker-compose.yml" exec -T postgres pg_dump -U kg -d kg -Fc > "$file.part"
mv "$file.part" "$file"
find "$OUT" -maxdepth 1 -name 'kg-*.dump' -mtime +"$((KEEP_DAYS - 1))" -delete
echo "$(date -u +%FT%TZ) backup $file ($(du -h "$file" | cut -f1)); kept: $(find "$OUT" -maxdepth 1 -name 'kg-*.dump' | wc -l | tr -d ' ')"
