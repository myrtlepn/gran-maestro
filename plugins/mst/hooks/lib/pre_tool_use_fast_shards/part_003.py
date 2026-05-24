def write_pending_confirm(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp_path = Path(f"{path}.tmp.{os.getpid()}")
    tmp_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
def expire_pending_confirm(project_root: Path, session_id: str, now: datetime) -> None:
    path = pending_confirm_path(project_root, session_id)
    payload = read_pending_confirm(path)
    if not payload or payload.get("consumed") is not False:
        return
    expires_at = parse_utc(str(payload.get("expires_at") or ""))
    if expires_at is None or expires_at > now:
        return
    payload["consumed"] = "expired"
    write_pending_confirm(path, payload)
def request_pending_confirm(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
    rule_id: str,
) -> int:
    now = utc_now()
    path = pending_confirm_path(project_root, session_id)
    args_canonical = tool_input if isinstance(tool_input, dict) else {}
    args_json = canonical_json(args_canonical)
    args_sha256 = sha256_text(args_json)
    existing = read_pending_confirm(path)

    if existing and existing.get("consumed") is False:
        expires_at = parse_utc(str(existing.get("expires_at") or ""))
        if expires_at is not None and expires_at <= now:
            existing["consumed"] = "expired"
            write_pending_confirm(path, existing)
        elif existing.get("tool") == tool_name and existing.get("args_sha256") == args_sha256:
            return 0

    created_at = format_utc(now)
    expires_at = format_utc(now + timedelta(seconds=pending_confirm_ttl()))
    pending_id = f"cf_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(6)}"
    payload = {
        "args_canonical": args_canonical,
        "args_sha256": args_sha256,
        "consumed": False,
        "created_at": created_at,
        "expires_at": expires_at,
        "id": pending_id,
        "tool": tool_name,
    }
    write_pending_confirm(path, payload)
    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "expires_at": expires_at,
            "pending_id": pending_id,
            "rule_id": rule_id,
            "timestamp": created_at,
            "tool": tool_name,
            "type": "confirm_requested",
        },
    )
def has_unconsumed_override_grant(
    project_root: Path,
    session_id: str,
    pending_id: str,
    tool_name: str,
    args_sha256: str,
) -> bool:
    grants = 0
    consumes = 0
    for event in load_history_events(project_root, session_id, {}):
        if (
            event.get("pending_id") == pending_id
            and event.get("tool") == tool_name
            and event.get("args_sha256") == args_sha256
        ):
            if event.get("type") == "override_granted":
                grants += 1
            elif event.get("type") == "override_consumed":
                consumes += 1
    return grants > consumes
def consume_pending_override(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
) -> Optional[int]:
    path = pending_confirm_path(project_root, session_id)
    pending = read_pending_confirm(path)
    if not pending:
        return None

    pending_id = str(pending.get("id") or "")
    pending_tool = str(pending.get("tool") or "")
    pending_args_sha = str(pending.get("args_sha256") or "")
    args_sha256 = sha256_text(canonical_json(tool_input if isinstance(tool_input, dict) else {}))
    if pending_tool == tool_name and pending_args_sha == args_sha256 and pending.get("consumed") is True:
        stderr("[policy-block] reused-grant pending override already consumed")
        return None
    if pending.get("consumed") is not False:
        return None
    if pending_tool != tool_name:
        return None

    if pending_args_sha != args_sha256:
        if has_unconsumed_override_grant(project_root, session_id, pending_id, pending_tool, pending_args_sha):
            stderr("args_sha256 mismatch on subsequent call")
        return None

    if not has_unconsumed_override_grant(project_root, session_id, pending_id, tool_name, args_sha256):
        return None

    timestamp = format_utc(utc_now())
    pending["consumed"] = True
    write_pending_confirm(path, pending)
    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "pending_id": pending_id,
            "timestamp": timestamp,
            "tool": tool_name,
            "type": "override_consumed",
        },
    )
def core_block_event(tool_name: str, tool_input: dict, rule_id: str, reason: str) -> dict:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args_json = canonical_json(tool_input if isinstance(tool_input, dict) else {})
    return {
        "args_sha256": sha256_text(args_json),
        "reason": reason,
        "rule_id": rule_id,
        "timestamp": timestamp,
        "tool": tool_name or "unknown",
        "type": "core_block",
    }
def emit_core_block_and_return(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
    rule_id: str,
    reason: str,
) -> int:
    if session_id:
        append_event_after_verified(
            project_root,
            home,
            session_id,
            core_block_event(tool_name, tool_input, rule_id, reason),
        )
    return block("core-block", rule_id, reason)
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
def load_tail_history_events(project_root: Path, session_id: str, limit: int = 500) -> List[dict]:
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        return []
    history_file = project_root / ".gran-maestro" / "sessions" / clean_sid / "history.ndjson"
    if not history_file.is_file():
        return []
    truncated = False
    try:
        with history_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            offset = min(size, 1024 * 1024)
            truncated = offset < size
            handle.seek(-offset, os.SEEK_END)
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        chunk = history_file.read_text(encoding="utf-8")

    lines = [line for line in chunk.splitlines() if line.strip()]
    if truncated and lines:
        lines = lines[1:]
    rows: List[dict] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        event = row.get("event", row) if isinstance(row, dict) else {}
        if isinstance(event, dict):
            rows.append(event)
    return rows
