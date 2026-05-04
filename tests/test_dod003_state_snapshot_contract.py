from __future__ import annotations

import hashlib
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
LEGACY_PPID = "313131"


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
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _canonical_env() -> dict[str, str]:
    return {
        "MST_SESSION_ID": ROOT_SESSION_ID,
        "MST_STATE_PPID": LEGACY_PPID,
        "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
    }


def test_snapshot_write_enforces_canonical_path_and_payload_boundary() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "2",
            "--total",
            "5",
            env=_canonical_env(),
        )

        assert result.returncode == 0, result.stderr
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        assert snapshot_path.relative_to(workspace / ".gran-maestro") == Path("state") / ROOT_SESSION_ID / "snapshot.json"
        assert list((workspace / ".gran-maestro" / "state").iterdir()) == [workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID]
        payload = _read_json(snapshot_path)
        assert payload["schema_version"] == 1
        assert payload["mst_session_id"] == ROOT_SESSION_ID
        assert payload["root_mst_id"] == "AGI-030"
        assert payload["sessionId"] == ROOT_SESSION_ID
        assert payload["workflow"] == {
            "current_skill": "mst:request",
            "current_step": 2,
            "total_steps": 5,
            "status": "active",
        }
        assert payload["continuation"]["stack_depth"] == 0
        assert payload["legacy_diagnostics"]["MST_STATE_PPID"] == LEGACY_PPID
        assert payload["legacy_diagnostics"]["MST_SNAPSHOT_SESSION_ID"] == "legacy-snapshot-alias"
        assert "session_id" not in payload
        assert "owner_ppid" not in payload
        assert "owner_session_id" not in payload
        assert not (workspace / ".gran-maestro" / "state" / LEGACY_PPID).exists()
        assert not (workspace / ".gran-maestro" / "state" / "default").exists()


def test_alias_only_existing_snapshot_is_not_repaired_or_mutated() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        _write_json(
            snapshot_path,
            {
                "sessionId": ROOT_SESSION_ID,
                "currentSkill": "legacy:alias",
                "currentStep": 1,
                "totalSteps": 1,
                "status": "active",
            },
        )
        before = _hashes(workspace)

        result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=_canonical_env(),
        )

        assert result.returncode != 0
        assert "missing mst_session_id" in f"{result.stdout}\n{result.stderr}"
        assert _hashes(workspace) == before


def test_root_mismatch_existing_snapshot_is_no_mutation_fail_closed() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        _write_json(
            snapshot_path,
            {
                "schema_version": 1,
                "mst_session_id": ROOT_SESSION_ID,
                "root_mst_id": "REQ-805",
                "currentSkill": "legacy:mismatch",
                "currentStep": 1,
                "totalSteps": 1,
                "status": "active",
            },
        )
        before = _hashes(workspace)

        result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=_canonical_env(),
        )

        assert result.returncode != 0
        assert "root_mst_id mismatch" in f"{result.stdout}\n{result.stderr}"
        assert _hashes(workspace) == before


def test_state_get_does_not_select_default_or_alias_snapshot() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "state" / "default" / "snapshot.json",
            {"sessionId": "default", "currentSkill": "legacy:default", "currentStep": 1, "totalSteps": 1},
        )
        _write_json(
            workspace / ".gran-maestro" / "state" / STALE_SESSION_ID / "snapshot.json",
            {
                "schema_version": 1,
                "mst_session_id": STALE_SESSION_ID,
                "root_mst_id": "REQ-805",
                "currentSkill": "legacy:stale",
                "currentStep": 1,
                "totalSteps": 1,
            },
        )
        before = _hashes(workspace)

        result = _run_mst(workspace, "state", "get", env=_canonical_env())

        assert result.returncode == 0, result.stderr
        assert "스냅샷 없음" in result.stdout
        assert "legacy:default" not in result.stdout
        assert "legacy:stale" not in result.stdout
        assert _hashes(workspace) == before


def main() -> int:
    tests = [
        test_snapshot_write_enforces_canonical_path_and_payload_boundary,
        test_alias_only_existing_snapshot_is_not_repaired_or_mutated,
        test_root_mismatch_existing_snapshot_is_no_mutation_fail_closed,
        test_state_get_does_not_select_default_or_alias_snapshot,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
