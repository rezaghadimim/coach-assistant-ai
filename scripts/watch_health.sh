#!/usr/bin/env bash
# Watch the running API and notify FAST when anything degrades.
#
#   ./scripts/watch_health.sh                 # poll every 15s, desktop + terminal alerts
#   INTERVAL=5 ./scripts/watch_health.sh      # faster polling
#   HEALTH_URL=http://myhost:8000/health ./scripts/watch_health.sh
#
# Alerts on:
#   - /health returning status != "ok" (each issue listed)
#   - the API being unreachable at all
#   - any NEW line appended to the error log (LOG_ERROR_FILE / logs/errors.log)
#
# Notifications: macOS desktop notification (osascript) + red terminal line + bell.
# Only alerts on STATE CHANGES, so a broken layer produces one alert, not spam.
# Recovery back to "ok" is announced too.
set -u

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
INTERVAL="${INTERVAL:-15}"
ERROR_LOG="${ERROR_LOG:-logs/errors.log}"

RED=$'\033[1;31m'; GREEN=$'\033[1;32m'; RESET=$'\033[0m'
last_state=""
last_size=0
[ -f "$ERROR_LOG" ] && last_size=$(wc -c < "$ERROR_LOG")

notify() { # $1=title $2=message
    printf '%s[%s] %s: %s%s\a\n' "$RED" "$(date '+%H:%M:%S')" "$1" "$2" "$RESET"
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"${2//\"/}\" with title \"Coach Assistant: $1\"" 2>/dev/null
    fi
}

recovered() {
    printf '%s[%s] RECOVERED: %s%s\n' "$GREEN" "$(date '+%H:%M:%S')" "$1" "$RESET"
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"$1\" with title \"Coach Assistant: recovered\"" 2>/dev/null
    fi
}

echo "watching $HEALTH_URL every ${INTERVAL}s (error log: $ERROR_LOG) — Ctrl-C to stop"

while true; do
    body=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)
    if [ -z "$body" ]; then
        state="down"
        [ "$last_state" != "down" ] && notify "API DOWN" "no response from $HEALTH_URL"
    else
        state=$(printf '%s' "$body" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("down"); raise SystemExit
status = d.get("status", "degraded")
issues = d.get("issues") or []
print(status + ("|" + "; ".join(issues) if issues else ""))')
        status="${state%%|*}"
        issues="${state#*|}"
        if [ "$status" != "ok" ] && [ "$state" != "$last_state" ]; then
            notify "DEGRADED" "${issues:-$status}"
        fi
    fi
    if [ "${state%%|*}" = "ok" ] && [ -n "$last_state" ] && [ "${last_state%%|*}" != "ok" ]; then
        recovered "all layers healthy again"
    fi
    last_state="$state"

    # New ERROR-level log lines → immediate alert with the first new line.
    if [ -f "$ERROR_LOG" ]; then
        size=$(wc -c < "$ERROR_LOG")
        if [ "$size" -gt "$last_size" ]; then
            new_line=$(tail -c +"$((last_size + 1))" "$ERROR_LOG" | head -1)
            notify "ERROR LOGGED" "${new_line:0:160}"
        fi
        last_size=$size
    fi

    sleep "$INTERVAL"
done
