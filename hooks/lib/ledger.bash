#!/usr/bin/env bash

if [ -n "${MST_LEDGER_BASH_SOURCED:-}" ]; then
  return 0
fi
MST_LEDGER_BASH_SOURCED=1

_mst_ledger_project_root() {
  local git_top candidate parent
  if [ -n "${PROJECT_ROOT:-}" ]; then
    printf '%s\n' "$PROJECT_ROOT"
    return 0
  fi
  git_top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  if [ -f "${git_top}/.git" ]; then
    candidate="$git_top"
    while [ -n "$candidate" ] && [ "$candidate" != "/" ]; do
      if [ -d "${candidate}/.gran-maestro" ] && [ -e "${candidate}/.git" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      parent="$(dirname "$candidate")"
      [ "$parent" = "$candidate" ] && break
      candidate="$parent"
    done
  fi
  printf '%s\n' "$git_top"
}

_mst_ledger_digest() {
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 | awk '{print substr($NF, 1, 12)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print substr($1, 1, 12)}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print substr($1, 1, 12)}'
  else
    python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:12])'
  fi
}

_mst_ledger_source() {
  case "${0:-}" in
    "${HOME:-}"/.claude/plugins/cache/*|*/.claude/plugins/cache/*) printf 'plugin_manifest\n' ;;
    "") printf 'unknown\n' ;;
    *) printf 'settings_local\n' ;;
  esac
}

_mst_ledger_json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

_mst_ledger_session_id() {
  local payload="${1:-}" session_id
  if [ -n "${CLAUDE_SESSION_ID:-}" ]; then
    printf '%s\n' "$CLAUDE_SESSION_ID"
    return 0
  fi
  if [[ "$payload" =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    printf 'pid-%s\n' "$$"
  fi
}

_mst_ledger_append() {
  local hook_event="$1" phase="$2" exit_code="${3:-}" root ledger_dir ledger lock payload digest row acquired i ts session_id source exit_json
  root="$(_mst_ledger_project_root)"
  ledger_dir="${root}/.gran-maestro"
  ledger="${ledger_dir}/hooks-ledger.ndjson"
  lock="${ledger}.lock"
  payload="${MST_LEDGER_STDIN_RAW-${STDIN_RAW-}}"
  if [ -n "${MST_LEDGER_PAYLOAD_DIGEST:-}" ]; then
    digest="$MST_LEDGER_PAYLOAD_DIGEST"
  else
    digest="$(printf '%s' "$payload" | _mst_ledger_digest)"
    MST_LEDGER_PAYLOAD_DIGEST="$digest"
  fi
  session_id="${MST_LEDGER_SESSION_ID:-$(_mst_ledger_session_id "$payload")}"
  MST_LEDGER_SESSION_ID="$session_id"
  source="${MST_LEDGER_INVOCATION_SOURCE:-$(_mst_ledger_source)}"
  MST_LEDGER_INVOCATION_SOURCE="$source"
  ts="$(date -u '+%Y-%m-%dT%H:%M:%S.000Z' 2>/dev/null || date -u '+%FT%TZ')"
  case "$exit_code" in
    ''|*[!0-9]*) exit_json=null ;;
    *) exit_json="$exit_code" ;;
  esac
  row="$(printf '{"ts":"%s","hook_event":"%s","phase":"%s","exit_code":%s,"payload_digest":"%s","session_id":"%s","invocation_source":"%s","pid":%s}' \
    "$(_mst_ledger_json_escape "$ts")" \
    "$(_mst_ledger_json_escape "$hook_event")" \
    "$(_mst_ledger_json_escape "$phase")" \
    "$exit_json" \
    "$(_mst_ledger_json_escape "$digest")" \
    "$(_mst_ledger_json_escape "$session_id")" \
    "$(_mst_ledger_json_escape "$source")" \
    "$$")"
  mkdir -p "$ledger_dir" || return 0
  acquired=0
  for i in 1 2 3 4 5; do
    if mkdir "$lock" 2>/dev/null; then
      acquired=1
      break
    fi
    sleep 0.02 2>/dev/null || true
  done
  [ "$acquired" = "1" ] || return 0
  printf '%s\n' "$row" >> "$ledger" 2>/dev/null || true
  rmdir "$lock" 2>/dev/null || true
}

emit_ledger_start() {
  ( set +e; _mst_ledger_append "$1" "start" "" >/dev/null 2>&1 ) || true
}

emit_ledger_complete() {
  ( set +e; _mst_ledger_append "$1" "complete" "${2:-}" >/dev/null 2>&1 ) || true
}
