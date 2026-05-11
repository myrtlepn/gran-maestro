"""REQ-734/T02: auto-chain-context UserPromptSubmit schema regression tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"
TEST_SESSION_ID = "MST-REQ-857-20260511T110121000Z-abcdef12"


def _copy_hook_to_plugin_cache(tmp_path: Path) -> Path:
    hook_path = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "gran-maestro"
        / "mst"
        / "test"
        / "hooks"
        / "mst-auto-chain-context.sh"
    )
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SCRIPT, hook_path)
    return hook_path


def _prepare_project_root(tmp_path: Path, *, use_real_mst: bool = True) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".git").write_text("gitdir: test\n", encoding="utf-8")

    if use_real_mst:
        (project_root / "scripts").symlink_to(REPO_ROOT / "scripts", target_is_directory=True)
    else:
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "mst.py").write_text(
            "#!/usr/bin/env python3\nprint('not-json')\n",
            encoding="utf-8",
        )

    return project_root


def _write_config(project_root: Path, *, auto_approve_on_unblock: bool = True) -> None:
    (project_root / ".gran-maestro" / "config.resolved.json").write_text(
        json.dumps(
            {"workflow": {"auto_approve_on_unblock": auto_approve_on_unblock}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_state(project_root: Path, payload: dict) -> Path:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{TEST_SESSION_ID}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return state_path


def _write_transcript(project_root: Path) -> Path:
    transcript_path = project_root / "session.jsonl"
    row = {
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 100_000,
                "cache_read_input_tokens": 20_000,
                "cache_creation_input_tokens": 10_000,
            },
        }
    }
    transcript_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return transcript_path


def _run_hook(
    hook_path: Path,
    project_root: Path,
    payload: dict,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(hook_path)],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MST_SESSION_ID": TEST_SESSION_ID},
    )


def _active_payload(transcript_path: Path, project_root: Path) -> dict:
    return {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(project_root),
        "transcript_path": str(transcript_path),
    }


def _active_result(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    hook_path = _copy_hook_to_plugin_cache(tmp_path)
    project_root = _prepare_project_root(tmp_path)
    _write_config(project_root)
    _write_state(project_root, {"workflow_active": True, "next_action": {"auto_mode": False}})
    transcript_path = _write_transcript(project_root)

    return _run_hook(hook_path, project_root, _active_payload(transcript_path, project_root))


def _hook_specific_output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "active hook must emit UserPromptSubmit JSON"
    payload = json.loads(result.stdout)
    hook_output = payload.get("hookSpecificOutput")
    assert isinstance(hook_output, dict)
    return hook_output


def test_active_emits_user_prompt_submit_json(tmp_path):
    result = _active_result(tmp_path)

    hook_output = _hook_specific_output(result)
    assert hook_output["hookEventName"] == "UserPromptSubmit"
    assert isinstance(hook_output["additionalContext"], str)
    assert hook_output["additionalContext"].strip()


def test_additional_context_preserves_4_lines(tmp_path):
    result = _active_result(tmp_path)

    additional_context = _hook_specific_output(result)["additionalContext"]
    for expected in (
        "컨텍스트 사용률:",
        "캐싱:",
        "workflow.auto_approve_on_unblock:",
        "안내:",
    ):
        assert expected in additional_context


def test_inactive_emits_empty(tmp_path):
    hook_path = _copy_hook_to_plugin_cache(tmp_path)
    project_root = _prepare_project_root(tmp_path)
    _write_config(project_root)
    _write_state(project_root, {"workflow_active": False, "next_action": {"auto_mode": False}})
    missing_transcript = project_root / "missing.jsonl"

    result = _run_hook(hook_path, project_root, _active_payload(missing_transcript, project_root))

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_parse_failure_fail_open(tmp_path):
    hook_path = _copy_hook_to_plugin_cache(tmp_path)
    project_root = _prepare_project_root(tmp_path, use_real_mst=False)
    _write_state(project_root, {"workflow_active": True, "next_action": {"auto_mode": False}})
    transcript_path = _write_transcript(project_root)

    result = _run_hook(hook_path, project_root, _active_payload(transcript_path, project_root))

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
