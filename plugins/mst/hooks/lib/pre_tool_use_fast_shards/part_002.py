def is_phase_readonly_git(args: List[str]) -> bool:
    if not args:
        return False
    subcommand = args[0]
    if subcommand not in PHASE_READONLY_GIT_COMMANDS:
        return False
    if subcommand == "branch":
        allowed_flags = {
            "-a",
            "-r",
            "-v",
            "-vv",
            "--all",
            "--remotes",
            "--verbose",
            "--list",
            "--show-current",
            "--contains",
            "--merged",
            "--no-merged",
            "--points-at",
        }
        for arg in args[1:]:
            if arg.startswith("--format"):
                continue
            if arg.startswith("-") and arg in allowed_flags:
                continue
            return False
        return True
    if subcommand == "diff":
        return not any(arg == "--output" or arg.startswith("--output=") for arg in args[1:])
    return True
def is_phase_readonly_find(args: List[str]) -> bool:
    return not any(arg in PHASE_FIND_MUTATING_OPTIONS for arg in args)
def is_phase_readonly_python(args: List[str]) -> bool:
    if not args:
        return False
    if args in (["-V"], ["--version"]):
        return True
    if args[:2] == ["-m", "py_compile"] and len(args) > 2:
        return True
    for index, arg in enumerate(args):
        if arg in {"-c", "--command"}:
            if index + 1 >= len(args):
                return False
            return PHASE_MUTATING_PYTHON_RE.search(args[index + 1]) is None
    return False
def is_phase_readonly_interpreter(args: List[str], mutating_re: re.Pattern) -> bool:
    if not args:
        return False
    if args in (["-v"], ["--version"]):
        return True
    for index, arg in enumerate(args):
        if arg == "-e":
            if index + 1 >= len(args):
                return False
            return mutating_re.search(args[index + 1]) is None
    return False
def is_phase_readonly_shell_wrapper(args: List[str]) -> bool:
    for index, arg in enumerate(args):
        if arg == "-c" or (arg.startswith("-") and "c" in arg[1:]):
            if index + 1 >= len(args):
                return False
            return not is_phase_gate_mutating_command(args[index + 1])
    return False
def is_phase_readonly_segment(segment: List[str]) -> bool:
    command, args = phase_effective_command(segment)
    if not command:
        return True
    if command in PHASE_READONLY_MST_SKILLS:
        return True
    if command in PHASE_READONLY_COMMANDS:
        return True
    if command == "find":
        return is_phase_readonly_find(args)
    if command == "git":
        return is_phase_readonly_git(args)
    if is_python_token(command):
        return is_phase_readonly_python(args)
    if is_ruby_token(command):
        return is_phase_readonly_interpreter(args, PHASE_MUTATING_RUBY_RE)
    if is_node_token(command):
        return is_phase_readonly_interpreter(args, PHASE_MUTATING_NODE_RE)
    if is_shell_wrapper_token(command):
        return is_phase_readonly_shell_wrapper(args)
    return False
def is_phase_gate_mutating_command(command: str) -> bool:
    tokens = shell_tokens_with_operators(command)
    if not tokens:
        return False
    segments = split_phase_shell_segments(tokens)
    if segments is None:
        return True
    return any(not is_phase_readonly_segment(segment) for segment in segments)
def project_key(project_root: Path) -> str:
    return sha256_text(os.path.realpath(project_root))[:16]
