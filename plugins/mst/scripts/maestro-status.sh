#!/bin/bash
# maestro-status.sh — Query Gran Maestro mode status from the shell.
# Usage: maestro-status.sh [--json | -q | --field <name>]
# Exit codes: 0 = active, 1 = inactive or not found.

MODE_FILE=""
DIR="${MAESTRO_PROJECT_DIR:-$(pwd)}"
while [ "$DIR" != "/" ] && [ -n "$DIR" ]; do
  if [ -f "$DIR/.gran-maestro/mode.json" ]; then
    MODE_FILE="$DIR/.gran-maestro/mode.json"
    break
  fi
  DIR=$(dirname "$DIR")
done

if [ -z "$MODE_FILE" ]; then
  case "${1:-}" in
    --json) echo '{"active":false,"error":"mode.json not found"}' ;;
    -q|--quiet) ;;
    --field) echo "null" ;;
    *) echo "off" ;;
  esac
  exit 1
fi

ACTIVE=$(jq -r '.active // false' "$MODE_FILE" 2>/dev/null)
BASE_DIR=$(dirname "$MODE_FILE")

# Count active (non-terminal) requests by scanning request directories
count_active_requests() {
  local count=0
  if [ -d "$BASE_DIR/requests" ]; then
    for req in "$BASE_DIR"/requests/*/request.json; do
      [ -f "$req" ] || continue
      s=$(jq -r '.status // ""' "$req" 2>/dev/null)
      case "$s" in done|completed|cancelled|failed) ;; *) count=$((count+1)) ;; esac
    done
  fi
  echo "$count"
}

case "${1:-}" in
  --json)
    jq '.' "$MODE_FILE" 2>/dev/null
    ;;
  -q|--quiet)
    ;;
  --field)
    FIELD="${2:-active}"
    if [ "$FIELD" = "active_requests" ]; then
      count_active_requests
    else
      jq -r ".$FIELD // empty" "$MODE_FILE" 2>/dev/null
    fi
    ;;
  *)
    if [ "$ACTIVE" = "true" ]; then
      REQS=$(count_active_requests)
      echo "on (requests: ${REQS:-0})"
    else
      echo "off"
    fi
    ;;
esac

[ "$ACTIVE" = "true" ] && exit 0 || exit 1
