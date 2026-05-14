from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_approve_passed_branch_has_auto_accept_guard_gate():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    assert skill_doc.exists(), f"missing file: {skill_doc}"

    content = skill_doc.read_text(encoding="utf-8")

    # passed 분기에서도 review 가드 메타가 남아 있으면 즉시 accept 연쇄 금지
    assert "guard_blocked" in content
    assert "skipped_minor_count" in content
    assert "protection_flags_count" in content
    assert "workflow.auto_accept_result == true AND guard_blocked == false" in content
    assert "workflow.auto_accept_result == true AND guard_blocked == true" in content


def test_approve_guard_blocked_branch_keeps_manual_accept_path():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    # guard 차단 시 auto accept 대신 수동 accept 경로를 유지해야 한다.
    assert "/mst:accept {REQ_ID}" in content
    assert "auto_accept_guard.blocked_reasons" in content


def test_review_guard_metadata_contract_reaches_approve_and_accept():
    review_doc = (ROOT / "skills" / "review" / "SKILL.md").read_text(encoding="utf-8")
    approve_doc = (ROOT / "skills" / "approve" / "SKILL.md").read_text(encoding="utf-8")
    accept_doc = (ROOT / "skills" / "accept" / "SKILL.md").read_text(encoding="utf-8")

    assert "blocked_reasons" in review_doc
    assert "review_issues_summary.auto_accept_guard.blocked == false" in review_doc
    assert "auto_accept_guard.blocked_reasons" in approve_doc
    assert "guard_blocked == true" in approve_doc
    assert "guard_blocked == false" in approve_doc
    assert "approve의 auto-accept guard 차단은 AUTO_MODE와 별개" in accept_doc


def test_approve_phase2_gate_uses_advance_phase2_stdout_json_contract():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    assert "request advance-phase2-if-ready {REQ_ID} --check --json" in content
    assert "request advance-phase2-if-ready {REQ_ID} --json" in content
    assert "Bash" in content
    assert "stdout JSON" in content
    assert "guard_blocked" in content
    assert "exit code" in content
    assert "JsonParse(Bash(" not in content
    assert 'all_committed = every(... ["committed", "done"])' not in content


def test_approve_phase2_and_phase3_use_batched_config_preload_without_req866_cli():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    assert (
        "config get intent_verification review.auto_review workflow.auto_accept_result --json"
        in content
    )
    assert "phase3_config_items" in content
    assert "REQ-866" in content
    assert "read-only summary" in content
    assert "request phase2-status" in content
    assert "workflow gate-summary" in content


def test_approve_phase2_dispatch_metadata_contract_matches_request_writer():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    for token in (
        "python3 {PLUGIN_ROOT}/scripts/mst.py request record-phase2-dispatch-attempt {REQ_ID}",
        "--task-num",
        "--task-id",
        "--attempt-id",
        "--dispatched-at",
        "--agent",
        "--worktree-path",
        "--log-path",
        "--expected-task-status-before",
        "--json",
        "background_task_ids",
        "attempts",
        "attempt_id",
        "dispatched_at",
        "agent",
        "worktree_path",
        "log_path",
        "expected_task_status_before",
        "task_id",
        "task_num",
        "record_phase2_dispatch_attempt",
    ):
        assert token in content


def test_review_phase2_ready_gate_contract():
    skill_doc = ROOT / "skills" / "review" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    assert "`committed`, `completed`, `done`, `accepted`" in content
    assert "수동 호출 전제조건(`committed`, `completed`, `done`, `accepted` 상태 태스크)" in content
    assert "수동 호출 전제조건(`committed` 태스크)" not in content
