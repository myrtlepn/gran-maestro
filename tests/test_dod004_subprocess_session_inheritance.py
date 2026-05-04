from __future__ import annotations

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
RESOURCE_IDS = {"AGI-030", "PLN-638", "REQ-811"}


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


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


def _parent_env() -> dict[str, str]:
    return {
        "MST_SESSION_ID": PARENT_SESSION_ID,
        "MST_CONTEXT_JSON": json.dumps(
            {
                "schema_version": 1,
                "mst_session_id": PARENT_SESSION_ID,
                "root_mst_id": "AGI-030",
                "resource_id": "REQ-811",
                "plan_id": "PLN-638",
                "preserve": "yes",
            }
        ),
        "MST_STATE_PPID": "424242",
    }


def _legacy_only_env() -> dict[str, str]:
    return {
        "MST_STATE_PPID": "818181",
        "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
        "MST_HOOK_STDIN_RAW": json.dumps(
            {
                "session_id": CLAUDE_SESSION_ID,
                "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
                "owner_ppid": 818181,
                "owner_session_id": "owner-diagnostic-only",
            }
        ),
    }


def _assert_canonical_payload(payload: dict) -> None:
    assert payload["schema_version"] == 1
    assert payload["mst_session_id"] == PARENT_SESSION_ID
    assert payload["root_mst_id"] == "AGI-030"


def _assert_resource_ids_are_not_session_identity(values: set[str]) -> None:
    assert PARENT_SESSION_ID in values
    assert values.isdisjoint(RESOURCE_IDS)


def _read_non_success_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["created_new_session"] is False
    assert payload["canonical_mst_session_id"] is None
    return payload


def test_state_set_and_set_workflow_create_only_parent_keyed_artifacts() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        env = _parent_env()

        snapshot_result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "3",
            env=env,
        )
        workflow_result = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--req",
            "REQ-807",
            "--next-skill",
            "mst:approve",
            env=env,
        )

        assert snapshot_result.returncode == 0, snapshot_result.stderr
        assert workflow_result.returncode == 0, workflow_result.stderr
        snapshot_payload = json.loads(
            (workspace / ".gran-maestro" / "state" / PARENT_SESSION_ID / "snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        workflow_payload = json.loads(
            (workspace / ".gran-maestro" / "tmp" / f"mst-state-{PARENT_SESSION_ID}.json").read_text(
                encoding="utf-8"
            )
        )
        _assert_canonical_payload(snapshot_payload)
        _assert_canonical_payload(workflow_payload)
        _assert_resource_ids_are_not_session_identity(
            {snapshot_payload["mst_session_id"], workflow_payload["mst_session_id"]}
        )
        assert not (workspace / ".gran-maestro" / "state" / "424242").exists()
        for resource_id in RESOURCE_IDS:
            assert not (workspace / ".gran-maestro" / "state" / resource_id).exists()
            assert not (workspace / ".gran-maestro" / "tmp" / f"mst-state-{resource_id}.json").exists()
        assert not (workspace / ".gran-maestro" / "tmp" / "mst-state-424242.json").exists()
        assert not (workspace / ".gran-maestro" / "state" / "default").exists()


def test_dispatch_register_and_heartbeat_keep_single_canonical_parent_session() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        env = _parent_env()

        register_result = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "dod004-dispatch-subprocess",
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
        heartbeat_result = _run_mst(
            workspace,
            "dispatch",
            "heartbeat",
            "--task-id",
            "dod004-dispatch-subprocess",
            "--phase",
            "running",
            env=env,
        )

        assert register_result.returncode == 0, register_result.stderr
        assert heartbeat_result.returncode == 0, heartbeat_result.stderr
        register_payload = json.loads(register_result.stdout)
        heartbeat_payload = json.loads(heartbeat_result.stdout)
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod004-dispatch-subprocess.json").read_text(
                encoding="utf-8"
            )
        )
        marker_payload = json.loads(
            (workspace / ".gran-maestro" / "active-flow" / f"{PARENT_SESSION_ID}.json").read_text(
                encoding="utf-8"
            )
        )
        canonical = {
            register_payload["mst_session_id"],
            heartbeat_payload["mst_session_id"],
            run_payload["mst_session_id"],
            marker_payload["mst_session_id"],
            marker_payload["session_id"],
        }
        assert canonical == {PARENT_SESSION_ID}
        _assert_resource_ids_are_not_session_identity(canonical)
        assert register_payload["root_mst_id"] == "AGI-030"
        assert heartbeat_payload["root_mst_id"] == "AGI-030"
        assert run_payload["root_mst_id"] == "AGI-030"
        for resource_id in RESOURCE_IDS:
            assert not (workspace / ".gran-maestro" / "run" / f"{resource_id}.json").exists()
            assert not (workspace / ".gran-maestro" / "active-flow" / f"{resource_id}.json").exists()


def test_missing_parent_with_legacy_only_env_fails_without_new_session_artifacts() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _hashes(workspace)
        env = _legacy_only_env()

        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=env,
        )
        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            env=env,
        )
        dispatch = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "dod004-legacy-only",
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

        combined = "\n".join(f"{result.stdout}\n{result.stderr}" for result in (snapshot, workflow, dispatch))
        assert snapshot.returncode != 0
        assert workflow.returncode != 0
        assert dispatch.returncode != 0
        assert _hashes(workspace) == before
        for result in (snapshot, workflow, dispatch):
            payload = _read_non_success_payload(result)
            assert payload["code"] == "legacy_identity_not_canonical_source"
            diagnostics = payload["legacy_diagnostics"]
            assert diagnostics["MST_STATE_PPID"] == "818181"
            assert diagnostics["MST_SNAPSHOT_SESSION_ID"] == "legacy-snapshot-alias"
            assert diagnostics["hook_session_id"] == CLAUDE_SESSION_ID
            assert diagnostics["hook_transcript_stem"] == TRANSCRIPT_SESSION_ID
        assert "generated" not in combined
        assert not (workspace / ".gran-maestro" / "sessions").exists()


def test_env_context_mismatch_fails_without_snapshot_tmp_run_or_active_flow_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _hashes(workspace)
        mismatch_env = {
            "MST_SESSION_ID": PARENT_SESSION_ID,
            "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
            "MST_STATE_PPID": "424242",
        }

        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=mismatch_env,
        )
        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            env=mismatch_env,
        )
        dispatch = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "dod004-mismatch",
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            env=mismatch_env,
        )

        combined = "\n".join(f"{result.stdout}\n{result.stderr}" for result in (snapshot, workflow, dispatch))
        assert snapshot.returncode != 0
        assert workflow.returncode != 0
        assert dispatch.returncode != 0
        assert _hashes(workspace) == before
        assert "mismatch" in combined
        assert not (workspace / ".gran-maestro" / "state" / PARENT_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "tmp").exists()
        assert not (workspace / ".gran-maestro" / "run").exists()
        assert not (workspace / ".gran-maestro" / "active-flow").exists()


def main() -> int:
    tests = [
        test_state_set_and_set_workflow_create_only_parent_keyed_artifacts,
        test_dispatch_register_and_heartbeat_keep_single_canonical_parent_session,
        test_missing_parent_with_legacy_only_env_fails_without_new_session_artifacts,
        test_env_context_mismatch_fails_without_snapshot_tmp_run_or_active_flow_mutation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
