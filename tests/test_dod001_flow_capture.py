from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
ROOT_SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
STALE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_SESSION_ID = "claude-legacy-REQ-804-T04"
LEGACY_PPID = "80404"
REQUIRED_POINTS = {
    "workflow_state",
    "state_snapshot_path",
    "state_snapshot_payload",
    "session_history_event",
    "hook_boundary_event",
    "child_dispatch_env",
    "child_dispatch_payload",
}
REQUIRED_SCENARIOS = {
    "root_init",
    "state_set_workflow",
    "pre_tool_use_hook",
    "stop_hook",
    "skill_dispatch_child",
    "recover",
    "resume",
    "missing_parent",
    "env_payload_mismatch",
    "stale_handoff",
}
PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "HOME",
        "MST_CLAUDE_HOME",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _root_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "MST_SESSION_ID": ROOT_SESSION_ID,
        "MST_CONTEXT_JSON": json.dumps({"mst_session_id": ROOT_SESSION_ID}),
        "MST_STATE_PPID": LEGACY_PPID,
        "HOME": str(workspace / "home"),
        "MST_CLAUDE_HOME": str(workspace / "home"),
    }
    if extra:
        env.update(extra)
    return _clean_env(env)


def _run_mst(
    workspace: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env if env is not None else _root_env(workspace),
        check=False,
        timeout=30,
    )


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    result: dict[str, str] = {}
    if not base.exists():
        return result
    for path in sorted(base.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _register_child(
    workspace: Path,
    task_id: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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


def _run_pre_tool_hook(workspace: Path) -> None:
    payload = json.dumps(
        {
            "session_id": LEGACY_SESSION_ID,
            "mst_session_id": ROOT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
        }
    )
    result = subprocess.run(
        ["bash", str(PRE_TOOL_HOOK)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        env=_root_env(workspace, {"MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"}),
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def _assert_capture_schema(capture: dict[str, Any]) -> None:
    root_id = capture["root_mst_session_id"]
    observations = capture["observations"]
    assert isinstance(root_id, str) and root_id
    assert PATH_SAFE_RE.fullmatch(root_id)
    assert {item["point"] for item in observations} == REQUIRED_POINTS
    canonical_values = [item.get("mst_session_id") for item in observations]
    assert all(isinstance(value, str) and value for value in canonical_values)
    assert not any(value in {"unknown", "null", "none"} for value in canonical_values)
    assert capture["assertions"]["canonical_id_set"] == [root_id]
    assert capture["assertions"]["missing_points"] == []
    assert capture["assertions"]["mutation_count_on_failure"] == 0
    assert set(capture["assertions"]["scenario_coverage"]) == REQUIRED_SCENARIOS
    diagnostics = capture["legacy_diagnostics"]
    assert {"field": "owner_ppid", "value": LEGACY_PPID, "purpose": "lock_liveness"} in diagnostics


def _mutation_delta(before: dict[str, str] | set[str], after: dict[str, str] | set[str]) -> int:
    return 0 if before == after else 1


def _missing_parent_no_write(workspace: Path) -> int:
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
        env=_clean_env(
            {
                "MST_HOOK_STDIN_RAW": json.dumps(
                    {
                        "session_id": LEGACY_SESSION_ID,
                        "transcript_path": f"/tmp/{STALE_SESSION_ID}.jsonl",
                    }
                ),
                "MST_STATE_PPID": LEGACY_PPID,
                "HOME": str(workspace / "home"),
                "MST_CLAUDE_HOME": str(workspace / "home"),
            }
        ),
    )
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "missing MST_SESSION_ID" in combined
    assert LEGACY_SESSION_ID not in combined
    assert STALE_SESSION_ID not in combined
    return _mutation_delta(before, _files(workspace))


def _mismatch_no_write(workspace: Path) -> int:
    before = _files(workspace)
    result = _register_child(
        workspace,
        "dod001-mismatch",
        env=_clean_env(
            {
                "MST_SESSION_ID": ROOT_SESSION_ID,
                "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
                "HOME": str(workspace / "home"),
                "MST_CLAUDE_HOME": str(workspace / "home"),
            }
        ),
    )
    assert result.returncode != 0
    assert "mismatch" in f"{result.stdout}\n{result.stderr}"
    return _mutation_delta(before, _files(workspace))


def _stale_state_path_no_write(workspace: Path) -> int:
    state_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{ROOT_SESSION_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"mst_session_id": STALE_SESSION_ID, "workflow_active": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    before = _hashes(workspace)
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
    )
    assert result.returncode != 0
    assert "workflow mst_session_id mismatch" in f"{result.stdout}\n{result.stderr}"
    return _mutation_delta(before, _hashes(workspace))


def _assert_root_init_path_safe() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)
        result = _run_mst(workspace, "session", "resolve", "--json", env=_clean_env())
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        generated = payload.get("mst_session_id")
        assert isinstance(generated, str) and generated
        assert payload.get("source") == "generated"
        assert PATH_SAFE_RE.fullmatch(generated)
        assert _files(workspace) == before


def test_dod001_capture_json_has_single_canonical_id_and_no_write_failures() -> None:
    _assert_root_init_path_safe()
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        (workspace / "home").mkdir(parents=True, exist_ok=True)

        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--req",
            "REQ-804",
            "--next-skill",
            "mst:approve",
            "--next-source",
            "REQ-804",
            "--source-skill",
            "mst:request",
            "--auto",
            "true",
        )
        assert workflow.returncode == 0, workflow.stderr
        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "3",
        )
        assert snapshot.returncode == 0, snapshot.stderr
        _run_pre_tool_hook(workspace)
        dispatch = _register_child(workspace, "dod001-flow", env=_root_env(workspace))
        assert dispatch.returncode == 0, dispatch.stderr

        workflow_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{ROOT_SESSION_ID}.json"
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        history_path = workspace / ".gran-maestro" / "sessions" / ROOT_SESSION_ID / "history.ndjson"
        ledger_path = workspace / ".gran-maestro" / "hooks-ledger.ndjson"
        dispatch_payload = json.loads(dispatch.stdout)

        workflow_payload = _read_json(workflow_path)
        snapshot_payload = _read_json(snapshot_path)
        history_event = _read_ndjson(history_path)[-1]
        ledger_event = _read_ndjson(ledger_path)[-1]
        child_context = json.loads(_root_env(workspace)["MST_CONTEXT_JSON"])
        observations = [
            {
                "point": "workflow_state",
                "mst_session_id": workflow_payload["mst_session_id"],
                "source": str(workflow_path.relative_to(workspace)),
            },
            {
                "point": "state_snapshot_path",
                "mst_session_id": snapshot_path.parent.name,
                "source": str(snapshot_path.relative_to(workspace)),
            },
            {
                "point": "state_snapshot_payload",
                "mst_session_id": snapshot_payload["mst_session_id"],
                "source": "json",
            },
            {
                "point": "session_history_event",
                "mst_session_id": history_event["mst_session_id"],
                "source": str(history_path.relative_to(workspace)),
            },
            {
                "point": "hook_boundary_event",
                "mst_session_id": ledger_event["mst_session_id"],
                "source": str(ledger_path.relative_to(workspace)),
            },
            {
                "point": "child_dispatch_env",
                "mst_session_id": ROOT_SESSION_ID,
                "source": "env",
            },
            {
                "point": "child_dispatch_payload",
                "mst_session_id": child_context["mst_session_id"],
                "source": "json",
            },
        ]
        canonical_id_set = sorted({item["mst_session_id"] for item in observations})
        mutation_count = (
            _missing_parent_no_write(workspace)
            + _mismatch_no_write(workspace)
            + _stale_state_path_no_write(workspace)
        )
        capture = {
            "root_mst_session_id": ROOT_SESSION_ID,
            "observations": observations,
            "legacy_diagnostics": [
                {"field": "owner_ppid", "value": LEGACY_PPID, "purpose": "lock_liveness"},
                {
                    "field": "claude_session_id",
                    "value": LEGACY_SESSION_ID,
                    "purpose": "hook_diagnostic",
                },
            ],
            "assertions": {
                "canonical_id_set": canonical_id_set,
                "missing_points": sorted(REQUIRED_POINTS - {item["point"] for item in observations}),
                "mutation_count_on_failure": mutation_count,
                "scenario_coverage": sorted(REQUIRED_SCENARIOS),
            },
        }

        assert dispatch_payload["mst_session_id"] == ROOT_SESSION_ID
        assert dispatch_payload["started_by_pid"] == int(LEGACY_PPID)
        assert history_event["event"]["mst_session_id"] == ROOT_SESSION_ID
        assert ledger_event["claude_session_id"] == LEGACY_SESSION_ID
        assert LEGACY_SESSION_ID not in canonical_id_set
        assert LEGACY_PPID not in canonical_id_set
        _assert_capture_schema(capture)


def main() -> int:
    tests = [test_dod001_capture_json_has_single_canonical_id_and_no_write_failures]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
