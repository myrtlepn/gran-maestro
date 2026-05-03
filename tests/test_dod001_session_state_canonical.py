from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ROOT_SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
LEGACY_HOOK_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "MST_HOOK_STDIN_RAW",
        "MST_CONTEXT_JSON",
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
        env=_clean_env(env),
        check=False,
        timeout=30,
    )


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _legacy_env() -> dict[str, str]:
    return {
        "MST_STATE_PPID": "424242",
        "MST_SNAPSHOT_SESSION_ID": "pid-legacy-snapshot",
        "MST_HOOK_STDIN_RAW": json.dumps(
            {
                "session_id": LEGACY_HOOK_SESSION_ID,
                "transcript_path": f"/tmp/{LEGACY_TRANSCRIPT_SESSION_ID}.jsonl",
            }
        ),
    }


def test_root_session_resolve_generates_one_path_safe_canonical_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(workspace, "session", "resolve", "--json")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        mst_session_id = payload.get("mst_session_id")
        assert isinstance(mst_session_id, str) and mst_session_id
        assert payload.get("session_id") == mst_session_id
        assert payload.get("source") == "generated"
        assert PATH_SAFE_RE.fullmatch(mst_session_id)
        assert ".." not in mst_session_id
        assert _files(workspace) == before


def test_missing_parent_mutating_state_writes_fail_without_legacy_or_uuid_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--next-skill",
            "mst:approve",
            env=_legacy_env(),
        )
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
            env=_legacy_env(),
        )

        assert workflow.returncode != 0
        assert snapshot.returncode != 0
        assert _files(workspace) == before
        combined = f"{workflow.stdout}\n{workflow.stderr}\n{snapshot.stdout}\n{snapshot.stderr}"
        assert "missing MST_SESSION_ID" in combined
        assert LEGACY_HOOK_SESSION_ID not in combined
        assert LEGACY_TRANSCRIPT_SESSION_ID not in combined
        assert "424242" not in combined


def test_legacy_values_are_diagnostic_only_not_canonical_sources() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        env = {"MST_SESSION_ID": ROOT_SESSION_ID, **_legacy_env()}

        result = _run_mst(workspace, "session", "resolve", "--json", env=env)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mst_session_id"] == ROOT_SESSION_ID
        assert payload["session_id"] == ROOT_SESSION_ID
        assert payload["source"] == "env:MST_SESSION_ID"
        canonical_values = {payload["mst_session_id"], payload["session_id"]}
        assert "424242" not in canonical_values
        assert LEGACY_HOOK_SESSION_ID not in canonical_values
        assert LEGACY_TRANSCRIPT_SESSION_ID not in canonical_values
        diagnostics = payload.get("legacy_diagnostics")
        assert diagnostics["MST_STATE_PPID"] == "424242"
        assert diagnostics["hook_session_id"] == LEGACY_HOOK_SESSION_ID
        assert diagnostics["hook_transcript_stem"] == LEGACY_TRANSCRIPT_SESSION_ID


def main() -> int:
    tests = [
        test_root_session_resolve_generates_one_path_safe_canonical_id,
        test_missing_parent_mutating_state_writes_fail_without_legacy_or_uuid_fallback,
        test_legacy_values_are_diagnostic_only_not_canonical_sources,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
