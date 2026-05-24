from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA_ROOT = REPO_ROOT.parents[3]
DETAIL_DOC = METADATA_ROOT / "agile" / "AGI-040" / "objective" / "details" / "agent-dispatch-replacement.md"
TARGET_PATHS = [
    "skills/approve/SKILL.md",
    "skills/request/SKILL.md",
    "skills/codex/SKILL.md",
    "skills/gemini/SKILL.md",
    "scripts/mst_cmds/dispatch_shards/part_001.py",
]
DIRECT_CLI_SURFACES = {
    "skills/approve/SKILL.md": "explicit_parallel_exception",
    "skills/request/SKILL.md": "policy_prohibition",
    "skills/codex/SKILL.md": "protected_skill_codex",
    "skills/gemini/SKILL.md": "protected_skill_gemini",
    "scripts/mst_cmds/dispatch_shards/part_001.py": "common_dispatch_runner",
}
DIRECT_CLI_TOKENS = ("codex exec", "gemini -p", "claude -p")


def _text(relative_path: str) -> str:
    path = relative_path if isinstance(relative_path, Path) else REPO_ROOT / relative_path
    if isinstance(path, Path) and path == DETAIL_DOC and not path.exists():
        pytest.skip(f"local AGI-040 detail doc is absent: {path}")
    return path.read_text(encoding="utf-8")


def _direct_cli_hits(relative_path: str) -> list[str]:
    return [
        line.strip()
        for line in _text(relative_path).splitlines()
        if any(token in line for token in DIRECT_CLI_TOKENS)
    ]


def test_dod005_inventory_classifies_target_direct_cli_surfaces() -> None:
    inventory = {
        relative_path: _direct_cli_hits(relative_path)
        for relative_path in TARGET_PATHS
        if _direct_cli_hits(relative_path)
    }

    assert set(inventory) == set(DIRECT_CLI_SURFACES)
    assert any("codex exec" in line for line in inventory["skills/codex/SKILL.md"])
    assert any("gemini -p" in line for line in inventory["skills/gemini/SKILL.md"])
    assert any("codex exec" in line for line in inventory["skills/request/SKILL.md"])
    assert any("codex exec" in line for line in inventory["skills/approve/SKILL.md"])
    assert any("gemini -p" in line for line in inventory["skills/approve/SKILL.md"])
    assert any("codex exec" in line for line in inventory["scripts/mst_cmds/dispatch_shards/part_001.py"])
    assert any("gemini -p" in line for line in inventory["scripts/mst_cmds/dispatch_shards/part_001.py"])

    approve_doc = _text("skills/approve/SKILL.md")
    request_doc = _text("skills/request/SKILL.md")
    dispatch_runner = _text("scripts/mst_cmds/dispatch_shards/part_001.py")

    assert "`Skill` 호출은 직렬이므로 병렬 실행 시 CLI 직접 호출 필요" in approve_doc
    assert "`Skill(mst:gemini)` 전환 불가" in approve_doc
    assert "직접 `codex exec` + master 커밋으로 전환한다" in request_doc
    assert "dispatch build does not support provider 'claude'. Use Task-based claude dispatch." in dispatch_runner


def test_dod005_replacement_categories_are_explicit_in_scope_docs() -> None:
    detail_doc = _text(DETAIL_DOC)
    approve_doc = _text("skills/approve/SKILL.md")
    request_doc = _text("skills/request/SKILL.md")

    assert 'Task(subagent_type: "general-purpose", run_in_background: true)' in detail_doc
    assert 'Skill(skill: "mst:codex")' in detail_doc
    assert 'Skill(skill: "mst:gemini")' in detail_doc
    assert "공통 dispatch runner" in detail_doc

    assert 'Task(subagent_type: "general-purpose", prompt: {prompt_file 내용}, run_in_background: true)' in approve_doc
    assert 'Skill(skill: "mst:codex", args: "--prompt-file {fix_omx_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-fix-R{N}")' in approve_doc
    assert 'Task(subagent_type:"general-purpose")' in request_doc
    assert 'Skill(skill:"mst:codex")' in request_doc


def test_dod005_parallel_dispatch_contract_preserves_agent_or_runner_lanes() -> None:
    detail_doc = _text(DETAIL_DOC)
    approve_doc = _text("skills/approve/SKILL.md")
    request_doc = _text("skills/request/SKILL.md")

    assert "Agent background 또는 공통 runner로 대체하는 기준" in detail_doc
    assert "`Skill` 호출은 직렬이므로 병렬 실행 시 CLI 직접 호출 필요" in approve_doc
    assert "trace는 `running.log`로 대체된다." in approve_doc
    assert "codex-dev/gemini-dev 병렬 태스크 → 공통 dispatch runner(`mst.py dispatch build` + background process) 사용" in request_doc
    assert 'Skill(skill: "mst:{agent}", run_in_background: true)' not in request_doc


def test_dod005_context_transfer_contract_stays_path_first() -> None:
    detail_doc = _text(DETAIL_DOC)
    approve_doc = _text("skills/approve/SKILL.md")
    request_doc = _text("skills/request/SKILL.md")

    assert "context file path만 전달하고" in detail_doc
    assert "output schema는 prompt에 직접 붙이지 말고 파일 경로로 전달할 수 있다." in detail_doc
    assert "Read로 context_files 경로를 로드하고 output_schema에 맞게 findings JSON을 반환하시오." in request_doc
    assert "프롬프트에는 request 원문, plan 원문, spec 초안, DoD/JTBD 원문을 절대 포함하지 않는다." in request_doc
    assert "PM 작성 요약만 신뢰하지 말고" in approve_doc
    assert "Read/inspection evidence" in approve_doc


def test_dod005_representative_evidence_and_failure_contracts_remain_explicit() -> None:
    detail_doc = _text(DETAIL_DOC)
    approve_doc = _text("skills/approve/SKILL.md")
    dispatch_runner = _text("scripts/mst_cmds/dispatch_shards/part_001.py")

    for token in (
        ".gran-maestro/run/{task_id}.json",
        "{task_dir}/running.log",
        "{task_dir}/traces/{provider}-{label}-{timestamp}.md",
        "dispatch attempt metadata",
        "timeout",
        "empty_result",
        "nonzero exit",
        "fallback",
    ):
        assert token in detail_doc

    for token in (
        "request record-phase2-dispatch-attempt",
        "--log-path {task_dir}/running.log",
        '"log_path": "{task_dir}/running.log"',
    ):
        assert token in approve_doc

    for token in ("dispatch register", "dispatch heartbeat", "EXIT_CODE:$EC"):
        assert token in dispatch_runner
