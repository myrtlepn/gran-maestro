def _default_level2_recall_manifest(reason: str, trigger: str) -> dict:
    trigger_token = str(trigger or "").strip()
    return {
        "level": 2,
        "reason": str(reason or "").strip().lower() or "fail",
        "trigger": trigger_token,
        "generated_at": _now_iso(),
        "dod_patch": {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        },
        "objective_refinements": [
            {
                "field": "objective.wording",
                "change_type": "precision",
                "before": "Keep objective wording precise for iterative delivery.",
                "after": "Keep objective wording precise for iterative delivery and evidence alignment.",
                "semantic_change": False,
            }
        ],
        "integration_sprint": {
            "insert": True,
            "title": "Integration Sprint",
            "rationale": f"trigger={trigger_token or 'n/a'}",
        },
        "stats": {
            "done_dod_modifications": 0,
        },
    }
def _load_level2_recall_manifest(agi_id: str, reason: str, trigger: str) -> dict:
    pending_path = _agi_recall_pending_manifest_path(agi_id)
    loaded = load_json(pending_path)
    if loaded is None:
        return _default_level2_recall_manifest(reason, trigger)
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid recall manifest: {pending_path}")
    manifest = dict(loaded)
    manifest.setdefault("level", 2)
    manifest.setdefault("reason", str(reason or "").strip().lower())
    manifest.setdefault("trigger", str(trigger or "").strip())
    manifest.setdefault("generated_at", _now_iso())
    if not isinstance(manifest.get("dod_patch"), dict):
        manifest["dod_patch"] = {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        }
    if not isinstance(manifest.get("objective_refinements"), list):
        manifest["objective_refinements"] = []
    if not isinstance(manifest.get("integration_sprint"), dict):
        manifest["integration_sprint"] = {"insert": True}
    if not isinstance(manifest.get("stats"), dict):
        manifest["stats"] = {}
    return manifest
def _coerce_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    token = str(value).strip()
    return [token] if token else []
def _normalize_recall_reason_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return token or "change"
def _load_level3_recall_manifest(agi_id: str, reason: str, trigger: str) -> dict:
    pending_path = _agi_recall_pending_manifest_path_for_level(agi_id, 3)
    loaded = load_json(pending_path)
    if loaded is None:
        raise ValueError(f"level 3 recall manifest not found: {pending_path}")
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid recall manifest: {pending_path}")

    manifest = dict(loaded)
    manifest["level"] = 3
    manifest.setdefault("reason", str(reason or "").strip().lower())
    manifest.setdefault("trigger", str(trigger or "").strip())
    manifest.setdefault("generated_at", _now_iso())
    if not isinstance(manifest.get("dod_patch"), dict):
        manifest["dod_patch"] = {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        }
    if not isinstance(manifest.get("objective_refinements"), list):
        manifest["objective_refinements"] = []
    manifest["affected_dods"] = _coerce_string_list(manifest.get("affected_dods"))
    manifest["drift_evidence"] = _coerce_string_list(manifest.get("drift_evidence"))
    return manifest
def _compute_objective_semantic_hash(content: str) -> str:
    entries = _extract_objective_surface_entries(content)
    if entries:
        canonical = "\n".join(_normalize_drift_surface_entry(entry).lower() for entry in entries)
    else:
        canonical = re.sub(r"\s+", " ", str(content or "").strip()).lower()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
def _upsert_objective_frontmatter_fields(content: str, fields: dict[str, object]) -> str:
    frontmatter = _extract_frontmatter_block(content)
    errors = list(frontmatter.get("errors") or [])
    if errors:
        raise ValueError("; ".join(str(err) for err in errors))

    frontmatter_text = str(frontmatter.get("frontmatter") or "")
    for key, value in fields.items():
        if isinstance(value, bool):
            rendered_value = "true" if value else "false"
        elif isinstance(value, int):
            rendered_value = str(value)
        else:
            rendered_value = _yaml_quote(str(value))
        frontmatter_text = _upsert_frontmatter_key_block(frontmatter_text, key, [f"{key}: {rendered_value}"])
    return _upsert_detail_frontmatter(content, frontmatter_text)
def _apply_level3_objective_refinements(content: str, manifest: dict) -> tuple[str, list[dict]]:
    updated_content = str(content or "")
    diff_rows: list[dict] = []

    refinements = manifest.get("objective_refinements")
    if not isinstance(refinements, list):
        return updated_content, diff_rows

    for raw_item in refinements:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        before = str(item.get("before") or "")
        after = str(item.get("after") or "")
        applied = False
        if before and after and before in updated_content:
            updated_content = updated_content.replace(before, after, 1)
            applied = True
        diff_rows.append(
            {
                "field": str(item.get("field") or ""),
                "change_type": str(item.get("change_type") or ""),
                "before": before,
                "after": after,
                "semantic_change": bool(item.get("semantic_change")),
                "applied": applied,
            }
        )
    return updated_content, diff_rows
