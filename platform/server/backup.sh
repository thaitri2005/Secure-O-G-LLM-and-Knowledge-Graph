#!/usr/bin/env bash
# Nightly PostgreSQL backup for the shared server (plan task B1). Keeps the last 7 days.
#
#   platform/server/backup.sh                         # writes /srv/backups/kg-<UTC time>.dump
#   15 3 * * * /srv/kg/repo/platform/server/backup.sh >> /srv/backups/backup.log 2>&1      # crontab -e, as kg
#
# The dump holds the question log: the questions people typed and how they marked the answers. Nothing else in the
# system is irreplaceable, so a copy must leave the server. Set BACKUP_REMOTE to an rsync target and every run
# copies the folder there:
#
#   BACKUP_REMOTE=backup@other-host:kg-backups/        # over SSH, with a key the kg user holds
#
# Check a backup now and then by restoring it: platform/server/restore_check.sh
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
if [ -n "${BACKUP_REMOTE:-}" ]; then
  # The folder as source, so that dumps pruned here are pruned there too; only the dumps are touched.
  rsync -a --delete --include='kg-*.dump' --exclude='*' "$OUT"/ "$BACKUP_REMOTE" && remote="copied to $BACKUP_REMOTE" || remote="COPY TO $BACKUP_REMOTE FAILED"
else
  remote="NOT copied off the server (set BACKUP_REMOTE)"
fi
echo "$(date -u +%FT%TZ) backup $file ($(du -h "$file" | cut -f1)); kept: $(find "$OUT" -maxdepth 1 -name 'kg-*.dump' | wc -l | tr -d ' '); $remote"
