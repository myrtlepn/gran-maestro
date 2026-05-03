from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
ROOT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-805-20260503T131853000Z-r4n8vd1c"
LEGACY_HOOK_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEGACY_TRANSCRIPT_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


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


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


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


def test_child_dispatch_env_payload_match_preserves_single_root_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        env = {
            "MST_SESSION_ID": ROOT_SESSION_ID,
            "MST_CONTEXT_JSON": json.dumps({"mst_session_id": ROOT_SESSION_ID}),
            "MST_STATE_PPID": "424242",
        }

        result = _register_child(workspace, "dod001-match", env)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        run_payload = json.loads(
            (workspace / ".gran-maestro" / "run" / "dod001-match.json").read_text(encoding="utf-8")
        )
        marker_payload = json.loads(
            (workspace / ".gran-maestro" / "active-flow" / f"{ROOT_SESSION_ID}.json").read_text(
                encoding="utf-8"
            )
        )
        observations = [
            {"point": "child_dispatch_env", "mst_session_id": env["MST_SESSION_ID"], "source": "env"},
            {
                "point": "child_dispatch_payload",
                "mst_session_id": json.loads(env["MST_CONTEXT_JSON"])["mst_session_id"],
                "source": "json",
            },
            {"point": "dispatch_capture", "mst_session_id": payload["mst_session_id"], "source": "stdout"},
            {"point": "dispatch_state_payload", "mst_session_id": run_payload["mst_session_id"], "source": "json"},
            {"point": "ledger_event", "mst_session_id": marker_payload["mst_session_id"], "source": "active-flow"},
        ]
        canonical_set = {item["mst_session_id"] for item in observations}

        assert canonical_set == {ROOT_SESSION_ID}
        assert marker_payload["session_id"] == ROOT_SESSION_ID
        assert marker_payload["mst_session_id"] == ROOT_SESSION_ID
        assert run_payload["started_by_pid"] == 424242


def test_child_dispatch_env_payload_mismatch_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)
        env = {
            "MST_SESSION_ID": ROOT_SESSION_ID,
            "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
        }

        result = _register_child(workspace, "dod001-mismatch", env)

        assert result.returncode != 0
        assert _files(workspace) == before
        assert "mismatch" in f"{result.stdout}\n{result.stderr}"


def test_child_dispatch_missing_parent_fails_without_uuid_or_legacy_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)
        env = {
            "MST_HOOK_STDIN_RAW": json.dumps(
                {
                    "session_id": LEGACY_HOOK_SESSION_ID,
                    "transcript_path": f"/tmp/{LEGACY_TRANSCRIPT_SESSION_ID}.jsonl",
                }
            ),
            "MST_STATE_PPID": "818181",
        }

        result = _register_child(workspace, "dod001-missing-parent", env)

        assert result.returncode != 0
        assert _files(workspace) == before
        combined = f"{result.stdout}\n{result.stderr}"
        assert "missing MST_SESSION_ID" in combined
        assert LEGACY_HOOK_SESSION_ID not in combined
        assert LEGACY_TRANSCRIPT_SESSION_ID not in combined
        assert "818181" not in combined


def test_dispatch_build_requires_existing_parent_session_without_resolve_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        prompt_file = workspace / "prompt.md"
        prompt_file.write_text("hello", encoding="utf-8")
        log_file = workspace / "dispatch.log"

        result = _run_mst(
            workspace,
            "dispatch",
            "build",
            "--provider",
            "codex",
            "--prompt-file",
            str(prompt_file),
            "--task-id",
            "dod001-build",
            "--worktree-dir",
            str(workspace),
            "--log-file",
            str(log_file),
            "--model",
            "gpt-test",
        )

        assert result.returncode == 0, result.stderr
        command = result.stdout.strip()
        assert "session resolve" not in command
        assert "MST_CONTEXT_JSON" in command

        before = _files(workspace)
        executed = subprocess.run(
            ["bash", "-c", command],
            cwd=workspace,
            capture_output=True,
            text=True,
            env=_env(),
            check=False,
            timeout=30,
        )

        assert executed.returncode == 2
        assert _files(workspace) == before
        assert "missing MST_SESSION_ID" in f"{executed.stdout}\n{executed.stderr}"


def main() -> int:
    tests = [
        test_child_dispatch_env_payload_match_preserves_single_root_id,
        test_child_dispatch_env_payload_mismatch_fails_without_mutation,
        test_child_dispatch_missing_parent_fails_without_uuid_or_legacy_fallback,
        test_dispatch_build_requires_existing_parent_session_without_resolve_fallback,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
