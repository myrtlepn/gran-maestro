from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SKILL = REPO_ROOT / "skills" / "request" / "SKILL.md"
APPROVE_SKILL = REPO_ROOT / "skills" / "approve" / "SKILL.md"
IMPL_REQUEST_TEMPLATE = REPO_ROOT / "templates" / "impl-request.md"
AGILE_SKILL = REPO_ROOT / "skills" / "agile" / "SKILL.md"
AGILE_PLAN_SKILL = REPO_ROOT / "skills" / "agile-plan" / "SKILL.md"
SPRINT_DISPATCH_TEMPLATE = REPO_ROOT / "templates" / "sprint-dispatch-prompt.md"

PROVIDER_SKILL_PATHS = [
    "skills/codex/SKILL.md",
    "skills/gemini/SKILL.md",
    "skills/claude/SKILL.md",
]

PROVIDER_REQUIRED_TOKENS = [
    "[CONTEXT_FILES]",
    "spec_context_manifest",
    "NO_SOURCE_PLAN",
    "NO_CONTEXT_MANIFEST",
    "[WORK_CONTRACT]",
    "read_requirements",
    "output_contract",
    "verification_contract",
    "failure_contract",
    "prompt-file path",
    "worktree path",
    "task id",
    "trace label",
    "running log",
    "exit code propagation",
    "wrapper-owned lifecycle boundary",
    "provider subprocess detail",
    "missing_context",
]

