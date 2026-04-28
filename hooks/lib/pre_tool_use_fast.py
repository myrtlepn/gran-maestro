#!/usr/bin/env python3
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ZERO_HASH = "0" * 64
MUTATING_RE = re.compile(r"(^|[ \t;|&])(rm|mv|cp|mkdir|rmdir|truncate|chmod|chown|touch|tee)([ \t]|$)")
INLINE_MUTATING_RE = re.compile(r"(^|[ \t;|&])((sed[ \t]+-i)|(perl[ \t]+-pi))([ \t]|$)")
SESSION_RENAME_RE = re.compile(r"(^|[ \t;|&])(mkdir|mv|rename)([ \t]|$)")
ALLOWLIST = {
    "tool_match",
    "arg_pattern",
    "history_exists",
    "history_not_exists_after",
    "path_protected",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stderr(message: str) -> None:
    print(message, file=sys.stderr)


def block(prefix: str, rule_id: str, message: str) -> int:
    stderr(f"[{prefix}] rule={rule_id} {message}")
    return 2


def sanitize_session_id(value: str) -> Optional[str]:
    if not value or "/" in value or ".." in value:
        return None
    if re.search(r"[^A-Za-z0-9._-]", value):
        return None
    return value


def normalize_path(raw_path: str, project_root: Path, home: Path) -> str:
    if raw_path == "~":
        return str(home)
    if raw_path.startswith("~/"):
        return str(home / raw_path[2:])
    if raw_path.startswith("/"):
        return raw_path
    if not raw_path:
        return ""
    return str(project_root / raw_path)


def is_mutating_command(command: str) -> bool:
    return bool(
        MUTATING_RE.search(command)
        or INLINE_MUTATING_RE.search(command)
        or ">" in command
    )


def project_key(project_root: Path) -> str:
    return sha256_text(os.path.realpath(project_root))[:16]


def history_paths(project_root: Path, home: Path, session_id: str) -> Tuple[Path, Path, Path, Path]:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = home / ".claude" / "gran-maestro-policy" / "ledger-heads" / f"{session_id}.head"
    verify_state = session_dir / "history.verify"
    return history_file, local_head, mirror_head, verify_state


def file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def read_head(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def sanitize_log_value(value: str) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").replace("\t", " ")


def resolve_flow_logger_script(project_root: Path) -> Path:
    project_script = project_root / "scripts" / "_flow_logger.py"
    if project_script.is_file():
        return project_script

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "scripts" / "_flow_logger.py"
        if candidate.is_file():
            return candidate
    return project_script


def warn_helper_failed(helper: str, status: int, detail: str = "") -> None:
    helper = sanitize_log_value(helper)
    detail = sanitize_log_value(detail)
    if detail:
        stderr(f"[mst-pre-tool-use] helper_failed helper={helper} exit={status} {detail}")
    else:
        stderr(f"[mst-pre-tool-use] helper_failed helper={helper} exit={status}")


def append_flow_event(
    project_root: Path,
    session_id: str,
    event_type: str,
    data: str,
    snapshot_path: Path,
    stdin_digest: str,
) -> None:
    flow_logger = resolve_flow_logger_script(project_root)
    if not flow_logger.is_file():
        warn_helper_failed("flow_logger", 127, f"path={flow_logger}")
        return

    import subprocess

    result = subprocess.run(
        [
            "python3",
            str(flow_logger),
            "append",
            "--project-root",
            str(project_root),
            "--session-id",
            session_id or "unknown",
            "--event-type",
            event_type,
            "--data",
            data,
            "--snapshot-path",
            str(snapshot_path) if snapshot_path else "",
            "--stdin-digest",
            stdin_digest,
            "--ppid",
            str(os.getppid()),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        warn_helper_failed("flow_logger", result.returncode, f"event_type={event_type}")


def resolve_durable_owner_session_id(project_root: Path) -> Optional[str]:
    base_dir = project_root / ".gran-maestro"
    request_terminal = {"done", "completed", "accepted", "cancelled"}
    plan_terminal = {"done", "completed", "cancelled"}
    values: List[str] = []

    def add_owner(path: Path, terminal_statuses=None, require_active: bool = False) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        status = str(payload.get("status") or "").strip().lower()
        if terminal_statuses is not None and status in terminal_statuses:
            return
        if require_active and status != "active":
            return

        owner_session_id = payload.get("owner_session_id")
        if isinstance(owner_session_id, str) and owner_session_id.strip():
            values.append(owner_session_id.strip())

    for path in (base_dir / "requests").glob("REQ-*/request.json"):
        add_owner(path, request_terminal)
    for path in (base_dir / "plans").glob("PLN-*/plan.json"):
        add_owner(path, plan_terminal)
    for path in (base_dir / "agile").glob("AGI-*/session.json"):
        add_owner(path, require_active=True)

    unique: List[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else None


def warn_session_id_mismatch_once_if_any(
    project_root: Path,
    payload: dict,
    raw: str,
    session_id: str,
) -> None:
    if not session_id:
        return

    gm_dir = project_root / ".gran-maestro"
    if not ((gm_dir / "requests").exists() or (gm_dir / "plans").exists() or (gm_dir / "agile").exists()):
        return

    snapshot_path = gm_dir / "state" / session_id / "snapshot.json"
    if not snapshot_path.is_file():
        return

    mst_tmp = project_root / ".gran-maestro" / "tmp"
    sentinel = mst_tmp / f"mst-mismatch-warn-{os.getppid()}-{session_id}.flag"
    if sentinel.is_file():
        return

    durable_sid = resolve_durable_owner_session_id(project_root)
    if not durable_sid:
        return

    snapshot_sid = ""
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        snapshot = {}
    if isinstance(snapshot, dict):
        for key in ("session_id", "sessionId"):
            value = snapshot.get(key)
            if isinstance(value, str) and value.strip():
                snapshot_sid = value.strip()
                break
    if not snapshot_sid:
        snapshot_sid = snapshot_path.parent.name.strip()
    if not snapshot_sid:
        return

    stdin_sid = payload.get("session_id")
    stdin_sid = stdin_sid.strip() if isinstance(stdin_sid, str) else ""
    if not stdin_sid or len({stdin_sid, snapshot_sid, durable_sid}) == 1:
        return

    try:
        mst_tmp.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return
    except OSError:
        return

    data = {
        "stdin_sid": stdin_sid,
        "snapshot_sid": snapshot_sid,
        "durable_sid": durable_sid,
        "hook": "mst-pre-tool-use",
    }
    stderr(
        "[session-id mismatch] stdin={} snapshot={} durable={} hook=mst-pre-tool-use".format(
            sanitize_log_value(stdin_sid),
            sanitize_log_value(snapshot_sid),
            sanitize_log_value(durable_sid),
        )
    )
    append_flow_event(
        project_root,
        session_id,
        "session_id_mismatch",
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        snapshot_path,
        sha256_text(raw),
    )


def read_verify_state(path: Path) -> Optional[Tuple[str, str, int]]:
    if not path.is_file():
        return None
    try:
        head_hash, fingerprint, seq = path.read_text(encoding="utf-8").rstrip("\n").split("\t")
        return head_hash, fingerprint, int(seq)
    except Exception:
        return None


def write_verify_state(path: Path, head_hash: str, fingerprint: str, seq: int) -> None:
    tmp_path = Path(f"{path}.tmp.{os.getpid()}")
    tmp_path.write_text(f"{head_hash}\t{fingerprint}\t{seq}\n", encoding="utf-8")
    os.replace(tmp_path, path)


def last_event_hash(history_file: Path) -> Optional[str]:
    if not history_file.is_file():
        return None
    try:
        with history_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size == 0:
                return None
            offset = min(size, 8192)
            handle.seek(-offset, os.SEEK_END)
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        chunk = history_file.read_text(encoding="utf-8")
    lines = [line for line in chunk.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        row = json.loads(lines[-1])
    except Exception:
        return None
    value = row.get("event_hash")
    return str(value) if isinstance(value, str) else None


def verify_history(project_root: Path, home: Path, session_id: str) -> Tuple[bool, Optional[str], int]:
    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    cached = read_verify_state(verify_state)
    if cached is not None:
        cached_head, cached_fingerprint, cached_seq = cached
        local_value = read_head(local_head)
        mirror_value = read_head(mirror_head)
        if local_value and local_value == mirror_value == cached_head:
            current_fingerprint = file_fingerprint(history_file)
            if current_fingerprint == cached_fingerprint:
                if current_fingerprint == "missing":
                    return True, cached_head, cached_seq
                last_hash = last_event_hash(history_file)
                if last_hash and last_hash == cached_head:
                    return True, cached_head, cached_seq

    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    if history_file.is_file():
        with history_file.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    stderr(f"history ledger mismatch: invalid json line={line_no}: {exc}")
                    return False, None, 0
                if not isinstance(row, dict):
                    stderr(f"history ledger mismatch: row is not object line={line_no}")
                    return False, None, 0
                if row.get("seq") != expected_seq:
                    stderr(f"history ledger mismatch: seq line={line_no}")
                    return False, None, 0
                if row.get("prev_hash") != expected_prev:
                    stderr(f"history ledger mismatch: prev_hash line={line_no}")
                    return False, None, 0
                event = row.get("event")
                if not isinstance(event, dict):
                    stderr(f"history ledger mismatch: event line={line_no}")
                    return False, None, 0
                canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
                computed = sha256_text(expected_prev + "\n" + canonical)
                if row.get("event_hash") != computed:
                    stderr(f"history ledger mismatch: event_hash line={line_no}")
                    return False, None, 0
                expected_prev = computed
                last_hash = computed
                expected_seq += 1

    local_value = read_head(local_head)
    mirror_value = read_head(mirror_head)
    has_entries = expected_seq > 1
    if has_entries and local_value is None:
        stderr("history ledger mismatch: missing history.head")
        return False, None, 0
    if has_entries and mirror_value is None:
        stderr("history ledger mismatch: missing home mirror head")
        return False, None, 0
    if local_value is not None and local_value != last_hash:
        stderr("history ledger mismatch: history.head")
        return False, None, 0
    if mirror_value is not None and mirror_value != last_hash:
        stderr("history ledger mismatch: home mirror head")
        return False, None, 0

    verify_state.parent.mkdir(parents=True, exist_ok=True)
    write_verify_state(verify_state, last_hash, file_fingerprint(history_file), expected_seq - 1)
    return True, last_hash, expected_seq - 1


def verify_history_locked(project_root: Path, home: Path, session_id: str) -> Tuple[bool, Optional[str], int]:
    history_file, _, _, _ = history_paths(project_root, home, session_id)
    session_dir = history_file.parent
    lock_dir = session_dir / "history.lock"
    session_dir.mkdir(parents=True, exist_ok=True)
    if not acquire_lock(lock_dir):
        stderr("history ledger mismatch: lock timeout")
        return False, None, 0
    try:
        return verify_history(project_root, home, session_id)
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def acquire_lock(lock_dir: Path) -> bool:
    tries = int(os.environ.get("MST_HISTORY_LOCK_TRIES", "20"))
    while tries > 0:
        try:
            lock_dir.mkdir()
            return True
        except FileExistsError:
            time.sleep(0.05)
            tries -= 1
    return False


def append_tool_call(project_root: Path, home: Path, session_id: str, tool_name: str, tool_input: dict) -> int:
    if not session_id:
        return 0
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        stderr("history ledger mismatch: invalid session_id")
        return 2

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, clean_sid)
    session_dir = history_file.parent
    lock_dir = session_dir / "history.lock"
    session_dir.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    if not acquire_lock(lock_dir):
        stderr("history ledger mismatch: lock timeout")
        return 2

    try:
        ok, prev_hash, seq = verify_history(project_root, home, clean_sid)
        if not ok:
            return 2
        prev_hash = prev_hash or ZERO_HASH
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args_json = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event = {
            "args_sha256": sha256_text(args_json),
            "timestamp": timestamp,
            "tool": tool_name or "unknown",
            "type": "tool_call",
        }
        canonical_event = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event_hash = sha256_text(prev_hash + "\n" + canonical_event)
        row = {
            "args_sha256": event["args_sha256"],
            "event": event,
            "event_hash": event_hash,
            "prev_hash": prev_hash,
            "seq": seq + 1,
            "timestamp": timestamp,
            "tool": event["tool"],
        }
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        local_head.write_text(event_hash + "\n", encoding="utf-8")
        mirror_head.write_text(event_hash + "\n", encoding="utf-8")
        write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
        return 0
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def append_tool_call_after_verified(project_root: Path, home: Path, session_id: str, tool_name: str, tool_input: dict) -> int:
    if not session_id:
        return 0

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = read_head(local_head) or ZERO_HASH
    seq = 0
    cached = read_verify_state(verify_state)
    if cached is not None and cached[0] == prev_hash:
        seq = cached[2]
    elif history_file.is_file():
        try:
            with history_file.open("rb") as handle:
                seq = sum(1 for line in handle if line.strip())
        except OSError:
            seq = 0

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args_json = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event = {
        "args_sha256": sha256_text(args_json),
        "timestamp": timestamp,
        "tool": tool_name or "unknown",
        "type": "tool_call",
    }
    canonical_event = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_hash = sha256_text(prev_hash + "\n" + canonical_event)
    row = {
        "args_sha256": event["args_sha256"],
        "event": event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "seq": seq + 1,
        "timestamp": timestamp,
        "tool": event["tool"],
    }
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
    return 0


def load_history_events(project_root: Path, session_id: str, cache: Dict) -> List[dict]:
    if "history_events" in cache:
        return cache["history_events"]
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        cache["history_events"] = []
        return cache["history_events"]
    history_file = project_root / ".gran-maestro" / "sessions" / clean_sid / "history.ndjson"
    rows: List[dict] = []
    if history_file.is_file():
        for line in history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            item = row.get("event", row)
            if isinstance(item, dict):
                rows.append(item)
    cache["history_events"] = rows
    return rows


def get_arg(tool_input: dict, key: str) -> str:
    value = tool_input.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arg_pattern(tool_input: dict, key: str, op: str, value) -> bool:
    observed = get_arg(tool_input, str(key or ""))
    if op == "equals":
        return observed == str(value)
    if op == "contains":
        return str(value) in observed
    if op == "regex":
        return re.search(str(value), observed) is not None
    if op == "in":
        return observed in [str(item) for item in value] if isinstance(value, list) else False
    return False


def match_object(row: dict, expected) -> bool:
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


def evaluate_policy(project_root: Path, home: Path, payload: dict) -> int:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    policy_dir = home / ".claude" / "gran-maestro-policy" / "projects" / project_key(project_root)
    manifest = policy_dir / "manifest.json"
    if not manifest.is_file():
        return 0

    cache_path = policy_dir / ".rule-engine-cache.json"

    def fingerprint(path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"

    def verified_rule_files():
        try:
            manifest_bytes = manifest.read_bytes()
            manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
        except Exception:
            stderr(f"[policy-block] manifest_invalid file={manifest}")
            raise SystemExit(2)
        if not isinstance(manifest_payload, dict) or manifest_payload.get("version") != 1 or not isinstance(manifest_payload.get("rules"), list):
            stderr(f"[policy-block] manifest_invalid file={manifest}")
            raise SystemExit(2)
        verified_files = []
        aggregate = hashlib.sha256()
        for item in manifest_payload.get("rules", []):
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "")
            expected_hash = str(item.get("sha256") or "")
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                stderr(f"[policy-block] manifest_path_invalid file={manifest} path={rel}")
                raise SystemExit(2)
            rule_path = policy_dir / rel
            if not rule_path.is_file():
                stderr(f"[policy-block] manifest_rule_missing file={rel}")
                raise SystemExit(2)
            actual_hash = hashlib.sha256(rule_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                stderr(f"[policy-block] manifest_sha256_mismatch file={rel} expected={expected_hash} actual={actual_hash}")
                raise SystemExit(2)
            aggregate.update(rel.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(actual_hash.encode("ascii"))
            aggregate.update(b"\n")
            verified_files.append(
                {
                    "path": rel,
                    "sha256": actual_hash,
                    "rule_path": rule_path,
                }
            )
        return {
            "manifest_fingerprint": fingerprint(manifest),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "rule_content_aggregate_sha256": aggregate.hexdigest(),
            "rule_count": len(verified_files),
            "files": verified_files,
        }

    def cache_valid(verification: dict):
        if not cache_path.is_file():
            return None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(cached, dict):
            return None
        if cached.get("manifest_fingerprint") != verification["manifest_fingerprint"]:
            return None
        if cached.get("manifest_sha256") != verification["manifest_sha256"]:
            return None
        if cached.get("rule_content_aggregate_sha256") != verification["rule_content_aggregate_sha256"]:
            return None
        if cached.get("rule_count") != verification["rule_count"]:
            return None
        files = cached.get("files")
        rules = cached.get("rules")
        if not isinstance(files, list) or not isinstance(rules, list):
            return None
        if cached.get("predicates_validated") is not True:
            return None
        cached_paths = [str(item.get("path") or "") for item in files if isinstance(item, dict)]
        verified_paths = [str(item["path"]) for item in verification["files"]]
        if cached_paths != verified_paths:
            return None
        return rules

    def unknown_predicate(rule_id: str, name: str) -> None:
        stderr(f"[policy-block] unknown_predicate rule={rule_id} predicate={name}")

    def validate_predicates(rule_id: str, condition) -> bool:
        if not isinstance(condition, dict):
            return True
        if "predicate" in condition:
            name = str(condition.get("predicate") or "")
            if name not in ALLOWLIST:
                unknown_predicate(rule_id, name)
                return False
        for key in ("all", "any"):
            predicates = condition.get(key)
            if isinstance(predicates, list):
                for item in predicates:
                    if not validate_predicates(rule_id, item):
                        return False
        return True

    verification = verified_rule_files()
    verified_files = verification["files"]
    compiled_rules = cache_valid(verification)
    if compiled_rules is None:
        compiled_rules = []
        for item in verified_files:
            rule_path = item["rule_path"]
            try:
                rule_payload = json.loads(rule_path.read_text(encoding="utf-8"))
            except Exception as exc:
                stderr(f"[policy-warning] rule_file_invalid file={rule_path.name} error={exc}")
                continue
            for rule in rule_payload.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                compiled_rules.append(
                    {
                        "id": str(rule.get("id") or rule_path.name),
                        "trigger": rule.get("trigger"),
                        "condition": rule.get("condition"),
                        "action": rule.get("action"),
                        "severity": rule.get("severity"),
                        "message": rule.get("message"),
                    }
                )
        for rule in compiled_rules:
            rule_id = str(rule.get("id") or "rule")
            if not validate_predicates(rule_id, rule.get("condition")):
                return 2
        tmp_path = Path(str(cache_path) + ".tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "manifest_fingerprint": verification["manifest_fingerprint"],
                    "manifest_sha256": verification["manifest_sha256"],
                    "rule_content_aggregate_sha256": verification["rule_content_aggregate_sha256"],
                    "rule_count": verification["rule_count"],
                    "files": [
                        {
                            "path": item["path"],
                            "sha256": item["sha256"],
                        }
                        for item in verified_files
                    ],
                    "predicates_validated": True,
                    "rules": compiled_rules,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)

    history_cache: dict = {}
    unknown_predicate_seen = False

    def path_protected(path_glob: str) -> bool:
        candidate = get_arg(tool_input, "file_path") or get_arg(tool_input, "path") or get_arg(tool_input, "command")
        expanded = candidate.replace("~", str(home), 1) if candidate.startswith("~") else candidate
        return fnmatch.fnmatch(expanded, str(path_glob)) or fnmatch.fnmatch(candidate, str(path_glob))

    def history_exists(type_filter) -> bool:
        return any(match_object(row, type_filter) for row in load_history_events(project_root, str(payload.get("session_id") or ""), history_cache))

    def history_not_exists_after(anchor, target) -> bool:
        rows = load_history_events(project_root, str(payload.get("session_id") or ""), history_cache)
        anchor_index = -1
        for index, row in enumerate(rows):
            if match_object(row, anchor):
                anchor_index = index
        if anchor_index < 0:
            return False
        return not any(match_object(row, target) for row in rows[anchor_index + 1 :])

    def eval_predicate(rule_id: str, predicate) -> bool:
        nonlocal unknown_predicate_seen
        if not isinstance(predicate, dict):
            return True
        if "predicate" in predicate:
            name = str(predicate.get("predicate") or "")
            if name not in ALLOWLIST:
                unknown_predicate(rule_id, name)
                raise SystemExit(2)
            if name == "tool_match":
                return tool_name == predicate.get("name")
            if name == "arg_pattern":
                return arg_pattern(tool_input, predicate.get("key"), predicate.get("op"), predicate.get("value"))
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
                payload_value = history.get("not_exists_after")
                if isinstance(payload_value, dict):
                    return history_not_exists_after(payload_value.get("anchor"), payload_value.get("target"))
        return True

    def trigger_matches(trigger) -> bool:
        if not isinstance(trigger, dict):
            return True
        tool = trigger.get("tool")
        if isinstance(tool, str) and tool and tool_name != tool:
            return False
        args = trigger.get("args")
        if isinstance(args, dict):
            for key, condition in args.items():
                if isinstance(condition, dict):
                    for op, value in condition.items():
                        if not arg_pattern(tool_input, key, op, value):
                            return False
                elif get_arg(tool_input, key) != str(condition):
                    return False
        return True

    def condition_matches(rule_id: str, condition) -> bool:
        if not isinstance(condition, dict):
            return True
        if "all" in condition:
            return all(eval_predicate(rule_id, item) for item in condition.get("all", []))
        if "any" in condition:
            return any(eval_predicate(rule_id, item) for item in condition.get("any", []))
        return eval_predicate(rule_id, condition)

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
            stderr(f"[policy-block] rule={rule_id} {message}")
            return 2
        if decision == "warn":
            stderr(f"[policy-warning] rule={rule_id} {message}")
    if unknown_predicate_seen:
        stderr("[policy-block] unknown_predicate fail_closed")
        return 2
    return 0


def hardcoded_core_check(project_root: Path, home: Path, payload: dict) -> int:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    raw_file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    command = str(tool_input.get("command") or "")
    file_path = normalize_path(raw_file_path, project_root, home)
    policy_root = str(home / ".claude" / "gran-maestro-policy")
    sessions_root = str(project_root / ".gran-maestro" / "sessions")

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/"):
        if "/rules.d/" in file_path or file_path.endswith("/manifest.json"):
            return block("core-block", "META-BYPASS-RULE-FILE", "정책 디렉토리는 LLM이 수정할 수 없습니다.")
        return block("core-block", "META-BYPASS-POLICY-DIR", "정책 디렉토리는 LLM이 수정할 수 없습니다.")

    if tool_name == "Bash" and is_mutating_command(command):
        if ".claude/gran-maestro-policy" in command or policy_root in command:
            if "/ledger-heads/" in command:
                return block("core-block", "META-BYPASS-LEDGER-SENTINEL", "ledger sentinel은 LLM이 직접 수정할 수 없습니다.")
            if "/rules.d/" in command or "manifest.json" in command:
                return block("core-block", "META-BYPASS-RULE-FILE", "정책 디렉토리는 LLM이 수정할 수 없습니다.")
            return block("core-block", "META-BYPASS-POLICY-DIR", "정책 디렉토리는 LLM이 수정할 수 없습니다.")

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.ndjson"):
        return block("core-block", "META-BYPASS-HISTORY-NDJSON", "history.ndjson은 LLM이 직접 수정할 수 없습니다.")

    if tool_name == "Bash" and is_mutating_command(command):
        if ".gran-maestro/sessions/" in command and "history.ndjson" in command:
            return block("core-block", "META-BYPASS-HISTORY-NDJSON", "history.ndjson은 LLM이 직접 수정할 수 없습니다.")
        if ".gran-maestro/sessions/" in command and (
            "history.head" in command or "history.verify" in command
        ):
            return block("core-block", "META-BYPASS-LEDGER-SENTINEL", "ledger sentinel은 LLM이 직접 수정할 수 없습니다.")
        if ".gran-maestro/sessions/" in command and SESSION_RENAME_RE.search(command):
            return block("core-block", "META-BYPASS-SESSION-ID-FORGERY", "session_id 디렉토리는 LLM이 직접 생성하거나 이름 변경할 수 없습니다.")

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.head"):
        return block("core-block", "META-BYPASS-LEDGER-SENTINEL", "ledger sentinel은 LLM이 직접 수정할 수 없습니다.")

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/ledger-heads/"):
        return block("core-block", "META-BYPASS-LEDGER-SENTINEL", "ledger sentinel은 LLM이 직접 수정할 수 없습니다.")

    return 0


def main() -> int:
    if len(sys.argv) != 2:
        stderr("usage: pre_tool_use_fast.py <project_root>")
        return 2

    project_root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get("HOME") or Path.home())
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    session_id = str(payload.get("session_id") or "").strip()
    clean_sid = ""
    lock_dir: Optional[Path] = None
    if session_id:
        clean_sid = sanitize_session_id(session_id)
        if clean_sid is None:
            stderr("history ledger mismatch: invalid session_id")
            return 2
        history_file, _, _, _ = history_paths(project_root, home, clean_sid)
        session_dir = history_file.parent
        lock_dir = session_dir / "history.lock"
        session_dir.mkdir(parents=True, exist_ok=True)
        if not acquire_lock(lock_dir):
            stderr("history ledger mismatch: lock timeout")
            return 2
        ok, _, _ = verify_history(project_root, home, clean_sid)
        if not ok:
            try:
                lock_dir.rmdir()
            except OSError:
                pass
            lock_dir = None
            return 2
        warn_session_id_mismatch_once_if_any(project_root, payload, raw, clean_sid)

    try:
        status = hardcoded_core_check(project_root, home, payload)
        if status:
            return status

        status = evaluate_policy(project_root, home, payload)
        if status:
            return status

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        if clean_sid:
            return append_tool_call_after_verified(
                project_root,
                home,
                clean_sid,
                str(payload.get("tool_name") or "").strip() or "unknown",
                tool_input,
            )
        return append_tool_call(
            project_root,
            home,
            session_id,
            str(payload.get("tool_name") or "").strip() or "unknown",
            tool_input,
        )
    finally:
        if lock_dir is not None:
            try:
                lock_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
