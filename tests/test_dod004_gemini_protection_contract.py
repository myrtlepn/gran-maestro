from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    assert start != -1, f"missing section: {heading}"
    next_heading = text.find("\n## ", start + len(marker))
    if next_heading == -1:
        next_heading = len(text)
    return text[start:next_heading]


def _run_dispatch_build(tmp_path: Path) -> str:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt-gemini.md"
    prompt_file.write_text("hello gemini", encoding="utf-8")
    log_file = workspace / "gemini.log"
    proc = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "dispatch",
            "build",
            "--provider",
            "gemini",
            "--prompt-file",
            str(prompt_file),
            "--task-id",
            "task-gemini",
            "--worktree-dir",
            str(workspace),
            "--log-file",
            str(log_file),
            "--model",
            "gemini-test-model",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_agy_skill_declares_fixed_identity_and_codex_parity_contract() -> None:
    text = _text("skills/agy/SKILL.md")

    identity = _section(text, "AGY Identity Protection Contract")
    assert "command_identity: `mst:agy`" in identity
    assert "/mst:plan" in identity and "/mst:request" in identity and "built-in plan mode" in identity
    assert "path rules" in identity
    assert "model resolve" in identity
    assert "trace label" in identity

    for marker in ("NEXT_ACTION", "step=returned", "[MST skill=...]"):
        assert marker in text
    assert "DOD-003 Context Transfer Contract" in text


def test_agy_delegation_contract_requires_context_failure_evidence_and_codex_fallback() -> None:
    text = _text("skills/agy/SKILL.md")
    contract = _section(text, "Delegation Failure and Fallback Contract")

    for token in (
        "context file path",
        "prompt-file path",
        "running log path",
        "evidence path",
        "evidence id",
        "verification criteria",
        "Codex fallback",
    ):
        assert token in contract

    for failure_kind in ("rate_limit", "timeout", "empty_result", "nonzero_exit"):
        assert failure_kind in contract

    assert "429" in contract or "rate-limit" in contract


def test_approve_agy_dev_direct_bash_exception_is_classified() -> None:
    text = _text("skills/approve/SKILL.md")
    section = _section(text, "DOD-004 agy-dev Direct Bash Exception Contract")

    assert "parallel dispatch" in section
    assert "Skill(mst:agy)" in section
    assert "direct Bash exception" in section
    assert "lifecycle" in section and "trace" in section and "exit" in section
    assert "running.log" in section
    assert "Codex fallback" in section
    for failure_kind in ("rate_limit", "timeout", "empty_result", "nonzero_exit"):
        assert failure_kind in section


def test_dispatch_agy_command_records_structured_failure_and_fallback_evidence(tmp_path: Path) -> None:
    command = _run_dispatch_build(tmp_path)

    assert "agy --print" in command
    assert "MST_PROVIDER_FAILURE_KIND" in command
    assert "rate_limit" in command
    assert "timeout" in command
    assert "empty_result" in command
    assert "nonzero_exit" in command
    assert "MST_PROVIDER_FALLBACK_CONDITION" in command
    assert "MST_PROVIDER_EVIDENCE_ID" in command
    assert "EXIT_CODE:" in command
    assert re.search(r"PROVIDER_FAILURE_KIND:\$\{MST_PROVIDER_FAILURE_KIND", command)


def test_dod002_direct_claude_print_mode_guidance_is_not_reintroduced() -> None:
    violations: list[str] = []
    for relative_path in ("skills/approve/SKILL.md", "skills/claude/SKILL.md", "skills/agile/SKILL.md"):
        text = _text(relative_path)
        for match in re.finditer(r"claude\s+(-p|--print)\b", text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{relative_path}:{line}: active direct Claude print-mode guidance")

    assert not violations, "DOD-002 direct Claude print-mode regression:\n" + "\n".join(violations)