REVIEW_REQUIRED_TOKENS = [
    "[CONTEXT_FILES]",
    "spec_context_manifest",
    "NO_SOURCE_PLAN",
    "NO_CONTEXT_MANIFEST",
    "[WORK_CONTRACT]",
    "read_requirements",
    "output_contract",
    "verification_contract",
    "failure_contract",
    "Read/inspection",
    "output schema",
    "markdown finding report",
    "verification evidence",
    "completion report",
    "missing_context",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains_all(text: str, expected: list[str], label: str) -> None:
    missing = [item for item in expected if item not in text]
    assert not missing, f"{label} missing required contract text: {missing}"


def _section_lines(text: str, anchor: str, window: int = 12) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if anchor in line:
            start = max(0, index - window)
            end = min(len(lines), index + window + 1)
            return "\n".join(lines[start:end])
    raise AssertionError(f"anchor not found: {anchor}")


def test_impl_request_template_declares_context_files_and_work_contract() -> None:
    text = _read(IMPL_REQUEST_TEMPLATE)

    assert "[CONTEXT_FILES]" in text
    for required_field in (
        "objective:",
        "objective_ids:",
        "plan:",
        "plan_json:",
        "plan_ids:",
        "spec:",
        "spec_context_manifest:",
        "previous_feedback:",
    ):
        assert required_field in text

    assert "[WORK_CONTRACT]" in text
    for required_field in (
        "read_requirements:",
        "output_contract:",
        "verification_contract:",
        "failure_contract:",
    ):
        assert required_field in text


def test_impl_request_template_requires_missing_context_markers_and_completion_evidence() -> None:
    text = _read(IMPL_REQUEST_TEMPLATE)

    for required_literal in (
        "NO_LINKED_OBJECTIVE",
        "NO_OBJECTIVE_IDS",
        "NO_SOURCE_PLAN",
        "NO_PLAN_JSON",
        "NO_PLAN_IDS",
        "NO_CONTEXT_MANIFEST",
        "missing_context",
        "변경 파일 목록",
        "completion report",
        "verify_cmd",
        "expected_signal",
    ):
        assert required_literal in text

    assert '`{{PLAN_PATH}}`가 `"N/A"`가 아니면' not in text
    assert '"N/A"면 source_plan 없음으로 보고' not in text
    assert "`{{PLAN_PATH}}`가 `NO_SOURCE_PLAN`이 아니면" in text
    assert "`NO_SOURCE_PLAN`이면 source_plan 없음으로 보고" in text


def test_impl_request_template_keeps_n_a_only_for_previous_feedback() -> None:
    text = _read(IMPL_REQUEST_TEMPLATE)
    plan_slot_section = _section_lines(text, "- plan:", window=1)
    previous_feedback_section = _section_lines(text, "- previous_feedback:", window=1)

    assert "N/A" not in plan_slot_section
    assert "NO_SOURCE_PLAN" in plan_slot_section
    assert "N/A" in previous_feedback_section


def test_approve_skill_documents_path_first_impl_brief_contract() -> None:
    text = _read(APPROVE_SKILL)

    assert "templates/impl-request.md" in text
    assert "[CONTEXT_FILES]" in text
    assert "[WORK_CONTRACT]" in text
    for required_literal in (
        "spec_context_manifest",
        "previous_feedback",
        "Read/inspection evidence",
        "verify_cmd",
        "expected_signal",
        "missing_context",
    ):
        assert required_literal in text


def test_request_skill_seeds_context_manifest_with_contract_sources() -> None:
    text = _read(REQUEST_SKILL)

    assert "§0 Context Manifest 후보 수집" in text
    for required_literal in (
        "plan.md",
        "plan.json",
        "plan.ids.json",
        "context-transfer-contract.md",
        "skills/request/SKILL.md",
        "skills/approve/SKILL.md",
        "templates/impl-request.md",
        "templates/spec.md",
        "missing_context",
    ):
        assert required_literal in text


@pytest.mark.parametrize("relative_path", PROVIDER_SKILL_PATHS)
def test_provider_skill_docs_define_context_transfer_contract(relative_path: str) -> None:
    text = _text(relative_path)
    missing = [token for token in PROVIDER_REQUIRED_TOKENS if token not in text]
    assert not missing, f"{relative_path} missing provider contract tokens: {missing}"


def test_review_skill_doc_defines_context_transfer_contract() -> None:
    text = _text("skills/review/SKILL.md")
    missing = [token for token in REVIEW_REQUIRED_TOKENS if token not in text]
    assert not missing, f"skills/review/SKILL.md missing review contract tokens: {missing}"


def test_review_skill_requires_structured_missing_context_reporting() -> None:
    text = _text("skills/review/SKILL.md")
    required_signals = [
        "missing_context",
        "NO_SOURCE_PLAN",
        "NO_CONTEXT_MANIFEST",
        "SOURCE_READ_FAILED",
        "CHANGE_READ_FAILED",
    ]
    missing = [token for token in required_signals if token not in text]
    assert not missing, f"skills/review/SKILL.md missing failure signals: {missing}"


def test_sprint_dispatch_template_uses_path_first_context_contract() -> None:
    text = _read(SPRINT_DISPATCH_TEMPLATE)

    _assert_contains_all(
        text,
        [
            "[CONTEXT_FILES]",
            "- objective:",
            "- objective_ids:",
            "- plan:",
            "- plan_json:",
            "- plan_ids:",
            "- spec:",
            "- spec_context_manifest:",
            "- sprint_context:",
            "- previous_feedback:",
            "[/CONTEXT_FILES]",
            "[WORK_CONTRACT]",
            "read_requirements: 구현 전 위 context file과 spec §0 Context Manifest 파일을 직접 Read/inspection한다.",
            "output_contract:",
            "verification_contract: verify_cmd, expected_signal, integration_smoke_id",
            "failure_contract: timeout, empty result, blocked, missing_context 상태를 구조화해 남긴다.",
            "[/WORK_CONTRACT]",
            "[DISPATCH_RESULT_CONTRACT]",
            "dispatch-result.json",
            "running log",
            "trace",
            "exit_code",
            "output-failure contract",
            "[COMPLETION_REPORT]",
            "changed files",
            "simplifications made",
            "remaining risks",
            "원문 대량 삽입 금지",
        ],
        "templates/sprint-dispatch-prompt.md",
    )


def test_agile_skill_requires_structured_missing_context_in_dispatch_contract() -> None:
    text = _read(AGILE_SKILL)

    _assert_contains_all(
        text,
        [
            "spec_context_manifest",
            "missing_context",
            "NO_OBJECTIVE_IDS",
            "NO_PLAN_JSON",
            "NO_PLAN_IDS",
            "NO_ACTIVE_SPEC",
            "NO_SPEC_CONTEXT_MANIFEST",
            "NO_PREVIOUS_FEEDBACK",
            "[WORK_CONTRACT]",
            "completion report",
            "dispatch-result.json",
        ],
        "skills/agile/SKILL.md",
    )
    assert '컨텍스트가 비어 있으면 `"N/A"`로 채워 graceful fallback 한다.' not in text


def test_approve_skill_requires_no_source_plan_but_allows_previous_feedback_n_a() -> None:
    text = _read(APPROVE_SKILL)
    plan_path_line = next(line for line in text.splitlines() if "{{PLAN_PATH}}" in line)
    previous_feedback_line = next(line for line in text.splitlines() if "{{PREV_FEEDBACK_PATH}}" in line)

    assert "NO_SOURCE_PLAN" in plan_path_line
    assert '"N/A"' not in plan_path_line
    assert "첫 실행 시 \"N/A\"" in previous_feedback_line


def test_approve_claude_dispatch_documents_prompt_worktree_and_wrapper_binding() -> None:
    text = _read(APPROVE_SKILL)
    claude_section = _section_lines(
        text,
        'Skill(skill: "mst:claude", args: "--prompt-file {prompt_file} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-impl")',
        window=14,
    )

    assert '--prompt-file {prompt_file} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-impl' in claude_section
    assert '--trace {REQ-ID}/{TASK-NUM}/phase2-impl")' in claude_section
    assert "python3 {PLUGIN_ROOT}/scripts/mst.py run" in claude_section
    assert "--task-id {REQ-ID}-T{TASK-NUM}" in claude_section
    assert "--log-dir {task_dir}" in claude_section
    assert "{task_dir}/running.log" in claude_section
    assert "exit-code propagation" in claude_section
    assert 'Skill(skill: "mst:claude", args: "--trace {REQ-ID}/{TASK-NUM}/phase2-impl")' not in text


def test_agile_plan_declares_downstream_context_transfer_requirements() -> None:
    text = _read(AGILE_PLAN_SKILL)

    _assert_contains_all(
        text,
        [
            "[CONTEXT_FILES]",
            "objective.ids.json",
            "NO_OBJECTIVE_IDS",
            "missing_context",
            "[WORK_CONTRACT]",
            "Read/inspection evidence",
            "completion report",
            "verify_cmd",
            "expected_signal",
            "integration_smoke_id",
            "NO_CONTEXT_MANIFEST",
        ],
        "skills/agile-plan/SKILL.md",
    )


def test_dispatch_contract_preserves_provider_neutral_lifecycle_evidence() -> None:
    agile_text = _read(AGILE_SKILL)
    template_text = _read(SPRINT_DISPATCH_TEMPLATE)

    _assert_contains_all(
        agile_text,
        [
            'Skill(skill: "mst:claude", args: "--prompt-file sprint-prompt.md --dir {PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/ --trace {AGI_ID}/S{NN}/dispatch")',
            "python3 {PLUGIN_ROOT}/scripts/mst.py run",
            "--task-id \"{AGI_ID}-S{NN}\"",
            "--provider codex",
            "--provider gemini",
            '--provider "$PROVIDER"',
            "--log-dir \"{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/\"",
            "sprint dispatch lifecycle tuple",
            "running log tee / trace path / session metadata / output-failure contract / exit code propagation",
            "running log path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/running.log`",
            "trace path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/traces/{provider}-*.md`",
        ],
        "skills/agile/SKILL.md",
    )
    _assert_contains_all(
        template_text,
        [
            "dispatch_result_path",
            "trace_path",
            "running_log_path",
            "success_signal",
            "failure_signal",
        ],
        "templates/sprint-dispatch-prompt.md",
    )


def test_claude_skill_defines_shared_lifecycle_boundary_between_dispatch_and_wrapper() -> None:
    text = _read(REPO_ROOT / "skills" / "claude" / "SKILL.md")
    lifecycle_section = _section_lines(text, "- lifecycle boundary mapping:", window=4)

    assert "--prompt-file {prompt_file}" in lifecycle_section
    assert "--dir {worktree_path}" in lifecycle_section
    assert "--trace {REQ-ID}/{TASK-NUM}/{label}" in lifecycle_section
    assert "--task-id {task_id}" in lifecycle_section
    assert "--log-dir {task_dir}" in lifecycle_section
    assert "{task_dir}/running.log" in lifecycle_section
    assert "exit code propagation" in lifecycle_section
