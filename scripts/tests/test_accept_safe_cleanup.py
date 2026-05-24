from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPT_SKILL = REPO_ROOT / "skills" / "accept" / "SKILL.md"
PROJECT_ROOT_REF = r'(?:\{PROJECT_ROOT\}|\$PROJECT_ROOT|\$\{PROJECT_ROOT\}|"\$PROJECT_ROOT"|"\$\{PROJECT_ROOT\}")'
FORBIDDEN_PROJECT_ROOT_DIRECT_PATTERNS = (
    re.compile(rf"\bgit\s+-C\s+{PROJECT_ROOT_REF}\s+commit\b"),
    re.compile(rf"\bgit\s+-C\s+{PROJECT_ROOT_REF}\s+checkout\b"),
    re.compile(rf"\bgit\s+-C\s+{PROJECT_ROOT_REF}\s+merge\s+--squash\b"),
    re.compile(rf"\bgit\s+-C\s+{PROJECT_ROOT_REF}\s+merge\s+--no-ff\b"),
)
FORBIDDEN_PROJECT_ROOT_CD_PATTERNS = (
    re.compile(rf"\bcd\s+{PROJECT_ROOT_REF}(?:(?:\s*&&|\s*;)\s*|\s*\n(?:[^\n]*\n){{0,4}}?)git\s+commit\b", re.S),
    re.compile(rf"\bcd\s+{PROJECT_ROOT_REF}(?:(?:\s*&&|\s*;)\s*|\s*\n(?:[^\n]*\n){{0,4}}?)git\s+checkout\b", re.S),
    re.compile(rf"\bcd\s+{PROJECT_ROOT_REF}(?:(?:\s*&&|\s*;)\s*|\s*\n(?:[^\n]*\n){{0,4}}?)git\s+merge\s+--squash\b", re.S),
    re.compile(rf"\bcd\s+{PROJECT_ROOT_REF}(?:(?:\s*&&|\s*;)\s*|\s*\n(?:[^\n]*\n){{0,4}}?)git\s+merge\s+--no-ff\b", re.S),
)


def _accept_skill_text() -> str:
    return ACCEPT_SKILL.read_text(encoding="utf-8")


def _step_section(text: str, start: str, end: str) -> str:
    match = re.search(rf"{re.escape(start)}(?P<body>.*?){re.escape(end)}", text, flags=re.S)
    assert match is not None
    return match.group("body")


def _cleanup_helper_block() -> str:
    match = re.search(
        r"```bash\n(?P<body>record_clean_failed\(\) \{.*?\n\})\n```",
        _accept_skill_text(),
        flags=re.S,
    )
    assert match is not None
    return match.group("body")


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


def _forbidden_project_root_destructive_commands(text: str) -> list[str]:
    violations: list[str] = []
    for block_number, block in enumerate(_bash_blocks(text), start=1):
        for pattern in (*FORBIDDEN_PROJECT_ROOT_DIRECT_PATTERNS, *FORBIDDEN_PROJECT_ROOT_CD_PATTERNS):
            for match in pattern.finditer(block):
                snippet = " ".join(match.group(0).split())
                violations.append(f"bash-block-{block_number}:{snippet}")
    return violations


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_fake_mst(plugin_root: Path) -> None:
    mst_path = plugin_root / "scripts" / "mst.py"
    mst_path.parent.mkdir(parents=True, exist_ok=True)
    mst_path.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

args = sys.argv[1:]
path = Path(args[args.index("--path") + 1])
task_id = path.name
if task_id.endswith("T01"):
    print(f"forced worktree remove failure for {task_id}", file=sys.stderr)
    sys.exit(12)

project_root = Path(os.environ["PROJECT_ROOT"])
meta_path = project_root / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
if meta_path.exists():
    meta_path.unlink()
sys.exit(0)
""",
        encoding="utf-8",
    )
    mst_path.chmod(0o755)


def _write_fake_git(bin_dir: Path, git_log: Path) -> None:
    git_path = bin_dir / "git"
    git_path.parent.mkdir(parents=True, exist_ok=True)
    git_path.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {git_log}
if printf '%s' "$*" | grep -q 'REQ-BRANCH-FAIL'; then
  echo 'forced request branch delete failure' >&2
  exit 23
fi
exit 0
""",
        encoding="utf-8",
    )
    git_path.chmod(0o755)


