#!/usr/bin/env bash
set -euo pipefail

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="$PWD" ;;
esac
case "$script_dir" in
  /*) ;;
  *) script_dir="$(cd "$script_dir" && pwd)" ;;
esac

_mst_hooks_dir_is_valid() {
  local dir="$1" parent
  case "$dir" in
    *'${CLAUDE_PLUGIN_ROOT}'*) return 1 ;;
    */.claude/plugins/cache/*/hooks) return 0 ;;
    */.claude/plugins/marketplaces/*/hooks) return 0 ;;
  esac
  if [ -f "$dir/lib/sha256.bash" ]; then
    return 0
  fi
  case "$dir" in
    */.claude/hooks)
      parent="${dir%/.claude/hooks}"
      [ -d "$parent/.gran-maestro" ] && return 0
      ;;
    */hooks)
      parent="${dir%/hooks}"
      { [ -d "$parent/.gran-maestro" ] || [ -e "$parent/.git" ]; } && return 0
      if [ -n "${BATS_TEST_TMPDIR:-}" ]; then
        case "$dir" in
          "$BATS_TEST_TMPDIR"/master-baseline/hooks) return 0 ;;
        esac
      fi
      ;;
  esac
  return 1
}

case "$script_dir" in
  *'${CLAUDE_PLUGIN_ROOT}'*)
    echo "[mst-hook] warning: unexpected execution path. Possible \${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open." >&2
    exit 0
    ;;
esac

if [ ! -f "$script_dir/lib/sha256.bash" ] && ! _mst_hooks_dir_is_valid "$script_dir"; then
  echo "[mst-hook] warning: unexpected execution path. Possible \${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open." >&2
  exit 0
fi

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
CURRENT_PPID="${MST_STATE_PPID:-$PPID}"
STATE_FILE="${MST_TMP}/mst-state-${CURRENT_PPID}.json"
STDIN_RAW="$(cat || true)"
MST_LEDGER_HOOK_EVENT="UserPromptSubmit"
if [ -f "${script_dir}/lib/ledger.bash" ]; then
  # shellcheck source=/dev/null
  source "${script_dir}/lib/ledger.bash" 2>/dev/null || true
fi
if declare -F emit_ledger_start >/dev/null 2>&1 && declare -F emit_ledger_complete >/dev/null 2>&1; then
  emit_ledger_start "$MST_LEDGER_HOOK_EVENT" || true
  _mst_ledger_complete_once() {
    local status="${1:-$?}"
    [ "${MST_LEDGER_COMPLETED:-0}" = "1" ] && return 0
    MST_LEDGER_COMPLETED=1
    emit_ledger_complete "$MST_LEDGER_HOOK_EVENT" "$status" || true
  }
  trap '_mst_ledger_exit_code=$?; _mst_ledger_complete_once "$_mst_ledger_exit_code"; exit "$_mst_ledger_exit_code"' EXIT
fi

is_auto_chain_active() {
  python3 - "$STATE_FILE" <<'PY' 2>/dev/null || true
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("false")
    raise SystemExit(0)

active = False
if isinstance(payload, dict):
    active = payload.get("workflow_active") is True
    next_action = payload.get("next_action")
    if isinstance(next_action, dict) and next_action.get("auto_mode") is True:
        active = True
print("true" if active else "false")
PY
}

extract_transcript_path() {
  printf '%s' "$STDIN_RAW" | python3 -c 'import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
value = payload.get("transcript_path") if isinstance(payload, dict) else ""
print(value.strip() if isinstance(value, str) else "")
' 2>/dev/null || true
}

if [ "$(is_auto_chain_active)" != "true" ]; then
  exit 0
fi

TRANSCRIPT_PATH="$(extract_transcript_path)"
if ! STATUS_JSON="$(
  cd "$PROJECT_ROOT" && python3 scripts/mst.py status context-usage \
    --transcript-path "$TRANSCRIPT_PATH" \
    --state-file "$STATE_FILE" 2>/dev/null
)"; then
  exit 0
fi

python3 - "$STATUS_JSON" <<'PY' 2>/dev/null || true
import json
import sys

try:
    payload = json.loads(sys.argv[1] if len(sys.argv) > 1 else "{}")
except Exception:
    raise SystemExit(0)

if not isinstance(payload, dict):
    raise SystemExit(0)

context_pct = payload.get("context_pct")
context_tokens = payload.get("context_tokens")
model_window = payload.get("model_window")
cache_available = payload.get("cache_available") is True
auto_approve = payload.get("auto_approve_on_unblock") is True

if isinstance(context_pct, (int, float)):
    pct_text = f"{context_pct * 100:.1f}%"
else:
    pct_text = "unknown"

tokens_text = str(context_tokens) if isinstance(context_tokens, int) else "unknown"
window_text = str(model_window) if isinstance(model_window, int) else "unknown"
cache_text = "true" if cache_available else "false"
auto_approve_text = "true" if auto_approve else "false"

ctx_lines = [
    f"- 컨텍스트 사용률: {pct_text} ({tokens_text} / {window_text} tokens)",
    f"- 캐싱: {cache_text}",
    f"- workflow.auto_approve_on_unblock: {auto_approve_text}",
    "- 안내: 위 수치가 위험 임계 이하이면 chain 지속이 정상 경로입니다. 컨텍스트 크기·토큰 효율·변경 추적 품질을 단독 근거로 chain을 끊지 마세요.",
]
additional = "[자동 연쇄 컨텍스트]\n" + "\n".join(ctx_lines)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": additional}}, ensure_ascii=False))
PY
