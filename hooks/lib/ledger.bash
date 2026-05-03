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

_mst_ledger_path_safe_id() {
  local value="${1:-}"
  case "$value" in
    ''|*/*|*'..'*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
  printf '%s\n' "$value"
}

_mst_ledger_json_string_field() {
  local key="$1" payload="${2:-}"
  if [[ "$payload" =~ \"$key\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
}

_mst_ledger_mst_session_id() {
  local payload="${1:-}" candidate
  candidate="${MST_SESSION_ID:-}"
  if [ -z "$candidate" ]; then
    candidate="$(_mst_ledger_json_string_field "mst_session_id" "$payload")"
  fi
  _mst_ledger_path_safe_id "$candidate" 2>/dev/null || true
}

_mst_ledger_claude_session_id() {
  local payload="${1:-}" candidate
  candidate="${CLAUDE_SESSION_ID:-}"
  if [ -z "$candidate" ]; then
    candidate="$(_mst_ledger_json_string_field "session_id" "$payload")"
  fi
  printf '%s\n' "$candidate"
}

_mst_ledger_append() {
  local hook_event="$1" phase="$2" exit_code="${3:-}" root ledger_dir ledger lock payload digest row acquired i ts mst_session_id claude_session_id source exit_json
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
  mst_session_id="${MST_LEDGER_MST_SESSION_ID:-$(_mst_ledger_mst_session_id "$payload")}"
  MST_LEDGER_MST_SESSION_ID="$mst_session_id"
  claude_session_id="${MST_LEDGER_CLAUDE_SESSION_ID:-$(_mst_ledger_claude_session_id "$payload")}"
  MST_LEDGER_CLAUDE_SESSION_ID="$claude_session_id"
  source="${MST_LEDGER_INVOCATION_SOURCE:-$(_mst_ledger_source)}"
  MST_LEDGER_INVOCATION_SOURCE="$source"
  ts="$(date -u '+%Y-%m-%dT%H:%M:%S.000Z' 2>/dev/null || date -u '+%FT%TZ')"
  case "$exit_code" in
    ''|*[!0-9]*) exit_json=null ;;
    *) exit_json="$exit_code" ;;
  esac
  row="$(printf '{"ts":"%s","hook_event":"%s","phase":"%s","exit_code":%s,"payload_digest":"%s","mst_session_id":"%s","claude_session_id":"%s","invocation_source":"%s","pid":%s}' \
    "$(_mst_ledger_json_escape "$ts")" \
    "$(_mst_ledger_json_escape "$hook_event")" \
    "$(_mst_ledger_json_escape "$phase")" \
    "$exit_json" \
    "$(_mst_ledger_json_escape "$digest")" \
    "$(_mst_ledger_json_escape "$mst_session_id")" \
    "$(_mst_ledger_json_escape "$claude_session_id")" \
    "$(_mst_ledger_json_escape "$source")" \
    "$$")"
  mkdir -p "$ledger_dir" 2>/dev/null || return 0
  acquired=0
  for i in 1 2 3 4 5; do
    if mkdir "$lock" 2>/dev/null; then
      acquired=1
      break
    fi
    sleep 0.02 2>/dev/null || true
  done
  if [ "$acquired" = "1" ]; then
    printf '%s\n' "$row" >> "$ledger" 2>/dev/null || true
    rmdir "$lock" 2>/dev/null || true
    return 0
  fi
  local overflow summary
  overflow="${ledger%.ndjson}.overflow.ndjson"
  summary="$(printf '%s' "$row" | head -c 100)"
  printf '[mst-ledger] lock contention skipped: %s, see %s\n' "$summary" "$overflow" >&2
  printf '%s\n' "$row" >> "$overflow" 2>/dev/null || true
  return 0
}

emit_ledger_start() {
  # stdout is suppressed (no row leakage to caller stdout) but stderr is
  # preserved so the AD-005 lock-contention warning reaches the user.
  ( set +e; _mst_ledger_append "$1" "start" "" >/dev/null ) || true
}

emit_ledger_complete() {
  ( set +e; _mst_ledger_append "$1" "complete" "${2:-}" >/dev/null ) || true
}
