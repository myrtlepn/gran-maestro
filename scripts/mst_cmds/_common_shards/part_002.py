def _validate_enqueue_entry(entry: dict) -> None:
    """auto=true인 entry가 args에 -a/--auto 토큰을 포함하는지 검증."""
    if not isinstance(entry, dict):
        return
    auto = bool(entry.get("auto", False))
    if not auto:
        return
    args = entry.get("args", "") or ""
    if not isinstance(args, str):
        args = str(args)
    tokens = args.split()
    if "-a" in tokens or "--auto" in tokens:
        return
    raise ValueError(
        "queue_enqueue: auto=true entry는 args에 '-a' 또는 '--auto' 토큰을 포함해야 합니다 "
        f"(skill={entry.get('skill')!r}, args={args!r})"
    )
_WINDOWS_LOCK_BYTES = 0x7FFFFFFF
def _lock_shared(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_RLCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_SH)
def _lock_exclusive(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
def _lock_exclusive_with_timeout(file_obj, timeout_sec: float = 5.0, poll_interval: float = 0.05):
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    if os.name == "nt":
        while True:
            try:
                file_obj.seek(0)
                msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, _WINDOWS_LOCK_BYTES)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"lock timeout ({timeout_sec}s) - another session is writing")
                time.sleep(poll_interval)

    while True:
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (BlockingIOError, OSError) as exc:
            if isinstance(exc, OSError) and exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock timeout ({timeout_sec}s) - another session is writing")
            time.sleep(poll_interval)
