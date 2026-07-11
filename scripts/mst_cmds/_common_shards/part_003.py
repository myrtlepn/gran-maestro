def _collect_objective_dod_items(content: str) -> dict[str, dict[str, object]]:
    pattern = re.compile(
        (
            r"<!--\s*"
            r"dod:\s*(?P<dod>[A-Za-z0-9_-]+)\s+"
            r"status:\s*(?P<status>\w+)\s+"
            r"priority:\s*(?P<priority>\w+)"
            r"(?:\s+domain:\s*(?P<domain>[A-Za-z0-9_\-]+))?"
            r"(?:\s+evidence_refs:\[(?P<evidence_refs>[^\]]*)\])?"
            r"\s*-->"
        ),
        re.IGNORECASE,
    )
    items = {}
    for match in pattern.finditer(content):
        dod_id = match.group("dod").upper()
        domain_match = match.group("domain")
        evidence_match = match.group("evidence_refs")
        if evidence_match:
            evidence_refs = [ref.strip() for ref in evidence_match.split(",") if ref.strip()]
        else:
            evidence_refs = []
        items[dod_id] = _ObjectiveDodItem({
            "status": match.group("status").lower(),
            "priority": match.group("priority").lower(),
            "domain": domain_match.lower() if domain_match else "unknown",
            "evidence_refs": evidence_refs,
        })
    return items
def _load_agile_config_merged() -> dict:
    defaults_config = load_json(_plugin_root() / "templates" / "defaults" / "config.json")
    resolved_config = load_json(BASE_DIR / "config.resolved.json")
    defaults_agile = defaults_config.get("agile") if isinstance(defaults_config, dict) else {}
    resolved_agile = resolved_config.get("agile") if isinstance(resolved_config, dict) else {}
    defaults_agile = defaults_agile if isinstance(defaults_agile, dict) else {}
    resolved_agile = resolved_agile if isinstance(resolved_agile, dict) else {}
    return deep_merge(defaults_agile, resolved_agile)
def _find_latest_agi_id() -> Optional[str]:
    latest_id = None
    latest_number = -1
    root = agile_dir()
    if not root.exists():
        return None

    for candidate in root.glob("AGI-*"):
        if not candidate.is_dir():
            continue
        matched = re.fullmatch(r"AGI-(\d+)", candidate.name)
        if matched is None:
            continue
        number = int(matched.group(1))
        if number > latest_number:
            latest_number = number
            latest_id = candidate.name
    return latest_id
