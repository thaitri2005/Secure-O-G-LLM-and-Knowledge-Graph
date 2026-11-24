#!/usr/bin/env bash
# Proves a backup can be restored: loads a dump into a throwaway PostgreSQL container and counts what came back.
# The running stores are not touched.
#
#   platform/server/restore_check.sh                       # the newest dump in /srv/backups
#   platform/server/restore_check.sh /path/to/kg-<time>.dump
#
# Prints the number of questions, marks, releases and chunks in the dump. Exit code 1 when the restore fails.
set -euo pipefail

OUT="${OUT:-/srv/backups}"
dump="${1:-$(ls -1t "$OUT"/kg-*.dump 2>/dev/null | head -1)}"
[ -n "$dump" ] && [ -f "$dump" ] || { echo "no dump found (looked in $OUT)" >&2; exit 1; }
IMAGE="pgvector/pgvector:pg16"
name="kg-restore-check-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$name" -e POSTGRES_USER=kg -e POSTGRES_PASSWORD=check -e POSTGRES_DB=kg "$IMAGE" >/dev/null
for _ in $(seq 30); do docker exec "$name" pg_isready -U kg -d kg >/dev/null 2>&1 && break; sleep 1; done
sleep 1
docker exec -i "$name" pg_restore -U kg -d kg --no-owner < "$dump"
echo "restored $dump"
docker exec "$name" psql -U kg -d kg -At -c "
  SELECT 'questions: ' || count(*) FROM questions
  UNION ALL SELECT 'marks: ' || count(*) FROM question_feedback
  UNION ALL SELECT 'releases: ' || count(*) FROM k1_releases
  UNION ALL SELECT 'chunks: ' || count(*) FROM chunks"
