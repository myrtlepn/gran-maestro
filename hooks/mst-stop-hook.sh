#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MST_TMP="${PROJECT_ROOT}/.gran-maestro/tmp"
STATE_FILE="${MST_TMP}/mst-state-${PPID}.json"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"
mkdir -p "$MST_TMP"

STDIN_RAW="$(cat || true)"


debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
}

HOOK_INFO="$(printf '%s' "$STDIN_RAW" | python3 -c 'import json, sys
raw = sys.stdin.read() or ""
stop_active = "unknown"
last_msg = ""

try:
    payload = json.loads(raw)
except Exception:
    payload = {}

if isinstance(payload, dict):
    value = payload.get("stop_hook_active")
    if value is True:
        stop_active = "true"
    elif value is False:
        stop_active = "false"

    candidates = [
        payload.get("last_assistant_message"),
        payload.get("assistant_message"),
        payload.get("message"),
        payload.get("reason"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            last_msg = candidate.strip()
            break

print(f"{stop_active}\t{last_msg}")
' 2>/dev/null || printf 'unknown\t\n')"

STOP_HOOK_ACTIVE="$(printf '%s' "$HOOK_INFO" | cut -f1)"
LAST_ASSISTANT_MESSAGE="$(printf '%s' "$HOOK_INFO" | cut -f2-)"

if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  debug_log "allow" "reason=stop_hook_active_true"
  exit 0
fi

contains_allow_pattern() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- 'AskUserQuestion|"tool_name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|workflow complete|final answer delivered|user requested stop'
}

if contains_allow_pattern "$LAST_ASSISTANT_MESSAGE" || contains_allow_pattern "$STDIN_RAW"; then
  debug_log "allow" "reason=explicit_allow_pattern"
  exit 0
fi

STATE_INFO="$(python3 - "$STATE_FILE" <<'PY'
import json
import os
import sys

path = sys.argv[1]
if not os.path.isfile(path):
    print("missing\tfalse\t\t\t0\t\t\tfalse\t")
    raise SystemExit(0)

try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    print("invalid\tfalse\t\t\t0\t\t\tfalse\t")
    raise SystemExit(0)

if not isinstance(payload, dict):
    print("invalid\tfalse\t\t\t0\t\t\tfalse\t")
    raise SystemExit(0)

workflow_active = bool(payload.get("workflow_active"))
current_skill = payload.get("current_skill") if isinstance(payload.get("current_skill"), str) else ""
active_req = payload.get("active_req") if isinstance(payload.get("active_req"), str) else ""
updated_at = payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else ""

iteration = payload.get("iteration")
if not isinstance(iteration, int):
    iteration = 0

next_skill = ""
next_source = ""
next_auto = False
source_skill = ""

next_action = payload.get("next_action")
if isinstance(next_action, dict):
    skill_candidates = [
        next_action.get("expected_skill"),
        next_action.get("skill"),
    ]
    source_candidates = [
        next_action.get("source_id"),
        next_action.get("source"),
    ]

    for candidate in skill_candidates:
        if isinstance(candidate, str) and candidate.strip():
            next_skill = candidate.strip()
            break

    for candidate in source_candidates:
        if isinstance(candidate, str) and candidate.strip():
            next_source = candidate.strip()
            break

    source_skill_value = next_action.get("source_skill")
    if isinstance(source_skill_value, str) and source_skill_value.strip():
        source_skill = source_skill_value.strip()

    auto_candidates = [next_action.get("auto_mode"), next_action.get("auto")]
    for candidate in auto_candidates:
        if candidate is True:
            next_auto = True
            break

print(
    "valid\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
        "true" if workflow_active else "false",
        current_skill,
        active_req,
        iteration,
        next_skill,
        next_source,
        "true" if next_auto else "false",
        source_skill,
        updated_at,
    )
)
PY
)"

STATE_STATUS="$(printf '%s' "$STATE_INFO" | cut -f1)"
WORKFLOW_ACTIVE="$(printf '%s' "$STATE_INFO" | cut -f2)"
CURRENT_SKILL="$(printf '%s' "$STATE_INFO" | cut -f3)"
ACTIVE_REQ="$(printf '%s' "$STATE_INFO" | cut -f4)"
ITERATION="$(printf '%s' "$STATE_INFO" | cut -f5)"
NEXT_SKILL="$(printf '%s' "$STATE_INFO" | cut -f6)"
NEXT_SOURCE="$(printf '%s' "$STATE_INFO" | cut -f7)"
NEXT_AUTO="$(printf '%s' "$STATE_INFO" | cut -f8)"
SOURCE_SKILL="$(printf '%s' "$STATE_INFO" | cut -f9)"
UPDATED_AT="$(printf '%s' "$STATE_INFO" | cut -f10-)"

if [ "$WORKFLOW_ACTIVE" != "true" ]; then
  debug_log "allow" "reason=workflow_inactive state_status=$STATE_STATUS"
  exit 0
fi

REASON="MST workflow is still active. Restore context and continue without stopping."
if [ -n "$CURRENT_SKILL" ]; then
  REASON="$REASON Current skill: $CURRENT_SKILL."
fi
if [ -n "$ACTIVE_REQ" ]; then
  REASON="$REASON Active request: $ACTIVE_REQ."
fi
if [ "$ITERATION" != "0" ]; then
  REASON="$REASON Iteration: $ITERATION."
fi
if [ -n "$UPDATED_AT" ]; then
  REASON="$REASON Last update: $UPDATED_AT."
fi
if [ "$NEXT_AUTO" = "true" ] && [ -n "$NEXT_SKILL" ]; then
  REASON="$REASON Next action: call Skill(\"$NEXT_SKILL\")"
  if [ -n "$NEXT_SOURCE" ]; then
    REASON="$REASON from $NEXT_SOURCE"
  fi
  if [ -n "$SOURCE_SKILL" ]; then
    REASON="$REASON (source_skill=$SOURCE_SKILL)"
  fi
  REASON="$REASON immediately."
elif [ -n "$NEXT_SKILL" ]; then
  REASON="$REASON Suggested next skill: $NEXT_SKILL."
fi
REASON="$REASON Do not stop; emit the next tool call now."

python3 - "$REASON" <<'PY'
import json
import sys

reason = sys.argv[1]
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PY

debug_log "block" "reason=workflow_active current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO"
exit 0
