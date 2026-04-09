#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
MST_TMP="${PROJECT_ROOT}/.gran-maestro/tmp"
BACKUP_FILE="${HOME}/.claude/mst-statusline-backup.json"
INPUT_JSON="$(cat || true)"

DEFAULT_HUD_COMMAND="$(cat <<'CMD'
bash -c 'plugin_dir=$(ls -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/claude-hud/claude-hud/*/ 2>/dev/null | sort -t/ -k$(echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache/claude-hud/claude-hud/" | tr "/" "\n" | wc -l)n | tail -1); exec "/opt/homebrew/bin/node" "${plugin_dir}/dist/index.js"'
CMD
)"

resolve_hud_command() {
  if [ -f "$BACKUP_FILE" ]; then
    local restored
    restored="$(python3 -c 'import json, sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    print("")
    sys.exit(0)

command = ""
if isinstance(data, dict):
    status_line = data.get("statusLine")
    if isinstance(status_line, dict):
        value = status_line.get("command")
        if isinstance(value, str):
            command = value
if command:
    print(command)
' "$BACKUP_FILE" 2>/dev/null || true)"
    if [ -n "$restored" ]; then
      if [[ "$restored" == *"mst-statusline"* ]]; then
        printf '%s' "$DEFAULT_HUD_COMMAND"
        return 0
      fi
      printf '%s' "$restored"
      return 0
    fi
  fi

  printf '%s' "$DEFAULT_HUD_COMMAND"
}

resolve_state_file() {
  local by_ppid latest
  by_ppid="${MST_TMP}/mst-state-${PPID}.json"
  if [ -f "$by_ppid" ]; then
    printf '%s' "$by_ppid"
    return 0
  fi

  latest="$(ls -1t "${MST_TMP}"/mst-state-*.json 2>/dev/null | head -n 1 || true)"
  printf '%s' "$latest"
}

extract_transcript_path() {
  printf '%s' "$INPUT_JSON" | python3 -c 'import json, sys
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception:
    data = {}

path = ""
if isinstance(data, dict):
    value = data.get("transcript_path")
    if isinstance(value, str):
        path = value.strip()

if path:
    print(path)
' 2>/dev/null || true
}

save_transcript_bridge() {
  local transcript_path="${1:-}"
  local bridge_file tmp_file
  [ -n "$transcript_path" ] || return 0
  mkdir -p "$MST_TMP"
  bridge_file="${MST_TMP}/mst-transcript-${PPID}.path"
  tmp_file="${bridge_file}.tmp.$$"
  if printf '%s' "$transcript_path" > "$tmp_file" 2>/dev/null; then
    mv "$tmp_file" "$bridge_file" 2>/dev/null || rm -f "$tmp_file"
  else
    rm -f "$tmp_file"
  fi
}

