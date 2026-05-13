def _promote_with_test_evidence(classification, repo_root, session_dir, sprint, depth):
    del depth  # 현재는 직전 sprint 증거만 사용
    updated = copy.deepcopy(classification if isinstance(classification, dict) else {})
    updated["wire_promotions"] = []
    new_island_files = updated.get("new_island_files")
    if not isinstance(new_island_files, list) or not new_island_files:
        return updated

    previous_result = {}
    if int(sprint) > 0:
        previous_path = session_dir / "sprints" / f"S{int(sprint) - 1:02d}" / "result.json"
        loaded = load_json(previous_path)
        if isinstance(loaded, dict):
            previous_result = loaded
    has_cached_result = bool(previous_result)
    cached_passed = _collect_passed_test_ids(previous_result) if has_cached_result else {}
    refs_by_file = _collect_test_reference_map(repo_root, sorted({str(path) for path in new_island_files if str(path).strip()}))
    if not any(refs_by_file.values()):
        return updated

    try:
        current_tree = _git_output(repo_root, "rev-parse", "HEAD^{tree}").strip()
    except RuntimeError:
        current_tree = ""

    fallback_runner: Optional[str] = None
    fallback_cache: dict[str, bool] = {}
    promotions = []
    previous_sprint_id = f"S{int(sprint) - 1:02d}" if int(sprint) > 0 else None

    for target_file in sorted(new_island_files):
        refs = refs_by_file.get(str(target_file), [])
        if not refs:
            continue
        test_files = sorted({item.split(":", 1)[0] for item in refs if item.startswith("tests/")})
        if not test_files:
            continue

        freshness = _freshness_for_test_evidence(repo_root, str(target_file), test_files, previous_result, current_tree) if has_cached_result else "stale"
        cached_test_ids: List[str] = []
        for test_file in test_files:
            cached_test_ids.extend(cached_passed.get(test_file, []))
        cached_test_ids = sorted(set(cached_test_ids))

        if has_cached_result and freshness in {"fresh", "acceptable"} and cached_test_ids:
            promotions.append(
                {
                    "file": str(target_file),
                    "promoted_by_test": True,
                    "evidence_source": "cached",
                    "evidence_sprint": previous_sprint_id,
                    "freshness": freshness,
                    "test_ids": cached_test_ids,
                }
            )
            continue

        if fallback_runner is None:
            fallback_runner = _detect_test_runner(repo_root)
        if not fallback_runner:
            continue

        executed = False
        all_passed = True
        fallback_test_ids: List[str] = []
        for test_file in test_files:
            if test_file in fallback_cache:
                passed = fallback_cache[test_file]
            else:
                passed = _run_selected_test_file(repo_root, fallback_runner, test_file)
                fallback_cache[test_file] = passed
            executed = True
            if not passed:
                all_passed = False
            else:
                fallback_test_ids.append(test_file)

        if not executed or not all_passed or not fallback_test_ids:
            continue

        promotions.append(
            {
                "file": str(target_file),
                "promoted_by_test": True,
                "evidence_source": "fallback",
                "evidence_sprint": previous_sprint_id,
                "freshness": freshness,
                "test_ids": sorted(set(fallback_test_ids)),
            }
        )

    if not promotions:
        return updated

    new_island_set = {str(path) for path in new_island_files}
    wire_files = {str(path) for path in updated.get("wire_files", [])}
    wire_refs = updated.get("wire_references")
    if not isinstance(wire_refs, dict):
        wire_refs = {}

    applied_promotions = []
    for promotion in promotions:
        target_file = str(promotion.get("file", "")).strip()
        if not target_file or target_file not in new_island_set:
            continue
        new_island_set.remove(target_file)
        wire_files.add(target_file)
        wire_refs[target_file] = refs_by_file.get(target_file, [])
        applied_promotions.append(promotion)

    updated["new_island_files"] = sorted(new_island_set)
    updated["wire_files"] = sorted(wire_files)
    updated["wire_references"] = wire_refs
    updated["wire"] = len(updated["wire_files"])
    updated["new_island"] = len(updated["new_island_files"])
    updated["wire_promotions"] = applied_promotions
    return updated
