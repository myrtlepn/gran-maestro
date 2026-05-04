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
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
ROOT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-805-20260503T131853000Z-r4n8vd1c"
LEGACY_HOOK_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


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


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def _read_non_success_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["created_new_session"] is False
    assert payload["canonical_mst_session_id"] is None
    return payload


def test_session_resolve_without_root_or_parent_fails_without_uuid_generation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(workspace, "session", "resolve", "--json")

        assert result.returncode != 0
        payload = _read_non_success_payload(result)
        assert payload["code"] == "missing_canonical_mst_session_id"
        assert payload["legacy_diagnostics"] == {}
        combined = _combined(result)
        assert not UUID_V4_RE.search(combined)
        assert _files(workspace) == before


def test_legacy_runtime_values_are_not_canonical_fallback_sources() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(workspace, "session", "resolve", "--json", env=_legacy_env())

        assert result.returncode != 0
        payload = _read_non_success_payload(result)
        assert payload["code"] == "legacy_identity_not_canonical_source"
        diagnostics = payload["legacy_diagnostics"]
        assert diagnostics["MST_STATE_PPID"] == "424242"
        assert diagnostics["MST_SNAPSHOT_SESSION_ID"] == "pid-legacy-snapshot"
        assert diagnostics["hook_session_id"] == LEGACY_HOOK_SESSION_ID
        assert diagnostics["hook_transcript_stem"] == LEGACY_TRANSCRIPT_SESSION_ID
        combined = _combined(result)
        assert "generated" not in combined
        assert _files(workspace) == before


def test_env_payload_mismatch_fails_without_generating_replacement() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(
            workspace,
            "session",
            "resolve",
            "--json",
            env={
                "MST_SESSION_ID": ROOT_SESSION_ID,
                "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
            },
        )

        assert result.returncode != 0
        combined = _combined(result)
        assert "mismatch" in combined
        assert "generated" not in combined
        assert _files(workspace) == before


def test_missing_parent_mutating_state_write_fails_without_legacy_or_uuid_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(
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

        assert result.returncode != 0
        payload = _read_non_success_payload(result)
        assert payload["code"] == "legacy_identity_not_canonical_source"
        diagnostics = payload["legacy_diagnostics"]
        assert diagnostics["MST_STATE_PPID"] == "424242"
        assert diagnostics["MST_SNAPSHOT_SESSION_ID"] == "pid-legacy-snapshot"
        assert diagnostics["hook_session_id"] == LEGACY_HOOK_SESSION_ID
        assert diagnostics["hook_transcript_stem"] == LEGACY_TRANSCRIPT_SESSION_ID
        combined = _combined(result)
        assert "generated" not in combined
        assert _files(workspace) == before


def test_inherited_structured_id_resolves_with_json_alias_equality() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        result = _run_mst(workspace, "session", "resolve", "--json", env={"MST_SESSION_ID": ROOT_SESSION_ID})

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mst_session_id"] == ROOT_SESSION_ID
        assert payload["session_id"] == ROOT_SESSION_ID
        assert payload["source"] == "env:MST_SESSION_ID"


def main() -> int:
    tests = [
        test_session_resolve_without_root_or_parent_fails_without_uuid_generation,
        test_legacy_runtime_values_are_not_canonical_fallback_sources,
        test_env_payload_mismatch_fails_without_generating_replacement,
        test_missing_parent_mutating_state_write_fails_without_legacy_or_uuid_fallback,
        test_inherited_structured_id_resolves_with_json_alias_equality,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