build_mst_line() {
  local state_file="$1"
  local transcript_path="${2:-}"
  local dispatch_run_dir="${3:-}"
  python3 -c 'import json, os, re, sys
from datetime import datetime, timezone

state_path = sys.argv[1] if len(sys.argv) > 1 else ""
transcript_path = sys.argv[2] if len(sys.argv) > 2 else ""
dispatch_run_dir = sys.argv[3] if len(sys.argv) > 3 else ""
MAX_TAIL_BYTES = 512 * 1024
SNIFF_LINE_LIMIT = 100
SKILL_TOOL_NAMES = {"Skill", "proxy_Skill"}


def parse_iso(ts: str):
    if not isinstance(ts, str) or not ts:
        return None
    normalized = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_elapsed(ts: str):
    started = parse_iso(ts)
    if started is None:
        return "0s"
    now = datetime.now(timezone.utc)
    total = int((now - started).total_seconds())
    if total < 0:
        total = 0
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"


def clean_skill(name, strip_namespace=False):
    if not isinstance(name, str):
        return ""
    value = re.sub(r"^mst:", "", name.split("\n", 1)[0].strip())
    if strip_namespace and ":" in value:
        value = value.rsplit(":", 1)[-1]
    return value


def extract_context_id(args):
    if not isinstance(args, str):
        return ""
    match = re.search(r"\b((?:PLN|REQ)-\d+)\b", args, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return ""


def render_line(labels, context_id):
    if not labels:
        return "MST idle"
    line = " > ".join(labels)
    if context_id:
        line += f" ({context_id})"
    return line


def render_from_state(path):
    if not path or not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    current_skill = clean_skill(data.get("current_skill"))
    if not current_skill:
        return None

    updated_at = ""
    for field in ("updated_at", "started_at"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            updated_at = value.strip()
            break

    label = f"{current_skill}({format_elapsed(updated_at)})"

    active_req = data.get("active_req")
    if isinstance(active_req, str):
        active_req = active_req.strip().upper()
    else:
        active_req = ""

    if not re.match(r"^(REQ|PLN)-\d+$", active_req):
        active_req = ""

    if not active_req:
        next_action = data.get("next_action")
        if isinstance(next_action, dict):
            for key in ("source_id", "source"):
                value = next_action.get(key)
                if isinstance(value, str) and re.match(r"^(REQ|PLN)-\d+$", value.strip().upper()):
                    active_req = value.strip().upper()
                    break

    return render_line([label], active_req)


def load_transcript_lines(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        file_size = os.path.getsize(path)
    except Exception:
        return None

    try:
        if file_size > MAX_TAIL_BYTES:
            start_offset = max(0, file_size - MAX_TAIL_BYTES)
            with open(path, "rb") as f:
                f.seek(start_offset)
                raw = f.read()
            text = raw.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            if start_offset > 0 and lines:
                lines = lines[1:]
            return lines

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()
    except Exception:
        return None


def schema_detected(lines):
    scanned = 0
    for line in lines:
        if not line.strip():
            continue
        scanned += 1
        if scanned > SNIFF_LINE_LIMIT:
            break
        try:
            entry = json.loads(line)
        except Exception:
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("tool_use", "tool_result"):
                return True
    return False


def render_from_transcript(path):
    lines = load_transcript_lines(path)
    if lines is None:
        return None
    if not schema_detected(lines):
        return None

    pending = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue

        timestamp = entry.get("timestamp") if isinstance(entry, dict) else ""
        message = entry.get("message") if isinstance(entry, dict) else {}
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                block_id = block.get("id")
                block_name = block.get("name")
                if not isinstance(block_id, str) or block_name not in SKILL_TOOL_NAMES:
                    continue
                input_data = block.get("input")
                if not isinstance(input_data, dict):
                    input_data = {}
                pending[block_id] = {
                    "skill": input_data.get("skill"),
                    "args": input_data.get("args"),
                    "timestamp": timestamp,
                }
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    pending.pop(tool_use_id, None)

    labels = []
    context_id = ""
    for info in pending.values():
        if not isinstance(info, dict):
            continue
        skill = clean_skill(info.get("skill"), strip_namespace=True)
        if not skill:
            continue
        started_at = info.get("timestamp") or ""
        labels.append(f"{skill}({format_elapsed(started_at)})")
        candidate_context_id = extract_context_id(info.get("args"))
        if candidate_context_id:
            context_id = candidate_context_id

    if not labels:
        return None
    return render_line(labels, context_id)


def build_dispatch_prefix(run_dir):
    if not run_dir or not os.path.isdir(run_dir):
        return ""

    now = datetime.now(timezone.utc)
    count = 0
    oldest_age = 0
    for name in os.listdir(run_dir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(run_dir, name)
        if not os.path.isfile(path):
            continue

        count += 1
        age = 10**9
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                heartbeat = payload.get("last_heartbeat")
                heartbeat_dt = parse_iso(heartbeat) if isinstance(heartbeat, str) else None
                if heartbeat_dt is not None:
                    age = int((now - heartbeat_dt).total_seconds())
                    if age < 0:
                        age = 0
        except Exception:
            age = 10**9

        if age > oldest_age:
            oldest_age = age

    if count == 0:
        return ""
    return f"MST {count} run · oldest {oldest_age}s"


def merge_with_dispatch_prefix(base_line, run_dir):
    prefix = build_dispatch_prefix(run_dir)
    if not prefix:
        return base_line

    suffix = base_line
    if isinstance(suffix, str) and suffix.startswith("MST "):
        suffix = suffix[4:]
    if suffix:
        return f"{prefix} · {suffix}"
    return prefix


state_line = render_from_state(state_path)
if state_line is not None:
    print(merge_with_dispatch_prefix(state_line, dispatch_run_dir))
    sys.exit(0)

transcript_line = render_from_transcript(transcript_path)
if transcript_line is not None:
    print(merge_with_dispatch_prefix(transcript_line, dispatch_run_dir))
    sys.exit(0)

print(merge_with_dispatch_prefix("MST idle", dispatch_run_dir))
' "$state_file" "$transcript_path" "$dispatch_run_dir" 2>/dev/null || printf 'MST idle\n'
}

HUD_COMMAND="$(resolve_hud_command)"
HUD_OUTPUT="$(printf '%s' "$INPUT_JSON" | sh -c "$HUD_COMMAND" 2>/dev/null || true)"
STATE_FILE="$(resolve_state_file)"
TRANSCRIPT_PATH="$(extract_transcript_path)"
DISPATCH_RUN_DIR="${PROJECT_ROOT}/.gran-maestro/run"
save_transcript_bridge "$TRANSCRIPT_PATH"
MST_LINE="$(build_mst_line "$STATE_FILE" "$TRANSCRIPT_PATH" "$DISPATCH_RUN_DIR")"

if [ -n "$HUD_OUTPUT" ]; then
  printf '%s\n' "$HUD_OUTPUT"
fi
printf '%s\n' "$MST_LINE"