def payload_scope(project_root: Path, payload: dict, tool_input: dict) -> Tuple[str, str]:
    req_id = ""
    task_id = ""
    for source in (payload, tool_input):
        for key in ("req_id", "request_id", "requestId"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                req_id = value.strip().upper()
                break
        for key in ("task_id", "taskId"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                task_id = value.strip().upper()
                break
    req_id = req_id or str(os.environ.get("MST_REQ_ID") or os.environ.get("REQ_ID") or "").strip().upper()
    task_id = task_id or str(os.environ.get("MST_TASK_ID") or os.environ.get("TASK_ID") or "").strip().upper()

    if not req_id or not task_id:
        match = re.search(r"(REQ-\d+)-(T\d+)", project_root.name, re.IGNORECASE)
        if match:
            req_id = req_id or match.group(1).upper()
            task_id = task_id or match.group(2).upper()
    return req_id, task_id
def event_scope_value(event: dict, *keys: str) -> str:
    for key in keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""
def event_scope_matches(event: dict, req_id: str, task_id: str) -> bool:
    event_req = event_scope_value(event, "req_id", "request_id", "requestId")
    event_task = event_scope_value(event, "task_id", "taskId")
    if not req_id or not task_id or not event_req or not event_task:
        return False
    return event_req == req_id and event_task == task_id
def has_phase_evidence(project_root: Path, session_id: str, req_id: str, task_id: str) -> bool:
    for event in reversed(load_tail_history_events(project_root, session_id)):
        event_type = str(event.get("type") or "")
        if event_type == "spec.accepted" and event_scope_matches(event, req_id, task_id):
            return True
    return False
def active_override_event(project_root: Path, session_id: str, tool_name: str, args_sha256: str) -> Optional[dict]:
    events = load_tail_history_events(project_root, session_id)
    consumed_ids = set()
    consumed_pairs = set()
    now = utc_now()
    for event in events:
        if str(event.get("type") or "") != "override_consumed":
            continue
        override_id = str(
            event.get("override_id")
            or event.get("pending_id")
            or event.get("confirm_id")
            or event.get("id")
            or ""
        )
        if override_id:
            consumed_ids.add(override_id)
        consumed_pairs.add((str(event.get("tool") or ""), str(event.get("args_sha256") or "")))

    for event in reversed(events):
        if str(event.get("type") or "") != "override_granted":
            continue
        if str(event.get("tool") or "") != tool_name:
            continue
        if str(event.get("args_sha256") or "") != args_sha256:
            continue
        override_id = str(
            event.get("override_id")
            or event.get("pending_id")
            or event.get("confirm_id")
            or event.get("id")
            or ""
        )
        if override_id and override_id in consumed_ids:
            continue
        if not override_id and (tool_name, args_sha256) in consumed_pairs:
            continue
        expires_at = parse_utc(str(event.get("expires_at") or ""))
        if expires_at is not None and expires_at <= now:
            continue
        return event
    return None
def active_pending_override(project_root: Path, session_id: str, tool_name: str, args_sha256: str) -> Optional[dict]:
    pending = read_pending_confirm(pending_confirm_path(project_root, session_id))
    if not pending:
        return None
    if pending.get("approved") is not True:
        return None
    if pending.get("consumed") is not False:
        return None
    if pending.get("tool") != tool_name or pending.get("args_sha256") != args_sha256:
        return None
    expires_at = parse_utc(str(pending.get("expires_at") or ""))
    if expires_at is not None and expires_at <= utc_now():
        return None
    return pending
def consume_phase_override(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    args_sha256: str,
    override: dict,
) -> int:
    timestamp = format_utc(utc_now())
    override_id = str(
        override.get("override_id")
        or override.get("pending_id")
        or override.get("confirm_id")
        or override.get("id")
        or ""
    )
    pending_path = pending_confirm_path(project_root, session_id)
    pending = read_pending_confirm(pending_path)
    if pending and pending.get("tool") == tool_name and pending.get("args_sha256") == args_sha256:
        if not override_id or pending.get("id") == override_id:
            pending["consumed"] = True
            pending["consumed_at"] = timestamp
            write_pending_confirm(pending_path, pending)

    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "override_id": override_id,
            "timestamp": timestamp,
            "tool": tool_name,
            "type": "override_consumed",
        },
    )
def is_phase_gate_mutating_tool(tool_name: str, tool_input: dict) -> bool:
    if tool_name in PHASE_MUTATING_TOOLS:
        return True
    if tool_name == "Bash":
        return is_phase_gate_mutating_command(str(tool_input.get("command") or ""))
    return False
def path_is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False
def is_phase_gate_draft_path(tool_input: dict, project_root: Path, home: Path) -> bool:
    draft_root = (project_root / ".gran-maestro" / "drafts").resolve()
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(normalize_path(value.strip(), project_root, home)).expanduser().resolve()
        if path_is_under(candidate, draft_root):
            return True
    return False
