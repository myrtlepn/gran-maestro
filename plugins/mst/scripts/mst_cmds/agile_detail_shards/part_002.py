def cmd_agile_drift_check(args):
    sprint_id = None
    if args.sprint:
        try:
            sprint_id = _normalize_sprint_id_token(str(args.sprint))
        except ValueError as exc:
            payload = {
                "status": "FAIL",
                "warn_level": "WARN",
                "sprint_id": None,
                "agi_id": None,
                "details_dir": None,
                "objective_path": None,
                "threshold": None,
                "warn_streak_limit": 2,
                "drift_score": None,
                "surface_total": 0,
                "covered_surface": [],
                "uncovered_surface": [],
                "warn_streak": 0,
                "escalate_flag": False,
                "ledger_path": str(_agile_state_ledger_path()),
                "checked_files": [],
                "warnings": [],
                "errors": [str(exc)],
            }
            _emit_drift_check_payload(payload, args.json)
            print(str(exc), file=sys.stderr)
            return 1

    drift_cfg = _load_agile_drift_config()
    enabled = bool(drift_cfg.get("enabled", True))
    try:
        warn_streak_limit = int(drift_cfg.get("warn_streak_limit", 2))
    except (TypeError, ValueError):
        warn_streak_limit = 2
    if warn_streak_limit < 1:
        warn_streak_limit = 2

    payload = {
        "status": "SKIP",
        "warn_level": "WARN",
        "sprint_id": sprint_id,
        "agi_id": None,
        "details_dir": None,
        "objective_path": None,
        "threshold": drift_cfg.get("threshold"),
        "warn_streak_limit": warn_streak_limit,
        "drift_score": None,
        "surface_total": 0,
        "covered_surface": [],
        "uncovered_surface": [],
        "warn_streak": 0,
        "escalate_flag": False,
        "ledger_path": str(_agile_state_ledger_path()),
        "checked_files": [],
        "warnings": [],
        "errors": [],
    }

    if not enabled:
        payload["warnings"].append("drift-check skipped: agile.drift.enabled=false")
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0

    threshold_raw = drift_cfg.get("threshold")
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        threshold = None
    if threshold is None:
        payload["warnings"].append("drift-check skipped: agile.drift.threshold is missing")
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0
    if threshold < 0.0 or threshold > 1.0:
        payload["warnings"].append("drift-check skipped: agile.drift.threshold must be between 0 and 1")
        payload["threshold"] = threshold
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0
    payload["threshold"] = threshold

    try:
        agi_id, details_dir, objective_path = _resolve_drift_check_target(args)
    except ValueError as exc:
        payload["status"] = "FAIL"
        payload["errors"].append(str(exc))
        _emit_drift_check_payload(payload, args.json)
        print(str(exc), file=sys.stderr)
        return 1

    payload["agi_id"] = agi_id
    payload["details_dir"] = str(details_dir)
    payload["objective_path"] = str(objective_path)

    if not details_dir.exists():
        reason = f"details dir not found: {details_dir}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1
    if not details_dir.is_dir():
        reason = f"details dir is not a directory: {details_dir}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1
    if not objective_path.exists():
        reason = f"objective file missing: {objective_path}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    try:
        objective_content = objective_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"failed to read objective: {exc}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    surface_entries = _extract_objective_surface_entries(objective_content)
    payload["surface_total"] = len(surface_entries)
    if not surface_entries:
        payload["warnings"].append("objective surface not found (JTBD + Project DoD)")

    corpus_tokens, detail_files, detail_warnings = _collect_drift_corpus_tokens(details_dir)
    payload["checked_files"] = [_relpath_display(path, _common.BASE_DIR.parent) for path in detail_files]
    payload["warnings"].extend(detail_warnings)
    if not detail_files:
        payload["warnings"].append(f"no detail files found: {details_dir}")

    covered_surface, uncovered_surface = _compute_drift_surface_coverage(surface_entries, corpus_tokens)
    drift_score = (len(covered_surface) / len(surface_entries)) if surface_entries else 0.0
    warn_level = "PASS" if surface_entries and drift_score >= threshold else "WARN"

    existing_entries = _load_agile_state_ledger_entries()
    prev_warn_streak = _previous_drift_warn_streak(existing_entries)
    warn_streak = (prev_warn_streak + 1) if warn_level == "WARN" else 0
    escalate_flag = warn_level == "WARN" and warn_streak >= warn_streak_limit

    ledger_entry = {
        "timestamp": _now_iso(),
        "agi_id": agi_id,
        "sprint_id": sprint_id,
        "drift_score": drift_score,
        "covered_surface": covered_surface,
        "uncovered_surface": uncovered_surface,
        "warn_level": warn_level,
        "warn_streak": warn_streak,
        "escalate_flag": escalate_flag,
    }
    _append_agile_state_ledger_entry(ledger_entry)

    payload.update(
        {
            "status": warn_level,
            "warn_level": warn_level,
            "drift_score": drift_score,
            "covered_surface": covered_surface,
            "uncovered_surface": uncovered_surface,
            "warn_streak": warn_streak,
            "escalate_flag": escalate_flag,
        }
    )
    if escalate_flag:
        payload["warnings"].append("warn streak limit reached; ESCALATE")

    _emit_drift_check_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    return 0