def _normalize_drift_surface_entry(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    return cleaned.strip(" -")
def _extract_drift_surface_candidate(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line or line.startswith("<!--"):
        return ""

    bullet_match = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line)
    if bullet_match is None:
        return ""
    candidate = bullet_match.group(1).strip()
    candidate = re.sub(r"^\[[xX ]\]\s*", "", candidate)
    candidate = re.sub(r"^DOD-[A-Za-z0-9_-]+\s*:\s*", "", candidate, flags=re.IGNORECASE)
    return _normalize_drift_surface_entry(candidate)
def _extract_objective_surface_entries(content: str) -> list[str]:
    entries: list[str] = []
    seen = set()
    section_kind = None

    for raw_line in str(content or "").splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
        if heading is not None:
            title = re.sub(r"[*`_]+", "", heading.group(1)).strip().lower()
            if "jtbd" in title:
                section_kind = "jtbd"
            elif "project dod" in title or "프로젝트 dod" in title or "프로젝트 완료 기준" in title:
                section_kind = "dod"
            else:
                section_kind = None
            continue

        if section_kind not in {"jtbd", "dod"}:
            continue

        candidate = _extract_drift_surface_candidate(raw_line)
        if not candidate:
            continue
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(candidate)

    if entries:
        return entries

    # Fallback for legacy objective formats.
    for raw_line in str(content or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        candidate = _extract_drift_surface_candidate(stripped)
        if not candidate:
            continue
        if not (
            re.search(r"\b(?:when i|i want to|so i can)\b", candidate, flags=re.IGNORECASE)
            or re.search(r"\bDOD-\w+", stripped, flags=re.IGNORECASE)
        ):
            continue
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(candidate)
    return entries
def _agile_state_ledger_path() -> Path:
    return agile_dir() / "agile-state.json"
def _load_agile_state_payload() -> tuple[list[dict], int, str]:
    data = load_json(_agile_state_ledger_path())
    if isinstance(data, list):
        entries = [item for item in data if isinstance(item, dict)]
        return entries, 0, "list"
    if isinstance(data, dict):
        raw_entries = data.get("entries")
        entries = [item for item in raw_entries if isinstance(item, dict)] if isinstance(raw_entries, list) else []
        raw_reopened = data.get("reopened_count", 0)
        try:
            reopened_count = int(raw_reopened)
        except (TypeError, ValueError):
            reopened_count = 0
        return entries, max(0, reopened_count), "dict"
    return [], 0, "none"
def _save_agile_state_payload(entries: list[dict], reopened_count: int, *, as_dict: bool):
    if as_dict:
        save_json(
            _agile_state_ledger_path(),
            {
                "entries": list(entries),
                "reopened_count": max(0, int(reopened_count)),
            },
        )
        return
    save_json(_agile_state_ledger_path(), list(entries))
def _load_agile_config_cast(key: str, default, caster):
    for path in (BASE_DIR / "config.resolved.json", _plugin_root() / "templates" / "defaults" / "config.json"):
        cfg = load_json(path)
        agile_cfg = cfg.get("agile") if isinstance(cfg, dict) else None
        if not isinstance(agile_cfg, dict) or key not in agile_cfg:
            continue
        try:
            return caster(agile_cfg.get(key))
        except (TypeError, ValueError):
            continue
    return default
def _load_agile_int_config(key: str, fallback: int) -> int:
    return _load_agile_config_cast(key, fallback, int)
TYPE_DIRS = {
    "req": ("requests", "REQ"),
    "idn": ("ideation", "IDN"),
    "dsc": ("discussion", "DSC"),
    "dbg": ("debug", "DBG"),
    "exp": ("explore",   "EXP"),
    "pln": ("plans",     "PLN"),
    "des": ("designs",   "DES"),
    "cap": ("captures", "CAP"),
    "fc": ("fact-checks", "FC"),
    "ref": ("references", "REF"),
    "intent": ("intent", "INTENT"),
    "agi": ("agile", "AGI"),
}
JSON_FILE_MAP = {
    "req": "request.json",
    "pln": "plan.json",
    "des": "design.json",
    "cap": "capture.json",
    "fc": "fact-check.json",
    "ref": "reference.json",
}
def type_archived_dir(type_key: str) -> Path:
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "archived"
def get_counter_path(type_key: str, dir_override: str = None) -> Path:
    if dir_override:
        return Path(dir_override) / "counter.json"
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "counter.json"
def _parse_utc_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        normalized = value
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None
def _capture_is_plan_active(plan_id):
    if not plan_id:
        return False
    plan_data = load_json(plans_dir() / str(plan_id) / "plan.json")
    if not isinstance(plan_data, dict):
        return False
    return plan_data.get("status") in ("active", "in_progress")
def _capture_expired(meta, now):
    created_at = _parse_utc_datetime(meta.get("created_at", "")) if isinstance(meta, dict) else None
    if created_at is None:
        return False
    ttl_expires_at = _parse_utc_datetime(meta.get("ttl_expires_at", ""))
    expires_at = ttl_expires_at or (created_at + timedelta(days=7))
    return now >= expires_at
def _project_root() -> Path:
    cwd = Path.cwd().resolve()
    worktrees_root = BASE_DIR / "worktrees"

    candidate = cwd
    while (
        candidate != BASE_DIR
        and candidate != worktrees_root
        and candidate.parent != worktrees_root
        and candidate.parent != candidate
    ):
        candidate = candidate.parent

    if candidate.parent == worktrees_root:
        return candidate

    return BASE_DIR.parent
def _read_versions() -> dict:
    """5파일에서 버전 읽기."""
    root = _project_root()
    pkg = load_json(root / "package.json") or {}
    plugin = load_json(root / ".claude-plugin" / "plugin.json") or {}
    market = load_json(root / ".claude-plugin" / "marketplace.json") or {}
    ext_manifest = load_json(root / "extension" / "manifest.json") or {}
    ext_package = load_json(root / "extension" / "package.json") or {}
    return {
        "package":     pkg.get("version", ""),
        "plugin":      plugin.get("version", ""),
        "marketplace": (market.get("plugins") or [{}])[0].get("version", ""),
        "ext_manifest": ext_manifest.get("version", ""),
        "ext_package":  ext_package.get("version", ""),
    }
def _resolve_archive_max_active(max_active_cfg, type_key: Optional[str]) -> int:
    value = max_active_cfg
    if isinstance(max_active_cfg, dict):
        value = max_active_cfg.get(type_key) if type_key else None
        if value is None:
            value = max_active_cfg.get("default", 200)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 200
def _archive_run_type(type_key: str, max_active: int, emit_output: bool) -> int:
    subdir, prefix = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    src_dir = BASE_DIR / subdir
    dst_dir = type_archived_dir(type_key)
    dst_dir.mkdir(parents=True, exist_ok=True)

    dirs = sorted(src_dir.glob(f"{prefix}-*"))
    json_file = JSON_FILE_MAP.get(type_key, "session.json")

    if type_key == "cap":
        now = datetime.now(timezone.utc)
        to_archive = []
        for d in dirs:
            if not d.is_dir():
                continue
            data = load_json(d / json_file) or {}
            if not _capture_expired(data, now):
                continue
            linked_plan = (data.get("linked_plan") or "").upper()
            if not _capture_is_plan_active(linked_plan):
                to_archive.append(d)
    else:
        completed = [d for d in dirs if d.is_dir() and
                     (load_json(d / json_file) or {}).get("status") in ("completed", "cancelled", "done", "consensus_reached", "converged")]

        if len(dirs) - len(completed) <= max_active:
            if emit_output:
                print("No archiving needed.")
            return 0

        to_archive = completed[:len(dirs) - max_active]

    if not to_archive:
        if emit_output:
            if type_key == "cap":
                print("No captures to archive.")
            else:
                print("No completed sessions to archive.")
        return 0

    ids = [d.name for d in to_archive]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"{subdir}-{ids[0]}-to-{ids[-1]}-{timestamp}.tar.gz"
    archive_path = dst_dir / archive_name

    if type_key == "cap":
        for d in to_archive:
            cap_json = d / json_file
            cap_data = load_json(cap_json) or {}
            cap_data["status"] = "archived"
            save_json(cap_json, cap_data)

    with tarfile.open(archive_path, "w:gz") as tar:
        for d in to_archive:
            tar.add(d, arcname=d.name)

    for d in to_archive:
        shutil.rmtree(d)

    if emit_output:
        print(f"Archived {len(to_archive)} sessions → {archive_name}")
    return len(to_archive)
def _compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
def _normalize_agy_config_aliases(config):
    if not isinstance(config, dict):
        return config

    normalized = copy.deepcopy(config)

    def move_key(parent, old_key, new_key):
        if isinstance(parent, dict) and old_key in parent:
            if new_key not in parent:
                parent[new_key] = parent[old_key]
            del parent[old_key]

    for section in ["debug", "explore", "discussion", "ideation", "prereview"]:
        move_key(normalized.get(section, {}).get("agents", {}), "gemini", "agy")

    models = normalized.get("models")
    if isinstance(models, dict):
        move_key(models.get("providers", {}), "gemini", "agy")
        roles = models.get("roles")
        if isinstance(roles, dict):
            for role_cfg in roles.values():
                items = role_cfg if isinstance(role_cfg, list) else [role_cfg]
                for item in items:
                    if isinstance(item, dict) and item.get("provider") == "gemini":
                        item["provider"] = "agy"

    delegation = normalized.get("delegation")
    if isinstance(delegation, dict):
        if delegation.get("default_provider") == "gemini":
            delegation["default_provider"] = "agy"
        priority = delegation.get("provider_priority")
        if isinstance(priority, list):
            next_priority = []
            for item in priority:
                mapped = "agy" if item == "gemini" else item
                if mapped not in next_priority:
                    next_priority.append(mapped)
            delegation["provider_priority"] = next_priority

    workflow = normalized.get("workflow")
    if isinstance(workflow, dict) and workflow.get("default_agent") == "gemini-dev":
        workflow["default_agent"] = "agy-dev"

    return normalized
def _load_config_for_get():
    resolved = load_json(BASE_DIR / "config.resolved.json")
    if isinstance(resolved, dict):
        return _apply_native_delegation_read_alias(_normalize_agy_config_aliases(resolved), resolved)

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json")
    overrides = load_json(BASE_DIR / "config.json")
    if isinstance(defaults, dict) and isinstance(overrides, dict):
        merged = _normalize_agy_config_aliases(deep_merge(defaults, overrides))
        return _apply_native_delegation_read_alias(merged, overrides)
    if isinstance(defaults, dict):
        return _normalize_agy_config_aliases(defaults)
    if isinstance(overrides, dict):
        return _apply_native_delegation_read_alias(_normalize_agy_config_aliases(overrides), overrides)
    return {}


def _apply_native_delegation_read_alias(config, provenance):
    if not isinstance(config, dict) or not isinstance(provenance, dict):
        return config
    source = provenance.get("delegation")
    target = config.get("delegation")
    if not isinstance(source, dict) or not isinstance(target, dict):
        return config
    legacy = source.get("native_codex_subagents")
    if not isinstance(legacy, dict):
        return config

    source_native = source.get("native") if isinstance(source.get("native"), dict) else {}
    target_native = target.get("native") if isinstance(target.get("native"), dict) else {}
    policy_explicit = "transport_policy" in source
    enabled_explicit = "enabled" in source_native
    scope_explicit = "scope" in source_native
    legacy_enabled = legacy.get("enabled") is not False

    if not policy_explicit and not enabled_explicit:
        target["transport_policy"] = "same-host-native-first" if legacy_enabled else "external-only"
        target_native["enabled"] = legacy_enabled
    elif policy_explicit and not enabled_explicit:
        target_native["enabled"] = source.get("transport_policy") == "same-host-native-first"
    elif enabled_explicit and not policy_explicit:
        target["transport_policy"] = "same-host-native-first" if source_native.get("enabled") else "external-only"
    if not scope_explicit and isinstance(legacy.get("scope"), str):
        target_native["scope"] = legacy["scope"]
    target["native"] = target_native
    return config
def _flat_diff(old, new, prefix=""):
    changes = {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        if old != new:
            changes[prefix or "<root>"] = (old, new)
        return changes

    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        full_key = f"{prefix}.{key}" if prefix else key
        old_value = old.get(key)
        new_value = new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changes.update(_flat_diff(old_value, new_value, full_key))
        elif old_value != new_value:
            changes[full_key] = (old_value, new_value)
    return changes
TASK_ID_PATTERN = re.compile(r"^(REQ-\d+)(?:-(.+))?$")
TASK_SEGMENT_PATTERN = re.compile(r"^\w+(-\w+)*$")
def parse_task_id(raw_id):
    r"""Parse a task ID like REQ-001-01 or REQ-100-T01-X into (request_id, task_segment).

    Mirrors the TS parseTaskId in src/core/task-id.ts. Raises ValueError if the
    input does not match ``^REQ-\d+(-\w+)*$``. Bare request IDs (REQ-001)
    are not task identifiers and also raise.
    """
    if not isinstance(raw_id, str):
        raise ValueError(f"invalid task id: {raw_id!r}")
    match = TASK_ID_PATTERN.match(raw_id)
    if not match or not match.group(2):
        raise ValueError(f"invalid task id: {raw_id}")
    segment = match.group(2)
    if not TASK_SEGMENT_PATTERN.match(segment):
        raise ValueError(f"invalid task id: {raw_id}")
    return match.group(1), segment
