from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STRUCTURED_PARENT = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STRUCTURED_STALE = "MST-REQ-805-20260503T131853000Z-r4n8vd1c"
LEGACY_CLAUDE_SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_TRANSCRIPT_SESSION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import _common
from scripts.mst_cmds import workflow


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=_env(env),
        check=False,
        timeout=30,
    )


def _register_child(workspace: Path, task_id: str, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
    return _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )


def _read_non_success_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["created_new_session"] is False
    assert payload["canonical_mst_session_id"] is None
    return payload


def _init_request(workspace: Path) -> None:
    req_dir = workspace / ".gran-maestro" / "requests" / "REQ-805"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "request.json").write_text(
        json.dumps({"id": "REQ-805", "current_phase": 2, "status": "phase2_execution"}, indent=2) + "\n",
        encoding="utf-8",
    )


def test_dispatch_child_env_and_context_inherit_parent_structured_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        env = {
            "MST_SESSION_ID": STRUCTURED_PARENT,
            "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STRUCTURED_PARENT, "keep": "value"}),
            "MST_STATE_PPID": "424242",
        }

        result = _register_child(workspace, "dod002-dispatch-inherit", env)

        assert result.returncode == 0, result.stderr
        stdout_payload = json.loads(result.stdout)
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod002-dispatch-inherit.json").read_text(encoding="utf-8")
        )
        active_marker = json.loads(
            (workspace / ".gran-maestro" / "active-flow" / f"{STRUCTURED_PARENT}.json").read_text(
                encoding="utf-8"
            )
        )
        assert stdout_payload["mst_session_id"] == STRUCTURED_PARENT
        assert run_payload["mst_session_id"] == STRUCTURED_PARENT
        assert active_marker["mst_session_id"] == STRUCTURED_PARENT
        assert active_marker["session_id"] == STRUCTURED_PARENT
        assert run_payload["started_by_pid"] == 424242


def test_workflow_child_env_and_context_inherit_parent_structured_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _init_request(workspace)
        _common.set_base_dir(workspace / ".gran-maestro")
        previous_env = os.environ.copy()
        calls: list[dict[str, object]] = []
        original_run_claude = workflow._run_claude

        def fake_run_claude(cmd: list[str], env: dict[str, str] | None = None) -> int:
            calls.append({"cmd": cmd, "env": dict(env or {})})
            req_path = workspace / ".gran-maestro" / "requests" / "REQ-805" / "request.json"
            payload = json.loads(req_path.read_text(encoding="utf-8"))
            payload["current_phase"] = 5
            payload["status"] = "done"
            req_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return 0

        try:
            os.environ.clear()
            os.environ.update(
                _env(
                    {
                        "MST_SESSION_ID": STRUCTURED_PARENT,
                        "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STRUCTURED_PARENT, "keep": "value"}),
                    }
                )
            )
            workflow._run_claude = fake_run_claude
            result = workflow.cmd_workflow_run(argparse.Namespace(target="REQ-805"))
        finally:
            workflow._run_claude = original_run_claude
            os.environ.clear()
            os.environ.update(previous_env)
            _common.set_base_dir(None)

        assert result == 0
        assert len(calls) == 1
        child_env = calls[0]["env"]
        assert isinstance(child_env, dict)
        context = json.loads(child_env["MST_CONTEXT_JSON"])
        assert child_env["MST_SESSION_ID"] == STRUCTURED_PARENT
        assert context["mst_session_id"] == STRUCTURED_PARENT
        assert context["keep"] == "value"


def test_child_context_payload_without_parent_env_inherits_canonical_identity() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        result = _register_child(
            workspace,
            "dod002-payload-only",
            {"MST_CONTEXT_JSON": json.dumps({"mst_session_id": STRUCTURED_PARENT})},
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mst_session_id"] == STRUCTURED_PARENT
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod002-payload-only.json").read_text(encoding="utf-8")
        )
        assert run_payload["mst_session_id"] == STRUCTURED_PARENT


def test_child_missing_parent_does_not_generate_from_child_or_legacy_ids() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)
        env = {
            "MST_HOOK_STDIN_RAW": json.dumps(
                {
                    "session_id": LEGACY_CLAUDE_SESSION,
                    "transcript_path": f"/tmp/{LEGACY_TRANSCRIPT_SESSION}.jsonl",
                    "tool_input": {"task_id": "REQ-805"},
                }
            ),
            "MST_STATE_PPID": "818181",
        }

        result = _register_child(workspace, "REQ-805-child-artifact", env)

        assert result.returncode != 0
        assert _files(workspace) == before
        payload = _read_non_success_payload(result)
        assert payload["code"] == "legacy_identity_not_canonical_source"
        diagnostics = payload["legacy_diagnostics"]
        assert diagnostics["MST_STATE_PPID"] == "818181"
        assert diagnostics["hook_session_id"] == LEGACY_CLAUDE_SESSION
        assert diagnostics["hook_transcript_stem"] == LEGACY_TRANSCRIPT_SESSION
        assert "REQ-805-child-artifact" not in f"{result.stdout}\n{result.stderr}"


def test_child_env_payload_mismatch_fails_without_replacement_generation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _register_child(
            workspace,
            "dod002-mismatch",
            {
                "MST_SESSION_ID": STRUCTURED_PARENT,
                "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STRUCTURED_STALE}),
            },
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _files(workspace) == before
        assert "mismatch" in combined
        assert "generated" not in combined


def main() -> int:
    tests = [
        test_dispatch_child_env_and_context_inherit_parent_structured_id,
        test_workflow_child_env_and_context_inherit_parent_structured_id,
        test_child_context_payload_without_parent_env_inherits_canonical_identity,
        test_child_missing_parent_does_not_generate_from_child_or_legacy_ids,
        test_child_env_payload_mismatch_fails_without_replacement_generation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
