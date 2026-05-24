def hardcoded_core_check(project_root: Path, home: Path, payload: dict) -> int:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    session_id = canonical_mst_session_id_from_payload(payload)
    clean_sid = sanitize_session_id(session_id) if session_id else None
    raw_file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    command = str(tool_input.get("command") or "")
    file_path = normalize_path(raw_file_path, project_root, home)
    policy_root = str(policy_home(home))
    sessions_root = str(project_root / ".gran-maestro" / "sessions")

    def core_block(rule_id: str, reason: str) -> int:
        return emit_core_block_and_return(
            project_root,
            home,
            clean_sid or "",
            tool_name,
            tool_input,
            rule_id,
            reason,
        )

    if tool_name == "ScheduleWakeup" and schedule_wakeup_block_active(project_root, payload):
        if os.environ.get("MST_ALLOW_SCHEDULE_WAKEUP") == "1":
            stderr("[mst] ScheduleWakeup escape hatch used")
            return 0
        stderr(SCHEDULE_WAKEUP_RESUME_HINT)
        return core_block(SCHEDULE_WAKEUP_BLOCK_RULE_ID, SCHEDULE_WAKEUP_BLOCK_REASON)

    if tool_name == "AskUserQuestion" and schedule_wakeup_block_active(project_root, payload):
        return core_block(ASK_USER_QUESTION_BLOCK_RULE_ID, ASK_USER_QUESTION_BLOCK_REASON)

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/"):
        if "/rules.d/" in file_path or file_path.endswith("/manifest.json"):
            return core_block(
                "META-BYPASS-RULE-FILE",
                "정책 디렉토리는 LLM이 수정할 수 없습니다.",
            )
        return core_block(
            "META-BYPASS-POLICY-DIR",
            "정책 디렉토리는 LLM이 수정할 수 없습니다.",
        )

    if tool_name == "Bash" and is_mutating_command(command):
        if ".claude/gran-maestro-policy" in command or policy_root in command:
            if "/ledger-heads/" in command:
                return core_block(
                    "META-BYPASS-LEDGER-SENTINEL",
                    "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
                )
            if "/rules.d/" in command or "manifest.json" in command:
                return core_block(
                    "META-BYPASS-RULE-FILE",
                    "정책 디렉토리는 LLM이 수정할 수 없습니다.",
                )
            return core_block(
                "META-BYPASS-POLICY-DIR",
                "정책 디렉토리는 LLM이 수정할 수 없습니다.",
            )

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.ndjson"):
        return core_block(
            "META-BYPASS-HISTORY-NDJSON",
            "history.ndjson은 LLM이 직접 수정할 수 없습니다.",
        )

    if tool_name == "Bash" and is_mutating_command(command):
        if ".gran-maestro/sessions/" in command and "history.ndjson" in command:
            return core_block(
                "META-BYPASS-HISTORY-NDJSON",
                "history.ndjson은 LLM이 직접 수정할 수 없습니다.",
            )
        if ".gran-maestro/sessions/" in command and (
            "history.head" in command or "history.verify" in command
        ):
            return core_block(
                "META-BYPASS-LEDGER-SENTINEL",
                "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
            )
        if ".gran-maestro/sessions/" in command and SESSION_RENAME_RE.search(command):
            return core_block(
                "META-BYPASS-SESSION-ID-FORGERY",
                "session_id 디렉토리는 LLM이 직접 생성하거나 이름 변경할 수 없습니다.",
            )

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.head"):
        return core_block(
            "META-BYPASS-LEDGER-SENTINEL",
            "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
        )

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/ledger-heads/"):
        return core_block(
            "META-BYPASS-LEDGER-SENTINEL",
            "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
        )

    return 0