def _collect_level3_affected_dods(manifest: dict, done_dod_ids: set[str]) -> list[str]:
    affected: list[str] = []
    seen = set()

    for token in _coerce_string_list(manifest.get("affected_dods")):
        try:
            dod_id = _normalize_dod_id(token)
        except ValueError:
            continue
        if dod_id in seen:
            continue
        seen.add(dod_id)
        affected.append(dod_id)

    for dod_id in sorted(_collect_manifest_touched_done_dods(manifest, done_dod_ids)):
        if dod_id in seen:
            continue
        seen.add(dod_id)
        affected.append(dod_id)
    return affected
def _build_level3_diff_payload(manifest: dict, objective_diff: list[dict]) -> dict:
    dod_patch = manifest.get("dod_patch") if isinstance(manifest.get("dod_patch"), dict) else {}
    dod_summary = {}
    for op_name, entries in dod_patch.items():
        if isinstance(entries, list) and entries:
            dod_summary[str(op_name)] = len(entries)
    return {
        "objective_refinements": objective_diff,
        "dod_patch": dod_summary,
    }
def _build_level3_approval_payload(
    manifest: dict,
    current_objective: str,
    done_dod_ids: set[str],
    *,
    reason: str,
    trigger: str,
    auto_mode_request: bool,
) -> dict:
    preview_content, objective_diff = _apply_level3_objective_refinements(current_objective, manifest)
    before_hash = _compute_objective_semantic_hash(current_objective)
    after_hash = _compute_objective_semantic_hash(preview_content)
    return {
        "approval_required": True,
        "level": 3,
        "reason": str(reason or "").strip(),
        "trigger": str(trigger or "").strip(),
        "before_hash": before_hash,
        "after_hash": after_hash,
        "diff": _build_level3_diff_payload(manifest, objective_diff),
        "affected_dods": _collect_level3_affected_dods(manifest, done_dod_ids),
        "drift_evidence": _coerce_string_list(manifest.get("drift_evidence")),
        "auto_mode": auto_mode_request,
    }
def _write_level3_history_entry(
    agi_id: str,
    *,
    event_token: str,
    reason: str,
    event_id: str,
    before_hash: str,
    after_hash: str,
    diff: dict,
    affected_dods: list[str],
    drift_evidence: list[str],
    approval_ticket: str,
) -> Path:
    history_dir = _agi_session_dir(agi_id) / "objective" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{event_token}_L3_{_normalize_recall_reason_token(reason)}.json"
    save_json(
        history_path,
        {
            "event_id": event_id,
            "level": 3,
            "approval_ticket": str(approval_ticket or "").strip(),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "diff": diff,
            "affected_dods": list(affected_dods),
            "drift_evidence": list(drift_evidence),
        },
    )
    return history_path
def _compute_level3_cooldown(project_size: int, recall_cfg: dict) -> int:
    base_cooldown = _compute_recall_cooldown(
        project_size,
        _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
    )
    multiplier = recall_cfg.get("level3_cooldown_multiplier", _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER)
    try:
        multiplier_value = int(multiplier)
    except (TypeError, ValueError):
        multiplier_value = _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER
    return base_cooldown * max(1, multiplier_value)
def _classify_change_manifest(manifest: dict, recall_cfg: dict) -> dict:
    level = 2
    confidence = 0.78
    summary = "Objective wording remains semantically stable; DoD patch stays within Level 2."

    if _manifest_exceeds_level2_scope(manifest):
        level = 3
        confidence = 0.92
        summary = "JTBD core intent changed; objective essence was redefined and requires Level 3 approval."

    payload = {
        "level": level,
        "confidence": confidence,
        "summary": summary,
    }

    project_size_raw = manifest.get("project_size")
    if project_size_raw is not None:
        try:
            project_size = max(1, int(project_size_raw))
        except (TypeError, ValueError):
            project_size = None
        if project_size is not None:
            level2_cooldown_raw = manifest.get("level2_cooldown")
            if level2_cooldown_raw is not None:
                try:
                    level2_cooldown = max(1, int(level2_cooldown_raw))
                except (TypeError, ValueError):
                    level2_cooldown = _compute_recall_cooldown(
                        project_size,
                        _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
                    )
            else:
                level2_cooldown = _compute_recall_cooldown(
                    project_size,
                    _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
                )
            multiplier = recall_cfg.get("level3_cooldown_multiplier", _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER)
            try:
                multiplier_value = max(1, int(multiplier))
            except (TypeError, ValueError):
                multiplier_value = _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER
            payload["cooldown"] = level2_cooldown * multiplier_value
    return payload