def cmd_agile_evidence_check(args):
    sprint_id = None
    if args.sprint:
        try:
            sprint_id = _normalize_sprint_id_token(str(args.sprint))
        except ValueError as exc:
            payload = {
                "status": "FAIL",
                "tier": "FAIL",
                "gate_enabled": False,
                "sprint_id": None,
                "agi_id": None,
                "details_dir": None,
                "project_root": str(_common.BASE_DIR.parent),
                "checked_files": [],
                "warnings": [],
                "violations": [str(exc)],
                "required_globs": {"project_type": "plugin", "patterns": [], "matches": {}},
                "bypass_reason": None,
            }
            _emit_evidence_check_payload(payload, args.json)
            print(str(exc), file=sys.stderr)
            return 1

    evidence_gate_cfg = _load_agile_evidence_gate_config()
    gate_enabled = bool(evidence_gate_cfg.get("enabled", True))
    project_root = _common.BASE_DIR.parent

    payload = {
        "status": "FAIL",
        "tier": "FAIL",
        "gate_enabled": gate_enabled,
        "sprint_id": sprint_id,
        "agi_id": None,
        "details_dir": None,
        "project_root": str(project_root),
        "checked_files": [],
        "warnings": [],
        "violations": [],
        "required_globs": {"project_type": "plugin", "patterns": [], "matches": {}},
        "bypass_reason": None,
    }

    if not gate_enabled:
        payload["status"] = "WARN"
        payload["tier"] = "WARN"
        payload["warnings"].append("evidence gate disabled by config (agile.evidence_gate.enabled=false)")
        _emit_evidence_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0

    try:
        agi_id, details_dir = _resolve_evidence_check_target(args)
    except ValueError as exc:
        payload["violations"].append(str(exc))
        _emit_evidence_check_payload(payload, args.json)
        print(str(exc), file=sys.stderr)
        return 1

    payload["agi_id"] = agi_id
    payload["details_dir"] = str(details_dir)

    if not details_dir.exists():
        payload["violations"].append(f"details dir not found: {details_dir}")
        _emit_evidence_check_payload(payload, args.json)
        print(payload["violations"][-1], file=sys.stderr)
        return 1
    if not details_dir.is_dir():
        payload["violations"].append(f"details dir is not a directory: {details_dir}")
        _emit_evidence_check_payload(payload, args.json)
        print(payload["violations"][-1], file=sys.stderr)
        return 1

    project_type, required_globs = _resolve_required_globs_config(evidence_gate_cfg)
    payload["required_globs"]["project_type"] = project_type
    payload["required_globs"]["patterns"] = list(required_globs)

    if not required_globs:
        payload["warnings"].append("required_globs not configured; contract artifact check skipped")

    required_matches = {}
    for pattern in required_globs:
        matched = [path for path in project_root.glob(pattern) if path.is_file()]
        required_matches[pattern] = [_relpath_display(path, project_root) for path in matched]
        if not matched:
            payload["violations"].append(f"required_globs unsatisfied: {pattern}")
    payload["required_globs"]["matches"] = required_matches

    detail_files = sorted(details_dir.glob("*.md"))
    if not detail_files:
        payload["violations"].append(f"no detail files found: {details_dir}")

    for detail_file in detail_files:
        detail_label = _relpath_display(detail_file, project_root)
        payload["checked_files"].append(detail_label)
        try:
            content = detail_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            payload["violations"].append(f"{detail_label}: failed to read detail ({exc})")
            continue

        parsed = parse_agile_detail_metadata(content)
        validation = validate_agile_detail_evidence(parsed)

        for warning in validation.get("warnings", []):
            payload["warnings"].append(f"{detail_label}: {warning}")
        for error in validation.get("errors", []):
            payload["violations"].append(f"{detail_label}: {error}")

        if not validation.get("valid"):
            continue

        evidence = validation.get("evidence") if isinstance(validation.get("evidence"), dict) else {}
        plan = evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {}
        runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else {}

        artifacts = plan.get("artifact_paths") if isinstance(plan.get("artifact_paths"), list) else []
        for artifact in artifacts:
            artifact_token = str(artifact).strip()
            if not artifact_token:
                continue
            matches = _resolve_project_matches(project_root, artifact_token)
            if not matches:
                payload["violations"].append(f"{detail_label}: artifact missing: {artifact_token}")

        entrypoint_path = str(plan.get("entrypoint_path") or "").strip()
        if entrypoint_path:
            entrypoint_file = entrypoint_path.split(":", 1)[0].strip()
            if entrypoint_file and not _resolve_project_matches(project_root, entrypoint_file):
                payload["violations"].append(f"{detail_label}: entrypoint missing: {entrypoint_file}")

        for field in ("integration_smoke_id", "verify_cmd", "expected_signal"):
            normalized = _normalize_tbd(runtime.get(field))
            if normalized == "TBD":
                payload["warnings"].append(f"{detail_label}: {field} is TBD")

    if payload["violations"]:
        payload["tier"] = "FAIL"
    elif payload["warnings"]:
        payload["tier"] = "WARN"
    else:
        payload["tier"] = "PASS"

    bypass_reason = str(args.accept_evidence_gap or "").strip()
    if payload["tier"] == "FAIL" and bypass_reason:
        payload["status"] = "BYPASSED"
        payload["bypass_reason"] = bypass_reason
        _append_agile_sprint_log(
            {
                "timestamp": _now_iso(),
                "event": "evidence-gap-accepted",
                "reason": bypass_reason,
                "agi_id": agi_id,
                "sprint_id": sprint_id,
                "details_dir": str(details_dir),
                "violations": list(payload["violations"]),
            }
        )
        _emit_evidence_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        for violation in payload["violations"]:
            print(str(violation), file=sys.stderr)
        return 0

    payload["status"] = payload["tier"]
    _emit_evidence_check_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    for violation in payload["violations"]:
        print(str(violation), file=sys.stderr)
    return 1 if payload["status"] == "FAIL" else 0
def cmd_agile_detail_validate_mapping(args):
    details_path = str(args.details_path)
    details_file = Path(details_path)
    if not details_file.exists():
        payload = _source_mapping_failure_payload(details_path, f"file not found: {details_path}")
        _emit_source_mapping_payload(payload, args.json)
        return 1
    if not details_file.is_file():
        payload = _source_mapping_failure_payload(details_path, f"not a file: {details_path}")
        _emit_source_mapping_payload(payload, args.json)
        return 1

    try:
        content = details_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload = _source_mapping_failure_payload(details_path, f"failed to read file: {exc}")
        _emit_source_mapping_payload(payload, args.json)
        return 1

    parsed = parse_source_mapping(content)
    payload = {
        "path": details_path,
        "original": parsed.get("original"),
        "source_type": parsed.get("source_type"),
        "evidence": parsed.get("evidence"),
        "skip_reason": parsed.get("skip_reason"),
        "sections": parsed.get("sections", []),
        "valid": bool(parsed.get("valid")),
        "errors": parsed.get("errors", []),
    }
    _emit_source_mapping_payload(payload, args.json)
    return 0 if payload["valid"] else 1
def cmd_agile_detail_validate_evidence(args):
    details_path = str(args.details_path)
    details_file = Path(details_path)
    if not details_file.exists():
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, f"file not found: {details_path}"),
            "evidence": {},
            "warnings": [],
            "errors": [f"file not found: {details_path}"],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(payload["errors"][0], file=sys.stderr)
        return 1
    if not details_file.is_file():
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, f"not a file: {details_path}"),
            "evidence": {},
            "warnings": [],
            "errors": [f"not a file: {details_path}"],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(payload["errors"][0], file=sys.stderr)
        return 1

    try:
        content = details_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"failed to read file: {exc}"
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, reason),
            "evidence": {},
            "warnings": [],
            "errors": [reason],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    parsed = parse_agile_detail_metadata(content)
    validation = validate_agile_detail_evidence(parsed)
    payload = {
        "path": details_path,
        "valid": bool(validation.get("valid")),
        "legacy": bool(validation.get("legacy")),
        "source_mapping": parsed.get("source_mapping"),
        "evidence": validation.get("evidence"),
        "warnings": validation.get("warnings", []),
        "errors": validation.get("errors", []),
    }
    _emit_evidence_validation_payload(payload, args.json)

    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    for error in payload["errors"]:
        print(str(error), file=sys.stderr)

    return 0 if payload["valid"] else 1
