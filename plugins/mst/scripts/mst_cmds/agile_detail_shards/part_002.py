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
