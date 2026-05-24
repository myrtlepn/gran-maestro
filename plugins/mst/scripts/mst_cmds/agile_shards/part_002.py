def cmd_agile_update(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed_fields = {}
    completion_forced_payload = None
    if args.status is not None:
        new_status = str(args.status)
        current_status = session.get("status")
        auto_mode = bool(session.get("auto_mode", False))
        if current_status == "active" and new_status == "paused" and auto_mode:
            authorized = (
                os.environ.get("MST_AGILE_PAUSE_AUTHORIZED") == "1"
                or getattr(args, "user_requested", False)
            )
            if not authorized:
                print(
                    "Error: 자발 정지 시도 차단 — AUTO_MODE sprint loop가 active인 상태에서 "
                    "권한 플래그 없이 paused로 전환할 수 없습니다. "
                    "사용자 직접 요청인 경우 --user-requested 또는 "
                    "MST_AGILE_PAUSE_AUTHORIZED=1 환경변수를 설정하세요.",
                    file=sys.stderr,
                )
                return 1
        if new_status == "completed":
            pending_reqs = []
            seen_req_ids = set()
            sprints_dir = _common.BASE_DIR / "agile" / agi_id / "sprints"
            for result_path in sorted(sprints_dir.glob("S*/result.json")):
                result_data = load_json(result_path) or {}
                req_id = result_data.get("req_id") if isinstance(result_data, dict) else None
                if not req_id or req_id in seen_req_ids:
                    continue
                seen_req_ids.add(req_id)
                request_data = load_json(_common.BASE_DIR / "requests" / req_id / "request.json") or {}
                status = str(request_data.get("status", "")).lower() if isinstance(request_data, dict) else ""
                if status not in {"done", "completed", "accepted"}:
                    pending_reqs.append(req_id)

            active_worktrees = []
            worktrees_dir = _common.BASE_DIR / "worktrees"
            for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
                meta_data = load_json(meta_path) or {}
                if not isinstance(meta_data, dict) or meta_data.get("state") == "cleaned":
                    continue
                raw_path = meta_data.get("path")
                if not raw_path:
                    continue
                worktree_path = Path(str(raw_path)).expanduser()
                if not worktree_path.is_absolute():
                    worktree_path = (_common.BASE_DIR.parent / worktree_path).resolve(strict=False)
                worktree_text = str(worktree_path)
                agi_match = meta_data.get("agi_id") == agi_id
                try:
                    relative_text = str(worktree_path.relative_to(_common.BASE_DIR))
                except ValueError:
                    relative_text = ""
                path_match = relative_text.startswith(f"worktrees/{agi_id}/sprint-")
                if agi_match or path_match:
                    active_worktrees.append(worktree_text)

            if getattr(args, "force", False):
                completion_forced_payload = {
                    "pending_reqs": pending_reqs,
                    "active_worktrees": active_worktrees,
                }
            elif pending_reqs or active_worktrees:
                _append_agile_event(
                    agi_id,
                    "agile.update.blocked",
                    {
                        "pending_reqs": pending_reqs,
                        "active_worktrees": active_worktrees,
                    },
                )
                print(
                    "[agile update] blocked: "
                    f"pending_reqs={json.dumps(pending_reqs, ensure_ascii=False)} "
                    f"active_worktrees={json.dumps(active_worktrees, ensure_ascii=False)}",
                    file=sys.stderr,
                )
                return 2
        session["status"] = new_status
        changed_fields["status"] = new_status
    if args.current_sprint is not None:
        if args.current_sprint < 0:
            print("Error: current_sprint must be >= 0", file=sys.stderr)
            return 1
        session["current_sprint"] = int(args.current_sprint)
        changed_fields["current_sprint"] = int(args.current_sprint)
    if args.steering_every is not None:
        if args.steering_every < 1:
            print("Error: --steering-every must be >= 1", file=sys.stderr)
            return 1
        session["steering_every"] = int(args.steering_every)
        changed_fields["steering_every"] = int(args.steering_every)
    if args.objective_version is not None:
        objective_data = session.get("objective")
        if not isinstance(objective_data, dict):
            objective_data = {"path": "objective/objective.md"}
            session["objective"] = objective_data
        objective_data["version"] = int(args.objective_version)
        changed_fields["objective_version"] = int(args.objective_version)

    if not changed_fields:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    saved = _save_agile_session(agi_id, session)
    if completion_forced_payload is not None:
        _append_agile_event(agi_id, "agile.update.forced", completion_forced_payload)
    _append_agile_event(agi_id, "agile.update", {"fields": changed_fields})

    if args.json:
        print(json.dumps(saved, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0
FINALIZE_ACCEPTED_STATUSES = {"done", "completed", "accepted"}
STALE_LOCK_SECONDS = 3600
ZERO_HASH = "0" * 64
def _diagnostic_payload(category: str, next_action: str, lock_path: Path, **fields: Any) -> dict:
    payload = {
        "category": category,
        "next_action": next_action,
        "lock_path": str(lock_path),
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return payload
def _diagnostic_base_dir(project_root: Path | str | None = None, base_dir: Path | str | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve(strict=False)
    if project_root is not None:
        return Path(project_root).expanduser().resolve(strict=False) / ".gran-maestro"
    if _common.BASE_DIR is not None:
        return Path(_common.BASE_DIR).resolve(strict=False)
    return Path.cwd().resolve(strict=False) / ".gran-maestro"
def _diagnostic_project_root(project_root: Path | str | None = None, base_dir: Path | str | None = None) -> Path:
    if project_root is not None:
        return Path(project_root).expanduser().resolve(strict=False)
    return _diagnostic_base_dir(base_dir=base_dir).parent
def _read_text_stripped(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
def _history_ledger_status_readonly(
    project_root: Path,
    home: Path,
    session_id: str,
    policy_home: Path | None = None,
) -> dict:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    resolved_policy_home = policy_home or home / ".claude" / "gran-maestro-policy"
    mirror_head = resolved_policy_home / "ledger-heads" / f"{session_id}.head"

    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    try:
        lines = history_file.read_text(encoding="utf-8").splitlines() if history_file.is_file() else []
    except OSError as exc:
        return {"ok": False, "reason": f"history read failed: {exc}"}

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            return {"ok": False, "reason": f"invalid json line={line_no}: {exc}"}
        if not isinstance(row, dict):
            return {"ok": False, "reason": f"row is not object line={line_no}"}
        if row.get("seq") != expected_seq:
            return {"ok": False, "reason": f"seq line={line_no}"}
        if row.get("prev_hash") != expected_prev:
            return {"ok": False, "reason": f"prev_hash line={line_no}"}
        event = row.get("event")
        if not isinstance(event, dict):
            return {"ok": False, "reason": f"event line={line_no}"}
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        computed = hashlib.sha256((expected_prev + "\n" + canonical).encode("utf-8")).hexdigest()
        if row.get("event_hash") != computed:
            return {"ok": False, "reason": f"event_hash line={line_no}"}
        expected_prev = computed
        last_hash = computed
        expected_seq += 1

    local_value = _read_text_stripped(local_head)
    mirror_value = _read_text_stripped(mirror_head)
    has_entries = expected_seq > 1
    if not has_entries:
        if local_value is not None and local_value != ZERO_HASH:
            return {"ok": False, "reason": "history.head non-zero for empty ledger"}
        if mirror_value is not None and mirror_value != ZERO_HASH:
            return {"ok": False, "reason": "mirror head non-zero for empty ledger"}
        return {"ok": True, "reason": "ok", "last_hash": ZERO_HASH, "seq": 0}

    if local_value is None:
        return {"ok": False, "reason": "missing history.head"}
    if mirror_value is None:
        return {"ok": False, "reason": "missing home mirror head"}
    if local_value != last_hash:
        return {"ok": False, "reason": "history.head"}
    if mirror_value != last_hash:
        return {"ok": False, "reason": "home mirror head"}
    return {"ok": True, "reason": "ok", "last_hash": last_hash, "seq": expected_seq - 1}
def _history_ledger_mismatch_payload(lock_path: Path, ledger_status: dict) -> dict | None:
    if ledger_status.get("ok"):
        return None
    return _diagnostic_payload(
        "ledger-mismatch",
        "run-ledger-verification",
        lock_path,
        ledger_status=ledger_status,
    )
def _path_has_symlink(path: Path, stop_at: Path) -> bool:
    current = path
    stop = stop_at.resolve(strict=False)
    while True:
        if current.is_symlink():
            return True
        if current.resolve(strict=False) == stop:
            return False
        if current.parent == current:
            return False
        current = current.parent
def _history_scope_status(base_dir: Path, session_id: str, lock_path: Path) -> tuple[bool, str]:
    expected = (base_dir / "sessions" / session_id / "history.lock").resolve(strict=False)
    resolved = lock_path.expanduser().resolve(strict=False)
    if _path_has_symlink(lock_path, base_dir.parent):
        return False, "symlink-lock-path"
    if resolved != expected:
        return False, f"expected={expected}"
    return True, "ok"
def _result_scope_status(base_dir: Path, agi_id: str, sprint_id: str, lock_path: Path) -> tuple[bool, str]:
    expected = (base_dir / "agile" / agi_id / "sprints" / sprint_id / ".result.lock").resolve(strict=False)
    resolved = lock_path.expanduser().resolve(strict=False)
    if _path_has_symlink(lock_path, base_dir.parent):
        return False, "symlink-lock-path"
    if resolved != expected:
        return False, f"expected={expected}"
    return True, "ok"
def _result_partial_artifact(sprint_dir: Path) -> Optional[Path]:
    candidates = []
    for pattern in ("*.tmp", "*.partial", ".*.tmp", "result.json.tmp", "result.md.tmp"):
        candidates.extend(sprint_dir.glob(pattern))
    for path in sorted(set(candidates)):
        if path.name == ".result.lock":
            continue
        if path.exists():
            return path
    result_json = sprint_dir / "result.json"
    if result_json.is_file():
        try:
            json.loads(result_json.read_text(encoding="utf-8"))
        except Exception:
            return result_json
    return None
def _load_lock_owner(lock_path: Path) -> tuple[dict, Optional[str]]:
    owner_path = lock_path / "owner.json"
    if not owner_path.is_file():
        return {}, "missing-owner-metadata"
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"malformed-owner-metadata: {exc}"
    if not isinstance(owner, dict):
        return {}, "owner-metadata-not-object"
    return owner, None
def _process_status(pid: Any) -> tuple[str, Optional[str]]:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return "unknown", "invalid-owner-pid"
    if pid_int <= 0:
        return "unknown", "invalid-owner-pid"
    try:
        os.kill(pid_int, 0)
        return "live", None
    except ProcessLookupError:
        return "missing", None
    except PermissionError as exc:
        return "inconclusive", str(exc)
    except OSError as exc:
        return "inconclusive", str(exc)
def _diagnose_history_lock(
    *,
    project_root: Path | str | None = None,
    base_dir: Path | str | None = None,
    home: Path | str | None = None,
    policy_home: Path | str | None = None,
    session_id: str | None = None,
    lock_path: Path | str | None = None,
    stale_after_sec: int = STALE_LOCK_SECONDS,
    **_: Any,
) -> dict:
    resolved_base_dir = _diagnostic_base_dir(project_root=project_root, base_dir=base_dir)
    resolved_project_root = _diagnostic_project_root(project_root=project_root, base_dir=resolved_base_dir)
    resolved_home = Path(home).expanduser().resolve(strict=False) if home is not None else Path.home()
    resolved_policy_home = (
        Path(policy_home).expanduser().resolve(strict=False) if policy_home is not None else None
    )
    sid = str(session_id or "").strip()
    resolved_lock_path = Path(lock_path).expanduser() if lock_path is not None else resolved_base_dir / "sessions" / sid / "history.lock"

    scope_ok, scope_status = _history_scope_status(resolved_base_dir, sid, resolved_lock_path)
    if not scope_ok:
        return _diagnostic_payload(
            "scope-mismatch",
            "inspect-lock-owner",
            resolved_lock_path,
            scope_status=scope_status,
        )

    ledger_status = _history_ledger_status_readonly(
        resolved_project_root,
        resolved_home,
        sid,
        policy_home=resolved_policy_home,
    )
    ledger_mismatch = _history_ledger_mismatch_payload(resolved_lock_path, ledger_status)
    if ledger_mismatch is not None:
        return ledger_mismatch

    owner, owner_reason = _load_lock_owner(resolved_lock_path)
    owner_pid = owner.get("owner_pid")
    owner_started_at = owner.get("owner_started_at")
    owner_session_id = owner.get("session_id")
    if owner_reason or owner_pid in (None, "") or owner_started_at in (None, "") or owner_session_id in (None, ""):
        return _diagnostic_payload(
            "owner-unknown",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=owner_reason or "insufficient-owner-identity",
            owner_status="unknown",
        )

    owner_status, status_reason = _process_status(owner_pid)
    if owner_status == "live":
        return _diagnostic_payload(
            "owner-live",
            "wait-for-owner",
            resolved_lock_path,
            owner_pid=int(owner_pid),
            owner_status="live",
        )
    if owner_status == "inconclusive":
        return _diagnostic_payload(
            "diagnosis-inconclusive",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=status_reason or "process lookup failed",
            owner_status="inconclusive",
        )
    if owner_status == "unknown":
        return _diagnostic_payload(
            "owner-unknown",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=status_reason or "insufficient-owner-identity",
            owner_status="unknown",
        )

    try:
        lock_age = max(0.0, time.time() - resolved_lock_path.stat().st_mtime)
    except OSError:
        lock_age = 0.0
    if lock_age >= float(stale_after_sec):
        return _diagnostic_payload(
            "history-lock-stale-candidate",
            "manual-recovery-approval",
            resolved_lock_path,
            lock_age=lock_age,
        )
    return _diagnostic_payload(
        "owner-unknown",
        "inspect-lock-owner",
        resolved_lock_path,
        reason="owner-missing-but-lock-age-below-threshold",
        owner_status="missing",
    )
def _diagnose_result_lock(
    *,
    project_root: Path | str | None = None,
    base_dir: Path | str | None = None,
    agi_id: str | None = None,
    sprint: int | None = None,
    sprint_id: str | None = None,
    lock_path: Path | str | None = None,
    **_: Any,
) -> dict:
    resolved_base_dir = _diagnostic_base_dir(project_root=project_root, base_dir=base_dir)
    agi = str(agi_id or "").strip()
    sid = str(sprint_id or "").strip() or (f"S{int(sprint):02d}" if sprint is not None else "")
    resolved_lock_path = Path(lock_path).expanduser() if lock_path is not None else resolved_base_dir / "agile" / agi / "sprints" / sid / ".result.lock"
    scope_ok, scope_status = _result_scope_status(resolved_base_dir, agi, sid, resolved_lock_path)
    if not scope_ok:
        return _diagnostic_payload(
            "scope-mismatch",
            "inspect-lock-owner",
            resolved_lock_path,
            scope_status=scope_status,
        )

    sprint_dir = resolved_lock_path.parent
    artifact_path = _result_partial_artifact(sprint_dir)
    if artifact_path is not None:
        return _diagnostic_payload(
            "partial-output-detected",
            "inspect-partial-output",
            resolved_lock_path,
            artifact_path=str(artifact_path),
        )

    if resolved_lock_path.exists():
        with open(resolved_lock_path, "a+", encoding="utf-8") as result_lock_file:
            acquired = False
            try:
                _common._lock_exclusive_with_timeout(result_lock_file, timeout_sec=0.0, poll_interval=0.01)
                acquired = True
            except TimeoutError:
                return _diagnostic_payload(
                    "result-lock-contention",
                    "wait-for-owner",
                    resolved_lock_path,
                    agi_id=agi,
                    sprint_id=sid,
                )
            finally:
                if acquired:
                    _common._unlock(result_lock_file)

    return _diagnostic_payload(
        "owner-unknown",
        "inspect-lock-owner",
        resolved_lock_path,
        reason="no-result-lock-contention-detected",
        owner_status="unknown",
        agi_id=agi,
        sprint_id=sid,
    )
def _diagnose_stale_lock(**context: Any) -> dict:
    kind = str(context.get("lock_kind") or context.get("kind") or "").strip().lower()
    lock_path = context.get("lock_path")
    lock_name = Path(lock_path).name if lock_path is not None else ""
    if kind == "result" or lock_name == ".result.lock":
        return _diagnose_result_lock(**context)
    return _diagnose_history_lock(**context)
diagnose_stale_lock = _diagnose_stale_lock
def diagnose_agile_stale_lock(**context: Any) -> dict:
    return _diagnose_stale_lock(**context)
def diagnose_history_lock(**context: Any) -> dict:
    return _diagnose_history_lock(**context)
def _load_first_json_object(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    return value
def _run_finalize_mst_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
def _finalize_mst_command(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(_common._mst_script_path()), *args]
    return _run_finalize_mst_command(command, cwd=project_root)
def _collect_finalize_req_ids(agi_id: str) -> list[str]:
    req_ids: list[str] = []
    seen: set[str] = set()
    sprints_dir = _agi_session_dir(agi_id) / "sprints"
    for result_path in sorted(sprints_dir.glob("S*/result.json")):
        result = load_json(result_path)
        if not isinstance(result, dict):
            continue
        raw_req_ids: list[str] = []
        req_id = result.get("req_id")
        if isinstance(req_id, str):
            raw_req_ids.append(req_id)
        generated = result.get("generated")
        generated_reqs = generated.get("req") if isinstance(generated, dict) else None
        if isinstance(generated_reqs, list):
            raw_req_ids.extend(value for value in generated_reqs if isinstance(value, str))
        for raw_req_id in raw_req_ids:
            normalized = _normalize_link_id(raw_req_id, "REQ")
            if normalized not in seen:
                seen.add(normalized)
                req_ids.append(normalized)
    return req_ids
def _inspect_request_status(project_root: Path, req_id: str) -> str:
    result = _finalize_mst_command(project_root, "request", "inspect", req_id, "--json")
    if result.returncode != 0 and "unrecognized arguments: --json" in result.stderr:
        result = _finalize_mst_command(project_root, "request", "inspect", req_id)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"request inspect failed: {req_id}"
        raise RuntimeError(message)

    payload = _load_first_json_object(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"request inspect returned invalid JSON: {req_id}")
    return str(payload.get("status") or "")
def _remove_finalize_worktrees(project_root: Path, agi_id: str) -> list[str]:
    removed: list[str] = []
    worktrees_root = _common.BASE_DIR / "worktrees" / agi_id
    if not worktrees_root.is_dir():
        return removed

    for worktree_path in sorted(worktrees_root.glob("sprint-*")):
        if not worktree_path.exists():
            continue
        if not worktree_path.is_dir():
            continue
        normalized_path = str(worktree_path.resolve(strict=False))
        result = _finalize_mst_command(
            project_root,
            "worktree",
            "remove",
            "--path",
            normalized_path,
            "--force",
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"worktree remove failed: {normalized_path}"
            raise RuntimeError(message)
        removed.append(normalized_path)
    return removed
def _run_finalize_orphan_cleanup(project_root: Path) -> tuple[dict, bool]:
    session_id = os.environ.get("MST_SESSION_ID", "").strip() or "phase5"

    def _cleanup(_context: dict) -> dict:
        result = _finalize_mst_command(project_root, "worktree", "detect-orphans", "--clean", "--json")
        payload = _load_first_json_object(result.stdout)
        if not isinstance(payload, dict):
            payload = {"cleaned": [], "failed": []}
        payload.setdefault("cleaned", [])
        payload.setdefault("failed", [])
        if result.returncode != 0 and not payload.get("failed"):
            message = result.stderr.strip() or result.stdout.strip() or "worktree detect-orphans failed"
            raise RuntimeError(message)
        return {
            "status": "ok" if result.returncode == 0 and not payload.get("failed") else "failed",
            "payload": payload,
            "returncode": result.returncode,
        }

    report = cleanup_mod.run_cleanup_with_lock_report(
        project_root=project_root,
        entrypoint="phase5",
        session_id=session_id,
        timeout_seconds=5.0,
        cleanup_fn=_cleanup,
    )
    payload = report.get("payload")
    if not isinstance(payload, dict):
        payload = {"cleaned": [], "failed": []}
    payload.setdefault("cleaned", [])
    payload.setdefault("failed", [])
    return payload, report.get("status") == "ok" and not payload.get("failed")
def _run_finalize_boundary_check(project_root: Path, agi_id: str) -> bool | None:
    result = _finalize_mst_command(project_root, "worktree", "check-boundary", "--agi", agi_id)
    if result.returncode == 0:
        return True

    stderr = result.stderr.strip()
    if (
        "invalid choice" in stderr
        or "unrecognized arguments: --agi" in stderr
        or "the following arguments are required" in stderr
    ):
        return None
    return False
def _print_finalize_payload(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"agi_id: {payload['agi_id']}")
    print(f"accepted_reqs: {', '.join(payload['accepted_reqs']) or '-'}")
    print(f"skipped_reqs: {', '.join(payload['skipped_reqs']) or '-'}")
    print(f"pending_accept_reqs: {', '.join(payload['pending_accept_reqs']) or '-'}")
    print(f"removed_worktrees: {len(payload['removed_worktrees'])}")
    print(f"orphan_cleanup.cleaned: {', '.join(payload['orphan_cleanup'].get('cleaned') or []) or '-'}")
    print(f"orphan_cleanup.failed: {', '.join(payload['orphan_cleanup'].get('failed') or []) or '-'}")
    print(f"boundary_ok: {payload['boundary_ok']}")
def _finalize_report_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, (list, dict, bool)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
def _write_finalize_final_report(agi_id: str, payload: dict, status: str) -> None:
    orphan_cleanup = payload.get("orphan_cleanup")
    if not isinstance(orphan_cleanup, dict):
        orphan_cleanup = {}
    removed_worktrees = payload.get("removed_worktrees")
    if not isinstance(removed_worktrees, list):
        removed_worktrees = []

    lines = [
        f"# {agi_id} Finalization Report",
        f"- generated_at: {_now_iso()}",
        f"- status: {status}",
        "",
        "## Accepted/Skipped REQs",
        f"- skipped_reqs: {_finalize_report_value(payload.get('skipped_reqs') or [])}",
        f"- pending_accept_reqs: {_finalize_report_value(payload.get('pending_accept_reqs') or [])}",
        "",
        "## Worktree Cleanup",
        f"- removed_worktrees: {len(removed_worktrees)}건 ({_finalize_report_value(removed_worktrees)})",
        "",
        "## Orphan Cleanup",
        f"- cleaned: {_finalize_report_value(orphan_cleanup.get('cleaned') or [])}",
        f"- failed: {_finalize_report_value(orphan_cleanup.get('failed') or [])}",
        "",
        "## Boundary Check",
        f"- boundary_ok: {_finalize_report_value(payload.get('boundary_ok'))}",
        "",
    ]
    report_path = _agi_session_dir(agi_id) / "final-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
def cmd_agile_finalize(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    project_root = _common.BASE_DIR.parent
    payload = {
        "agi_id": agi_id,
        "accepted_reqs": [],
        "skipped_reqs": [],
        "pending_accept_reqs": [],
        "removed_worktrees": [],
        "orphan_cleanup": {"cleaned": [], "failed": []},
        "boundary_ok": None,
    }
    _append_agile_event(agi_id, "agile.finalize.step.load_session", {"ok": True})

    try:
        req_ids = _collect_finalize_req_ids(agi_id)
        _append_agile_event(agi_id, "agile.finalize.step.collect_reqs", {"ok": True, "req_ids": req_ids})

        for req_id in req_ids:
            status = _inspect_request_status(project_root, req_id)
            if status in FINALIZE_ACCEPTED_STATUSES:
                payload["skipped_reqs"].append(req_id)
            else:
                payload["pending_accept_reqs"].append(req_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.inspect_reqs",
            {
                "ok": True,
                "skipped_reqs": payload["skipped_reqs"],
                "pending_accept_reqs": payload["pending_accept_reqs"],
            },
        )

        payload["removed_worktrees"] = _remove_finalize_worktrees(project_root, agi_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.remove_worktrees",
            {"ok": True, "removed_worktrees": payload["removed_worktrees"]},
        )

        orphan_cleanup, orphan_ok = _run_finalize_orphan_cleanup(project_root)
        payload["orphan_cleanup"] = orphan_cleanup
        _append_agile_event(
            agi_id,
            "agile.finalize.step.orphan_cleanup",
            {"ok": orphan_ok, "orphan_cleanup": orphan_cleanup},
        )

        payload["boundary_ok"] = _run_finalize_boundary_check(project_root, agi_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.boundary_check",
            {"ok": payload["boundary_ok"] is not False, "boundary_ok": payload["boundary_ok"]},
        )
    except Exception as exc:
        _append_agile_event(agi_id, "agile.finalize.step.failed", {"ok": False, "error": str(exc)})
        print(f"Error: {exc}", file=sys.stderr)
        _write_finalize_final_report(agi_id, payload, "failed")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 1

    if payload["pending_accept_reqs"]:
        pending = ", ".join(payload["pending_accept_reqs"])
        print(f"[finalize] pending accept: {pending}", file=sys.stderr)
        _append_agile_event(
            agi_id,
            "agile.finalize.pending_accept",
            {"pending_accept_reqs": payload["pending_accept_reqs"]},
        )
        _write_finalize_final_report(agi_id, payload, "pending_accept")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 2

    if payload["orphan_cleanup"].get("failed"):
        _append_agile_event(
            agi_id,
            "agile.finalize.failed",
            {"orphan_cleanup": payload["orphan_cleanup"]},
        )
        _write_finalize_final_report(agi_id, payload, "failed")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 1

    _append_agile_event(agi_id, "agile.finalize.ok", payload)
    _write_finalize_final_report(agi_id, payload, "ok")
    _print_finalize_payload(payload, getattr(args, "json", False))
    return 0
