#!/usr/bin/env bash

if [ -n "${MST_LOGGING_BASH_SOURCED:-}" ]; then
  return 0
fi
MST_LOGGING_BASH_SOURCED=1

debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
}

sanitize_log_value() {
  local value="${1:-}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  value="${value//$'\t'/ }"
  printf '%s' "$value"
}

warn_helper_failed() {
  local helper="$1"
  local status="${2:-1}"
  local detail="${3:-}"
  local prefix="${MST_HOOK_LOG_PREFIX:-mst-hook}"

  helper="$(sanitize_log_value "$helper")"
  status="$(sanitize_log_value "$status")"
  detail="$(sanitize_log_value "$detail")"
  if [ -n "$detail" ]; then
    printf '[%s] helper_failed helper=%s exit=%s %s\n' "$prefix" "$helper" "$status" "$detail" >&2
  else
    printf '[%s] helper_failed helper=%s exit=%s\n' "$prefix" "$helper" "$status" >&2
  fi
}

log_boundary_event() {
  local event_type="${1:-event}"
  local task_id="${2:-unknown}"
  local result="${3:-unknown}"
  local message="${4:-}"
  local ts log_dir

  event_type="${event_type//$'\n'/ }"
  task_id="${task_id//$'\n'/ }"
  result="${result//$'\n'/ }"
  message="${message//$'\n'/ }"
  event_type="${event_type//$'\r'/ }"
  task_id="${task_id//$'\r'/ }"
  result="${result//$'\r'/ }"
  message="${message//$'\r'/ }"

  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +%FT%TZ)"
  log_dir="$(dirname "$BOUNDARY_LOG_FILE")"
  mkdir -p "$log_dir" 2>/dev/null || return 0
  printf '%s | %s | %s | %s | %s | %s\n' \
    "$ts" "$HOOK_NAME" "$event_type" "$task_id" "$result" "$message" \
    >> "$BOUNDARY_LOG_FILE" 2>/dev/null || true
}
