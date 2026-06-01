def cmd_agile_result(args):
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

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    planned = _split_csv_values(args.planned)
    completed = _split_csv_values(args.completed)
    try:
        pln_ids = [_normalize_link_id(value, "PLN") for value in _split_csv_values(args.pln)]
        req_ids = [_normalize_link_id(value, "REQ") for value in _split_csv_values(args.req)]
        sprint_goals = _parse_agile_sprint_goals(args.sprint_goals)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    sprint_id = f"S{args.sprint:02d}"
    timestamp = _now_iso()

    payload = {
        "sprint_id": sprint_id,
        "status": str(args.status),
        "planned": planned,
        "completed": completed,
        "generated": {
            "pln": pln_ids,
            "req": req_ids,
        },
        "sprint_goals": sprint_goals,
        "timestamp": timestamp,
        "sprint_kind": str(args.sprint_kind or "user_observable"),
        "user_observable_change": None,
        "foundational_reason": None,
    }
    if payload["sprint_kind"] == "foundational":
        if args.foundational_reason is not None:
            payload["foundational_reason"] = str(args.foundational_reason)
    else:
        if args.user_observable_change is not None:
            payload["user_observable_change"] = str(args.user_observable_change)
    if args.summary is not None:
        payload["summary"] = str(args.summary)
    if args.outcome is not None:
        payload["outcome"] = str(args.outcome)
    if args.sprint_purpose is not None:
        payload["sprint_purpose"] = str(args.sprint_purpose)
    if args.selection_reason is not None:
        payload["selection_reason"] = str(args.selection_reason)
    if args.target_dod is not None:
        payload["target_dod"] = str(args.target_dod)
    if args.target_dod_text is not None:
        payload["target_dod_text"] = str(args.target_dod_text)
    if getattr(args, "dod_ref", None) is not None:
        payload["dod_ref"] = str(args.dod_ref)
    if getattr(args, "domain", None) is not None:
        payload["domain_ref"] = str(args.domain)
    if args.previous_direction is not None:
        payload["previous_direction"] = str(args.previous_direction)
    if args.previous_lessons is not None:
        payload["previous_lessons"] = str(args.previous_lessons)
    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    result_lock_path = sprint_dir / ".result.lock"
    aux_warnings = []

    def _record_aux_warning(stage, exc):
        aux_warnings.append(
            {
                "stage": stage,
                "error_class": exc.__class__.__name__,
                "message": str(exc)[:500],
            }
        )
        print(f"[warn] {stage} hook 실패: {exc}", file=sys.stderr)

    with open(result_lock_path, "a+", encoding="utf-8") as result_lock_file:
        result_lock_acquired = False
        try:
            _common._lock_exclusive_with_timeout(result_lock_file, timeout_sec=5.0, poll_interval=0.05)
            result_lock_acquired = True
        except TimeoutError as exc:
            diagnostic = _diagnostic_payload(
                "result-lock-contention",
                "wait-for-owner",
                result_lock_path,
                agi_id=agi_id,
                sprint_id=sprint_id,
                compatible_signal="lock-contention",
            )
            print(
                "Error: agile result lock-contention (lock timeout) "
                "category=result-lock-contention next_action=wait-for-owner "
                f"agi_id={agi_id} sprint_id={sprint_id} lock_path={result_lock_path} detail={exc}",
                file=sys.stderr,
            )
            print(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True), file=sys.stderr)
            return 1

        try:
            result_md_path = sprint_dir / "result.md"
            result_md_lines = [
                f"# {sprint_id} Result",
                "",
            ]
            why_keys = (
                "sprint_purpose",
                "selection_reason",
                "target_dod",
                "target_dod_text",
                "previous_direction",
                "previous_lessons",
            )
            has_why = any(key in payload for key in why_keys)
            if has_why:
                target_dod = payload.get("target_dod") or "-"
                target_dod_text = payload.get("target_dod_text") or "-"
                if target_dod == "-" and target_dod_text == "-":
                    target_dod_line = "-"
                elif target_dod_text == "-":
                    target_dod_line = target_dod
                elif target_dod == "-":
                    target_dod_line = target_dod_text
                else:
                    target_dod_line = f"{target_dod} — {target_dod_text}"
                result_md_lines.extend(
                    [
                        "## 이 스프린트를 왜 했는가",
                        f"- 스프린트 목적: {payload.get('sprint_purpose') or '-'}",
                        f"- 대상 DoD: {target_dod_line}",
                        f"- 선택 근거: {payload.get('selection_reason') or '-'}",
                        f"- 직전 회고 방향: {payload.get('previous_direction') or '-'}",
                        f"- 직전 교훈: {payload.get('previous_lessons') or '-'}",
                        "",
                    ]
                )
            result_md_lines.extend(
                [
                    f"- status: {payload['status']}",
                    f"- planned: {', '.join(planned) if planned else '-'}",
                    f"- completed: {', '.join(completed) if completed else '-'}",
                    f"- generated PLN: {', '.join(pln_ids) if pln_ids else '-'}",
                    f"- generated REQ: {', '.join(req_ids) if req_ids else '-'}",
                    f"- summary: {payload.get('summary', '-')}",
                    f"- outcome: {payload.get('outcome', '-')}",
                    f"- timestamp: {timestamp}",
                    "",
                ]
            )
            result_md_lines.extend(_render_sprint_goals_md_lines(sprint_goals))
            result_md_path.write_text("\n".join(result_md_lines), encoding="utf-8")
            _append_agile_event(
                agi_id,
                "agile.result",
                {
                    "sprint_id": sprint_id,
                    "status": payload["status"],
                },
            )

            # Auto-update index/links.json when PLN/REQ IDs are provided
            if pln_ids or req_ids:
                try:
                    links_path = _agi_links_path(agi_id)
                    links = load_json(links_path) or {}
                    if not isinstance(links, dict):
                        links = {}
                    links["agi_id"] = agi_id
                    links.setdefault("pln", [])
                    links.setdefault("req", [])
                    for plan_id in pln_ids:
                        if plan_id not in links["pln"]:
                            links["pln"].append(plan_id)
                    for req_id in req_ids:
                        if req_id not in links["req"]:
                            links["req"].append(req_id)
                    links["updated_at"] = _now_iso()
                    save_json(links_path, links)
                except Exception as exc:
                    _record_aux_warning("links-update", exc)

            # drift report skeleton 생성 (status in [done, failed]일 때만)
            drift_report_path = None
            if args.status in ("done", "failed"):
                try:
                    drift_report_path = _generate_drift_report_skeleton(
                        agi_id=agi_id,
                        sprint_num=args.sprint,
                        source_plan=getattr(args, "pln", None),
                        dod_ref=getattr(args, "dod_ref", None),
                        original_dod_text=None,  # MVP에서는 None, 향후 확장
                    )
                except Exception as exc:
                    _record_aux_warning("drift-report", exc)

                # recall patch manifest skeleton 생성 (drift-report classification 기반)
                try:
                    classification = None
                    if drift_report_path is not None:
                        try:
                            report_data = json.loads(Path(drift_report_path).read_text(encoding="utf-8"))
                            classification = report_data.get("classification")
                        except Exception:
                            classification = None
                    if classification in ("drift_warning", "objective_stale"):
                        _generate_recall_patch_manifest_skeleton(
                            agi_id=agi_id,
                            sprint_num=args.sprint,
                            classification=classification,
                            drift_report_path=drift_report_path,
                        )
                except Exception as exc:
                    _record_aux_warning("recall-manifest", exc)

            payload["aux_status"] = "partial" if aux_warnings else "ok"
            payload["aux_warnings"] = aux_warnings
            save_json(sprint_dir / "result.json", payload)
        finally:
            if result_lock_acquired:
                _common._unlock(result_lock_file)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(sprint_dir / "result.json"))
    return 0