def evaluate_phase_gate(project_root: Path, home: Path, payload: dict, session_id: str) -> Tuple[int, List[dict]]:
    tool_name = str(payload.get("tool_name") or "").strip() or "unknown"
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if is_phase_gate_draft_path(tool_input, project_root, home):
        return 0, []
    if not is_phase_gate_mutating_tool(tool_name, tool_input):
        return 0, []

    args_sha256 = sha256_text(canonical_json(tool_input))
    req_id, task_id = payload_scope(project_root, payload, tool_input)
    if has_phase_evidence(project_root, session_id, req_id, task_id):
        return 0, [
            {
                "args_sha256": args_sha256,
                "decision": "normal_allow",
                "message": "phase gate satisfied",
                "rule_id": PHASE_GATE_RULE_ID,
                "tool": tool_name,
            }
        ]

    override = active_override_event(project_root, session_id, tool_name, args_sha256) or active_pending_override(
        project_root,
        session_id,
        tool_name,
        args_sha256,
    )
    if override is not None:
        status = consume_phase_override(project_root, home, session_id, tool_name, args_sha256, override)
        return status, [{"decision": "override_allow", "rule_id": PHASE_GATE_RULE_ID, "message": "override consumed"}]

    message = "mutating tool requires spec.accepted or approved override"
    stderr(f"[policy-block] rule={PHASE_GATE_RULE_ID} {message}")
    return 2, [
        {
            "args_sha256": args_sha256,
            "decision": "policy_block",
            "message": message,
            "rule_id": PHASE_GATE_RULE_ID,
            "tool": tool_name,
        }
    ]
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
def evaluate_policy(project_root: Path, home: Path, payload: dict) -> Tuple[int, List[dict]]:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    policy_dir = policy_home(home) / "projects" / project_key(project_root)
    manifest = policy_dir / "manifest.json"
    if not manifest.is_file():
        return 0, []

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
        if "predicate" in condition or "name" in condition:
            name = str(condition.get("predicate") or condition.get("name") or "")
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
            raw_rules = rule_payload.get("rules")
            if not isinstance(raw_rules, list) and isinstance(rule_payload, dict) and rule_payload.get("id"):
                raw_rules = [rule_payload]
            if not isinstance(raw_rules, list):
                continue
            for rule in raw_rules:
                if not isinstance(rule, dict):
                    continue
                if "match" in rule or "predicate" in rule or "decision" in rule:
                    compiled_rules.append(
                        {
                            "id": str(rule.get("id") or rule_path.name),
                            "trigger": rule.get("match"),
                            "condition": rule.get("predicate"),
                            "action": {
                                "decision": rule.get("decision"),
                                "message": rule.get("reason") or rule.get("message"),
                            },
                            "severity": rule.get("severity"),
                            "message": rule.get("reason") or rule.get("message"),
                        }
                    )
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
                return 2, [{"decision": "policy_block", "rule_id": rule_id, "message": "unknown_predicate"}]
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
    decisions: List[dict] = []

    def path_protected(path_glob: str) -> bool:
        raw_glob = str(path_glob or "")
        expanded_glob = os.path.expanduser(raw_glob)
        target = (
            get_arg(tool_input, "file_path")
            or get_arg(tool_input, "notebook_path")
            or get_arg(tool_input, "path")
            or get_arg(tool_input, "command")
        )
        if not target:
            return False
        expanded_target = os.path.expanduser(target)
        target_abs = os.path.abspath(expanded_target)
        glob_abs = os.path.abspath(expanded_glob)
        return (
            fnmatch.fnmatch(target_abs, glob_abs)
            or fnmatch.fnmatch(expanded_target, expanded_glob)
            or fnmatch.fnmatch(target, raw_glob)
        )

    def history_exists(type_filter) -> bool:
        return any(match_object(row, type_filter) for row in load_history_events(project_root, canonical_mst_session_id_from_payload(payload), history_cache))

    def history_not_exists_after(anchor, target) -> bool:
        rows = load_history_events(project_root, canonical_mst_session_id_from_payload(payload), history_cache)
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
        if "predicate" in predicate or "name" in predicate:
            name = str(predicate.get("predicate") or predicate.get("name") or "")
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
        if "all" in trigger:
            items = trigger.get("all")
            return all(trigger_matches(item) for item in items) if isinstance(items, list) else True
        if "any" in trigger:
            items = trigger.get("any")
            return any(trigger_matches(item) for item in items) if isinstance(items, list) else True
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
            return 2, [{"decision": "policy_block", "rule_id": rule_id, "message": message}]
        if decision == "warn":
            stderr(f"[policy-warning] rule={rule_id} {message}")
            decisions.append({"decision": "warn", "rule_id": rule_id, "message": message})
    if unknown_predicate_seen:
        stderr("[policy-block] unknown_predicate fail_closed")
        return 2, [{"decision": "policy_block", "rule_id": "unknown_predicate", "message": "fail_closed"}]
    return 0, decisions
