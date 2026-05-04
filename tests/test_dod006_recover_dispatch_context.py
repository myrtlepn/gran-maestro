from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-AGI-030-20260504T160133000Z-dod006a1"
OTHER_SID = "MST-AGI-030-20260504T160133000Z-dod006b2"
ROOT = "AGI-030"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


def _context(session_id: str = SID) -> dict:
    return {
        "prompt_summary": "diagnostic-only",
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "workflow": {"current_skill": "mst:request", "status": "active"},
            "history": {"head_hash": "a" * 64, "seq": 7},
            "next_execution": {
                "env": {"MST_SESSION_ID": session_id},
                "context": {"mst_session_id": session_id, "recovery_fingerprint": "recover:test"},
            },
        },
    }


def _env(context: dict | list | None = None, *, session_id: str = SID) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_SESSION_ID"] = session_id
    env["MST_CONTEXT_JSON"] = json.dumps(_context() if context is None else context, separators=(",", ":"))
    return env


def _run(workspace: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_recovered_context_bundle_is_propagated_to_dispatch_register_and_heartbeat() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        _init_workspace(workspace)
        env = _env()

        register = _run(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "dod006-dispatch",
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
        heartbeat = _run(
            workspace,
            "dispatch",
            "heartbeat",
            "--task-id",
            "dod006-dispatch",
            "--phase",
            "running",
            env=env,
        )

        assert register.returncode == 0, register.stderr
        assert heartbeat.returncode == 0, heartbeat.stderr
        register_payload = json.loads(register.stdout)
        heartbeat_payload = json.loads(heartbeat.stdout)
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod006-dispatch.json").read_text(encoding="utf-8")
        )
        for payload in (register_payload, heartbeat_payload, run_payload):
            assert payload["schema_version"] == 1
            assert payload["mst_session_id"] == SID
            assert payload["root_mst_id"] == ROOT


def test_child_env_preserves_recovered_context_and_rejects_mismatch_or_non_object() -> None:
    from scripts.mst_cmds import session as session_mod

    previous_env = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(_env())
        child_env = session_mod.child_env_with_required_session_context()
        child_context = json.loads(child_env["MST_CONTEXT_JSON"])
        assert child_env["MST_SESSION_ID"] == SID
        assert child_context["mst_session_id"] == SID
        assert child_context["root_mst_id"] == ROOT
        assert child_context["core_rehydration"]["mst_session_id"] == SID
        assert child_context["core_rehydration"]["next_execution"]["env"]["MST_SESSION_ID"] == SID
        assert child_context["core_rehydration"]["next_execution"]["context"]["mst_session_id"] == SID

        os.environ["MST_CONTEXT_JSON"] = json.dumps(_context(OTHER_SID), separators=(",", ":"))
        try:
            session_mod.child_env_with_required_session_context()
        except ValueError as exc:
            assert "mismatch" in str(exc)
        else:
            raise AssertionError("mismatched recovered context should fail closed")

        os.environ["MST_CONTEXT_JSON"] = json.dumps(["not", "an", "object"])
        try:
            session_mod.child_env_with_required_session_context()
        except ValueError as exc:
            assert "JSON object" in str(exc)
        else:
            raise AssertionError("non-object MST_CONTEXT_JSON should fail closed")
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def main() -> int:
    test_recovered_context_bundle_is_propagated_to_dispatch_register_and_heartbeat()
    test_child_env_preserves_recovered_context_and_rejects_mismatch_or_non_object()
    print("PASS test_recovered_context_bundle_is_propagated_to_dispatch_register_and_heartbeat")
    print("PASS test_child_env_preserves_recovered_context_and_rejects_mismatch_or_non_object")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
