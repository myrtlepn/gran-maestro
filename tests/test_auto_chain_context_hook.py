from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"


def _prepare_workspace(workspace: Path) -> None:
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    for name in ("scripts", "templates"):
        target = workspace / name
        if not target.exists():
            target.symlink_to(REPO_ROOT / name, target_is_directory=True)


def _write_config(workspace: Path, *, auto_approve_on_unblock: bool) -> None:
    gm_dir = workspace / ".gran-maestro"
    gm_dir.mkdir(parents=True, exist_ok=True)
    (gm_dir / "config.resolved.json").write_text(
        json.dumps(
            {"workflow": {"auto_approve_on_unblock": auto_approve_on_unblock}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_state(workspace: Path, payload: dict) -> Path:
    state_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return state_path


def _write_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_hook(workspace: Path, payload: dict | str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(workspace / "home"),
        "CLAUDE_CONFIG_DIR": str(workspace / "home" / ".claude"),
    }
    if isinstance(payload, str):
        stdin = payload
    else:
        stdin = json.dumps(payload, ensure_ascii=False)
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        cwd=workspace,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_full_block_format_when_workflow_active(tmp_path):
    workspace = tmp_path / "workspace"
    _prepare_workspace(workspace)
    _write_config(workspace, auto_approve_on_unblock=True)
    _write_state(
        workspace,
        {
            "workflow_active": True,
            "next_action": {"auto_mode": False},
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(transcript_path)

    result = _run_hook(workspace, {"transcript_path": str(transcript_path)})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "[자동 연쇄 컨텍스트]" in additional
    assert "- 컨텍스트 사용률: 65.0% (130000 / 200000 tokens)" in additional
    assert "- 캐싱: true" in additional
    assert "- workflow.auto_approve_on_unblock: true" in additional
    assert "위 수치가 위험 임계 이하이면 chain 지속이 정상 경로입니다." in additional
    assert "단독 근거로 chain을 끊지 마세요." in additional


def test_full_block_format_when_next_action_auto_mode(tmp_path):
    workspace = tmp_path / "workspace"
    _prepare_workspace(workspace)
    _write_config(workspace, auto_approve_on_unblock=False)
    _write_state(
        workspace,
        {
            "workflow_active": False,
            "next_action": {"auto_mode": True},
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(transcript_path)

    result = _run_hook(workspace, {"transcript_path": str(transcript_path)})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "[자동 연쇄 컨텍스트]" in additional
    assert "- workflow.auto_approve_on_unblock: false" in additional


def test_no_op_when_not_in_chain(tmp_path):
    workspace = tmp_path / "workspace"
    _prepare_workspace(workspace)
    _write_config(workspace, auto_approve_on_unblock=True)
    _write_state(
        workspace,
        {
            "workflow_active": False,
            "next_action": {"auto_mode": False},
        },
    )

    result = _run_hook(workspace, {"transcript_path": str(workspace / "missing.jsonl")})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_no_op_on_missing_state_or_bad_stdin(tmp_path):
    workspace = tmp_path / "workspace"
    _prepare_workspace(workspace)

    result = _run_hook(workspace, "not-json")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