def _unlock(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
def _queue_read_entries() -> list[dict]:
    path = _queue_path()
    if not path.exists():
        return []

    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_shared(lock_f)
        try:
            if not path.exists():
                return []
            with open(path, "r", encoding="utf-8") as f:
                return _queue_parse_entries(f.read().splitlines())
        finally:
            _unlock(lock_f)
def _queue_compact(mutator):
    path = _queue_path()
    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_exclusive(lock_f)
        try:
            if not path.exists():
                new_entries, result = mutator([])
                if new_entries:
                    tmp_name = None
                    try:
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w",
                            encoding="utf-8",
                            delete=False,
                            dir=str(path.parent),
                            prefix=".pending.",
                            suffix=".tmp",
                        )
                        tmp_name = tmp.name
                        for entry in new_entries:
                            tmp.write(_compact_json(entry) + "\n")
                        tmp.flush()
                        os.fsync(tmp.fileno())
                        tmp.close()
                        os.replace(tmp_name, path)
                    except Exception:
                        if tmp_name:
                            try:
                                os.unlink(tmp_name)
                            except OSError:
                                pass
                        raise
                return result

            with open(path, "r", encoding="utf-8") as f:
                entries = _queue_parse_entries(f.read().splitlines())
            new_entries, result = mutator(entries)

            tmp_name = None
            try:
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                    dir=str(path.parent),
                    prefix=".pending.",
                    suffix=".tmp",
                )
                tmp_name = tmp.name
                for entry in new_entries:
                    tmp.write(_compact_json(entry) + "\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp_name, path)
            except Exception:
                if tmp_name:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                raise
            return result
        finally:
            _unlock(lock_f)
def queue_enqueue(data: dict) -> dict:
    _validate_enqueue_entry(data)
    entry = _queue_build_entry(data)
    path = _queue_path()
    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    line = _compact_json(entry) + "\n"

    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_exclusive(lock_f)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            _unlock(lock_f)

    return entry
def _build_reconcile_phase2_action(req_id: str, attempt: dict, *, source: str) -> dict:
    return {
        "kind": "reconcile_phase2",
        "req_id": req_id,
        "attempt_id": str(attempt.get("attempt_id") or "").strip(),
        "created_at": _queue_timestamp(),
        "source": source,
        "status": "queued",
        "task_num": _normalize_task_num(attempt.get("task_num")),
        "task_id": str(attempt.get("task_id") or "").strip(),
        "log_path": str(attempt.get("log_path") or "").strip(),
        "worktree_path": str(attempt.get("worktree_path") or "").strip(),
    }
def upsert_reconcile_phase2_action(req_id: str, *, attempt: dict | None = None, **kwargs) -> dict:
    normalized_req_id = _normalize_request_id(req_id)
    attempt_data = dict(attempt or {})
    for key, value in kwargs.items():
        if key not in attempt_data and value is not None:
            attempt_data[key] = value

    required_fields = ("task_num", "task_id", "attempt_id", "log_path", "worktree_path")
    missing_fields = [
        field for field in required_fields if not str(attempt_data.get(field) or "").strip()
    ]
    if missing_fields:
        return {
            "created": False,
            "noop": True,
            "kind": "reconcile_phase2",
            "req_id": normalized_req_id,
            "attempt_id": str(attempt_data.get("attempt_id") or "").strip(),
            "manual_reconcile_required": True,
            "reason": f"missing_reconcile_action_fields:{','.join(missing_fields)}",
            "action": None,
        }

    action = _build_reconcile_phase2_action(
        normalized_req_id,
        attempt_data,
        source=str(attempt_data.get("source") or "phase2_dispatch").strip() or "phase2_dispatch",
    )
    terminal_statuses = {"done", "cancelled", "blocked", "version_skew_blocked"}

    path = _queue_path()
    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    line = _compact_json(action) + "\n"

    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_exclusive(lock_f)
        try:
            existing_entries: list[dict] = []
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    for raw_line in f.read().splitlines():
                        text = raw_line.strip()
                        if not text:
                            continue
                        try:
                            value = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(value, dict):
                            existing_entries.append(value)

            for existing_entry in existing_entries:
                if str(existing_entry.get("kind") or "").strip() != "reconcile_phase2":
                    continue
                if str(existing_entry.get("req_id") or "").strip().upper() != normalized_req_id:
                    continue
                if str(existing_entry.get("attempt_id") or "").strip() != action["attempt_id"]:
                    continue

                existing_status = str(existing_entry.get("status") or "").strip().lower()
                if existing_status in {"queued", "running"}:
                    return {
                        "created": False,
                        "noop": True,
                        "kind": "reconcile_phase2",
                        "req_id": normalized_req_id,
                        "attempt_id": action["attempt_id"],
                        "reason": f"existing_reconcile_phase2_{existing_status}",
                        "action": copy.deepcopy(existing_entry),
                    }
                if existing_status in terminal_statuses:
                    return {
                        "created": False,
                        "noop": True,
                        "kind": "reconcile_phase2",
                        "req_id": normalized_req_id,
                        "attempt_id": action["attempt_id"],
                        "manual_reconcile_required": existing_status in {
                            "blocked",
                            "version_skew_blocked",
                        },
                        "reason": f"existing_reconcile_phase2_{existing_status}",
                        "action": copy.deepcopy(existing_entry),
                    }

            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            _unlock(lock_f)

    return {
        "created": True,
        "noop": False,
        "kind": "reconcile_phase2",
        "req_id": normalized_req_id,
        "attempt_id": action["attempt_id"],
        "reason": None,
        "action": copy.deepcopy(action),
    }
def queue_reconcile_phase2_action(req_id: str, *, attempt: dict | None = None, **kwargs) -> dict:
    return upsert_reconcile_phase2_action(req_id, attempt=attempt, **kwargs)
def ensure_reconcile_phase2_action(req_id: str, *, attempt: dict | None = None, **kwargs) -> dict:
    return upsert_reconcile_phase2_action(req_id, attempt=attempt, **kwargs)
def _task_level_phase2_attempts(request_data: dict) -> list[dict]:
    tasks = request_data.get("tasks")
    if not isinstance(tasks, list):
        return []

    attempts: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_attempts = task.get("attempts")
        if not isinstance(task_attempts, list):
            continue
        for attempt in task_attempts:
            if not isinstance(attempt, dict):
                continue
            normalized_attempt = dict(attempt)
            if not normalized_attempt.get("task_num"):
                task_identity = task.get("task_num")
                if task_identity is None:
                    task_identity = task.get("id")
                if task_identity is not None:
                    normalized_attempt["task_num"] = task_identity
            attempts.append(normalized_attempt)
    return attempts
def _phase2_reconcile_attempts(request_data: dict) -> list[dict]:
    attempts_by_id: dict[str, dict] = {}
    ordered_ids: list[str] = []

    for attempt in _task_level_phase2_attempts(request_data):
        attempt_id = str(attempt.get("attempt_id") or "").strip()
        if not attempt_id or attempt_id in attempts_by_id:
            continue
        attempts_by_id[attempt_id] = dict(attempt)
        ordered_ids.append(attempt_id)

    background_attempts = request_data.get("background_task_ids")
    if isinstance(background_attempts, list):
        for attempt in background_attempts:
            if not isinstance(attempt, dict):
                continue
            attempt_id = str(attempt.get("attempt_id") or "").strip()
            if not attempt_id:
                continue
            if attempt_id not in attempts_by_id:
                ordered_ids.append(attempt_id)
            attempts_by_id[attempt_id] = dict(attempt)

    return [attempts_by_id[attempt_id] for attempt_id in ordered_ids]
def ensure_request_phase2_reconcile_actions(
    req_id: str,
    *,
    request_data: dict | None = None,
    source: str = "phase2_continuation",
) -> dict:
    normalized_req_id = _normalize_request_id(req_id)
    data = request_data if isinstance(request_data, dict) else _load_request(normalized_req_id)
    summary = {
        "req_id": normalized_req_id,
        "attempt_count": 0,
        "created_count": 0,
        "noop_count": 0,
        "manual_reconcile_required": False,
        "results": [],
    }
    if not isinstance(data, dict):
        summary["reason"] = "unknown_request"
        return summary

    phase, status = _phase_status_tuple(data)
    if phase != 2 or status.strip().lower() != "phase2_execution":
        summary["reason"] = "not_phase2_execution"
        return summary

    attempts = _phase2_reconcile_attempts(data)
    if not attempts:
        summary["reason"] = "missing_phase2_dispatch_metadata"
        return summary

    for attempt in attempts:
        result = upsert_reconcile_phase2_action(
            normalized_req_id,
            attempt=attempt,
            source=source,
        )
        summary["results"].append(result)
        summary["attempt_count"] += 1
        if result.get("created") is True:
            summary["created_count"] += 1
        if result.get("noop") is True:
            summary["noop_count"] += 1
        if result.get("manual_reconcile_required") is True:
            summary["manual_reconcile_required"] = True

    summary["reason"] = None
    return summary
def queue_peek() -> dict | None:
    for entry in _queue_read_entries():
        if not _is_workflow_queue_entry(entry):
            continue
        if entry.get("status") == "queued":
            return copy.deepcopy(entry)
    return None
def queue_mark_running(entry_id: str) -> dict | None:
    target_entry_id = str(entry_id or "")
    if not target_entry_id:
        return None

    def _mutator(entries):
        for entry in entries:
            if not _is_workflow_queue_entry(entry):
                continue
            if entry.get("entry_id") != target_entry_id:
                continue
            if entry.get("status") != "queued":
                return entries, None
            entry["status"] = "running"
            entry["consumed_at"] = _queue_timestamp()
            return entries, copy.deepcopy(entry)
        return entries, None

    return _queue_compact(_mutator)
def queue_pop() -> dict | None:
    while True:
        peeked = None
        for entry in _queue_read_entries():
            if not _is_workflow_queue_entry(entry):
                continue
            if entry.get("status") == "queued":
                peeked = entry
                break
        if peeked is None:
            return None
        entry_id = peeked.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            continue
        result = queue_mark_running(entry_id)
        if result is not None:
            return result
def queue_list(status: str | None) -> list[dict]:
    entries = [entry for entry in _queue_read_entries() if _is_workflow_queue_entry(entry)]
    if not status or status == "all":
        return entries
    return [entry for entry in entries if entry.get("status") == status]
def queue_complete(action_id: str, result: str | None = None) -> dict | None:
    """Mark queue entry complete by `entry_id` (preferred) or legacy `id`."""
    now = _queue_timestamp()
    warn = None

    def _mutator(entries):
        nonlocal warn
        for entry in entries:
            if not _is_workflow_queue_entry(entry):
                continue
            matches_entry_id = entry.get("entry_id") == action_id
            matches_id = entry.get("id") == action_id
            if not (matches_entry_id or matches_id):
                continue
            status = str(entry.get("status", ""))
            if status in ("done", "failed"):
                warn = f"already terminal: {action_id}"
                return entries, copy.deepcopy(entry)
            entry["status"] = "done"
            entry["completed_at"] = now
            if result is not None:
                entry["result"] = result
            return entries, copy.deepcopy(entry)
        warn = f"action not found: {action_id}"
        return entries, None

    output = _queue_compact(_mutator)
    if warn:
        print(f"[mst] warning: {warn}", file=sys.stderr)
    return output
def queue_fail(action_id: str, error: str | None = None) -> dict | None:
    """Mark queue entry failed by `entry_id` (preferred) or legacy `id`."""
    now = _queue_timestamp()
    warn = None

    def _mutator(entries):
        nonlocal warn
        for entry in entries:
            if not _is_workflow_queue_entry(entry):
                continue
            matches_entry_id = entry.get("entry_id") == action_id
            matches_id = entry.get("id") == action_id
            if not (matches_entry_id or matches_id):
                continue
            status = str(entry.get("status", ""))
            if status in ("done", "failed"):
                warn = f"already terminal: {action_id}"
                return entries, copy.deepcopy(entry)
            entry["status"] = "failed"
            entry["completed_at"] = now
            if error is not None:
                entry["error"] = error
            return entries, copy.deepcopy(entry)
        warn = f"action not found: {action_id}"
        return entries, None

    output = _queue_compact(_mutator)
    if warn:
        print(f"[mst] warning: {warn}", file=sys.stderr)
    return output
def queue_count(status: str = "queued") -> int:
    return len(queue_list(status))
def _create_intent_store():
    try:
        from scripts.intent_store import IntentStoreError, SqliteIntentStore
        store = SqliteIntentStore(BASE_DIR.parent)
    except ImportError as exc:
        print(
            f"Error: intent store dependency missing ({exc}). Install with: pip install pyyaml",
            file=sys.stderr,
        )
        return None, Exception
    except Exception as exc:
        print(f"Error: failed to initialize intent store ({exc})", file=sys.stderr)
        return None, Exception
    return store, IntentStoreError
def fact_checks_dir() -> Path:
    return BASE_DIR / "fact-checks"
def _normalize_fact_check_id(value: str) -> str:
    fc_id = (value or "").strip().upper()
    if not re.fullmatch(r"FC-\d+", fc_id):
        raise ValueError(f"Invalid fact-check id: {value}")
    return fc_id
def _fact_check_path(fc_id: str) -> Path:
    return fact_checks_dir() / fc_id / "fact-check.json"
def _iter_fact_check_paths():
    pattern = str(fact_checks_dir() / "FC-*" / "fact-check.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]
DEFAULT_REFERENCE_KEYWORDS = [
    "library",
    "framework",
    "api",
    "sdk",
    "protocol",
    "version",
    "dependency",
    "react",
    "next.js",
    "typescript",
    "python",
    "node",
    "라이브러리",
    "프레임워크",
    "의존성",
    "버전",
]
DEFAULT_REFERENCE_CONFIG = {
    "cache_ttl_days": 7,
    "cutoff_threshold_months": 1,
    "auto_search": True,
    "max_searches_per_step": 3,
}
def agile_dir() -> Path:
    return BASE_DIR / "agile"
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
def _normalize_agi_id(value: str) -> str:
    agi_id = (value or "").strip().upper()
    if not re.fullmatch(r"AGI-\d+", agi_id):
        raise ValueError(f"Invalid AGI id: {value}")
    return agi_id
def _normalize_link_id(value: str, prefix: str) -> str:
    token = (value or "").strip().upper()
    if not token:
        raise ValueError(f"Invalid {prefix} id: {value}")
    if not token.startswith(f"{prefix}-"):
        raise ValueError(f"Invalid {prefix} id: {value}")
    return token
def _split_csv_values(raw_values) -> List[str]:
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    values = []
    for raw_value in raw_values:
        for token in str(raw_value).split(","):
            cleaned = token.strip()
            if cleaned:
                values.append(cleaned)
    return values
_SOURCE_MAPPING_RE = re.compile(
    r"^<!--\s*source-mapping:\s*original=(?P<original>\S+)\s+sections=\[(?P<sections>.*?)\]\s*-->$"
)
def _parse_source_mapping_sections(raw_sections: str) -> tuple[list[str], list[str]]:
    sections: list[str] = []
    errors: list[str] = []

    for raw_token in str(raw_sections).split(","):
        token = raw_token.strip()
        if not token:
            continue
        if token.startswith(("'", '"')):
            if len(token) < 2 or token[-1] != token[0]:
                errors.append(f"invalid section token: {raw_token.strip()}")
                continue
            token = token[1:-1].strip()
        elif token.endswith(("'", '"')):
            errors.append(f"invalid section token: {raw_token.strip()}")
            continue
        if not token:
            errors.append(f"invalid section token: {raw_token.strip()}")
            continue
        sections.append(token)

    if not sections:
        errors.append("sections list is empty")

    return sections, errors
def parse_source_mapping(text: str) -> dict:
    result = {
        "original": None,
        "sections": [],
        "valid": False,
        "errors": [],
    }
    lines = str(text).splitlines()
    if not lines:
        result["errors"].append("source-mapping metadata is missing in first line")
        return result

    first_line = lines[0].strip()
    if not first_line:
        result["errors"].append("source-mapping metadata is missing in first line")
        return result

    match = _SOURCE_MAPPING_RE.fullmatch(first_line)
    if match is None:
        result["errors"].append("source-mapping metadata is missing or malformed in first line")
        return result

    sections, section_errors = _parse_source_mapping_sections(match.group("sections"))
    if section_errors:
        result["errors"].extend(section_errors)
        return result

    result["original"] = match.group("original")
    result["sections"] = sections
    result["valid"] = True
    return result
def _strip_balanced_quotes(value: str) -> str:
    token = str(value).strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1].strip()
    return token
def _extract_frontmatter_block(content: str) -> dict:
    lines = str(content).splitlines(keepends=True)
    payload = {
        "has_frontmatter": False,
        "frontmatter": "",
        "prefix": "",
        "suffix": str(content),
        "errors": [],
    }
    if not lines:
        return payload

    probe_index = 0
    first_line = lines[0].strip()
    if _SOURCE_MAPPING_RE.fullmatch(first_line):
        probe_index = 1

    while probe_index < len(lines) and not lines[probe_index].strip():
        probe_index += 1

    if probe_index >= len(lines) or lines[probe_index].strip() != "---":
        return payload

    for end_index in range(probe_index + 1, len(lines)):
        if lines[end_index].strip() != "---":
            continue
        payload["has_frontmatter"] = True
        payload["frontmatter"] = "".join(lines[probe_index + 1:end_index])
        payload["prefix"] = "".join(lines[:probe_index])
        payload["suffix"] = "".join(lines[end_index + 1:])
        return payload

    payload["errors"].append("frontmatter block is malformed")
    return payload
def _extract_yaml_scalar(frontmatter: str, key: str):
    pattern = re.compile(rf"(?m)^[ \t]*{re.escape(str(key))}[ \t]*:[ \t]*([^\n\r]*)[ \t]*$")
    match = pattern.search(str(frontmatter))
    if match is None:
        return None
    return _strip_balanced_quotes(match.group(1))
def _extract_yaml_list(frontmatter: str, key: str):
    lines = str(frontmatter).splitlines()
    key_re = re.compile(rf"^(\s*){re.escape(str(key))}\s*:\s*(.*?)\s*$")
    item_re = re.compile(r"^\s*-\s*(.*?)\s*$")

    for index, line in enumerate(lines):
        key_match = key_re.match(line)
        if key_match is None:
            continue

        inline = key_match.group(2).strip()
        if inline:
            if inline.startswith("[") and inline.endswith("]"):
                tokens, token_errors = _parse_source_mapping_sections(inline[1:-1])
                return [] if token_errors else tokens
            parsed = _strip_balanced_quotes(inline)
            return [parsed] if parsed else []

        key_indent = len(key_match.group(1))
        items = []
        probe = index + 1
        while probe < len(lines):
            next_line = lines[probe]
            if not next_line.strip():
                probe += 1
                continue
            leading_spaces = len(next_line) - len(next_line.lstrip(" "))
            if leading_spaces <= key_indent:
                break
            item_match = item_re.match(next_line)
            if item_match is None:
                break
            token = _strip_balanced_quotes(item_match.group(1))
            if token:
                items.append(token)
            probe += 1
        return items
    return None
def _normalize_tbd(value):
    if value is None:
        return "TBD"
    token = str(value).strip()
    if not token or token.upper() == "TBD":
        return "TBD"
    return token
def parse_agile_detail_metadata(content: str) -> dict:
    source_mapping = parse_source_mapping(content)
    frontmatter = _extract_frontmatter_block(content)
    evidence = {}

    artifact_paths = _extract_yaml_list(frontmatter.get("frontmatter"), "artifact_paths")
    entrypoint_path = _extract_yaml_scalar(frontmatter.get("frontmatter"), "entrypoint_path")
    entrypoint = _extract_yaml_scalar(frontmatter.get("frontmatter"), "entrypoint")
    reason = _extract_yaml_scalar(frontmatter.get("frontmatter"), "reason")
    integration_smoke_id = _extract_yaml_scalar(frontmatter.get("frontmatter"), "integration_smoke_id")
    verify_cmd = _extract_yaml_scalar(frontmatter.get("frontmatter"), "verify_cmd")
    expected_signal = _extract_yaml_scalar(frontmatter.get("frontmatter"), "expected_signal")

    has_plan_fields = any(
        field is not None
        for field in (artifact_paths, entrypoint_path, entrypoint, reason)
    )
    has_runtime_fields = any(
        field is not None
        for field in (integration_smoke_id, verify_cmd, expected_signal)
    )

    if has_plan_fields:
        plan = {}
        if artifact_paths is not None:
            plan["artifact_paths"] = artifact_paths
        if entrypoint_path is not None:
            plan["entrypoint_path"] = entrypoint_path
        if entrypoint is not None:
            plan["entrypoint"] = entrypoint
        if reason is not None:
            plan["reason"] = reason
        evidence["plan"] = plan

    if has_runtime_fields:
        runtime = {}
        if integration_smoke_id is not None:
            runtime["integration_smoke_id"] = integration_smoke_id
        if verify_cmd is not None:
            runtime["verify_cmd"] = verify_cmd
        if expected_signal is not None:
            runtime["expected_signal"] = expected_signal
        evidence["runtime"] = runtime

    return {
        "source_mapping": source_mapping,
        "evidence": evidence,
        "has_frontmatter": bool(frontmatter.get("has_frontmatter")),
        "errors": list(frontmatter.get("errors") or []),
    }
def _agi_session_dir(agi_id: str) -> Path:
    return agile_dir() / agi_id
def _agi_session_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "session.json"
def _agi_events_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "events.ndjson"
def _agi_objective_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "objective.md"
def _agi_objective_changelog_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "changelog.ndjson"
def _agi_links_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "index" / "links.json"
def _agile_sprint_log_path() -> Path:
    return agile_dir() / "sprint-log.json"
def _append_agile_sprint_log(entry: dict):
    path = _agile_sprint_log_path()
    existing = load_json(path)
    rows = existing if isinstance(existing, list) else []
    rows.append(entry)
    save_json(path, rows)
def _append_ndjson(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))
        f.write("\n")
def _append_agile_event(agi_id: str, event: str, payload=None):
    event_data = {
        "timestamp": _now_iso(),
        "event": event,
    }
    if isinstance(payload, dict):
        event_data.update(payload)
    _append_ndjson(_agi_events_path(agi_id), event_data)
def _load_agile_session(agi_id: str):
    session_path = _agi_session_path(agi_id)
    data = load_json(session_path)
    if not isinstance(data, dict):
        raise ValueError(f"{agi_id} session not found")
    return data, session_path
def _save_agile_session(agi_id: str, data):
    payload = dict(data)
    payload["id"] = agi_id
    payload["updated_at"] = _now_iso()
    save_json(_agi_session_path(agi_id), payload)
    return payload
class _ObjectiveDodItem(dict):
    """Backward-compatible DoD item mapping.

    `evidence_refs` is now a first-class field, but legacy tests and callers may
    compare against dicts that do not include this key.
    """

    def __eq__(self, other):
        if not isinstance(other, dict):
            return super().__eq__(other)
        left = dict(self)
        right = dict(other)
        if "evidence_refs" not in right:
            left.pop("evidence_refs", None)
        if "evidence_refs" not in left:
            right.pop("evidence_refs", None)
        return left == right
