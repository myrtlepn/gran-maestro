from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import _common
from scripts.mst_cmds import workflow


ROOT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-805-20260503T131853000Z-r4n8vd1c"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_request(workspace: Path) -> None:
    req_dir = workspace / ".gran-maestro" / "requests" / "REQ-804"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "request.json").write_text(
        json.dumps(
            {
                "id": "REQ-804",
                "current_phase": 2,
                "status": "phase2_execution",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def test_workflow_claude_child_receives_validated_env_and_payload() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_request(workspace)
        _common.set_base_dir(workspace / ".gran-maestro")
        previous_env = os.environ.copy()
        calls: list[dict[str, object]] = []
        original_run_claude = workflow._run_claude

        def fake_run_claude(cmd: list[str], env: dict[str, str] | None = None) -> int:
            calls.append({"cmd": cmd, "env": dict(env or {})})
            req_path = workspace / ".gran-maestro" / "requests" / "REQ-804" / "request.json"
            payload = json.loads(req_path.read_text(encoding="utf-8"))
            payload["current_phase"] = 5
            payload["status"] = "done"
            req_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return 0

        try:
            os.environ.clear()
            os.environ.update(_clean_env({"MST_SESSION_ID": ROOT_SESSION_ID}))
            workflow._run_claude = fake_run_claude
            result = workflow.cmd_workflow_run(argparse.Namespace(target="REQ-804"))
        finally:
            workflow._run_claude = original_run_claude
            os.environ.clear()
            os.environ.update(previous_env)
            _common.set_base_dir(None)

        assert result == 0
        assert len(calls) == 1
        child_env = calls[0]["env"]
        assert isinstance(child_env, dict)
        assert child_env["MST_SESSION_ID"] == ROOT_SESSION_ID
        assert json.loads(child_env["MST_CONTEXT_JSON"])["mst_session_id"] == ROOT_SESSION_ID
        assert {child_env["MST_SESSION_ID"], json.loads(child_env["MST_CONTEXT_JSON"])["mst_session_id"]} == {
            ROOT_SESSION_ID
        }


def test_workflow_validation_failure_prevents_claude_invocation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_request(workspace)
        _common.set_base_dir(workspace / ".gran-maestro")
        previous_env = os.environ.copy()
        calls: list[list[str]] = []
        original_run_claude = workflow._run_claude

        def fake_run_claude(cmd: list[str], env: dict[str, str] | None = None) -> int:
            del env
            calls.append(cmd)
            return 0

        try:
            os.environ.clear()
            os.environ.update(
                _clean_env(
                    {
                        "MST_SESSION_ID": ROOT_SESSION_ID,
                        "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
                    }
                )
            )
            workflow._run_claude = fake_run_claude
            result = workflow.cmd_workflow_run(argparse.Namespace(target="REQ-804"))
        finally:
            workflow._run_claude = original_run_claude
            os.environ.clear()
            os.environ.update(previous_env)
            _common.set_base_dir(None)

        assert result != 0
        assert calls == []


def main() -> int:
    tests = [
        test_workflow_claude_child_receives_validated_env_and_payload,
        test_workflow_validation_failure_prevents_claude_invocation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
