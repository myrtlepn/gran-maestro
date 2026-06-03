from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts.mst_cmds import _common
from scripts.mst_cmds import agile as agile_cmds
from scripts.mst_cmds import session as session_mod


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MST_SESSION_RE = re.compile(r"^MST-AGI-\d{3}-\d{8}T\d{9}Z-[a-z0-9]{8,}$")


def _clean_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(workspace / ".gran-maestro" / "policy")
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
        env=_clean_env(workspace, env),
        check=False,
        timeout=30,
    )


def test_agile_init_persists_canonical_mst_session_metadata(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_mst(tmp_path, "agile", "init", "--steering-every", "3", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    agi_id = payload["agi_id"]
    mst_session_id = payload["mst_session_id"]
    assert agi_id == "AGI-001"
    assert MST_SESSION_RE.fullmatch(mst_session_id)
    assert payload["root_mst_id"] == agi_id

    root_session_path = tmp_path / ".gran-maestro" / "agile" / agi_id / "session.json"
    session_metadata_path = tmp_path / ".gran-maestro" / "sessions" / mst_session_id / "session.json"
    history_path = tmp_path / ".gran-maestro" / "sessions" / mst_session_id / "history.ndjson"
    head_path = tmp_path / ".gran-maestro" / "sessions" / mst_session_id / "history.head"
    verify_path = tmp_path / ".gran-maestro" / "sessions" / mst_session_id / "history.verify"

    root_payload = json.loads(root_session_path.read_text(encoding="utf-8"))
    session_payload = json.loads(session_metadata_path.read_text(encoding="utf-8"))
    assert root_payload["mst_session_id"] == mst_session_id
    assert session_payload["mst_session_id"] == mst_session_id
    assert session_payload["root_artifact_path"] == f"agile/{agi_id}/session.json"
    assert history_path.is_file()
    assert head_path.is_file()
    assert verify_path.is_file()


def test_agile_init_mst_session_id_drives_state_snapshot(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    init = _run_mst(tmp_path, "agile", "init", "--steering-every", "3", "--json")
    assert init.returncode == 0, init.stderr
    init_payload = json.loads(init.stdout)
    mst_session_id = init_payload["mst_session_id"]
    agi_id = init_payload["agi_id"]

    state = _run_mst(
        tmp_path,
        "state",
        "set",
        "--skill",
        "agile-plan",
        "--step",
        "3",
        "--total",
        "3",
        env={
            "MST_SESSION_ID": mst_session_id,
            "MST_CONTEXT_JSON": json.dumps(
                {
                    "schema_version": 1,
                    "mst_session_id": mst_session_id,
                    "root_mst_id": agi_id,
                },
                separators=(",", ":"),
            ),
        },
    )

    assert state.returncode == 0, state.stderr
    snapshot_path = tmp_path / ".gran-maestro" / "state" / mst_session_id / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["mst_session_id"] == mst_session_id
    assert snapshot["root_mst_id"] == agi_id
    assert snapshot["workflow"]["current_skill"] == "agile-plan"


def test_agile_init_session_flow_reports_incomplete_ledger(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    init = _run_mst(tmp_path, "agile", "init", "--steering-every", "3", "--json")
    assert init.returncode == 0, init.stderr
    init_payload = json.loads(init.stdout)
    mst_session_id = init_payload["mst_session_id"]

    flow = _run_mst(tmp_path, "session", "flow", mst_session_id, "--json")

    assert flow.returncode == 2
    assert "projection not found" not in flow.stderr
    payload = json.loads(flow.stdout)
    assert payload["mst_session_id"] == mst_session_id
    assert payload["projection_exists"] is False
    codes = {
        str(item.get("code") or item.get("field") or "")
        for item in payload.get("diagnostics", [])
        if isinstance(item, dict)
    }
    assert "missing_event_family" in codes


def test_agile_init_fails_when_final_session_verification_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir()
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    monkeypatch.setenv("MST_POLICY_HOME", str(base_dir / "policy"))

    def fail_verify(_agi_id: str, _mst_session_id: str) -> dict:
        raise ValueError("forced missing root session")

    monkeypatch.setattr(agile_cmds, "_verify_agile_init_session", fail_verify)

    exit_code = agile_cmds.cmd_agile_init(SimpleNamespace(steering_every=3, json=True))
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "agile init session verification failed for AGI-001" in captured.err
    assert not (base_dir / "agile" / "AGI-001" / "session.json").exists()
    assert not any((base_dir / "sessions").glob("MST-AGI-001-*"))


def test_session_flow_lazily_generates_projection_from_verified_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    policy_home = tmp_path / ".gran-maestro" / "policy"
    monkeypatch.setenv("MST_POLICY_HOME", str(policy_home))
    init = _run_mst(tmp_path, "agile", "init", "--steering-every", "3", "--json")
    assert init.returncode == 0, init.stderr
    init_payload = json.loads(init.stdout)
    mst_session_id = init_payload["mst_session_id"]
    agi_id = init_payload["agi_id"]

    base_dir = tmp_path / ".gran-maestro"
    event_types = [
        ("skill.enter", {"skill": "mst:agile-plan", "step": 0}),
        ("skill.step", {"skill": "mst:agile-plan", "step": 1}),
        ("action.queued", {"next_action": {"skill": "mst:agile", "source_id": agi_id}}),
        ("continue.queued_action", {"transition": "continue.queued_action"}),
        ("context.compacted", {"current_node": "mst:agile-plan.step-1"}),
        ("skill.recover", {"skill": "mst:recover", "step": 1}),
        ("context.rehydrated", {"rehydration_transition": "continue.rehydrate_retry"}),
        ("guard.inspect_only_verification", {"transition": "guard.inspect_only_verification"}),
        ("blocker.detected", {"blocker": {"type": "state_inconsistency", "critical": False}}),
        ("blocker.resolved", {"blocker": {"type": "state_inconsistency"}}),
        ("action.completed", {"action_id": "agile-plan-complete"}),
        ("skill.exit", {"skill": "mst:agile-plan", "step": 3, "status": "done"}),
        ("terminal.completed", {"transition": "terminal.completed"}),
    ]
    for index, (event_type, extra) in enumerate(event_types, 1):
        session_mod.write_session_history_event(
            base_dir,
            mst_session_id,
            {
                "event_type": event_type,
                "artifact_id": agi_id,
                "resource_id": agi_id,
                "idempotency_key": f"{mst_session_id}:flow-test:{index}:{event_type}",
                "created_at": f"2026-06-01T10:00:{index:02d}.000Z",
                **extra,
            },
        )

    flow = _run_mst(tmp_path, "session", "flow", mst_session_id, "--json")

    assert flow.returncode == 0, flow.stderr
    payload = json.loads(flow.stdout)
    assert payload["status"] == "ok"
    assert payload["view_kind"] == "dod017.execution-flow.cli-view"
    assert payload["mst_session_id"] == mst_session_id
    assert (base_dir / "sessions" / mst_session_id / "execution-flow.json").is_file()
    assert (base_dir / "sessions" / mst_session_id / "execution-flow.d2").is_file()