def policy_home(home: Path) -> Path:
    raw = os.environ.get("MST_POLICY_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return home / ".claude" / "gran-maestro-policy"
def allowlist_path(home: Path) -> Path:
    return policy_home(home) / "allowlist.json"
def parse_allowlist_expiry(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
def allowlist_target(tool_input: dict) -> str:
    for key in ("command", "file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
def protected_allowlist_target(tool_input: dict) -> str:
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
def is_protected_target(target_path: str) -> bool:
    if not target_path:
        return False
    expanded_target = os.path.expanduser(target_path)
    target_abs = os.path.abspath(expanded_target)
    for pattern in PROTECTED_PATH_PATTERNS:
        expanded_pattern = os.path.expanduser(pattern)
        pattern_abs = os.path.abspath(expanded_pattern)
        if (
            fnmatch.fnmatch(target_abs, pattern_abs)
            or fnmatch.fnmatch(expanded_target, expanded_pattern)
            or fnmatch.fnmatch(target_path, pattern)
        ):
            return True
    return False
def check_allowlist(home: Path, tool_name: str, tool_input: dict) -> bool:
    if tool_name in ALLOWLIST_PROTECTED_TARGET_TOOLS and is_protected_target(
        protected_allowlist_target(tool_input)
    ):
        return False

    path = allowlist_path(home)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    now = datetime.now(timezone.utc)
    target = allowlist_target(tool_input)
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("tool") != tool_name:
            continue
        expires_at = entry.get("expires_at")
        if expires_at:
            expiry = parse_allowlist_expiry(expires_at)
            if expiry is None or now >= expiry:
                continue
        if fnmatch.fnmatch(target, str(entry.get("args_pattern") or "*")):
            return True
    return False
def history_paths(project_root: Path, home: Path, session_id: str) -> Tuple[Path, Path, Path, Path]:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = policy_home(home) / "ledger-heads" / f"{session_id}.head"
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

    if not has_entries:
        if local_value is not None and local_value != ZERO_HASH:
            stderr("history ledger mismatch: self-heal failed: ndjson empty but heads non-zero (rotation suspected)")
            return False, None, 0
        if mirror_value is not None and mirror_value != ZERO_HASH:
            stderr("history ledger mismatch: self-heal failed: ndjson empty but heads non-zero (rotation suspected)")
            return False, None, 0

    if has_entries and local_value is None:
        stderr("history ledger mismatch: missing history.head")
        return False, None, 0
    if has_entries and mirror_value is None:
        stderr("history ledger mismatch: missing home mirror head")
        return False, None, 0
    if has_entries and local_value == ZERO_HASH:
        stderr("history ledger mismatch: history.head")
        return False, None, 0
    if has_entries and mirror_value == ZERO_HASH:
        stderr("history ledger mismatch: home mirror head")
        return False, None, 0

    def head_within_ndjson(head: Optional[str]) -> bool:
        if head is None or head == last_hash or head == ZERO_HASH:
            return True
        if not history_file.is_file():
            return False
        with history_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict) and row.get("event_hash") == head:
                    return True
        return False

    if local_value is not None and not head_within_ndjson(local_value):
        stderr("history ledger mismatch: self-heal failed: head ahead of ndjson last_hash")
        return False, None, 0
    if mirror_value is not None and not head_within_ndjson(mirror_value):
        stderr("history ledger mismatch: self-heal failed: head ahead of ndjson last_hash")
        return False, None, 0

    if last_hash != ZERO_HASH and (
        (local_value is not None and local_value != last_hash)
        or (mirror_value is not None and mirror_value != last_hash)
    ):
        if verify_state.exists():
            if local_value != last_hash:
                stderr("history ledger mismatch: history.head")
                return False, None, 0
            stderr("history ledger mismatch: home mirror head")
            return False, None, 0
        prev_local = local_value or ZERO_HASH
        prev_mirror = mirror_value or ZERO_HASH
        targets = []

        def atomic_write_head(path: Path, value: str) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(f"{path}.tmp.{os.getpid()}")
            tmp_path.write_text(value + "\n", encoding="utf-8")
            os.replace(tmp_path, path)

        if mirror_value != last_hash:
            atomic_write_head(mirror_head, last_hash)
            targets.append("mirror")
        if local_value != last_hash:
            atomic_write_head(local_head, last_hash)
            targets.append("local")
        stderr(
            f"[mst-history-self-heal] session={session_id} restored={last_hash[:12]} "
            f"targets={','.join(targets)} prev_local={prev_local[:12]} prev_mirror={prev_mirror[:12]}"
        )

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
def inspect_hot_path_history_cursor(project_root: Path, home: Path, session_id: str) -> Tuple[bool, Optional[str], int, str]:
    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    cached = read_verify_state(verify_state)
    if cached is None:
        return False, None, 0, "missing history.verify cursor"

    cached_head, cached_fingerprint, cached_seq = cached
    if not cached_head or len(cached_head) != 64:
        return False, None, 0, "invalid history.verify cursor head"

    local_value = read_head(local_head)
    mirror_value = read_head(mirror_head)
    if not local_value:
        return False, None, 0, "missing history.head"
    if not mirror_value:
        return False, None, 0, "missing home mirror head"
    if local_value != mirror_value:
        return False, None, 0, "local and mirror history heads differ"
    if local_value != cached_head:
        return False, None, 0, "history.verify cursor does not match current head"

    current_fingerprint = file_fingerprint(history_file)
    if current_fingerprint != cached_fingerprint:
        return False, None, 0, "history.verify cursor fingerprint is stale"
    if current_fingerprint != "missing":
        tail_hash = last_event_hash(history_file)
        if tail_hash != cached_head:
            return False, None, 0, "history.verify cursor does not match ledger tail"
    elif cached_head != ZERO_HASH:
        return False, None, 0, "history.verify cursor points to a missing ledger"

    return True, cached_head, cached_seq, ""
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
def history_has_idempotency_key(history_file: Path, idempotency_key: str) -> bool:
    if not idempotency_key or not history_file.is_file():
        return False
    try:
        lines = history_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        event = row.get("event") if isinstance(row, dict) else None
        if isinstance(event, dict) and event.get("idempotency_key") == idempotency_key:
            return True
    return False
def build_history_row(event: dict, prev_hash: str, seq: int, session_id: str) -> Tuple[dict, str]:
    stamped_event = dict(event)
    parts = session_id.rsplit("-", 2)
    if len(parts) != 3 or not parts[0].startswith("MST-"):
        raise ValueError("history ledger mismatch: invalid structured mst_session_id")
    root_mst_id = parts[0][4:]
    stamped_event.pop("session_id", None)
    stamped_event["mst_session_id"] = session_id
    existing_root = stamped_event.get("root_mst_id")
    if existing_root is not None and existing_root != root_mst_id:
        raise ValueError("history ledger mismatch: root_mst_id")
    stamped_event["root_mst_id"] = root_mst_id
    existing_schema = stamped_event.get("schema_version")
    if existing_schema is not None and existing_schema != 1:
        raise ValueError("history ledger mismatch: schema_version")
    stamped_event["schema_version"] = 1
    event_type = stamped_event.get("event_type") or stamped_event.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("history ledger mismatch: event_type")
    stamped_event["event_type"] = event_type.strip()
    created_at = stamped_event.get("created_at") or stamped_event.get("timestamp")
    if not isinstance(created_at, str) or not created_at.strip():
        created_at = format_utc(utc_now())
    stamped_event["created_at"] = created_at.strip()
    idempotency_key = stamped_event.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        stable_event = {
            key: value
            for key, value in stamped_event.items()
            if key not in {"timestamp", "created_at", "idempotency_key"}
        }
        stable_json = canonical_json(stable_event)
        idempotency_key = f"{session_id}:{stamped_event['event_type']}:{sha256_text(stable_json)}"
    stamped_event["idempotency_key"] = idempotency_key.strip()
    canonical_event = canonical_json(stamped_event)
    event_hash = sha256_text(prev_hash + "\n" + canonical_event)
    row = {
        "event": stamped_event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "seq": seq,
        "mst_session_id": session_id,
    }
    for key in (
        "schema_version",
        "root_mst_id",
        "event_type",
        "created_at",
        "idempotency_key",
        "tool",
        "args_sha256",
        "timestamp",
    ):
        if key in stamped_event:
            row[key] = stamped_event[key]
    return row, event_hash
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
        try:
            row, event_hash = build_history_row(event, prev_hash, seq + 1, clean_sid)
        except ValueError as exc:
            stderr(str(exc))
            return 2
        if history_has_idempotency_key(history_file, str(row.get("idempotency_key") or "")):
            return 0
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(row) + "\n")
        mirror_head.write_text(event_hash + "\n", encoding="utf-8")
        local_head.write_text(event_hash + "\n", encoding="utf-8")
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
    history_file.parent.mkdir(parents=True, exist_ok=True)
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
    try:
        row, event_hash = build_history_row(event, prev_hash, seq + 1, session_id)
    except ValueError as exc:
        stderr(str(exc))
        return 2
    if history_has_idempotency_key(history_file, str(row.get("idempotency_key") or "")):
        return 0
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(row) + "\n")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
    return 0