def _compute_integration_verdict(classification, threshold):
    total = int(classification.get("total", 0))
    ratio = (float(classification.get("new_island", 0)) / total) if total > 0 else 0.0
    exceeded = ratio > float(threshold)
    return {"new_island_threshold": float(threshold), "exceeded": exceeded, "force_wire_recommended": exceeded}
def _render_integration_context_md(payload, output_path):
    files = payload.get("files", {})
    ratios = payload.get("ratios", {})
    verdict = payload.get("verdict", {})
    lines = [f"# Integration Context ({payload.get('sprint', '-')})", "", "## 1. 변경 파일 트리 (분류별)", ""]
    lines.extend([f"- total: {files.get('total', 0)}", f"- modify: {files.get('modify', 0)}"])
    lines.extend([f"  - {path}" for path in payload.get("modify_files", [])])
    lines.append(f"- wire: {files.get('wire', 0)}")
    lines.extend([f"  - {path}" for path in payload.get("wire_files", [])])
    lines.append(f"- new_island: {files.get('new_island', 0)}")
    lines.extend([f"  - {path}" for path in payload.get("new_island_files", [])])
    lines.extend(
        [
            "",
            "## 2. Entrypoint 상태",
            "",
            f"- entrypoint_touched_ratio: {ratios.get('entrypoint_touched', 0.0):.2%}",
            f"- new_island_ratio: {ratios.get('new_island', 0.0):.2%}",
            f"- threshold: {verdict.get('new_island_threshold', 0.0):.2f}",
            f"- force_wire_recommended: {verdict.get('force_wire_recommended', False)}",
            "",
            "## 3. 직전 Sprint 사용자 관찰 변화 요약",
        ]
    )
    changes = payload.get("recent_user_observable_changes", [])
    lines.extend([f"- {item.get('sprint', '-')}: {item.get('user_observable_change', '-')}" for item in changes] if changes else ["- 없음"])
    lines.extend(["", "## 4. wire 파일별 통합 지점"])
    if payload.get("wire_files"):
        for path in payload.get("wire_files", []):
            lines.append(f"- {path}")
            lines.extend([f"  - {ref}" for ref in payload.get("wire_references", {}).get(path, [])] or ["  - reference not found"])
    else:
        lines.append("- 없음")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
def _collect_alignment_payload(agi_id, sprint, depth):
    sprint_id = f"S{int(sprint):02d}"
    window_sprints = _window_sprint_ids(int(sprint), max(1, int(depth)))
    session_dir = _agi_session_dir(agi_id)
    objective_path = _agi_objective_path(agi_id)
    dods = []
    warning = None
    if objective_path.exists():
        dods = [{"id": dod_id, "status": item.get("status"), "priority": item.get("priority")} for dod_id, item in sorted(_collect_objective_dod_items(objective_path.read_text(encoding="utf-8")).items())]
    else:
        warning = "objective file missing"
    payload = {
        "agi_id": agi_id,
        "sprint": sprint_id,
        "depth": max(1, int(depth)),
        "objective_dods": dods,
        "integration_context_path": str(session_dir / "sprints" / sprint_id / "integration-context.md"),
        "recent_results": [],
        "recent_retrospectives": [],
    }
    for sid in reversed(window_sprints):
        result_path = session_dir / "sprints" / sid / "result.json"
        retro_path = session_dir / "sprints" / sid / "retrospective.json"
        if result_path.exists():
            payload["recent_results"].append(str(result_path))
        if retro_path.exists():
            payload["recent_retrospectives"].append(str(retro_path))
    if warning:
        payload["warning"] = warning
    return payload
