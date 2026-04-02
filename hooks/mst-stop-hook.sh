#!/usr/bin/env bash
set -euo pipefail

resolve_project_root() {
  local git_top candidate parent
  git_top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

  if [ -f "${git_top}/.git" ]; then
    candidate="$git_top"
    while [ -n "$candidate" ] && [ "$candidate" != "/" ]; do
      if [ -d "${candidate}/.gran-maestro" ] && [ -e "${candidate}/.git" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      parent="$(dirname "$candidate")"
      if [ "$parent" = "$candidate" ]; then
        break
      fi
      candidate="$parent"
    done
  fi

  printf '%s\n' "$git_top"
}

PROJECT_ROOT="$(resolve_project_root)"
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
agile_auto_mode = "unknown"
last_msg = ""

def parse_bool(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "y", "on"):
            return "true"
        if text in ("0", "false", "no", "n", "off"):
            return "false"
    return "unknown"

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

    for key in ("agile_auto_mode", "agileAutoMode", "AUTO_MODE", "auto_mode"):
        parsed = parse_bool(payload.get(key))
        if parsed != "unknown":
            agile_auto_mode = parsed
            break

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

print(f"{stop_active}\t{agile_auto_mode}\t{last_msg}")
' 2>/dev/null || printf 'unknown\tunknown\t\n')"

STOP_HOOK_ACTIVE="$(printf '%s' "$HOOK_INFO" | cut -f1)"
AGILE_AUTO_MODE_HINT="$(printf '%s' "$HOOK_INFO" | cut -f2)"
LAST_ASSISTANT_MESSAGE="$(printf '%s' "$HOOK_INFO" | cut -f3-)"

if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  debug_log "allow" "reason=stop_hook_active_true"
  exit 0
fi

contains_allow_pattern() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- '"tool_name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|"name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|workflow complete|final answer delivered|user requested stop'
}

contains_agile_allow_marker() {
  local text="$1"
  printf '%s' "$text" | grep -Fq "[스티어링 체크포인트]" \
    || printf '%s' "$text" | grep -Fq "[비상 스티어링]" \
    || printf '%s' "$text" | grep -Fq "[Sprint 0]" \
    || printf '%s' "$text" | grep -Fq "[자동 중단]"
}

contains_agile_text_question() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- '계속할까요|진행할까요|계속[[:space:]]*진행하시겠습니까|멈추고|중단할까요'
}

emit_block_json() {
  local reason="$1"
  python3 - "$reason" <<'PY'
import json
import sys

reason = sys.argv[1]
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PY
}

persist_block_state() {
  local reason="$1"
  python3 - "$STATE_FILE" "$reason" <<'PY'
import json
import os
import sys

path = sys.argv[1]
reason = sys.argv[2]

payload = {}
if os.path.isfile(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        payload = {}

if not isinstance(payload, dict):
    payload = {}

block_count = payload.get("block_count")
if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
    block_count = 0

block_count += 1
payload["block_count"] = block_count
payload["last_block_reason"] = reason if isinstance(reason, str) else ""

tmp_path = f"{path}.tmp"
try:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
except Exception:
    pass

print(block_count)
PY
}

STATE_INFO="$(python3 - "$STATE_FILE" <<'PY'
import json
import os
import sys

def emit(
    status,
    workflow_active=False,
    current_skill="",
    active_req="",
    iteration=0,
    next_skill="",
    next_source="",
    next_auto=False,
    source_skill="",
    has_next_action=False,
    updated_at="",
    agile_loop_active=False,
    block_count=0,
    last_block_reason="",
):
    if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
        block_count = 0
    if not isinstance(last_block_reason, str):
        last_block_reason = ""
    last_block_reason = last_block_reason.replace("\t", " ").replace("\n", " ").strip()
    print(
        "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
            status,
            "true" if workflow_active else "false",
            current_skill,
            active_req,
            iteration,
            next_skill,
            next_source,
            "true" if next_auto else "false",
            source_skill,
            "true" if has_next_action else "false",
            updated_at,
            "true" if agile_loop_active else "false",
            block_count,
            last_block_reason,
        )
    )

