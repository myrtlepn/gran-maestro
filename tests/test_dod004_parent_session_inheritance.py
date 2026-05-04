from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
PARENT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-807-20260503T131853000Z-r4n8vd1c"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import _common
from scripts.mst_cmds import workflow


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


def _init_request(workspace: Path) -> None:
    req_dir = workspace / ".gran-maestro" / "requests" / "REQ-807"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "request.json").write_text(
        json.dumps({"id": "REQ-807", "current_phase": 2, "status": "phase2_execution"}, indent=2) + "\n",
        encoding="utf-8",
    )


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
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


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=_clean_env(env),
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


def test_parent_env_context_run_payload_and_active_marker_keep_exact_session_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        context = {"mst_session_id": PARENT_SESSION_ID, "unrelated": {"keep": True}}
        env = {
            "MST_SESSION_ID": PARENT_SESSION_ID,
            "MST_CONTEXT_JSON": json.dumps(context, separators=(",", ":")),
            "MST_STATE_PPID": "424242",
        }

        result = _register_child(workspace, "dod004-parent-dispatch", env)

        assert result.returncode == 0, result.stderr
        stdout_payload = json.loads(result.stdout)
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod004-parent-dispatch.json").read_text(encoding="utf-8")
        )
        active_marker = json.loads(
            (workspace / ".gran-maestro" / "active-flow" / f"{PARENT_SESSION_ID}.json").read_text(
                encoding="utf-8"
            )
        )
        observed = {
            env["MST_SESSION_ID"],
            json.loads(env["MST_CONTEXT_JSON"])["mst_session_id"],
            stdout_payload["mst_session_id"],
            run_payload["mst_session_id"],
            active_marker["mst_session_id"],
            active_marker["session_id"],
        }
        assert observed == {PARENT_SESSION_ID}
        assert run_payload["started_by_pid"] == 424242


def test_workflow_child_invocation_inherits_parent_context_and_preserves_unrelated_keys() -> None:
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
            req_path = workspace / ".gran-maestro" / "requests" / "REQ-807" / "request.json"
            payload = json.loads(req_path.read_text(encoding="utf-8"))
            payload["current_phase"] = 5
            payload["status"] = "done"
            req_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return 0

        try:
            os.environ.clear()
            os.environ.update(
                _clean_env(
                    {
                        "MST_SESSION_ID": PARENT_SESSION_ID,
                        "MST_CONTEXT_JSON": json.dumps(
                            {
                                "mst_session_id": PARENT_SESSION_ID,
                                "unrelated": {"keep": "value"},
                                "list_key": [1, 2, 3],
                            }
                        ),
                    }
                )
            )
            workflow._run_claude = fake_run_claude
            result = workflow.cmd_workflow_run(argparse.Namespace(target="REQ-807"))
        finally:
            workflow._run_claude = original_run_claude
            os.environ.clear()
            os.environ.update(previous_env)
            _common.set_base_dir(None)

        assert result == 0
        assert len(calls) == 1
        child_env = calls[0]["env"]
        assert isinstance(child_env, dict)
        child_context = json.loads(child_env["MST_CONTEXT_JSON"])
        assert child_env["MST_SESSION_ID"] == PARENT_SESSION_ID
        assert child_context["mst_session_id"] == PARENT_SESSION_ID
        assert child_context["unrelated"] == {"keep": "value"}
        assert child_context["list_key"] == [1, 2, 3]


def test_missing_parent_with_legacy_metadata_fails_closed_without_generated_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _hashes(workspace)
        env = {
            "MST_HOOK_STDIN_RAW": json.dumps(
                {
                    "session_id": CLAUDE_SESSION_ID,
                    "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
                    "owner_ppid": 818181,
                    "owner_session_id": "owner-diagnostic-only",
                }
            ),
            "MST_STATE_PPID": "818181",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
        }

        result = _register_child(workspace, "dod004-missing-parent", env)

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _hashes(workspace) == before
        assert "missing MST_SESSION_ID" in combined
        assert not UUID_V4_RE.search(combined)
        assert CLAUDE_SESSION_ID not in combined
        assert TRANSCRIPT_SESSION_ID not in combined
        assert "818181" not in combined
        assert not (workspace / ".gran-maestro" / "run").exists()
        assert not (workspace / ".gran-maestro" / "active-flow").exists()
        assert not (workspace / ".gran-maestro" / "tmp").exists()


def test_workflow_env_context_mismatch_fails_closed_without_invoking_child_provider() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _init_request(workspace)
        before = _hashes(workspace)
        _common.set_base_dir(workspace / ".gran-maestro")
        previous_env = os.environ.copy()
        calls: list[dict[str, object]] = []
        original_run_claude = workflow._run_claude

        def fake_run_claude(cmd: list[str], env: dict[str, str] | None = None) -> int:
            calls.append({"cmd": cmd, "env": dict(env or {})})
            return 0

        try:
            os.environ.clear()
            os.environ.update(
                _clean_env(
                    {
                        "MST_SESSION_ID": PARENT_SESSION_ID,
                        "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
                    }
                )
            )
            workflow._run_claude = fake_run_claude
            result = workflow.cmd_workflow_run(argparse.Namespace(target="REQ-807"))
        finally:
            workflow._run_claude = original_run_claude
            os.environ.clear()
            os.environ.update(previous_env)
            _common.set_base_dir(None)

        assert result != 0
        assert calls == []
        assert _hashes(workspace) == before


def main() -> int:
    tests = [
        test_parent_env_context_run_payload_and_active_marker_keep_exact_session_id,
        test_workflow_child_invocation_inherits_parent_context_and_preserves_unrelated_keys,
        test_missing_parent_with_legacy_metadata_fails_closed_without_generated_fallback,
        test_workflow_env_context_mismatch_fails_closed_without_invoking_child_provider,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