def cmd_agile_integration_review(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    depth = int(args.depth) if args.depth is not None else _load_agile_int_config("integration_review_depth", 3)
    threshold = float(args.threshold) if args.threshold is not None else _load_agile_float_config("new_island_threshold", 0.20)
    if depth < 1:
        print("Error: --depth must be >= 1", file=sys.stderr)
        return 1

    repo_root = Path.cwd().resolve()
    session_dir = _agi_session_dir(agi_id)
    try:
        since_ref, until_ref = _resolve_git_window_refs(repo_root, depth)
        classification = _classify_changed_files(repo_root, since_ref, until_ref, args.reference_pattern)
        classification = _promote_with_test_evidence(classification, repo_root, session_dir, args.sprint, depth)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    verdict = _compute_integration_verdict(classification, threshold)
    escape_reason = str(args.escape_reason).strip() if args.escape_reason else None
    verdict["escape_hatch_used"] = bool(escape_reason) and bool(verdict.get("exceeded"))
    verdict["escape_reason"] = escape_reason

    total = int(classification.get("total", 0))
    ratios = {
        "new_island": (float(classification.get("new_island", 0)) / total) if total else 0.0,
        "entrypoint_touched": (float(classification.get("entrypoint_touched_count", 0)) / total) if total else 0.0,
    }
    sprint_id = f"S{args.sprint:02d}"
    window_sprints = _window_sprint_ids(args.sprint, depth)
    sprint_dir = session_dir / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)

    streak_max = max(1, _load_agile_int_config("integration_wire_streak_max", 3))
    streak = 0
    for idx in range(args.sprint, -1, -1):
        if idx == args.sprint:
            force_wire = bool(verdict.get("force_wire_recommended"))
        else:
            prev = load_json(session_dir / "sprints" / f"S{idx:02d}" / "integration-review.json")
            force_wire = bool(prev.get("verdict", {}).get("force_wire_recommended")) if isinstance(prev, dict) else False
        if not force_wire:
            break
        streak += 1

    payload = {
        "sprint": sprint_id,
        "depth": depth,
        "window_sprints": window_sprints,
        "files": {k: classification.get(k, 0) for k in ("total", "modify", "wire", "new_island")} | {"new_island_files": classification.get("new_island_files", [])},
        "wire_promotions": classification.get("wire_promotions", []),
        "ratios": ratios,
        "verdict": verdict,
        "wire_streak": {"current": streak, "max": streak_max, "exceeded": streak >= streak_max},
    }
    payload["llm_gate"] = {
        "triggered": False,
        "verdict": None,
        "reason": None,
    }
    save_json(sprint_dir / "integration-review.json", payload)

    changes = []
    for sid in reversed(window_sprints):
        result = load_json(session_dir / "sprints" / sid / "result.json")
        change = result.get("user_observable_change") if isinstance(result, dict) else None
        if change:
            changes.append({"sprint": sid, "user_observable_change": str(change)})
    _render_integration_context_md(
        {
            **payload,
            "modify_files": classification.get("modify_files", []),
            "wire_files": classification.get("wire_files", []),
            "new_island_files": classification.get("new_island_files", []),
            "wire_references": classification.get("wire_references", {}),
            "recent_user_observable_changes": changes,
        },
        sprint_dir / "integration-context.md",
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(sprint_dir / "integration-context.md"))
    return 0
def cmd_agile_alignment_package(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.sprint < 0 or args.depth < 1:
        print("Error: --sprint must be >= 0 and --depth must be >= 1", file=sys.stderr)
        return 1
    payload = _collect_alignment_payload(agi_id, args.sprint, args.depth)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
    return 0
def cmd_agile_link(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        pln_ids = [_normalize_link_id(value, "PLN") for value in _split_csv_values(args.pln)]
        req_ids = [_normalize_link_id(value, "REQ") for value in _split_csv_values(args.req)]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not pln_ids and not req_ids:
        print("Error: provide at least one --pln or --req", file=sys.stderr)
        return 1

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
    _append_agile_event(
        agi_id,
        "agile.link",
        {
            "pln": pln_ids,
            "req": req_ids,
        },
    )

    if args.json:
        print(json.dumps(links, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0
