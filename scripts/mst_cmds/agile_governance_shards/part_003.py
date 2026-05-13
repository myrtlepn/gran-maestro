def cmd_agile_recall(args):
    level_raw = args.level if args.level is not None else _RECALL_DEFAULT_LEVEL
    try:
        level = int(level_raw)
    except (TypeError, ValueError):
        level = _RECALL_DEFAULT_LEVEL

    reason = str(args.reason or "").strip().lower()
    trigger = str(args.trigger or "").strip()
    approval_ticket = str(getattr(args, "approval_ticket", "") or "").strip()
    bypass_requested = bool(args.bypass_cooldown)
    fingerprint = str(args.fingerprint or trigger or "").strip()

    payload = {
        "status": "FAIL",
        "level": level,
        "agi_id": None,
        "reason": reason,
        "trigger": trigger,
        "project_size": 0,
        "sprint_index": 0,
        "cooldown_window": None,
        "cap_limit": None,
        "cap_used": 0,
        "rollback_token": None,
        "manifest_path": None,
        "agile_plan_patch": {"called": False},
        "patch_budget": {
            "done_total": 0,
            "requested_modifications": 0,
            "max_modifications": 0,
        },
        "bypass": {
            "requested": bypass_requested,
            "used": False,
            "fingerprint": fingerprint or None,
        },
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_recall_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    if level not in {2, 3}:
        return _fail("recall level must be 2 or 3")
    if reason not in {"fail", "drift"}:
        return _fail("reason must be fail or drift")

    recall_cfg = _load_agile_recall_config()
    enabled = bool(recall_cfg.get("enabled", True))
    if not enabled:
        payload["status"] = "SKIP"
        payload["warnings"].append("recall disabled (agile.recall.enabled=false)")
        _emit_recall_payload(payload, args.json)
        print(payload["warnings"][0], file=sys.stderr)
        return 0

    try:
        if args.agi_id:
            agi_id = _normalize_agi_id(str(args.agi_id))
        else:
            agi_id = _find_latest_agi_id()
            if agi_id is None:
                raise ValueError("AGI session not found; provide --agi-id")
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        return _fail(str(exc))

    payload["agi_id"] = agi_id

    try:
        sprint_index = int(session.get("current_sprint", 0))
    except (TypeError, ValueError):
        sprint_index = 0
    payload["sprint_index"] = max(0, sprint_index)

    project_size = _compute_recall_project_size(session, agi_id)
    cooldown_ratio = _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO)
    cap_ratio = _safe_float(recall_cfg.get("cap_ratio"), _RECALL_DEFAULT_CAP_RATIO)
    cooldown_window = (
        _compute_level3_cooldown(project_size, recall_cfg)
        if level == 3
        else _compute_recall_cooldown(project_size, cooldown_ratio)
    )
    cap_limit = _compute_recall_cap(project_size, cap_ratio)
    payload["project_size"] = project_size
    payload["cooldown_window"] = cooldown_window
    payload["cap_limit"] = cap_limit

    rollback_token_path = _create_recall_rollback_token()
    payload["rollback_token"] = str(rollback_token_path)

    history = _load_agile_recall_history(agi_id)
    cap_used = sum(1 for row in history if str(row.get("status") or "").upper() == "PASS")
    payload["cap_used"] = cap_used
    if cap_used >= cap_limit:
        return _fail("Cap exceeded, steering checkpoint required")

    last_success = _find_last_successful_recall(history)
    cooldown_active = False
    if isinstance(last_success, dict):
        try:
            last_sprint = int(last_success.get("sprint_index", -10**6))
        except (TypeError, ValueError):
            last_sprint = -10**6
        try:
            last_window = int(last_success.get("cooldown_window", cooldown_window))
        except (TypeError, ValueError):
            last_window = cooldown_window
        cooldown_active = _is_within_cooldown_window(payload["sprint_index"], last_sprint, last_window)

    if cooldown_active:
        if not bypass_requested:
            return _fail("Cooldown active")
        if not _is_evidence_hard_fail(reason, trigger):
            return _fail("Cooldown bypass allowed only for evidence hard fail")
        if not fingerprint:
            return _fail("Cooldown bypass requires fingerprint")
        for row in reversed(history):
            bypass = row.get("bypass")
            if not isinstance(bypass, dict):
                continue
            if not bool(bypass.get("used")):
                continue
            if str(bypass.get("fingerprint") or "") != fingerprint:
                continue
            try:
                row_sprint = int(row.get("sprint_index", -10**6))
            except (TypeError, ValueError):
                row_sprint = -10**6
            try:
                row_window = int(row.get("cooldown_window", cooldown_window))
            except (TypeError, ValueError):
                row_window = cooldown_window
            if _is_within_cooldown_window(payload["sprint_index"], row_sprint, row_window):
                return _fail("fingerprint already bypassed in cooldown")
        payload["bypass"]["used"] = True
    elif bypass_requested:
        payload["warnings"].append("bypass requested but cooldown inactive")

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        return _fail(f"objective file missing: {objective_path}")

    try:
        objective_content = objective_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"failed to read objective: {exc}")

    dod_items = _collect_objective_dod_items(objective_content)
    done_dod_ids = {
        dod_id
        for dod_id, meta in dod_items.items()
        if str(meta.get("status") or "").strip().lower() == "done"
    }
    done_total = len(done_dod_ids)
    patch_budget_max = min(3, math.ceil(done_total * 0.20)) if done_total > 0 else 0
    payload["patch_budget"]["done_total"] = done_total
    payload["patch_budget"]["max_modifications"] = patch_budget_max

    try:
        manifest = (
            _load_level3_recall_manifest(agi_id, reason, trigger)
            if level == 3
            else _load_level2_recall_manifest(agi_id, reason, trigger)
        )
    except ValueError as exc:
        return _fail(str(exc))

    if level == 2 and _manifest_exceeds_level2_scope(manifest):
        return _fail("Level 2 scope exceeded, use Level 3 with user approval")

    touched_done_dods = _collect_manifest_touched_done_dods(manifest, done_dod_ids)
    missing_unlock = _recall_done_dods_missing_unlock(agi_id, touched_done_dods)
    if missing_unlock:
        return _fail(f"unlock required before recall for done DoD: {', '.join(missing_unlock)}")

    requested_mods = _estimate_done_modifications(manifest, done_dod_ids)
    payload["patch_budget"]["requested_modifications"] = requested_mods
    if requested_mods > patch_budget_max:
        return _fail("Patch budget exceeded (max 3 or 20%)")

    recall_dir = _agi_recall_dir(agi_id)
    recall_dir.mkdir(parents=True, exist_ok=True)
    manifest_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = recall_dir / f"manifest-{manifest_token}.json"
    save_json(manifest_path, manifest)
    save_json(recall_dir / "manifest-latest.json", manifest)
    payload["manifest_path"] = str(manifest_path)

    auto_mode_request = bool(_load_auto_mode_config().get("request", False))
    approval_payload = None
    if level == 3:
        approval_payload = _build_level3_approval_payload(
            manifest,
            objective_content,
            done_dod_ids,
            reason=reason,
            trigger=trigger,
            auto_mode_request=auto_mode_request,
        )
        payload["approval_required"] = True
        payload["approval"] = approval_payload
        if not approval_ticket:
            message = "Level 3 requires --approval-ticket (user approval required)"
            payload["status"] = "FAIL"
            payload["errors"] = [message]
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print("USER APPROVAL REQUIRED")
                print(json.dumps(approval_payload, ensure_ascii=False))
            print(message, file=sys.stderr)
            return 1

    patch_call = _record_agile_plan_patch_invocation(
        agi_id,
        level=level,
        reason=reason,
        trigger=trigger,
        manifest_path=manifest_path,
    )
    payload["agile_plan_patch"] = patch_call

    objective_version = None
    event_id = None
    objective_history_path = None
    if level == 3 and approval_payload is not None:
        updated_objective, objective_diff = _apply_level3_objective_refinements(objective_content, manifest)
        event_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        event_id = f"EVT-L3-{event_token}"

        frontmatter = _extract_frontmatter_block(objective_content)
        frontmatter_text = str(frontmatter.get("frontmatter") or "")
        version_raw = _extract_yaml_scalar(frontmatter_text, "version")
        if version_raw is None:
            objective_data = session.get("objective") if isinstance(session.get("objective"), dict) else {}
            version_raw = objective_data.get("version", 0)
        try:
            current_version = int(version_raw)
        except (TypeError, ValueError):
            current_version = 0
        objective_version = current_version + 1

        updated_objective = _upsert_objective_frontmatter_fields(
            updated_objective,
            {
                "version": objective_version,
                "last_event_id": event_id,
                "semantic_hash": approval_payload["after_hash"],
            },
        )
        try:
            objective_path.write_text(updated_objective, encoding="utf-8")
        except OSError as exc:
            return _fail(f"failed to write objective: {exc}")

        objective_data = session.get("objective")
        if not isinstance(objective_data, dict):
            objective_data = {"path": "objective/objective.md"}
            session["objective"] = objective_data
        objective_data["version"] = objective_version
        _save_agile_session(agi_id, session)

        objective_history_path = _write_level3_history_entry(
            agi_id,
            event_token=event_token,
            reason=reason,
            event_id=event_id,
            before_hash=approval_payload["before_hash"],
            after_hash=approval_payload["after_hash"],
            diff=_build_level3_diff_payload(manifest, objective_diff),
            affected_dods=list(approval_payload["affected_dods"]),
            drift_evidence=list(approval_payload["drift_evidence"]),
            approval_ticket=approval_ticket,
        )
        payload["objective"] = {
            "version": objective_version,
            "last_event_id": event_id,
            "semantic_hash": approval_payload["after_hash"],
            "history_path": str(objective_history_path),
        }

    history_entry = {
        "timestamp": _now_iso(),
        "status": "PASS",
        "level": level,
        "agi_id": agi_id,
        "sprint_index": payload["sprint_index"],
        "reason": reason,
        "trigger": trigger,
        "cooldown_window": cooldown_window,
        "cap_limit": cap_limit,
        "rollback_token": str(rollback_token_path),
        "manifest_path": str(manifest_path),
        "bypass": {
            "requested": bypass_requested,
            "used": bool(payload["bypass"]["used"]),
            "fingerprint": fingerprint or None,
        },
        "patch_budget": dict(payload["patch_budget"]),
    }
    if level == 3:
        history_entry["approval_ticket"] = approval_ticket
        history_entry["objective_version"] = objective_version
        history_entry["last_event_id"] = event_id
    history.append(history_entry)
    _save_agile_recall_history(agi_id, history)

    _append_agile_event(
        agi_id,
        "agile.recall",
        {
            "status": "PASS",
            "level": level,
            "reason": reason,
            "trigger": trigger,
            "bypass": bool(payload["bypass"]["used"]),
            "approval_ticket": approval_ticket or None,
            "last_event_id": event_id,
        },
    )
    _append_agile_sprint_log(
        {
            "timestamp": _now_iso(),
            "event": "agile-recall",
            "agi_id": agi_id,
            "reason": reason,
            "trigger": trigger,
            "manifest_path": str(manifest_path),
            "level": level,
        }
    )

    payload["status"] = "PASS"
    _emit_recall_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    return 0