def _record_agile_plan_patch_invocation(
    agi_id: str,
    *,
    level: int,
    reason: str,
    trigger: str,
    manifest_path: Path,
) -> dict:
    invocation_id = f"recall-{uuid.uuid4().hex[:12]}"
    payload = {
        "timestamp": _now_iso(),
        "invocation_id": invocation_id,
        "mode": "patch",
        "level": int(level),
        "reason": str(reason or "").strip(),
        "trigger": str(trigger or "").strip(),
        "manifest_path": str(manifest_path),
    }
    _append_ndjson(_agi_recall_invocation_log_path(agi_id), payload)
    return {
        "called": True,
        "invocation_id": invocation_id,
        "log_path": str(_agi_recall_invocation_log_path(agi_id)),
    }
def _emit_recall_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "FAIL").upper()
    if status == "PASS":
        print("PASS")
    elif status == "SKIP":
        print("WARN: recall disabled")
    else:
        errors = payload.get("errors") or []
        print(str(errors[0]) if errors else "FAIL")
    print(f"agi_id: {payload.get('agi_id') or '-'}")
    print(f"reason: {payload.get('reason') or '-'}")
    print(f"trigger: {payload.get('trigger') or '-'}")
    print(f"cooldown: {payload.get('cooldown_window')}")
    print(f"cap: {payload.get('cap_used')}/{payload.get('cap_limit')}")
def _resolve_agi_target(agi_id_raw: Optional[str]) -> str:
    if agi_id_raw:
        agi_id = _normalize_agi_id(str(agi_id_raw))
    else:
        agi_id = _find_latest_agi_id()
        if agi_id is None:
            raise ValueError("AGI session not found; provide --agi-id")
    _load_agile_session(agi_id)
    return agi_id
def _detail_file_for_dod(details_dir: Path, dod_id: str) -> Path:
    direct = details_dir / f"{dod_id}.md"
    if direct.exists() and direct.is_file():
        return direct

    for candidate in sorted(details_dir.glob("*.md")):
        if candidate.stem.upper() == dod_id:
            return candidate
    raise ValueError(f"detail file not found for {dod_id}")
def _detail_frontmatter_or_fail(content: str) -> tuple[dict, str]:
    parsed = parse_agile_detail_metadata(content)
    frontmatter = _extract_frontmatter_block(content)
    errors = list(frontmatter.get("errors") or [])
    errors.extend(parsed.get("errors") or [])
    if errors:
        raise ValueError("; ".join(str(err) for err in errors))
    if not frontmatter.get("has_frontmatter"):
        raise ValueError("detail frontmatter is missing")
    return parsed, str(frontmatter.get("frontmatter") or "")
def _frontmatter_truthy(frontmatter: str, key: str) -> bool:
    value = _extract_yaml_scalar(frontmatter, key)
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
def _frontmatter_int(frontmatter: str, key: str, default: int = 0) -> int:
    value = _extract_yaml_scalar(frontmatter, key)
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
def _load_unlock_forbidden_patterns(unlock_cfg: dict) -> list[str]:
    raw_patterns = unlock_cfg.get("forbidden_patterns") if isinstance(unlock_cfg, dict) else None
    if isinstance(raw_patterns, list):
        patterns = [str(token).strip().lower() for token in raw_patterns if str(token).strip()]
        if patterns:
            return patterns
    return list(_UNLOCK_FORBIDDEN_REASON_PATTERNS)
def _reason_has_forbidden_pattern(reason: str, patterns: list[str]) -> bool:
    normalized = str(reason or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9가-힣]+", " ", normalized)
    tokens = {token for token in normalized.split() if token}
    for pattern in patterns:
        target = str(pattern or "").strip().lower()
        if not target:
            continue
        if target in tokens:
            return True
        if re.search(rf"\b{re.escape(target)}\b", normalized):
            return True
    return False
def _validate_unlock_reason(reason: str, forbidden_patterns: list[str]) -> Optional[str]:
    token = str(reason or "").strip()
    if not token:
        return "reason required (min 20 chars)"
    if len(token) < 20 or len(token) > 500:
        return "reason rejected (too short or forbidden pattern)"
    if _reason_has_forbidden_pattern(token, forbidden_patterns):
        return "reason rejected (too short or forbidden pattern)"
    return None