def cmd_agile_detail_append(args):
    target_dir = Path(str(args.target_dir)).resolve()
    target_path = target_dir / f"{args.domain}.md"
    chunk_id = int(args.chunk_id)
    content_path = Path(str(args.content_file))
    if not content_path.exists():
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"content-file not found: {content_path}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1
    if not content_path.is_file():
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"content-file not found: {content_path}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1

    try:
        content = content_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"failed to read content-file: {exc}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1

    payload = apply_chunk_append(target_path, chunk_id, content)
    _emit_chunk_append_payload(payload, args.json)
    return 0 if payload.get("valid") else 1
def cmd_agile_detail_generate_anchors(args):
    details_dir = Path(str(args.details_dir)).resolve()
    output_path = Path(str(args.output)).resolve() if getattr(args, "output", None) else None
    payload = build_objective_anchor_manifest(details_dir, output_path)

    if payload.get("valid"):
        manifest_path = Path(str(payload["manifest_path"]))
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(payload.get("anchors") or [], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            payload["valid"] = False
            payload.setdefault("errors", []).append(f"failed to write manifest: {exc}")

    _emit_anchor_manifest_payload(payload, args.json)
    for error in payload.get("errors") or []:
        print(str(error), file=sys.stderr)
    return 0 if payload.get("valid") else 1
def cmd_agile_detail(args):
    subcommand = getattr(args, "detail_subcommand", None)
    dispatch = {
        "validate-mapping": cmd_agile_detail_validate_mapping,
        "validate-evidence": cmd_agile_detail_validate_evidence,
        "append": cmd_agile_detail_append,
        "generate-anchors": cmd_agile_detail_generate_anchors,
    }
    fn = dispatch.get(subcommand)
    if fn is None:
        print("Error: detail subcommand is required (validate-mapping|validate-evidence|append|generate-anchors)", file=sys.stderr)
        return 1
    return fn(args)
_SIDECAR_SCHEMA_VERSION = 1
_SIDECAR_SCHEMAS = [
    {
        "name": "objective_anchor_manifest",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/objective.ids.json",
        "format": "json_array",
        "required_fields": ["id", "source_file", "text", "kind", "grade", "domain_slug", "dod_refs"],
        "producer": "mst.py agile detail generate-anchors --details-dir ...",
        "consumer": "mst.py agile coverage-check --anchor-manifest ...; downstream context handoff",
        "missing_behavior": "fail_objective_completion",
        "invalid_behavior": "fail_objective_completion",
        "required_for_completion": True,
        "min_items": 1,
    },
    {
        "name": "handoff_manifest",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/handoff-manifest.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "context_files", "skip_reasons", "created_at"],
        "producer": "mst.py agile sidecar-build",
        "consumer": "mst:agile, mst:request, mst:approve",
        "missing_behavior": "missing_context_non_success",
        "invalid_behavior": "fail_downstream_handoff",
        "required_for_completion": True,
    },
    {
        "name": "review_findings",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/adversarial-review-findings.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "rounds", "findings", "unresolved_blocking_count"],
        "producer": "mst.py agile sidecar-build",
        "consumer": "mst.py agile objective-check; sprint completion report",
        "missing_behavior": "fail_objective_completion",
        "invalid_behavior": "fail_objective_completion",
        "required_for_completion": True,
    },
    {
        "name": "finding_trace_manifest",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/finding-trace.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "findings", "unmapped_major_or_higher_count"],
        "producer": "mst.py agile sidecar-build",
        "consumer": "mst.py agile objective-check; downstream implementation report",
        "missing_behavior": "fail_objective_completion",
        "invalid_behavior": "fail_objective_completion",
        "required_for_completion": True,
    },
    {
        "name": "section_review_inventory",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/section-review-inventory.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "sections", "unreviewed_required_count"],
        "producer": "mst.py agile sidecar-build",
        "consumer": "mst.py agile objective-check",
        "missing_behavior": "fail_objective_completion",
        "invalid_behavior": "fail_objective_completion",
        "required_for_completion": True,
    },
    {
        "name": "d3_detail_results",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/d3-findings.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "threshold", "details", "blocking_count"],
        "producer": "mst.py agile sidecar-build",
        "consumer": "mst.py agile objective-check; completion report",
        "missing_behavior": "missing_context_non_success",
        "invalid_behavior": "fail_objective_completion",
        "required_for_completion": True,
    },
    {
        "name": "reference_links",
        "path_template": ".gran-maestro/agile/{agi_id}/objective/reference-links.json",
        "format": "json_object",
        "required_fields": ["schema_version", "agi_id", "references", "unlinked_reference_count"],
        "producer": "mst.py reference add + agile reference linker",
        "consumer": "objective reference section; downstream context handoff",
        "missing_behavior": "explicit_no_references_or_missing_context",
        "invalid_behavior": "fail_reference_handoff",
        "required_for_completion": False,
    },
    {
        "name": "state_snapshot",
        "path_template": ".gran-maestro/state/{mst_session_id}/snapshot.json",
        "format": "json_object",
        "required_fields": ["schema_version", "mst_session_id", "root_mst_id", "workflow", "history"],
        "producer": "MST_SESSION_ID=... mst.py state set ...",
        "consumer": "stop hook, resume, dashboard",
        "missing_behavior": "structured_non_success_when_canonical_identity_missing",
        "invalid_behavior": "fail_resume_state_validation",
        "required_for_completion": True,
    },
]
def _render_sidecar_schema_entry(schema: dict, agi_id: str | None, mst_session_id: str | None) -> dict:
    entry = dict(schema)
    path_template = str(schema.get("path_template") or "")
    rendered = path_template
    if agi_id:
        rendered = rendered.replace("{agi_id}", agi_id)
    if mst_session_id:
        rendered = rendered.replace("{mst_session_id}", mst_session_id)
    if _common.BASE_DIR.name == ".gran-maestro" and rendered.startswith(".gran-maestro/"):
        rendered = rendered[len(".gran-maestro/") :]
    entry["path"] = str(_common.BASE_DIR / rendered) if "{" not in rendered else None
    return entry
def _resolve_manifest_context_path(path_value: str) -> Path:
    candidate = Path(str(path_value)).expanduser()
    if candidate.is_absolute():
        return candidate
    return _common.BASE_DIR.parent / candidate