def main() -> int:
    if len(sys.argv) != 2:
        stderr("usage: pre_tool_use_fast.py <project_root>")
        return 2

    project_root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get("HOME") or Path.home())
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        stderr("[policy-block] payload_parse_failure invalid hook payload JSON")
        return 2
    if not isinstance(payload, dict):
        stderr("[policy-block] payload_parse_failure hook payload must be a JSON object")
        return 2

    session_id = canonical_mst_session_id_from_payload(payload)
    clean_sid = ""
    lock_dir: Optional[Path] = None
    if session_id:
        clean_sid = sanitize_session_id(session_id)
        if clean_sid is None:
            stderr("history ledger mismatch: invalid session_id")
            return 2
        history_file, _, _, _ = history_paths(project_root, home, clean_sid)
        session_dir = history_file.parent
        lock_dir = session_dir / "history.lock"
        session_dir.mkdir(parents=True, exist_ok=True)
        if not acquire_lock(lock_dir):
            stderr("history ledger mismatch: lock timeout")
            return 2
        ok, _, _, cursor_reason = inspect_hot_path_history_cursor(project_root, home, clean_sid)
        if not ok:
            stderr(
                "history ledger mismatch: "
                f"{cursor_reason}; inspect-only state/history consistency verification required"
            )
            try:
                lock_dir.rmdir()
            except OSError:
                pass
            lock_dir = None
            return 2
        warn_session_id_mismatch_once_if_any(project_root, payload, raw, clean_sid)

    try:
        tool_name = str(payload.get("tool_name") or "").strip() or "unknown"
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}

        if clean_sid:
            expire_pending_confirm(project_root, clean_sid, utc_now())

        if tool_name == "Bash":
            command = str(tool_input.get("command") or "")
            blocked_command = blocked_mst_command(command, project_root, home)
            if blocked_command:
                reason = (
                    f"LLM Bash cannot execute {blocked_command}; "
                    "use an out-of-band user terminal approval path or fix the cause."
                )
                if clean_sid:
                    append_event_after_verified(
                        project_root,
                        home,
                        clean_sid,
                        core_block_event(tool_name, tool_input, LLM_MST_CLI_RULE_ID, reason),
                    )
                return block("core-block", LLM_MST_CLI_RULE_ID, reason)

        status = hardcoded_core_check(project_root, home, payload)
        if status:
            return status

        if clean_sid:
            override_status = consume_pending_override(project_root, home, clean_sid, tool_name, tool_input)
            if override_status is not None:
                return override_status

        allowlisted = check_allowlist(home, tool_name, tool_input)
        policy_decisions: List[dict] = []
        if allowlisted:
            policy_decisions.append(
                {
                    "decision": "normal_allow",
                    "rule_id": "MST-HOOK-ALLOWLIST",
                    "message": "allowlist matched",
                }
            )
        else:
            status, policy_decisions = evaluate_policy(project_root, home, payload)
            if status:
                if clean_sid and policy_decisions:
                    decision = policy_decisions[0]
                    if decision.get("decision") == "policy_block":
                        timestamp = format_utc(utc_now())
                        args_sha256 = sha256_text(canonical_json(tool_input))
                        side_effect_status = append_event_after_verified(
                            project_root,
                            home,
                            clean_sid,
                            {
                                "args_sha256": args_sha256,
                                "message": str(decision.get("message") or ""),
                                "rule_id": str(decision.get("rule_id") or "policy_block"),
                                "timestamp": timestamp,
                                "tool": str(payload.get("tool_name") or "").strip() or "unknown",
                                "type": "policy_block",
                            },
                        )
                        if side_effect_status:
                            return side_effect_status
                        side_effect_status = request_pending_confirm(
                            project_root,
                            home,
                            clean_sid,
                            tool_name,
                            tool_input,
                            str(decision.get("rule_id") or "policy_block"),
                        )
                        if side_effect_status:
                            return side_effect_status
                return status

        phase_decisions: List[dict] = []
        if clean_sid and not allowlisted:
            status, phase_decisions = evaluate_phase_gate(project_root, home, payload, clean_sid)
            if status:
                if phase_decisions and phase_decisions[0].get("decision") == "policy_block":
                    decision = phase_decisions[0]
                    timestamp = format_utc(utc_now())
                    args_sha256 = str(decision.get("args_sha256") or sha256_text(canonical_json(tool_input)))
                    side_effect_status = append_event_after_verified(
                        project_root,
                        home,
                        clean_sid,
                        {
                            "args_sha256": args_sha256,
                            "message": str(decision.get("message") or ""),
                            "rule_id": str(decision.get("rule_id") or "policy_block"),
                            "timestamp": timestamp,
                            "tool": str(payload.get("tool_name") or "").strip() or "unknown",
                            "type": "policy_block",
                        },
                    )
                    if side_effect_status:
                        return side_effect_status
                    side_effect_status = request_pending_confirm(
                        project_root,
                        home,
                        clean_sid,
                        str(payload.get("tool_name") or "").strip() or "unknown",
                        tool_input,
                        str(decision.get("rule_id") or "policy_block"),
                    )
                    if side_effect_status:
                        return side_effect_status
                return status

        if clean_sid:
            args_json = canonical_json(tool_input)
            args_sha256 = sha256_text(args_json)
            for decision in policy_decisions + phase_decisions:
                decision_type = decision.get("decision")
                if decision_type not in {"warn", "normal_allow"}:
                    continue
                timestamp = format_utc(utc_now())
                side_effect_status = append_event_after_verified(
                    project_root,
                    home,
                    clean_sid,
                    {
                        "args_sha256": args_sha256,
                        "message": str(decision.get("message") or ""),
                        "rule_id": str(decision.get("rule_id") or decision_type),
                        "timestamp": timestamp,
                        "tool": tool_name,
                        "type": "warn_auto_allow" if decision_type == "warn" else "normal_allow",
                    },
                )
                if side_effect_status:
                    return side_effect_status
        if clean_sid:
            return append_tool_call_after_verified(
                project_root,
                home,
                clean_sid,
                tool_name,
                tool_input,
            )
        return append_tool_call(
            project_root,
            home,
            session_id,
            tool_name,
            tool_input,
        )
    finally:
        if lock_dir is not None:
            try:
                lock_dir.rmdir()
            except OSError:
                pass
if __name__ == "__main__":
    raise SystemExit(main())