def _run_cleanup_driver(tmp_path: Path, driver: str) -> subprocess.CompletedProcess[str]:
    project_root = tmp_path / "project"
    plugin_root = tmp_path / "plugin"
    bin_dir = tmp_path / "bin"
    git_log = tmp_path / "git.log"
    worktrees_dir = project_root / ".gran-maestro" / "worktrees"
    worktrees_dir.mkdir(parents=True)

    for task_id in ("REQ-680-T01", "REQ-680-T02"):
        _write_json(
            worktrees_dir / f"{task_id}.meta.json",
            {
                "taskId": task_id,
                "path": str(worktrees_dir / task_id),
                "branch": f"gran-maestro/main/{task_id}",
                "state": "active",
                "preserved": "keep",
            },
        )

    _write_fake_mst(plugin_root)
    _write_fake_git(bin_dir, git_log)
    script = (
        "set -euo pipefail\n"
        f"{_cleanup_helper_block()}\n"
        f"PROJECT_ROOT={project_root!s}\n"
        f"PLUGIN_ROOT={plugin_root!s}\n"
        "REQ_ID=REQ-680\n"
        "export PROJECT_ROOT PLUGIN_ROOT REQ_ID\n"
        f"PATH={bin_dir!s}:$PATH\n"
        f"GIT_LOG={git_log!s}\n"
        "export GIT_LOG\n"
        f"{driver}\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_accept_step4_cleanup_commands_do_not_silence_failures() -> None:
    content = _accept_skill_text()
    step_3_3 = _step_section(content, "**3-3. REQ 브랜치 삭제**", "3.5.")
    step_4 = _step_section(content, "4. **정리**", "4.5.")

    for section in (step_3_3, step_4):
        for line in section.splitlines():
            if "worktree remove" in line or "branch -D" in line:
                assert "|| true" not in line

    assert "record_clean_failed()" in step_4
    assert "clean_failed" in step_4


def test_accept_skill_forbids_project_root_destructive_git_commands() -> None:
    violations = _forbidden_project_root_destructive_commands(_accept_skill_text())

    assert violations == []


def test_accept_skill_does_not_hardcode_master_base_fallback() -> None:
    content = _accept_skill_text()

    hardcoded_shell_fallback = "CONFIG_BASE_BRANCH:-" + "master"
    hardcoded_doc_arrow = "→ `" + "master" + "`"
    hardcoded_doc_sentence = "fallback: `config.worktree.base_branch` " + hardcoded_doc_arrow

    assert hardcoded_shell_fallback not in content
    assert hardcoded_doc_arrow not in content
    assert hardcoded_doc_sentence not in content


def test_accept_cleanup_records_worktree_failure_and_continues(tmp_path: Path) -> None:
    result = _run_cleanup_driver(
        tmp_path,
        """
cleanup_task_safely "T01" "$PROJECT_ROOT/.gran-maestro/worktrees/REQ-680-T01" "gran-maestro/main/REQ-680-T01"
cleanup_task_safely "T02" "$PROJECT_ROOT/.gran-maestro/worktrees/REQ-680-T02" "gran-maestro/main/REQ-680-T02"
delete_req_branch_safely "gran-maestro/main/REQ-680" "T01" "T02"
""",
    )

    assert result.returncode == 0, result.stderr
    meta_t01 = tmp_path / "project" / ".gran-maestro" / "worktrees" / "REQ-680-T01.meta.json"
    meta_t02 = tmp_path / "project" / ".gran-maestro" / "worktrees" / "REQ-680-T02.meta.json"
    meta = json.loads(meta_t01.read_text(encoding="utf-8"))
    git_log = (tmp_path / "git.log").read_text(encoding="utf-8")

    assert meta["state"] == "clean_failed"
    assert meta["preserved"] == "keep"
    assert meta["clean_failed"]["exit_code"] == 12
    assert "worktree remove" in meta["clean_failed"]["command"]
    assert meta["clean_failed"]["message"] == "forced worktree remove failure for REQ-680-T01"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*Z", meta["clean_failed"]["timestamp"])
    assert not meta_t02.exists()
    assert "branch -D gran-maestro/main/REQ-680-T02" in git_log
    assert "branch -D gran-maestro/main/REQ-680" in git_log


def test_accept_req_branch_delete_failure_marks_each_task_meta(tmp_path: Path) -> None:
    result = _run_cleanup_driver(
        tmp_path,
        'delete_req_branch_safely "gran-maestro/main/REQ-BRANCH-FAIL" "T01" "T02"',
    )

    assert result.returncode == 0, result.stderr
    for task_id in ("T01", "T02"):
        meta_path = tmp_path / "project" / ".gran-maestro" / "worktrees" / f"REQ-680-{task_id}.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["state"] == "clean_failed"
        assert meta["clean_failed"]["exit_code"] == 23
        assert "branch -D gran-maestro/main/REQ-BRANCH-FAIL" in meta["clean_failed"]["command"]
        assert meta["clean_failed"]["message"] == "forced request branch delete failure"