def _validate_handoff_manifest_payload(payload: dict, result: dict) -> None:
    context_files = payload.get("context_files")
    skip_reasons = payload.get("skip_reasons")
    if not isinstance(context_files, list):
        result["errors"].append("context_files must be a list")
        context_files = []
    elif not context_files:
        result["errors"].append("context_files must not be empty")
    if not isinstance(skip_reasons, list):
        result["errors"].append("skip_reasons must be a list")
        skip_reasons = []

    seen_kinds: set[str] = set()
    skipped_kinds: set[str] = set()
    has_objective = False
    has_anchor_manifest = False
    has_detail = False

    for index, item in enumerate(context_files):
        if not isinstance(item, dict):
            result["errors"].append(f"context_files item {index} must be an object")
            continue
        raw_path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not raw_path:
            result["errors"].append(f"context_files item {index} missing path")
            continue
        if not kind:
            result["errors"].append(f"context_files item {index} missing kind")
        else:
            seen_kinds.add(kind)
        resolved = _resolve_manifest_context_path(raw_path)
        if not resolved.is_file():
            result["errors"].append(f"context_files item {index} path not found: {raw_path}")
        if raw_path.endswith("objective.md"):
            has_objective = True
        if raw_path.endswith("objective.ids.json"):
            has_anchor_manifest = True
        if "/details/" in raw_path and raw_path.endswith(".md"):
            has_detail = True

    for index, item in enumerate(skip_reasons):
        if not isinstance(item, dict):
            result["errors"].append(f"skip_reasons item {index} must be an object")
            continue
        kind = str(item.get("kind") or "").strip()
        raw_path = str(item.get("path") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not kind and not raw_path:
            result["errors"].append(f"skip_reasons item {index} missing kind or path")
        if not reason:
            result["errors"].append(f"skip_reasons item {index} missing reason")
        if kind:
            skipped_kinds.add(kind)

    if not has_objective:
        result["errors"].append("handoff manifest missing objective.md context file")
    if not has_anchor_manifest:
        result["errors"].append("handoff manifest missing objective.ids.json context file")
    if not has_detail:
        result["errors"].append("handoff manifest missing detail context file")
    for expected_kind in ("design", "references", "previous_feedback"):
        if expected_kind not in seen_kinds and expected_kind not in skipped_kinds:
            result["errors"].append(f"handoff manifest missing context or skip reason for {expected_kind}")
def _validate_json_sidecar(path: Path, schema: dict) -> dict:
    result = {
        "path": str(path),
        "exists": path.exists(),
        "valid": False,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append(f"missing sidecar: {schema.get('name')}")
        return result
    if not path.is_file():
        result["errors"].append(f"sidecar is not a file: {path}")
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"].append(f"failed to read JSON sidecar: {exc}")
        return result

    required_fields = list(schema.get("required_fields") or [])
    if schema.get("format") == "json_array":
        if not isinstance(payload, list):
            result["errors"].append("sidecar must be a JSON array")
            return result
        min_items = int(schema.get("min_items") or 0)
        if len(payload) < min_items:
            result["errors"].append(f"sidecar must contain at least {min_items} item(s)")
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                result["errors"].append(f"item {index} must be an object")
                continue
            missing = [field for field in required_fields if field not in item]
            if missing:
                result["errors"].append(f"item {index} missing fields: {', '.join(missing)}")
    elif schema.get("format") == "json_object":
        if not isinstance(payload, dict):
            result["errors"].append("sidecar must be a JSON object")
            return result
        missing = [field for field in required_fields if field not in payload]
        if missing:
            result["errors"].append(f"missing fields: {', '.join(missing)}")
        for count_field in (
            "unresolved_blocking_count",
            "unmapped_major_or_higher_count",
            "unreviewed_required_count",
            "blocking_count",
            "unlinked_reference_count",
        ):
            if count_field not in required_fields:
                continue
            raw_count = payload.get(count_field)
            if not isinstance(raw_count, int) or isinstance(raw_count, bool):
                result["errors"].append(f"{count_field} must be an integer")
                continue
            if raw_count != 0:
                result["errors"].append(f"{count_field} must be 0")
        if schema.get("name") == "handoff_manifest":
            _validate_handoff_manifest_payload(payload, result)
    else:
        result["errors"].append(f"unsupported sidecar format: {schema.get('format')}")

    result["valid"] = not result["errors"]
    return result
def _load_agile_mst_session_id(agi_id: str | None) -> str | None:
    if not agi_id:
        return None
    try:
        session, _ = _load_agile_session(agi_id)
    except ValueError:
        return None
    value = session.get("mst_session_id") if isinstance(session, dict) else None
    return str(value).strip() if isinstance(value, str) and value.strip() else None
def build_sidecar_schema_payload(agi_id: str | None = None, mst_session_id: str | None = None, validate_existing: bool = False) -> dict:
    normalized_agi_id = _normalize_agi_id(agi_id) if agi_id else None
    normalized_mst_session_id = str(mst_session_id or "").strip() or _load_agile_mst_session_id(normalized_agi_id)
    entries = [
        _render_sidecar_schema_entry(schema, normalized_agi_id, normalized_mst_session_id)
        for schema in _SIDECAR_SCHEMAS
    ]
    payload = {
        "schema_version": _SIDECAR_SCHEMA_VERSION,
        "agi_id": normalized_agi_id,
        "mst_session_id": normalized_mst_session_id,
        "sidecars": entries,
        "valid": True,
        "errors": [],
    }
    if not validate_existing:
        return payload

    validations = []
    for entry in entries:
        path = entry.get("path")
        if path is None:
            result = {
                "name": entry.get("name"),
                "path": None,
                "exists": False,
                "valid": False,
                "errors": [f"cannot validate unresolved path: {entry.get('path_template')}"],
            }
        else:
            result = _validate_json_sidecar(Path(path), entry)
            result["name"] = entry.get("name")
        validations.append(result)
        if entry.get("required_for_completion") and not result.get("valid"):
            payload["valid"] = False
            payload["errors"].extend(f"{entry.get('name')}: {err}" for err in result.get("errors", []))
    payload["validations"] = validations
    return payload
def _emit_sidecar_schema_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    print(f"Schema version: {payload.get('schema_version')}")
    print(f"AGI: {payload.get('agi_id') or '-'}")
    print(f"Valid: {'true' if payload.get('valid') else 'false'}")
    for sidecar in payload.get("sidecars") or []:
        print(f"- {sidecar.get('name')}: {sidecar.get('path') or sidecar.get('path_template')}")
    for error in payload.get("errors") or []:
        print(f"ERROR: {error}", file=sys.stderr)
def cmd_agile_sidecar_schema(args):
    mst_session_id = str(getattr(args, "mst_session_id", "") or "").strip() or None
    payload = build_sidecar_schema_payload(
        getattr(args, "agi_id", None),
        mst_session_id=mst_session_id,
        validate_existing=bool(getattr(args, "validate_existing", False)),
    )
    _emit_sidecar_schema_payload(payload, getattr(args, "json", False))
    return 0 if payload.get("valid") else 1
def _sidecar_schema_by_name(name: str) -> dict | None:
    for schema in _SIDECAR_SCHEMAS:
        if schema.get("name") == name:
            return schema
    return None
def _objective_sidecar_path(agi_id: str, sidecar_name: str, mst_session_id: str | None = None) -> Path:
    schema = _sidecar_schema_by_name(sidecar_name)
    if schema is None:
        raise ValueError(f"unknown sidecar: {sidecar_name}")
    rendered = _render_sidecar_schema_entry(schema, agi_id, mst_session_id).get("path")
    if not rendered:
        raise ValueError(f"cannot resolve sidecar path: {sidecar_name}")
    return Path(str(rendered))
def _write_sidecar_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def _rel_to_project(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_common.BASE_DIR.parent.resolve()))
    except ValueError:
        return str(path)
def _load_json_sidecar(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
def _objective_root_for_sidecars(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective"
def _detail_files_for_sidecars(agi_id: str) -> list[Path]:
    details_dir = _objective_root_for_sidecars(agi_id) / "details"
    return sorted(details_dir.glob("*.md")) if details_dir.exists() else []
def _dod_refs_for_detail_file(path: Path) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return sorted(set(_ANCHOR_DOD_RE.findall(content)))
_REFERENCE_ID_RE = re.compile(r"\bREF-\d+\b", re.IGNORECASE)
def _collect_reference_mentions(agi_id: str) -> dict[str, list[str]]:
    objective_root = _objective_root_for_sidecars(agi_id)
    candidates = [objective_root / "objective.md"] + _detail_files_for_sidecars(agi_id)
    mentions: dict[str, list[str]] = {}
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _REFERENCE_ID_RE.findall(content):
            ref_id = match.upper()
            rel_path = _rel_to_project(path)
            mentions.setdefault(ref_id, [])
            if rel_path not in mentions[ref_id]:
                mentions[ref_id].append(rel_path)
    return mentions
def _build_reference_links_payload(agi_id: str) -> dict:
    from scripts.mst_cmds import reference as _reference

    mentions = _collect_reference_mentions(agi_id)
    config = _reference._load_reference_config()
    references = []
    unlinked_count = 0
    for ref_id, linked_paths in sorted(mentions.items()):
        ref_path = _common.BASE_DIR / "references" / ref_id / "reference.json"
        ref_payload = load_json(ref_path)
        if not isinstance(ref_payload, dict):
            references.append(
                {
                    "ref_id": ref_id,
                    "linked_paths": linked_paths,
                    "status": "missing_reference",
                }
            )
            unlinked_count += 1
            continue
        references.append(
            {
                "ref_id": ref_id,
                "topic": str(ref_payload.get("topic") or ""),
                "url": str(ref_payload.get("url") or ""),
                "freshness": _reference._check_reference_freshness(ref_payload, config=config),
                "linked_paths": linked_paths,
                "status": "linked",
            }
        )
    skip_reasons = []
    if not references:
        skip_reasons.append(
            {
                "kind": "references",
                "reason": "no_explicit_reference_ids_in_objective_context",
            }
        )
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "references": references,
        "unlinked_reference_count": unlinked_count,
        "skip_reasons": skip_reasons,
        "reference_config": {
            "auto_search": bool(config.get("auto_search")),
            "cache_ttl_days": config.get("cache_ttl_days"),
            "cutoff_threshold_months": config.get("cutoff_threshold_months"),
            "max_searches_per_step": config.get("max_searches_per_step"),
        },
        "created_at": _now_iso(),
    }
def _anchors_by_dod(anchors) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if not isinstance(anchors, list):
        return mapping
    for item in anchors:
        if not isinstance(item, dict):
            continue
        anchor_id = str(item.get("id") or "").strip()
        if not anchor_id:
            continue
        for dod_ref in item.get("dod_refs") or []:
            token = str(dod_ref or "").strip().upper()
            if token:
                mapping.setdefault(token, []).append(anchor_id)
    return mapping
def _build_handoff_manifest(agi_id: str) -> dict:
    objective_root = _objective_root_for_sidecars(agi_id)
    context_files = []
    skip_reasons = []
    candidates = [
        objective_root / "objective.md",
        objective_root / "objective.ids.json",
    ] + _detail_files_for_sidecars(agi_id)
    for path in candidates:
        if path.exists() and path.is_file():
            context_files.append({"path": _rel_to_project(path), "kind": "objective_context"})
        else:
            skip_reasons.append({"path": _rel_to_project(path), "reason": "missing"})
    optional_context = {
        "design": objective_root / "design.md",
        "references": objective_root / "reference-links.json",
        "previous_feedback": objective_root / "previous-feedback.md",
    }
    for kind, path in optional_context.items():
        if path.exists() and path.is_file():
            context_files.append({"path": _rel_to_project(path), "kind": kind})
        else:
            skip_reasons.append({"kind": kind, "reason": "not_applicable_or_missing"})
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "context_files": context_files,
        "skip_reasons": skip_reasons,
        "created_at": _now_iso(),
    }
_FINDING_RE = re.compile(
    r"^\s*[-*]\s+\*\*(?P<id>F-[A-Za-z0-9_-]+)\s+(?P<severity>critical|high|major|medium|low)\s+(?P<title>[^*]+)\*\*:\s*(?P<summary>.*)$",
    re.IGNORECASE,
)
_BULLET_SEVERITY_RE = re.compile(
    r"^\s*[-*]\s+\*\*(?P<severity>Critical|High|Major|Medium|Low)\s*-\s*(?P<title>[^*]+)\*\*:\s*(?P<summary>.*)$"
)
def _collect_review_findings(agi_id: str) -> list[dict]:
    findings: list[dict] = []
    sequence = 1
    for detail_file in _detail_files_for_sidecars(agi_id):
        try:
            content = detail_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        file_dods = _dod_refs_for_detail_file(detail_file)
        for raw_line in content.splitlines():
            finding_id = None
            severity = None
            title = None
            summary = None
            match = _FINDING_RE.match(raw_line)
            if match:
                finding_id = match.group("id").upper()
                severity = match.group("severity").lower()
                title = match.group("title").strip()
                summary = match.group("summary").strip()
            else:
                match = _BULLET_SEVERITY_RE.match(raw_line)
                if match:
                    finding_id = f"F-LOCAL-{sequence:03d}"
                    sequence += 1
                    severity = match.group("severity").lower()
                    title = match.group("title").strip()
                    summary = match.group("summary").strip()
            if not finding_id:
                continue
            line_dods = sorted(set(_ANCHOR_DOD_RE.findall(raw_line)))
            findings.append(
                {
                    "finding_id": finding_id,
                    "source_id": _rel_to_project(detail_file),
                    "evidence_id": f"{detail_file.stem}:{len(findings) + 1}",
                    "severity": severity,
                    "title": title,
                    "summary": summary,
                    "dod_refs": line_dods or file_dods,
                    "anchor_refs": [],
                    "disposition": "mapped_to_objective",
                }
            )
    return findings
def _build_review_findings_payload(agi_id: str) -> dict:
    findings = _collect_review_findings(agi_id)
    unresolved = [
        item for item in findings
        if str(item.get("severity") or "").lower() in {"critical", "high", "major"}
        and str(item.get("disposition") or "") not in {"mapped_to_objective", "deferred_with_reason", "accepted"}
    ]
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "rounds": [{"id": "sidecar-build", "created_at": _now_iso(), "source": "objective_details"}],
        "findings": findings,
        "unresolved_blocking_count": len(unresolved),
    }