def cmd_agile_objective_transition(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    from scripts.mst_cmds.state import _check_read_only

    read_only_status = _check_read_only(agi_id)
    if read_only_status:
        return read_only_status

    try:
        dod_id = _normalize_dod_id(args.story)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    current_content = objective_path.read_text(encoding="utf-8")
    before_items = _collect_objective_dod_items(current_content)
    updated_content, found, changed = _update_objective_dod_status(
        current_content,
        dod_id,
        str(args.status).strip().lower(),
    )
    if not found:
        print(f"Error: DoD item not found ({dod_id})", file=sys.stderr)
        return 1

    story_upper = str(args.story or "").upper()
    evidence_refs_arg = getattr(args, "evidence_ref", []) or []
    if evidence_refs_arg:
        marker_pattern = re.compile(
            (
                rf"(<!--\s*dod:\s*{re.escape(story_upper)}\s+[^>]*?)"
                r"(?:\s+evidence_refs:\[([^\]]*)\])?"
                r"\s*(-->)"
            ),
            re.IGNORECASE,
        )

        def _replace_marker(match):
            prefix = match.group(1).rstrip()
            existing_refs = match.group(2)
            existing_list = [r.strip() for r in existing_refs.split(",")] if existing_refs else []
            existing_list = [r for r in existing_list if r]
            seen = set(existing_list)
            merged = list(existing_list)
            for ref in evidence_refs_arg:
                ref = str(ref).strip()
                if ref and ref not in seen:
                    merged.append(ref)
                    seen.add(ref)
            evidence_str = ",".join(merged)
            return f"{prefix} evidence_refs:[{evidence_str}] {match.group(3)}"

        updated_content = marker_pattern.sub(_replace_marker, updated_content, count=1)

    deferred_promoted: List[str] = []
    deferred_sprints: List[str] = []

    if getattr(args, "deferred_promote", False):
        if args.sprint is None:
            print("Error: --deferred-promote requires --sprint", file=sys.stderr)
            return 1
        if args.sprint < 0:
            print("Error: --sprint must be >= 0", file=sys.stderr)
            return 1

        streak_limit = _load_agile_int_config("foundational_streak_max", 2) + 1
        sprint_cursor = int(args.sprint) - 1
        chain_payloads: List[tuple[str, dict]] = []
        while sprint_cursor >= 0 and len(chain_payloads) < streak_limit:
            sprint_id = f"S{sprint_cursor:02d}"
            result_path = _agi_session_dir(agi_id) / "sprints" / sprint_id / "result.json"
            result_payload = load_json(result_path)
            if not isinstance(result_payload, dict):
                break
            sprint_kind = str(result_payload.get("sprint_kind", "user_observable")).strip().lower()
            if sprint_kind != "foundational":
                break
            deferred_sprints.append(sprint_id)
            chain_payloads.append((sprint_id, result_payload))
            sprint_cursor -= 1

        working_items = _collect_objective_dod_items(updated_content)
        for _, result_payload in chain_payloads:
            for candidate_dod in _extract_dod_ids_from_result_payload(result_payload):
                status = str(working_items.get(candidate_dod, {}).get("status", "")).strip().lower()
                if status != "proposed_done":
                    continue
                updated_content, candidate_found, candidate_changed = _update_objective_dod_status(
                    updated_content,
                    candidate_dod,
                    "done",
                )
                if not candidate_found or not candidate_changed:
                    continue
                deferred_promoted.append(candidate_dod)
                item = working_items.get(candidate_dod)
                if isinstance(item, dict):
                    item["status"] = "done"

        if deferred_promoted:
            deduped: List[str] = []
            seen = set()
            for dod in deferred_promoted:
                if dod in seen:
                    continue
                seen.add(dod)
                deduped.append(dod)
            deferred_promoted = sorted(deduped)

    overall_changed = changed or bool(deferred_promoted)
    if overall_changed:
        objective_path.write_text(updated_content, encoding="utf-8")

    after_items = _collect_objective_dod_items(updated_content)
    from_status = before_items.get(dod_id, {}).get("status")
    to_status = after_items.get(dod_id, {}).get("status")
    priority = after_items.get(dod_id, {}).get("priority")
    _append_ndjson(
        _agi_objective_changelog_path(agi_id),
        {
            "timestamp": _now_iso(),
            "event": "objective-transition",
            "dod": dod_id,
            "from_status": from_status,
            "to_status": to_status,
            "priority": priority,
            "changed": changed,
        },
    )
    if getattr(args, "deferred_promote", False):
        _append_ndjson(
            _agi_objective_changelog_path(agi_id),
            {
                "timestamp": _now_iso(),
                "event": "deferred-promote",
                "sprint": f"S{int(args.sprint):02d}" if args.sprint is not None and args.sprint >= 0 else None,
                "sprints": deferred_sprints,
                "dods": deferred_promoted,
            },
        )
    _append_agile_event(
        agi_id,
        "agile.objective-transition",
        {
            "dod": dod_id,
            "from_status": from_status,
            "to_status": to_status,
            "priority": priority,
            "changed": changed,
        },
    )

    output = {
        "agi_id": agi_id,
        "story": dod_id,
        "dod": dod_id,
        "status": to_status,
        "priority": priority,
        "changed": changed,
    }
    if getattr(args, "deferred_promote", False):
        output["deferred_promote"] = {
            "sprints": deferred_sprints,
            "dods": deferred_promoted,
        }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0
def cmd_agile_objective_check(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    content = objective_path.read_text(encoding="utf-8")
    dod_items = _collect_objective_dod_items(content)

    requested_dod_id = getattr(args, "dod_id", None)
    if requested_dod_id:
        dod_key = requested_dod_id.upper()
        if dod_key not in dod_items:
            print(f"Error: DoD '{requested_dod_id}' not found", file=sys.stderr)
            return 1
        item = dod_items[dod_key]
        single_output = {
            "agi_id": agi_id,
            "dod_id": dod_key,
            "status": item.get("status"),
            "priority": item.get("priority"),
            "domain": item.get("domain", "unknown"),
            "evidence_refs": item.get("evidence_refs", []),
        }
        if args.json:
            print(json.dumps(single_output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(single_output, ensure_ascii=False))
        return 0

    if not dod_items:
        output = {
            "agi_id": agi_id,
            "all_done": False,
            "incomplete": [],
            "dods": {},
            "warning": "no DoD items found",
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(output, ensure_ascii=False))
        return 0

    incomplete = sorted([
        dod_id for dod_id, item in dod_items.items()
        if item.get("status", "").lower() not in {"done", "completed"}
    ])
    status_only = {dod_id: item.get("status") for dod_id, item in dod_items.items()}
    legacy_dods = {}
    for dod_id, item in dod_items.items():
        if not isinstance(item, dict):
            legacy_dods[dod_id] = item
            continue
        item_copy = dict(item)
        item_copy.pop("evidence_refs", None)
        legacy_dods[dod_id] = item_copy
    output = {
        "agi_id": agi_id,
        "all_done": len(incomplete) == 0,
        "incomplete": incomplete,
        "dods": legacy_dods,
        "stories": status_only,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0
def cmd_agile_objective_snapshot(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    history_dir = objective_path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    highest_version = 0
    for candidate in history_dir.glob("v*.md"):
        match = re.fullmatch(r"v(\d+)\.md", candidate.name)
        if not match:
            continue
        highest_version = max(highest_version, int(match.group(1)))

    snapshot_version = highest_version + 1
    snapshot_path = history_dir / f"v{snapshot_version}.md"
    shutil.copyfile(objective_path, snapshot_path)

    _append_ndjson(
        _agi_objective_changelog_path(agi_id),
        {
            "timestamp": _now_iso(),
            "version": snapshot_version,
            "reason": str(args.reason),
        },
    )

    objective_data = session.get("objective")
    if not isinstance(objective_data, dict):
        objective_data = {"path": "objective/objective.md", "version": 0}
        session["objective"] = objective_data

    try:
        current_objective_version = int(objective_data.get("version", 0))
    except (TypeError, ValueError):
        current_objective_version = 0
    objective_data["version"] = current_objective_version + 1

    saved_session = _save_agile_session(agi_id, session)
    _append_agile_event(
        agi_id,
        "agile.objective-snapshot",
        {
            "version": snapshot_version,
            "reason": str(args.reason),
            "objective_version": objective_data["version"],
        },
    )

    output = {
        "agi_id": agi_id,
        "version": snapshot_version,
        "reason": str(args.reason),
        "snapshot": str(snapshot_path),
        "objective_version": objective_data["version"],
        "updated_at": saved_session.get("updated_at"),
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0
