#!/usr/bin/env bash

gm_policy_project_key() {
  local real_path
  real_path="$(cd "$PROJECT_ROOT" 2>/dev/null && pwd -P)" || real_path="$PROJECT_ROOT"
  printf '%s' "$real_path" | gm_sha256_text | cut -c1-16
}

gm_policy_project_dir() {
  local key
  key="$(gm_policy_project_key)"
  printf '%s/.claude/gran-maestro-policy/projects/%s\n' "$HOME" "$key"
}

gm_policy_block() {
  local rule_id="$1"
  local message="$2"
  printf '[core-block] rule=%s %s\n' "$rule_id" "$message" >&2
  exit 2
}

gm_policy_normalize_path() {
  local path="${1:-}"
  if [ "$path" = "~" ]; then
    printf '%s\n' "$HOME"
    return
  fi
  if [ "${path:0:2}" = "~/" ]; then
    printf '%s/%s\n' "$HOME" "${path:2}"
    return
  fi
  case "$path" in
    /*) printf '%s\n' "$path" ;;
    "") printf '\n' ;;
    *) printf '%s/%s\n' "$PROJECT_ROOT" "$path" ;;
  esac
}

gm_policy_extract_event() {
  if [ -n "${MST_HOOK_TOOL_NAME:-}" ] || [ -n "${MST_HOOK_FILE_PATH:-}" ] || [ -n "${MST_HOOK_COMMAND:-}" ]; then
    printf '%s\t%s\t%s\n' "${MST_HOOK_TOOL_NAME:-}" "${MST_HOOK_FILE_PATH:-}" "${MST_HOOK_COMMAND:-}"
    return 0
  fi

  MST_HOOK_STDIN_RAW="$STDIN_RAW" python3 - <<'PY' 2>/dev/null || printf '\t\t\n'
import json
import os

try:
    payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

tool = str(payload.get("tool_name") or "").strip()
tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}
file_path = tool_input.get("file_path") or tool_input.get("path") or ""
command = tool_input.get("command") or ""
if not isinstance(file_path, str):
    file_path = ""
if not isinstance(command, str):
    command = ""
print("{}\t{}\t{}".format(tool, file_path.replace("\t", " "), command.replace("\t", " ")))
PY
}

gm_policy_is_mutating_command() {
  local command="$1"
  [[ "$command" =~ (^|[[:space:];|&])(rm|mv|cp|mkdir|rmdir|truncate|chmod|chown|touch|tee)([[:space:]]|$) ]] && return 0
  [[ "$command" =~ (^|[[:space:];|&])(sed[[:space:]]+-i|perl[[:space:]]+-pi)([[:space:]]|$) ]] && return 0
  [[ "$command" == *">"* ]] && return 0
  return 1
}

gm_policy_hardcoded_core_check() {
  local info tool raw_file_path command file_path policy_root sessions_root
  info="$(gm_policy_extract_event)"
  tool="$(printf '%s' "$info" | cut -f1)"
  raw_file_path="$(printf '%s' "$info" | cut -f2)"
  command="$(printf '%s' "$info" | cut -f3-)"
  file_path="$(gm_policy_normalize_path "$raw_file_path")"
  policy_root="$HOME/.claude/gran-maestro-policy"
  sessions_root="$PROJECT_ROOT/.gran-maestro/sessions"

  if [[ "$file_path" == "$policy_root/"* ]] && [[ "$tool" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    if [[ "$file_path" == *"/rules.d/"* || "$file_path" == */manifest.json ]]; then
      gm_policy_block "META-BYPASS-RULE-FILE" "정책 디렉토리는 LLM이 수정할 수 없습니다."
    fi
    gm_policy_block "META-BYPASS-POLICY-DIR" "정책 디렉토리는 LLM이 수정할 수 없습니다."
  fi

  if [[ "$tool" == "Bash" ]] && gm_policy_is_mutating_command "$command"; then
    if [[ "$command" == *".claude/gran-maestro-policy"* || "$command" == *"$policy_root"* ]]; then
      if [[ "$command" == *"/ledger-heads/"* ]]; then
        gm_policy_block "META-BYPASS-LEDGER-SENTINEL" "ledger sentinel은 LLM이 직접 수정할 수 없습니다."
      fi
      if [[ "$command" == *"/rules.d/"* || "$command" == *"manifest.json"* ]]; then
        gm_policy_block "META-BYPASS-RULE-FILE" "정책 디렉토리는 LLM이 수정할 수 없습니다."
      fi
      gm_policy_block "META-BYPASS-POLICY-DIR" "정책 디렉토리는 LLM이 수정할 수 없습니다."
    fi
  fi

  if [[ "$file_path" == "$sessions_root/"*"/history.ndjson" ]] && [[ "$tool" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    gm_policy_block "META-BYPASS-HISTORY-NDJSON" "history.ndjson은 LLM이 직접 수정할 수 없습니다."
  fi

  if [[ "$tool" == "Bash" ]] && gm_policy_is_mutating_command "$command"; then
    if [[ "$command" == *".gran-maestro/sessions/"* && "$command" == *"history.ndjson"* ]]; then
      gm_policy_block "META-BYPASS-HISTORY-NDJSON" "history.ndjson은 LLM이 직접 수정할 수 없습니다."
    fi
    if [[ "$command" == *".gran-maestro/sessions/"* ]] && [[ "$command" == *"history.head"* || "$command" == *"history.verify"* ]]; then
      gm_policy_block "META-BYPASS-LEDGER-SENTINEL" "ledger sentinel은 LLM이 직접 수정할 수 없습니다."
    fi
    if [[ "$command" == *".gran-maestro/sessions/"* ]] && [[ "$command" =~ (^|[[:space:];|&])(mkdir|mv|rename)([[:space:]]|$) ]]; then
      gm_policy_block "META-BYPASS-SESSION-ID-FORGERY" "session_id 디렉토리는 LLM이 직접 생성하거나 이름 변경할 수 없습니다."
    fi
  fi

  if [[ "$file_path" == "$sessions_root/"*"/history.head" ]] && [[ "$tool" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    gm_policy_block "META-BYPASS-LEDGER-SENTINEL" "ledger sentinel은 LLM이 직접 수정할 수 없습니다."
  fi

  if [[ "$file_path" == "$policy_root/ledger-heads/"* ]] && [[ "$tool" =~ ^(Write|Edit|MultiEdit)$ ]]; then
    gm_policy_block "META-BYPASS-LEDGER-SENTINEL" "ledger sentinel은 LLM이 직접 수정할 수 없습니다."
  fi
}

gm_policy_verify_manifest() {
  gm_policy_rule_engine_run "verify-only"
}

gm_policy_rule_engine_run() {
  local mode="${1:-full}" policy_dir manifest status
  policy_dir="$(gm_policy_project_dir)"
  manifest="$policy_dir/manifest.json"
  [ -f "$manifest" ] || return 0

  set +e
  MST_HOOK_STDIN_RAW="$STDIN_RAW" python3 - "$mode" "$PROJECT_ROOT" "$policy_dir" "$manifest" <<'PY'
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

mode = sys.argv[1]
project_root = Path(sys.argv[2])
policy_dir = Path(sys.argv[3])
manifest = Path(sys.argv[4])
raw = os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}"

try:
    event = json.loads(raw)
except Exception:
    event = {}
if not isinstance(event, dict):
    event = {}
tool_input = event.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}

cache_path = policy_dir / ".rule-engine-cache.json"

ALLOWLIST = {
    "tool_match",
    "arg_pattern",
    "history_exists",
    "history_not_exists_after",
    "path_protected",
}


def block_unknown(rule_id, predicate):
    print(f"[policy-block] unknown_predicate rule={rule_id} predicate={predicate}", file=sys.stderr)


unknown_predicate_seen = False


def fingerprint(path):
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def cache_valid():
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("manifest_fingerprint") != fingerprint(manifest):
        return None
    files = payload.get("files")
    rules = payload.get("rules")
    if not isinstance(files, list) or not isinstance(rules, list):
        return None
    for item in files:
        if not isinstance(item, dict):
            return None
        rel = str(item.get("path") or "")
        expected = str(item.get("fingerprint") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            return None
        rule_path = policy_dir / rel
        if not rule_path.is_file():
            return None
        if fingerprint(rule_path) != expected:
            return None
    return rules


def write_cache(files, rules):
    payload = {
        "manifest_fingerprint": fingerprint(manifest),
        "files": files,
        "rules": rules,
    }
    tmp_path = Path(str(cache_path) + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_path, cache_path)


def get_arg(key):
    value = tool_input.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arg_pattern(key, op, value):
    observed = get_arg(str(key or ""))
    if op == "equals":
        return observed == str(value)
    if op == "contains":
        return str(value) in observed
    if op == "regex":
        return re.search(str(value), observed) is not None
    if op == "in":
        values = value if isinstance(value, list) else []
        return observed in [str(item) for item in values]
    return False


def path_protected(path_glob):
    candidate = get_arg("file_path") or get_arg("path") or get_arg("command")
    expanded = candidate.replace("~", str(Path.home()), 1) if candidate.startswith("~") else candidate
    return fnmatch.fnmatch(expanded, str(path_glob)) or fnmatch.fnmatch(candidate, str(path_glob))


def history_path():
    sid = event.get("session_id")
    if not isinstance(sid, str) or not sid.strip():
        return None
    path = project_root / ".gran-maestro" / "sessions" / sid.strip() / "history.ndjson"
    return path if path.is_file() else None


def iter_history():
    path = history_path()
    if path is None:
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def match_object(row, expected):
    if not isinstance(expected, dict):
        return False
    for key, value in expected.items():
        observed = row.get(key)
        if isinstance(value, dict) and "in" in value:
            if observed not in value.get("in", []):
                return False
        elif observed != value:
            return False
    return True


def history_exists(type_filter):
    return any(match_object(row.get("event", row), type_filter) for row in iter_history())


def history_not_exists_after(anchor, target):
    rows = [row.get("event", row) for row in iter_history()]
    anchor_index = -1
    for index, row in enumerate(rows):
        if match_object(row, anchor):
            anchor_index = index
    if anchor_index < 0:
        return False
    return not any(match_object(row, target) for row in rows[anchor_index + 1 :])


def eval_predicate(rule_id, predicate):
    global unknown_predicate_seen
    if not isinstance(predicate, dict):
        return True

    if "predicate" in predicate:
        name = str(predicate.get("predicate") or "")
        if name not in ALLOWLIST:
            block_unknown(rule_id, name)
            raise SystemExit(2)
        if name == "tool_match":
            return event.get("tool_name") == predicate.get("name")
        if name == "arg_pattern":
            return arg_pattern(predicate.get("key"), predicate.get("op"), predicate.get("value"))
        if name == "path_protected":
            return path_protected(predicate.get("path_glob"))
        if name == "history_exists":
            return history_exists(predicate.get("type_filter"))
        if name == "history_not_exists_after":
            return history_not_exists_after(predicate.get("anchor"), predicate.get("target"))

    if "history" in predicate:
        history = predicate.get("history")
        if isinstance(history, dict) and "exists" in history:
            return history_exists(history.get("exists"))
        if isinstance(history, dict) and "not_exists_after" in history:
            payload = history.get("not_exists_after")
            if isinstance(payload, dict):
                return history_not_exists_after(payload.get("anchor"), payload.get("target"))

    return True


def trigger_matches(trigger):
    if not isinstance(trigger, dict):
        return True
    tool = trigger.get("tool")
    if isinstance(tool, str) and tool and event.get("tool_name") != tool:
        return False
    args = trigger.get("args")
    if isinstance(args, dict):
        for key, condition in args.items():
            if isinstance(condition, dict):
                for op, value in condition.items():
                    if not arg_pattern(key, op, value):
                        return False
            elif get_arg(key) != str(condition):
                return False
    return True


def condition_matches(rule_id, condition):
    if not isinstance(condition, dict):
        return True
    if "all" in condition:
        return all(eval_predicate(rule_id, item) for item in condition.get("all", []))
    if "any" in condition:
        return any(eval_predicate(rule_id, item) for item in condition.get("any", []))
    return eval_predicate(rule_id, condition)


def verified_rule_files():
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        print(f"[policy-block] manifest_invalid file={manifest}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("rules"), list):
        print(f"[policy-block] manifest_invalid file={manifest}", file=sys.stderr)
        raise SystemExit(2)

    verified = []
    for item in payload.get("rules", []):
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        expected = str(item.get("sha256") or "")
        if rel.startswith("/") or ".." in Path(rel).parts:
            print(f"[policy-block] manifest_path_invalid file={manifest} path={rel}", file=sys.stderr)
            raise SystemExit(2)

        rule_path = policy_dir / rel
        if not rule_path.is_file():
            print(f"[policy-block] manifest_rule_missing file={rel}", file=sys.stderr)
            raise SystemExit(2)

        actual = hashlib.sha256(rule_path.read_bytes()).hexdigest()
        if actual != expected:
            print(
                f"[policy-block] manifest_sha256_mismatch file={rel} expected={expected} actual={actual}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        verified.append({"path": rel, "fingerprint": fingerprint(rule_path), "rule_path": rule_path})
    return verified


def compile_rules(verified_files):
    compiled = []
    for item in verified_files:
        rule_path = item["rule_path"]
        try:
            payload = json.loads(rule_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[policy-warning] rule_file_invalid file={rule_path.name} error={exc}", file=sys.stderr)
            continue
        for rule in payload.get("rules", []):
            if not isinstance(rule, dict):
                continue
            compiled.append(
                {
                    "id": str(rule.get("id") or rule_path.name),
                    "trigger": rule.get("trigger"),
                    "condition": rule.get("condition"),
                    "action": rule.get("action"),
                    "severity": rule.get("severity"),
                    "message": rule.get("message"),
                }
            )
    return compiled


def validate_predicates(rule_id, condition):
    if not isinstance(condition, dict):
        return True
    if "predicate" in condition:
        name = str(condition.get("predicate") or "")
        if name not in ALLOWLIST:
            block_unknown(rule_id, name)
            return False
    for key in ("all", "any"):
        predicates = condition.get(key)
        if isinstance(predicates, list):
            for item in predicates:
                if not validate_predicates(rule_id, item):
                    return False
    return True


verified_files = verified_rule_files()
compiled_rules = cache_valid()
if compiled_rules is None:
    compiled_rules = compile_rules(verified_files)
    write_cache(
        [{"path": item["path"], "fingerprint": item["fingerprint"]} for item in verified_files],
        compiled_rules,
    )

for rule in compiled_rules:
    rule_id = str(rule.get("id") or "rule")
    if not validate_predicates(rule_id, rule.get("condition")):
        raise SystemExit(2)

if mode == "verify-only":
    raise SystemExit(0)


for rule in compiled_rules:
    rule_id = str(rule.get("id") or "rule")
    if not trigger_matches(rule.get("trigger")):
        continue
    if not condition_matches(rule_id, rule.get("condition")):
        continue
    action = rule.get("action") if isinstance(rule.get("action"), dict) else {}
    decision = action.get("decision") or ("block" if rule.get("severity") == "block" else "warn")
    message = str(action.get("message") or rule.get("message") or rule_id)
    if decision == "block":
        print(f"[policy-block] rule={rule_id} {message}", file=sys.stderr)
        raise SystemExit(2)
    if decision == "warn":
        print(f"[policy-warning] rule={rule_id} {message}", file=sys.stderr)

if unknown_predicate_seen:
    print("[policy-block] unknown_predicate fail_closed", file=sys.stderr)
    raise SystemExit(2)

raise SystemExit(0)
PY
  status=$?
  set -e
  return "$status"
}

gm_policy_rule_engine_check() {
  gm_policy_rule_engine_run "full"
}

gm_policy_preflight() {
  local status
  gm_policy_hardcoded_core_check
  gm_policy_rule_engine_check
  status=$?
  if [ "$status" -ne 0 ]; then
    exit "$status"
  fi
}