def _build_finding_trace_payload(agi_id: str, review_findings: dict) -> dict:
    anchor_manifest = _load_json_sidecar(_objective_sidecar_path(agi_id, "objective_anchor_manifest"))
    anchor_map = _anchors_by_dod(anchor_manifest)
    traced = []
    unmapped = 0
    for finding in review_findings.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        dod_refs = [str(item).strip().upper() for item in finding.get("dod_refs") or [] if str(item).strip()]
        anchor_refs = sorted({anchor for dod in dod_refs for anchor in anchor_map.get(dod, [])})
        severity = str(finding.get("severity") or "").lower()
        is_major_or_higher = severity in {"critical", "high", "major"}
        if is_major_or_higher and (not dod_refs or not anchor_refs):
            unmapped += 1
        traced_item = dict(finding)
        traced_item["anchor_refs"] = anchor_refs
        traced_item["trace_status"] = "mapped" if dod_refs and anchor_refs else "unmapped"
        traced.append(traced_item)
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "findings": traced,
        "unmapped_major_or_higher_count": unmapped,
    }
def _build_section_review_inventory_payload(agi_id: str, finding_trace: dict) -> dict:
    findings_by_source: dict[str, list[str]] = {}
    for finding in finding_trace.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        source_id = str(finding.get("source_id") or "").strip()
        finding_id = str(finding.get("finding_id") or "").strip()
        if source_id and finding_id:
            findings_by_source.setdefault(source_id, []).append(finding_id)
    sections = []
    objective_path = _agi_objective_path(agi_id)
    if objective_path.exists():
        sections.append(
            {
                "section_id": "objective",
                "path": _rel_to_project(objective_path),
                "required": True,
                "reviewed_by": "sidecar-build",
                "finding_ids": findings_by_source.get(_rel_to_project(objective_path), []),
                "no_issue_reason": "objective parsed; findings are tracked in detail sections",
            }
        )
    for detail_file in _detail_files_for_sidecars(agi_id):
        rel_path = _rel_to_project(detail_file)
        finding_ids = findings_by_source.get(rel_path, [])
        sections.append(
            {
                "section_id": detail_file.stem,
                "path": rel_path,
                "required": True,
                "reviewed_by": "sidecar-build",
                "finding_ids": finding_ids,
                "no_issue_reason": "" if finding_ids else "reviewed with no blocking finding",
            }
        )
    unreviewed = [
        item for item in sections
        if item.get("required") is True and not item.get("reviewed_by")
    ]
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "sections": sections,
        "unreviewed_required_count": len(unreviewed),
    }