def cmd_agile_diagnose_lock(args):
    context = {
        "project_root": _common.BASE_DIR.parent if _common.BASE_DIR is not None else Path.cwd(),
        "base_dir": _common.BASE_DIR if _common.BASE_DIR is not None else Path.cwd() / ".gran-maestro",
        "home": Path.home(),
        "policy_home": Path.home() / ".claude" / "gran-maestro-policy",
        "session_id": getattr(args, "session_id", None),
        "lock_path": Path(args.lock_path).expanduser() if args.lock_path else None,
        "lock_kind": args.lock_kind,
        "kind": args.lock_kind,
        "agi_id": getattr(args, "agi_id", None),
        "sprint": getattr(args, "sprint", None),
        "sprint_id": getattr(args, "sprint_id", None),
        "stale_after_sec": getattr(args, "stale_after_sec", STALE_LOCK_SECONDS),
    }
    payload = _diagnose_stale_lock(**context)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
def cmd_agile_dispatch_result(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
        pln_id = _normalize_link_id(args.pln, "PLN") if args.pln else None
        req_id = _normalize_link_id(args.req, "REQ") if args.req else None
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    sprint_id = f"S{args.sprint:02d}"
    payload = {
        "agi_id": agi_id,
        "sprint": int(args.sprint),
        "status": str(args.status),
        "pln_id": pln_id,
        "req_id": req_id,
        "commit_sha": str(args.commit_sha) if args.commit_sha is not None else None,
        "sprint_kind": str(args.sprint_kind) if args.sprint_kind is not None else None,
        "exit_code": int(args.exit_code),
        "failure_reason": str(args.failure_reason) if args.failure_reason is not None else None,
        "result_recorded": bool(args.result_recorded),
        "retrospective_recorded": bool(args.retrospective_recorded),
    }

    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    dispatch_result_path = sprint_dir / "dispatch-result.json"
    save_json(dispatch_result_path, payload)
    _append_agile_event(
        agi_id,
        "agile.dispatch-result",
        {
            "sprint_id": sprint_id,
            "status": payload["status"],
            "exit_code": payload["exit_code"],
        },
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(dispatch_result_path))
    return 0
def cmd_agile_retrospective(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1
    if args.velocity_planned < 0:
        print("Error: --velocity-planned must be >= 0", file=sys.stderr)
        return 1
    if args.velocity_completed < 0:
        print("Error: --velocity-completed must be >= 0", file=sys.stderr)
        return 1

    succeeded = _split_csv_values(args.succeeded) if args.succeeded else []

    try:
        failed = _parse_agile_failed_items(args.failed)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sprint_id = f"S{args.sprint:02d}"
    velocity_rate = 0 if args.velocity_planned == 0 else round(
        args.velocity_completed / args.velocity_planned,
        4,
    )
    limitations_normalized = str(args.limitations).strip() if args.limitations else ""
    payload = {
        "sprint_id": sprint_id,
        "status": str(args.status),
        "succeeded": succeeded,
        "failed": failed,
        "velocity": {
            "planned": int(args.velocity_planned),
            "completed": int(args.velocity_completed),
            "rate": velocity_rate,
        },
        "known_limitations": limitations_normalized,
        "lessons_learned": str(args.lessons),
        "direction": str(args.direction),
        "timestamp": _now_iso(),
    }

    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    retrospective_path = sprint_dir / "retrospective.json"
    save_json(retrospective_path, payload)
    known_issues = [
        issue
        for issue in _load_agile_known_issues(agi_id)
        if str(issue.get("status", "")).strip().lower() == "open"
    ]

    succeeded_lines = "\n".join(f"- {item}" for item in succeeded) if succeeded else "- 없음"
    failed_lines = (
        "\n".join(
            (
                f"- 시도한 접근: {entry.get('tried_approach', '-')}"
                f" | 실패 원인: {entry.get('failure_reason', '-')}"
            )
            for entry in failed
        )
        if failed
        else "- 없음"
    )
    known_issue_lines = (
        "\n".join(
            (
                f"- {str(issue.get('id', '-')).upper()} "
                f"[{str(issue.get('severity', '-')).upper()}] "
                f"{str(issue.get('description', '-')).strip()} "
                f"(sprint: {str(issue.get('sprint_id', '-')).strip()}, status: {str(issue.get('status', '-')).strip()})"
            )
            for issue in known_issues
        )
        if known_issues
        else "- 없음"
    )
    template_path = _plugin_root() / "templates" / "retrospective.md"
    try:
        template_content = template_path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"Error: retrospective template not found: {template_path} ({e})", file=sys.stderr)
        return 1
    replacements = {
        "SPRINT_ID": sprint_id,
        "STATUS": str(payload["status"]),
        "TIMESTAMP": str(payload["timestamp"]),
        "SUCCEEDED_ITEMS": succeeded_lines,
        "FAILED_ITEMS": failed_lines,
        "VELOCITY_PLANNED": str(payload["velocity"]["planned"]),
        "VELOCITY_COMPLETED": str(payload["velocity"]["completed"]),
        "VELOCITY_RATE": str(payload["velocity"]["rate"]),
        "KNOWN_LIMITATIONS": str(payload["known_limitations"]) or "없음",
        "LESSONS_LEARNED": str(payload["lessons_learned"]),
        "DIRECTION": str(payload["direction"]),
        "KNOWN_ISSUES": known_issue_lines,
    }
    retrospective_md_content = template_content
    for key, value in replacements.items():
        retrospective_md_content = retrospective_md_content.replace(f"{{{{{key}}}}}", value)
    (sprint_dir / "retrospective.md").write_text(retrospective_md_content, encoding="utf-8")

    _append_agile_event(
        agi_id,
        "agile.retrospective",
        {
            "sprint_id": sprint_id,
            "status": payload["status"],
        },
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(retrospective_path))
    return 0
def cmd_agile_known_issues_add(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    description = str(args.description).strip()
    if not description:
        print("Error: --description is required", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    issue = {
        "id": _next_known_issue_id(issues),
        "description": description,
        "severity": str(args.severity).strip().upper(),
        "sprint_id": f"S{args.sprint:02d}",
        "status": "open",
        "created_at": _now_iso(),
    }
    issues.append(issue)
    save_json(_agi_known_issues_path(agi_id), issues)
    _append_agile_event(
        agi_id,
        "agile.known-issues.add",
        {
            "issue_id": issue["id"],
            "severity": issue["severity"],
            "status": issue["status"],
        },
    )

    if args.json:
        print(json.dumps(issue, ensure_ascii=False, indent=2))
    else:
        print(issue["id"])
    return 0
def cmd_agile_known_issues_resolve(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
        issue_id = _normalize_known_issue_id(args.issue_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    target_issue = None
    changed = False
    for issue in issues:
        normalized_id = str(issue.get("id", "")).strip().upper()
        if normalized_id != issue_id:
            continue
        target_issue = issue
        if str(issue.get("status", "")).strip().lower() != "resolved":
            issue["status"] = "resolved"
            issue["resolved_at"] = _now_iso()
            changed = True
        elif "resolved_at" not in issue:
            issue["resolved_at"] = _now_iso()
            changed = True
        break

    if target_issue is None:
        print(f"Error: known issue not found ({issue_id})", file=sys.stderr)
        return 1

    if changed:
        save_json(_agi_known_issues_path(agi_id), issues)

    _append_agile_event(
        agi_id,
        "agile.known-issues.resolve",
        {
            "issue_id": issue_id,
            "status": "resolved",
        },
    )

    if args.json:
        print(json.dumps(target_issue, ensure_ascii=False, indent=2))
    else:
        print(issue_id)
    return 0
def cmd_agile_known_issues_list(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    if args.status:
        status_filter = str(args.status).strip().lower()
        issues = [
            issue
            for issue in issues
            if str(issue.get("status", "")).strip().lower() == status_filter
        ]

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return 0

    for issue in issues:
        print(
            (
                f"{str(issue.get('id', '')).strip().upper()}\t"
                f"{str(issue.get('status', '')).strip().lower()}\t"
                f"{str(issue.get('severity', '')).strip().upper()}\t"
                f"{str(issue.get('sprint_id', '')).strip()}\t"
                f"{str(issue.get('description', '')).strip()}"
            )
        )
    return 0
def cmd_agile_known_issues(args):
    subcommand = getattr(args, "known_issues_subcommand", None)
    dispatch = {
        "add": cmd_agile_known_issues_add,
        "resolve": cmd_agile_known_issues_resolve,
        "list": cmd_agile_known_issues_list,
    }
    fn = dispatch.get(subcommand)
    if fn is None:
        print("Error: known-issues subcommand is required (add|resolve|list)", file=sys.stderr)
        return 1
    return fn(args)
def cmd_agile_review(args):
    perspective = str(args.perspective).strip()
    enabled_status = _validate_adversarial_review_enabled(perspective)
    if enabled_status:
        return enabled_status

    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    draft_dir_arg = str(getattr(args, "draft_dir", "") or "").strip()
    draft_dir = Path(draft_dir_arg).expanduser() if draft_dir_arg else None
    if draft_dir is not None and not draft_dir.is_absolute():
        draft_dir = (Path.cwd() / draft_dir).resolve()
    if draft_dir is not None:
        draft_objective = draft_dir / "objective.md"
        if not draft_objective.exists() or not draft_objective.is_file():
            print(f"Error: draft objective not found: {draft_objective}", file=sys.stderr)
            return 1
        context_files = [draft_objective]
        draft_details = draft_dir / "details"
        if draft_details.exists() and draft_details.is_dir():
            context_files.extend(sorted(draft_details.glob("*.md")))
        return _emit_adversarial_review_payload(
            context_files,
            perspective,
            context_source="draft",
            draft_dir=draft_dir,
        )

    if not objective_path.exists():
        print(f"Error: objective not found: {objective_path}", file=sys.stderr)
        return 1

    context_files = [objective_path]
    details_dir = objective_path.parent / "details"
    if details_dir.exists():
        context_files.extend(sorted(details_dir.glob("*.md")))

    return _emit_adversarial_review_payload(context_files, perspective)