def _validate_unlock_evidence(category: str, evidence: str) -> Optional[str]:
    category_token = str(category or "").strip()
    evidence_token = str(evidence or "").strip()
    hint = _UNLOCK_CATEGORY_HINTS.get(category_token, "supporting evidence")

    fail_message = f"evidence required for category {category_token} ({hint})"
    if not evidence_token:
        return fail_message

    parts = _split_csv_values(evidence_token)
    if category_token == "upstream_evidence_changed":
        if len(parts) < 2:
            return fail_message
        try:
            _normalize_dod_id(parts[0])
        except ValueError:
            return fail_message
        return None
    if category_token == "integration_regression":
        if len(parts) < 2:
            return fail_message
        return None
    if category_token == "new_dependency_dod":
        if not parts:
            return fail_message
        try:
            _normalize_dod_id(parts[0])
        except ValueError:
            return fail_message
        return None
    if category_token == "objective_precision_fix":
        if not parts:
            return fail_message
        return None
    return f"invalid unlock category: {category_token}"
def _increment_agile_state_reopened_count() -> int:
    entries, reopened_count, _ = _load_agile_state_payload()
    updated_count = reopened_count + 1
    _save_agile_state_payload(entries, updated_count, as_dict=True)
    return updated_count
def _recall_done_dods_missing_unlock(agi_id: str, done_dod_ids: set[str]) -> list[str]:
    if not done_dod_ids:
        return []

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    missing: list[str] = []
    for dod_id in sorted(done_dod_ids):
        try:
            detail_file = _detail_file_for_dod(details_dir, dod_id)
            content = detail_file.read_text(encoding="utf-8")
            _, frontmatter = _detail_frontmatter_or_fail(content)
        except (OSError, UnicodeDecodeError, ValueError):
            missing.append(dod_id)
            continue

        status = str(_extract_yaml_scalar(frontmatter, "status") or "").strip().lower()
        history = _parse_unlock_history(frontmatter)
        if status != "in_progress" or not history:
            missing.append(dod_id)
    return missing