def _ambiguity_score_for_detail(content: str) -> tuple[float, list[str]]:
    reasons = []
    lowered = content.lower()
    for token in ("tbd", "todo"):
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            reasons.append(f"contains {token}")
    for token in ("미정", "정의되지 않음"):
        if token in content:
            reasons.append(f"contains {token}")
    nonblank_lines = [line for line in content.splitlines() if line.strip()]
    if len(nonblank_lines) < 8:
        reasons.append("detail is too short")
    score = min(1.0, len(reasons) / 4.0)
    return score, reasons
def _build_d3_results_payload(agi_id: str, threshold: float) -> dict:
    details = []
    blocking_count = 0
    for detail_file in _detail_files_for_sidecars(agi_id):
        try:
            content = detail_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            score = 1.0
            reasons = [f"failed to read detail: {exc}"]
        else:
            score, reasons = _ambiguity_score_for_detail(content)
        passed = score <= threshold
        if not passed:
            blocking_count += 1
        details.append(
            {
                "path": _rel_to_project(detail_file),
                "ambiguity_score": score,
                "pass": passed,
                "reasons": reasons,
            }
        )
    return {
        "schema_version": 1,
        "agi_id": agi_id,
        "threshold": threshold,
        "details": details,
        "blocking_count": blocking_count,
    }
def build_sidecar_artifacts(agi_id: str, *, d3_threshold: float = 0.25, refresh_anchors: bool = False) -> dict:
    normalized_agi_id = _normalize_agi_id(agi_id)
    objective_root = _objective_root_for_sidecars(normalized_agi_id)
    details_dir = objective_root / "details"
    written = []
    errors = []

    anchor_path = _objective_sidecar_path(normalized_agi_id, "objective_anchor_manifest")
    if refresh_anchors or not anchor_path.exists():
        anchor_payload = build_objective_anchor_manifest(details_dir, anchor_path)
        if anchor_payload.get("valid"):
            try:
                _write_sidecar_json(anchor_path, anchor_payload.get("anchors") or [])
                written.append({"name": "objective_anchor_manifest", "path": str(anchor_path)})
            except OSError as exc:
                errors.append(f"objective_anchor_manifest: failed to write: {exc}")
        else:
            errors.extend(f"objective_anchor_manifest: {err}" for err in anchor_payload.get("errors") or [])

    handoff = _build_handoff_manifest(normalized_agi_id)
    review_findings = _build_review_findings_payload(normalized_agi_id)
    finding_trace = _build_finding_trace_payload(normalized_agi_id, review_findings)
    section_inventory = _build_section_review_inventory_payload(normalized_agi_id, finding_trace)
    d3_results = _build_d3_results_payload(normalized_agi_id, d3_threshold)
    reference_links = _build_reference_links_payload(normalized_agi_id)
    sidecar_payloads = {
        "handoff_manifest": handoff,
        "review_findings": review_findings,
        "finding_trace_manifest": finding_trace,
        "section_review_inventory": section_inventory,
        "d3_detail_results": d3_results,
        "reference_links": reference_links,
    }
    for name, payload in sidecar_payloads.items():
        path = _objective_sidecar_path(normalized_agi_id, name)
        try:
            _write_sidecar_json(path, payload)
            written.append({"name": name, "path": str(path)})
        except OSError as exc:
            errors.append(f"{name}: failed to write: {exc}")

    validation = build_sidecar_schema_payload(normalized_agi_id, validate_existing=True)
    return {
        "schema_version": 1,
        "agi_id": normalized_agi_id,
        "written": written,
        "valid": not errors and all(
            item.get("valid") or item.get("name") == "state_snapshot"
            for item in validation.get("validations") or []
            if item.get("name") != "reference_links"
        ),
        "errors": errors,
        "sidecar_schema": validation,
    }