def append_event_after_verified(project_root: Path, home: Path, session_id: str, event: dict) -> int:
    if not session_id:
        return 0

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    history_file.parent.mkdir(parents=True, exist_ok=True)
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

    try:
        row, event_hash = build_history_row(event, prev_hash, seq + 1, session_id)
    except ValueError as exc:
        stderr(str(exc))
        return 2
    if history_has_idempotency_key(history_file, str(row.get("idempotency_key") or "")):
        return 0
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(row) + "\n")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
    return 0
def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def parse_utc(value: str) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
def workflow_state_file(project_root: Path, payload: Optional[dict] = None) -> Optional[Path]:
    session_id = canonical_mst_session_id_from_payload(payload or {})
    clean_sid = sanitize_session_id(session_id) if session_id else None
    if not clean_sid:
        return None
    return project_root / ".gran-maestro" / "tmp" / f"mst-state-{clean_sid}.json"
def load_workflow_state(project_root: Path, payload: Optional[dict] = None) -> Optional[dict]:
    path = workflow_state_file(project_root, payload)
    if path is None:
        return None
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
def schedule_wakeup_block_active(project_root: Path, payload: Optional[dict] = None, now: Optional[datetime] = None) -> bool:
    payload = load_workflow_state(project_root, payload)
    if not isinstance(payload, dict):
        return False

    now = now or utc_now()
    updated_at = parse_utc(payload.get("updated_at"))
    if updated_at is not None and (now - updated_at).total_seconds() > SCHEDULE_WAKEUP_STATE_TTL_SECONDS:
        return False

    if payload.get("workflow_active") is True:
        return True

    last_active_at = parse_utc(payload.get("last_active_at"))
    if last_active_at is None:
        return False
    return (now - last_active_at).total_seconds() <= SCHEDULE_WAKEUP_GRACE_SECONDS
def pending_confirm_ttl() -> int:
    raw = os.environ.get("MST_PENDING_CONFIRM_TTL_SECONDS") or os.environ.get("MST_CONFIRM_TTL_SECONDS") or "86400"
    try:
        value = int(raw)
    except ValueError:
        return 86400
    return value if value > 0 else 86400
def pending_confirm_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "sessions" / session_id / "pending-confirm.json"
def read_pending_confirm(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