def cmd_agile_unlock(args):
    payload = {
        "status": "FAIL",
        "agi_id": None,
        "dod_id": None,
        "detail_path": None,
        "category": str(args.category or "").strip(),
        "reason": str(args.reason or "").strip(),
        "evidence": str(args.evidence or "").strip(),
        "reopened_count": 0,
        "dependents_marked": [],
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_unlock_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    try:
        dod_id = _normalize_dod_id(str(args.dod))
    except ValueError as exc:
        return _fail(str(exc))
    payload["dod_id"] = dod_id

    unlock_cfg = _load_agile_unlock_config()
    if not bool(unlock_cfg.get("enabled", True)):
        return _fail("unlock disabled by config")

    reason_error = _validate_unlock_reason(args.reason, _load_unlock_forbidden_patterns(unlock_cfg))
    if reason_error:
        return _fail(reason_error)

    evidence_error = _validate_unlock_evidence(args.category, args.evidence)
    if evidence_error:
        return _fail(evidence_error)

    try:
        agi_id = _resolve_agi_target(args.agi_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["agi_id"] = agi_id

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    if not details_dir.exists():
        return _fail(f"details dir not found: {details_dir}")
    if not details_dir.is_dir():
        return _fail(f"details dir is not a directory: {details_dir}")

    try:
        detail_path = _detail_file_for_dod(details_dir, dod_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["detail_path"] = str(detail_path)

    try:
        current_content = detail_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"failed to read detail: {exc}")

    try:
        parsed, frontmatter = _detail_frontmatter_or_fail(current_content)
    except ValueError as exc:
        return _fail(str(exc))

    if parsed.get("evidence"):
        current_content = upsert_agile_detail_evidence(current_content, parsed.get("evidence"))
        try:
            _, frontmatter = _detail_frontmatter_or_fail(current_content)
        except ValueError as exc:
            return _fail(str(exc))

    current_status = str(_extract_yaml_scalar(frontmatter, "status") or "").strip().lower()
    if current_status != "done":
        return _fail(f"unlock allowed only for done DoD (current status: {current_status or 'unknown'})")

    history = _parse_unlock_history(frontmatter)
    history.append(
        {
            "timestamp": _now_iso(),
            "category": str(args.category).strip(),
            "reason": str(args.reason).strip(),
            "evidence": str(args.evidence).strip(),
        }
    )

    reopened_count = max(_frontmatter_int(frontmatter, "reopened_count", 0) + 1, len(history))
    updated_frontmatter = _remove_frontmatter_key_block(frontmatter, "revalidation_required")
    updated_frontmatter = _upsert_frontmatter_key_block(updated_frontmatter, "status", ["status: in_progress"])
    updated_frontmatter = _upsert_frontmatter_key_block(
        updated_frontmatter,
        "unlock_history",
        _render_unlock_history_block(history),
    )
    updated_frontmatter = _upsert_frontmatter_key_block(
        updated_frontmatter,
        "reopened_count",
        [f"reopened_count: {reopened_count}"],
    )

    updated_content = _upsert_detail_frontmatter(current_content, updated_frontmatter)
    try:
        detail_path.write_text(updated_content, encoding="utf-8")
    except OSError as exc:
        return _fail(f"failed to write detail: {exc}")

    dependents_marked: list[str] = []
    for candidate in sorted(details_dir.glob("*.md")):
        if candidate == detail_path:
            continue
        try:
            raw = candidate.read_text(encoding="utf-8")
            _, candidate_frontmatter = _detail_frontmatter_or_fail(raw)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

        blocked_by = _extract_yaml_list(candidate_frontmatter, "blocked_by") or []
        blocked_set = set()
        for token in blocked_by:
            try:
                blocked_set.add(_normalize_dod_id(str(token)))
            except ValueError:
                continue
        if dod_id not in blocked_set:
            continue

        if _frontmatter_truthy(candidate_frontmatter, "revalidation_required"):
            dependents_marked.append(candidate.stem.upper())
            continue

        candidate_frontmatter = _upsert_frontmatter_key_block(
            candidate_frontmatter,
            "revalidation_required",
            ["revalidation_required: true"],
        )
        patched = _upsert_detail_frontmatter(raw, candidate_frontmatter)
        try:
            candidate.write_text(patched, encoding="utf-8")
        except OSError:
            continue
        dependents_marked.append(candidate.stem.upper())

    global_reopened_count = _increment_agile_state_reopened_count()
    _append_agile_event(
        agi_id,
        "agile.unlock",
        {
            "dod_id": dod_id,
            "category": str(args.category).strip(),
            "dependents_marked": dependents_marked,
            "reopened_count": global_reopened_count,
        },
    )

    payload["status"] = "PASS"
    payload["dependents_marked"] = dependents_marked
    payload["reopened_count"] = global_reopened_count
    _emit_unlock_payload(payload, args.json)
    return 0
def cmd_agile_revalidate_done(args):
    payload = {
        "status": "FAIL",
        "agi_id": None,
        "dod_id": None,
        "detail_path": None,
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_revalidate_done_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    try:
        dod_id = _normalize_dod_id(str(args.dod))
    except ValueError as exc:
        return _fail(str(exc))
    payload["dod_id"] = dod_id

    try:
        agi_id = _resolve_agi_target(args.agi_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["agi_id"] = agi_id

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    if not details_dir.exists():
        return _fail(f"details dir not found: {details_dir}")
    if not details_dir.is_dir():
        return _fail(f"details dir is not a directory: {details_dir}")

    try:
        detail_path = _detail_file_for_dod(details_dir, dod_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["detail_path"] = str(detail_path)

    try:
        current_content = detail_path.read_text(encoding="utf-8")
        _, frontmatter = _detail_frontmatter_or_fail(current_content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _fail(str(exc))

    updated_frontmatter = _remove_frontmatter_key_block(frontmatter, "revalidation_required")
    updated_content = _upsert_detail_frontmatter(current_content, updated_frontmatter)

    try:
        detail_path.write_text(updated_content, encoding="utf-8")
    except OSError as exc:
        return _fail(f"failed to write detail: {exc}")

    _append_agile_event(agi_id, "agile.revalidate_done", {"dod_id": dod_id})
    payload["status"] = "PASS"
    _emit_revalidate_done_payload(payload, args.json)
    return 0
def cmd_agile_classify_change(args):
    manifest_path = Path(str(args.manifest))
    if not manifest_path.exists():
        print(f"Error: manifest not found ({manifest_path})", file=sys.stderr)
        return 1

    loaded = load_json(manifest_path)
    if not isinstance(loaded, dict):
        print(f"Error: invalid manifest ({manifest_path})", file=sys.stderr)
        return 1

    payload = _classify_change_manifest(dict(loaded), _load_agile_recall_config())
    level = int(payload.get("level", 2))
    label = f"Level {level}"
    confidence = float(payload.get("confidence", 0.0))
    summary = str(payload.get("summary") or "").strip()

    print(label)
    print(f"confidence: {confidence:.2f}")
    if payload.get("cooldown") is not None:
        print(f"cooldown: {payload['cooldown']}")
    if summary:
        print(f"summary: {summary}")
    return 0