def cmd_agile_sidecar_build(args):
    try:
        payload = build_sidecar_artifacts(
            getattr(args, "agi_id", None),
            d3_threshold=float(getattr(args, "d3_threshold", 0.25)),
            refresh_anchors=bool(getattr(args, "refresh_anchors", False)),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"AGI: {payload.get('agi_id')}")
        print(f"Written: {len(payload.get('written') or [])}")
        for error in payload.get("errors") or []:
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if not payload.get("errors") else 1
def _window_sprint_ids(sprint: int, depth: int) -> List[str]:
    return [f"S{idx:02d}" for idx in range(max(0, sprint - depth + 1), sprint + 1)]
def _load_agile_float_config(key: str, fallback: float) -> float:
    return _load_agile_config_cast(key, fallback, float)
def _git_output(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout
def _resolve_git_window_refs(repo_root: Path, depth: int) -> tuple[str, str]:
    commits = [line.strip() for line in _git_output(repo_root, "rev-list", "--max-count", str(depth + 1), "HEAD").splitlines() if line.strip()]
    if not commits:
        raise RuntimeError("no commits found")
    return (commits[-1] if len(commits) > depth else "4b825dc642cb6eb9a060e54bf8d69288fbee4904", "HEAD")
def _classify_changed_files(repo_root, since_ref, until_ref, reference_pattern=None):
    diff_range = f"{since_ref}..{until_ref}"
    changed = [line.split("\t")[-1].strip() for line in _git_output(repo_root, "diff", "--name-status", "--diff-filter=AM", diff_range).splitlines() if "\t" in line]
    changed = sorted({path for path in changed if path})
    added = {line.strip() for line in _git_output(repo_root, "diff", "--name-only", "--diff-filter=A", diff_range).splitlines() if line.strip()}
    tracked = [line.strip() for line in _git_output(repo_root, "ls-files").splitlines() if line.strip() and not line.startswith(".gran-maestro/")]
    content_cache: dict[str, str] = {}

    def _regex_for(path: str):
        path_obj = Path(path)
        stem_raw = path_obj.stem
        stem = re.escape(stem_raw)
        parent_stem = re.escape(path_obj.parent.name) if stem_raw == "__init__" and path_obj.parent.name else None
        dotted = re.escape(str(Path(path).with_suffix("")).replace("/", "."))
        escaped_path = re.escape(path)
        if reference_pattern:
            try:
                return re.compile(str(reference_pattern).format(module=stem, module_path=dotted, path=escaped_path), flags=re.IGNORECASE)
            except Exception:
                return re.compile(str(reference_pattern), flags=re.IGNORECASE)
        patterns = [
            rf"\bfrom\s+{stem}\b",
            rf"\bimport\s+{stem}\b",
            rf"\bfrom\s+{dotted}\b",
            rf"\bimport\s+{dotted}\b",
            rf"\b{stem}\s*\.\s*(?:register|setup|init|initialize)\s*\(",
            rf"require\([^)]*{stem}[^)]*\)",
            rf"\b{escaped_path}\b",
            rf"\]\({escaped_path}\)",
        ]
        if parent_stem:
            patterns.extend(
                [
                    rf"\bfrom\s+{parent_stem}\b",
                    rf"\bimport\s+{parent_stem}\b",
                    rf"\b{parent_stem}\s*\.\s*(?:register|setup|init|initialize)\s*\(",
                ]
            )
        pattern = "|".join(patterns)
        return re.compile(pattern, flags=re.IGNORECASE)

    def _refs_for(path: str) -> List[str]:
        regex = _regex_for(path)
        refs = []
        for candidate in tracked:
            if candidate == path:
                continue
            if candidate not in content_cache:
                p = repo_root / candidate
                content_cache[candidate] = p.read_text(encoding="utf-8", errors="ignore") if p.exists() and p.is_file() else ""
            text = content_cache[candidate]
            match = regex.search(text)
            if match:
                refs.append(f"{candidate}:{text.count(chr(10), 0, match.start()) + 1}")
        return refs

    modify_files: List[str] = []
    wire_files: List[str] = []
    new_island_files: List[str] = []
    wire_refs: dict[str, List[str]] = {}
    for path in changed:
        if path not in added:
            modify_files.append(path)
            continue
        if path.startswith("tests/"):
            wire_files.append(path)
            wire_refs[path] = ["tests/* 신규 파일은 wire로 분류"]
            continue
        refs = _refs_for(path)
        if refs:
            wire_files.append(path)
            wire_refs[path] = refs
        else:
            new_island_files.append(path)

    entrypoint_prefix = ("scripts/", "skills/", "templates/", "hooks/", "agents/", "src/", "extension/", "frontend/")
    return {
        "total": len(changed),
        "modify": len(modify_files),
        "wire": len(wire_files),
        "new_island": len(new_island_files),
        "new_island_files": sorted(new_island_files),
        "modify_files": sorted(modify_files),
        "wire_files": sorted(wire_files),
        "wire_references": wire_refs,
        "entrypoint_touched_count": sum(1 for path in changed if path.startswith(entrypoint_prefix)),
    }
def _reference_regex_for(path: str, reference_pattern: Optional[str] = None):
    path_obj = Path(path)
    stem_raw = path_obj.stem
    stem = re.escape(stem_raw)
    parent_stem = re.escape(path_obj.parent.name) if stem_raw == "__init__" and path_obj.parent.name else None
    parent_dotted = (
        re.escape(str(path_obj.parent).replace("/", "."))
        if stem_raw == "__init__" and str(path_obj.parent) not in {"", "."}
        else None
    )
    dotted = re.escape(str(Path(path).with_suffix("")).replace("/", "."))
    escaped_path = re.escape(path)
    if reference_pattern:
        try:
            return re.compile(
                str(reference_pattern).format(module=stem, module_path=dotted, path=escaped_path),
                flags=re.IGNORECASE,
            )
        except Exception:
            return re.compile(str(reference_pattern), flags=re.IGNORECASE)
    patterns = [
        rf"\bfrom\s+{stem}\b",
        rf"\bimport\s+{stem}\b",
        rf"\bfrom\s+{dotted}\b",
        rf"\bimport\s+{dotted}\b",
        rf"\b{stem}\s*\.\s*(?:register|setup|init|initialize)\s*\(",
        rf"require\([^)]*{stem}[^)]*\)",
        rf"\b{escaped_path}\b",
        rf"\]\({escaped_path}\)",
    ]
    if parent_stem:
        patterns.extend(
            [
                rf"\bfrom\s+{parent_stem}\b",
                rf"\bimport\s+{parent_stem}\b",
                rf"\b{parent_stem}\s*\.\s*(?:register|setup|init|initialize)\s*\(",
            ]
        )
    if parent_dotted:
        patterns.extend(
            [
                rf"\bfrom\s+{parent_dotted}\b",
                rf"\bimport\s+{parent_dotted}\b",
            ]
        )
    return re.compile("|".join(patterns), flags=re.IGNORECASE)
def _status_is_pass(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if value is None:
        return False
    return str(value).strip().lower() in {"pass", "passed", "ok", "success", "true"}
def _test_file_from_identifier(value: str) -> Optional[str]:
    token = str(value or "").strip().replace("\\", "/")
    if not token:
        return None
    candidate = token.split("::", 1)[0].strip()
    if candidate.startswith("./"):
        candidate = candidate[2:]
    return candidate if candidate.startswith("tests/") else None
def _record_passed_test(passed_map: dict[str, List[str]], test_file: str, test_id: str):
    normalized_file = str(test_file or "").strip().replace("\\", "/")
    if not normalized_file.startswith("tests/"):
        return
    normalized_id = str(test_id or normalized_file).strip()
    passed_map.setdefault(normalized_file, []).append(normalized_id)
def _ingest_test_result_item(passed_map: dict[str, List[str]], key: str, value):
    key_token = str(key or "").strip()
    if isinstance(value, dict):
        status = value.get("status")
        if status is None:
            status = value.get("result")
        if status is None and "passed" in value:
            status = value.get("passed")
        test_id = str(value.get("test_id") or value.get("id") or key_token).strip()
        test_file = str(value.get("test_file") or "").strip().replace("\\", "/")
        if not test_file:
            test_file = _test_file_from_identifier(test_id) or _test_file_from_identifier(key_token) or ""
        if _status_is_pass(status):
            _record_passed_test(passed_map, test_file, test_id or key_token)
        nested_tests = value.get("tests")
        if isinstance(nested_tests, dict):
            for nested_key, nested_value in nested_tests.items():
                _ingest_test_result_item(passed_map, str(nested_key), nested_value)
        return
    if isinstance(value, list):
        for item in value:
            _ingest_test_result_item(passed_map, key_token, item)
        return
    if _status_is_pass(value):
        test_id = key_token
        test_file = _test_file_from_identifier(key_token) or (key_token if key_token.startswith("tests/") else "")
        _record_passed_test(passed_map, test_file, test_id)
def _collect_passed_test_ids(result_payload: dict) -> dict[str, List[str]]:
    if not isinstance(result_payload, dict):
        return {}
    passed_map: dict[str, List[str]] = {}
    candidates = []
    root_test_results = result_payload.get("test_results")
    if isinstance(root_test_results, dict):
        candidates.append(root_test_results)
    sprint_goals = result_payload.get("sprint_goals")
    if isinstance(sprint_goals, list):
        for goal in sprint_goals:
            if not isinstance(goal, dict):
                continue
            evidence = goal.get("evidence")
            if not isinstance(evidence, dict):
                continue
            test_results = evidence.get("test_results")
            if isinstance(test_results, dict):
                candidates.append(test_results)
    for test_results in candidates:
        for key, value in test_results.items():
            _ingest_test_result_item(passed_map, str(key), value)
    return {test_file: sorted(set(test_ids)) for test_file, test_ids in passed_map.items()}
def _collect_test_reference_map(repo_root: Path, targets: List[str]) -> dict[str, List[str]]:
    tests_root = repo_root / "tests"
    if not tests_root.exists() or not tests_root.is_dir():
        return {path: [] for path in targets}

    test_contents: dict[str, str] = {}
    for candidate in sorted(tests_root.rglob("*")):
        if not candidate.is_file():
            continue
        rel_path = candidate.relative_to(repo_root).as_posix()
        test_contents[rel_path] = candidate.read_text(encoding="utf-8", errors="ignore")

    refs: dict[str, List[str]] = {}
    for path in targets:
        regex = _reference_regex_for(path)
        path_refs: List[str] = []
        for candidate, content in test_contents.items():
            if candidate == path:
                continue
            match = regex.search(content)
            if not match:
                continue
            line_no = content.count(chr(10), 0, match.start()) + 1
            path_refs.append(f"{candidate}:{line_no}")
        refs[path] = sorted(path_refs)
    return refs
def _detect_test_runner(repo_root: Path) -> Optional[str]:
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        return "pytest"
    if (repo_root / "pytest.ini").exists():
        return "pytest"
    if (repo_root / "deno.json").exists():
        return "deno"
    if (repo_root / "go.mod").exists():
        return "go"
    return None
def _run_selected_test_file(repo_root: Path, runner: str, test_file: str) -> bool:
    if runner == "pytest":
        cmd = [sys.executable, "-m", "pytest", test_file, "-v"]
    elif runner == "deno":
        cmd = ["deno", "test", test_file]
    elif runner == "go":
        package_dir = Path(test_file).parent.as_posix().strip(".")
        target = "./..." if not package_dir else f"./{package_dir}"
        cmd = ["go", "test", target]
    else:
        return False

    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    except OSError:
        return False
    return proc.returncode == 0
def _freshness_for_test_evidence(
    repo_root: Path,
    target_file: str,
    test_files: List[str],
    result_payload: dict,
    current_git_tree: str,
) -> str:
    if not isinstance(result_payload, dict):
        return "stale"
    result_tree = str(
        result_payload.get("git_tree")
        or result_payload.get("result_git_tree")
        or result_payload.get("repo_tree")
        or ""
    ).strip()
    if result_tree and current_git_tree and result_tree == current_git_tree:
        return "fresh"

    result_commit = str(
        result_payload.get("result_commit")
        or result_payload.get("git_commit")
        or result_payload.get("commit")
        or result_payload.get("head_commit")
        or ""
    ).strip()
    if not result_commit:
        return "stale"

    compare_targets = [target_file, *test_files]
    try:
        changed = [
            line.strip()
            for line in _git_output(repo_root, "diff", "--name-only", f"{result_commit}..HEAD", "--", *compare_targets).splitlines()
            if line.strip()
        ]
    except RuntimeError:
        return "stale"
    return "acceptable" if not changed else "stale"
