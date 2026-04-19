from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(
    workspace: Path,
    *args: str,
    input_payload: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        input=input_payload,
        capture_output=True,
        text=True,
        check=False,
        env=merged_env,
    )


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


def _write_state(workspace: Path, payload: dict, *, name: str = "state.json") -> Path:
    state_path = workspace / ".gran-maestro" / "tmp" / name
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return state_path


def _write_transcript(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def test_context_usage_sums_tokens_and_state_flags(tmp_path):
    workspace = tmp_path / "workspace"
    _write_config(workspace, auto_approve_on_unblock=True)
    state_path = _write_state(
        workspace,
        {
            "workflow_active": True,
            "next_action": {"auto_mode": False},
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(
        transcript_path,
        [
            {"message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 1}}},
            {
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {
                        "input_tokens": 100_000,
                        "cache_read_input_tokens": 25_000,
                        "cache_creation_input_tokens": 5_000,
                    },
                }
            },
        ],
    )

    proc = _run_mst(
        workspace,
        "status",
        "context-usage",
        "--transcript-path",
        str(transcript_path),
        "--state-file",
        str(state_path),
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {
        "context_pct": 0.65,
        "context_tokens": 130_000,
        "model_window": 200_000,
        "cache_available": True,
        "auto_approve_on_unblock": True,
        "workflow_active": True,
        "in_auto_chain": True,
    }


def test_context_usage_accepts_stdin_payload_and_env_model(tmp_path):
    workspace = tmp_path / "workspace"
    _write_config(workspace, auto_approve_on_unblock=False)
    transcript_path = workspace / "session.jsonl"
    _write_transcript(
        transcript_path,
        [
            {
                "model": "unknown-model",
                "message": {
                    "usage": {
                        "input_tokens": 250_000,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        ],
    )

    proc = _run_mst(
        workspace,
        "status",
        "context-usage",
        input_payload=json.dumps({"transcript_path": str(transcript_path)}),
        env={"CLAUDE_MODEL": "claude-opus-4-7"},
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["context_tokens"] == 250_000
    assert payload["model_window"] == 1_000_000
    assert payload["context_pct"] == 0.25
    assert payload["cache_available"] is False
    assert payload["workflow_active"] is False
    assert payload["in_auto_chain"] is False


def test_context_usage_unknown_model_and_missing_state_are_graceful(tmp_path):
    workspace = tmp_path / "workspace"
    _write_config(workspace, auto_approve_on_unblock=False)
    transcript_path = workspace / "session.jsonl"
    _write_transcript(
        transcript_path,
        [
            {
                "message": {
                    "model": "claude-future-model",
                    "usage": {"input_tokens": 42},
                }
            }
        ],
    )

    proc = _run_mst(
        workspace,
        "status",
        "context-usage",
        "--transcript-path",
        str(transcript_path),
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["context_pct"] is None
    assert payload["context_tokens"] == 42
    assert payload["model_window"] is None
    assert payload["cache_available"] is False
    assert payload["auto_approve_on_unblock"] is False
    assert payload["workflow_active"] is False
    assert payload["in_auto_chain"] is False


def test_context_usage_missing_or_broken_transcript_exits_zero(tmp_path):
    workspace = tmp_path / "workspace"
    _write_config(workspace, auto_approve_on_unblock=False)
    broken_path = workspace / "broken.jsonl"
    broken_path.write_text("{not-json}\n", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "status",
        "context-usage",
        "--transcript-path",
        str(broken_path),
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["context_pct"] is None
    assert payload["context_tokens"] == 0
    assert payload["model_window"] is None
    assert payload["cache_available"] is False
