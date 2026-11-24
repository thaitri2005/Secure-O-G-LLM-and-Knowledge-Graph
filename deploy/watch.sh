#!/usr/bin/env bash
# Tells the team when the application stops answering, and when it is back (specification §11.4).
# Run it from cron on a machine that is NOT the server, so a server that is down is noticed too:
#
#   */5 * * * * SMOKE_PASSWORD='<the shared password>' ALERT_WEBHOOK='<webhook address>' \
#       /path/to/repo/deploy/watch.sh https://kg.example.org >> $HOME/kg-watch.log 2>&1
#
# It runs the quick smoke test (gate, frontend, health, ready): no question is asked and nothing is logged.
# A message is sent only when the state changes, so a long outage is one message, not one every five minutes.
# ALERT_WEBHOOK is an incoming-webhook address of the group chat (Slack, Discord, Mattermost, Google Chat: each takes
# a JSON body with "text", Discord "content"). Without it the script only writes its log.
set -uo pipefail

URL="${1:?usage: watch.sh <address of the application> [user]}"
USER_NAME="${2:-team}"
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${WATCH_STATE:-${TMPDIR:-/tmp}/kg-watch-$(printf '%s' "$URL" | tr -c 'A-Za-z0-9' '_').state}"

output="$(python3 "$HERE/smoke_test.py" --url "$URL" --user "$USER_NAME" --quick 2>&1)"
[ $? -eq 0 ] && now="up" || now="down"
before="$(cat "$STATE" 2>/dev/null || echo up)"
echo "$(date -u +%FT%TZ) $URL $now"
[ "$now" = "down" ] && echo "$output"

sent=0
if [ "$now" != "$before" ] && [ -n "${ALERT_WEBHOOK:-}" ]; then
  if [ "$now" = "down" ]; then
    message="Drilling reports application is DOWN at $URL: $(printf '%s' "$output" | grep -E '^(FAIL|WARN)' | head -3 | tr '\n' ' ')"
  else
    message="Drilling reports application is back up at $URL."
  fi
  # Discord wants "content", Slack, Mattermost and Google Chat want "text"; a browser-like agent, since some refuse
  # the default one. If the message cannot be sent the state is not saved, so the next run tries again.
  python3 - "$ALERT_WEBHOOK" "$message" <<'PY' || sent=1
import json, sys, urllib.request
field = "content" if "discord" in sys.argv[1] else "text"
body = json.dumps({field: sys.argv[2]}).encode()
request = urllib.request.Request(sys.argv[1], body, {"Content-Type": "application/json", "User-Agent": "kg-watch/1.0"})
try:
    urllib.request.urlopen(request, timeout=15)
except Exception as error:
    print(f"could not send the alert: {error}")
    sys.exit(1)
PY
fi
[ "$sent" -eq 0 ] && echo "$now" > "$STATE"
[ "$now" = "up" ]