path = sys.argv[1]
if not os.path.isfile(path):
    emit("missing")
    raise SystemExit(0)

try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    emit("invalid")
    raise SystemExit(0)

if not isinstance(payload, dict):
    emit("invalid")
    raise SystemExit(0)

workflow_active = bool(payload.get("workflow_active"))
current_skill = payload.get("current_skill") if isinstance(payload.get("current_skill"), str) else ""
active_req = payload.get("active_req") if isinstance(payload.get("active_req"), str) else ""
updated_at = payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else ""
agile_loop_active = payload.get("agile_loop_active")
if not isinstance(agile_loop_active, bool):
    agile_loop_active = False

block_count = payload.get("block_count")
if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
    block_count = 0

last_block_reason = payload.get("last_block_reason")
if not isinstance(last_block_reason, str):
    last_block_reason = ""

iteration = payload.get("iteration")
if not isinstance(iteration, int):
    iteration = 0

next_skill = ""
next_source = ""
next_auto = False
source_skill = ""
has_next_action = False

next_action = payload.get("next_action")
if isinstance(next_action, dict):
    has_next_action = True
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

emit(
    "valid",
    workflow_active=workflow_active,
    current_skill=current_skill,
    active_req=active_req,
    iteration=iteration,
    next_skill=next_skill,
    next_source=next_source,
    next_auto=next_auto,
    source_skill=source_skill,
    has_next_action=has_next_action,
    updated_at=updated_at,
    agile_loop_active=agile_loop_active,
    block_count=block_count,
    last_block_reason=last_block_reason,
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
HAS_NEXT_ACTION="$(printf '%s' "$STATE_INFO" | cut -f10)"
UPDATED_AT="$(printf '%s' "$STATE_INFO" | cut -f11)"
AGILE_LOOP_ACTIVE="$(printf '%s' "$STATE_INFO" | cut -f12)"
BLOCK_COUNT="$(printf '%s' "$STATE_INFO" | cut -f13)"
LAST_BLOCK_REASON="$(printf '%s' "$STATE_INFO" | cut -f14-)"

if [ "$WORKFLOW_ACTIVE" != "true" ]; then
  debug_log "allow" "reason=workflow_inactive state_status=$STATE_STATUS"
  exit 0
fi

if ! printf '%s' "$BLOCK_COUNT" | grep -Eq '^[0-9]+$'; then
  BLOCK_COUNT="0"
fi

AGILE_GUARD_ACTIVE="false"
if [ "$AGILE_LOOP_ACTIVE" = "true" ] || [ "$CURRENT_SKILL" = "mst:agile" ]; then
  AGILE_GUARD_ACTIVE="true"
fi

AGILE_AUTO_MODE_ACTIVE="false"
if [ "$AGILE_AUTO_MODE_HINT" = "true" ]; then
  AGILE_AUTO_MODE_ACTIVE="true"
elif [ "$AGILE_AUTO_MODE_HINT" = "false" ]; then
  AGILE_AUTO_MODE_ACTIVE="false"
elif [ "$NEXT_AUTO" = "true" ]; then
  AGILE_AUTO_MODE_ACTIVE="true"
fi

ALLOW_PATTERN_FOUND="false"
if contains_allow_pattern "$LAST_ASSISTANT_MESSAGE" || contains_allow_pattern "$STDIN_RAW"; then
  ALLOW_PATTERN_FOUND="true"
fi

AGILE_ALLOW_CONTEXT="${LAST_ASSISTANT_MESSAGE}
${STDIN_RAW}"

if [ "$AGILE_LOOP_ACTIVE" = "true" ] && [ "$AGILE_AUTO_MODE_ACTIVE" = "true" ] && contains_agile_text_question "$AGILE_ALLOW_CONTEXT"; then
  NEXT_BLOCK_COUNT=$((BLOCK_COUNT + 1))
  REASON="Sprint loop active in AUTO_MODE=true; text-based question patterns are blocked."
  REASON="$REASON Remove phrases like '계속할까요?', '진행할까요?', '멈추고' and continue autonomously."
  REASON="$REASON Consecutive block count: $NEXT_BLOCK_COUNT."
  if [ "$NEXT_BLOCK_COUNT" -ge 3 ]; then
    REASON="[자동 중단] $REASON Escalate to user for steering."
  fi
  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$NEXT_BLOCK_COUNT")"
  emit_block_json "$REASON"
  debug_log "block" "reason=agile_text_question_in_auto_mode agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE current_skill=$CURRENT_SKILL block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

if [ "$ALLOW_PATTERN_FOUND" = "true" ] && [ "$AGILE_GUARD_ACTIVE" = "true" ] && contains_agile_allow_marker "$AGILE_ALLOW_CONTEXT"; then
  debug_log "allow" "reason=agile_allow_pattern_whitelisted workflow_active=$WORKFLOW_ACTIVE current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE"
  exit 0
fi

if [ "$ALLOW_PATTERN_FOUND" = "true" ] && [ "$AGILE_GUARD_ACTIVE" = "true" ]; then
  NEXT_BLOCK_COUNT=$((BLOCK_COUNT + 1))
  REMAINING_DODS="continue current sprint backlog"
  if [ -n "$NEXT_SOURCE" ]; then
    REMAINING_DODS="$NEXT_SOURCE"
  elif [ -n "$ACTIVE_REQ" ]; then
    REMAINING_DODS="$ACTIVE_REQ"
  fi

  REASON="Sprint loop active; remaining DoDs: $REMAINING_DODS."
  REASON="$REASON AskUserQuestion is allowed only with agile whitelist markers."
  if [ -n "$CURRENT_SKILL" ]; then
    REASON="$REASON Current skill: $CURRENT_SKILL."
  fi
  if [ -n "$ACTIVE_REQ" ]; then
    REASON="$REASON Active request: $ACTIVE_REQ."
  fi
  REASON="$REASON Consecutive block count: $NEXT_BLOCK_COUNT."

  if [ "$NEXT_BLOCK_COUNT" -ge 3 ]; then
    REASON="[자동 중단] $REASON Escalate to user for steering."
  fi

  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$NEXT_BLOCK_COUNT")"
  emit_block_json "$REASON"
  debug_log "block" "reason=agile_allow_pattern_missing_marker current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

if [ "$HAS_NEXT_ACTION" != "true" ]; then
  if [ "$ALLOW_PATTERN_FOUND" = "true" ]; then
    debug_log "allow" "reason=explicit_allow_pattern_no_next_action workflow_active=$WORKFLOW_ACTIVE"
    exit 0
  fi
else
  if [ "$NEXT_AUTO" = "true" ]; then
    debug_log "block_decision" "reason=next_action_auto_override skip_allow_pattern=true next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE"
  else
    debug_log "block_decision" "reason=next_action_present skip_allow_pattern=true next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO"
  fi
fi

REASON="Workflow active, continue current skill and context without stopping."
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
if [ "$HAS_NEXT_ACTION" = "true" ] && [ -n "$NEXT_SKILL" ]; then
  NEXT_ARGS="-a"
  if [ -n "$NEXT_SOURCE" ]; then
    NEXT_ARGS="-a $NEXT_SOURCE"
  fi
  REASON="$REASON You MUST call Skill(skill: \"$NEXT_SKILL\", args: \"$NEXT_ARGS\") immediately."
  if [ -n "$SOURCE_SKILL" ]; then
    REASON="$REASON Transition source_skill: $SOURCE_SKILL."
  fi
elif [ "$HAS_NEXT_ACTION" = "true" ]; then
  REASON="$REASON Next action is pending; do not stop."
elif [ -n "$NEXT_SKILL" ]; then
  REASON="$REASON Workflow active, continue current skill before transitioning to $NEXT_SKILL."
fi
REASON="$REASON Do not stop; emit the next tool call now."

PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$((BLOCK_COUNT + 1))")"
emit_block_json "$REASON"
debug_log "block" "reason=workflow_active current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT last_block_reason=$LAST_BLOCK_REASON"
exit 0
