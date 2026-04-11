import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
STOP_GATE_REASONS = REPO_ROOT / "hooks" / "stop-agile-gate-reasons.json"


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_stop_hook(workspace: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(STOP_HOOK)],
        cwd=workspace,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )


def _state_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"


def _write_workflow_state(workspace: Path, payload: dict):
    path = _state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_active_session(workspace: Path, agi_id: str = "AGI-012", updated_at: str = "2026-04-12T00:00:00Z") -> Path:
    session_path = workspace / ".gran-maestro" / "agile" / agi_id / "session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                "id": agi_id,
                "agi_id": agi_id,
                "status": "active",
                "updated_at": updated_at,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return session_path


def _write_stop_audit_entries(workspace: Path, agi_id: str, entries: list[dict]) -> Path:
    audit_path = workspace / ".gran-maestro" / "agile" / agi_id / "stop-audit.ndjson"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False))
            f.write("\n")
    return audit_path


def _write_stop_gate_reasons(workspace: Path) -> Path:
    target = workspace / "hooks" / "stop-agile-gate-reasons.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STOP_GATE_REASONS.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _sample_entries() -> list[dict]:
    return [
        {
            "event_id": "SAT-000001",
            "timestamp": "2026-04-12T00:00:00Z",
            "agi_id": "AGI-012",
            "classification": "blocked",
            "declared_reason": None,
        },
        {
            "event_id": "SAT-000002",
            "timestamp": "2026-04-12T00:01:00Z",
            "agi_id": "AGI-012",
            "classification": "blocked",
            "declared_reason": "unrecoverable_external_failure",
        },
        {
            "event_id": "SAT-000003",
            "timestamp": "2026-04-12T00:02:00Z",
            "agi_id": "AGI-012",
            "classification": "allowed",
            "declared_reason": None,
        },
    ]


def test_stop_audit_append_blocked_entry(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-605",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    proc = _run_stop_hook(
        workspace,
        {
            "stop_hook_active": False,
            "last_assistant_message": "continue sprint execution",
        },
    )

    assert proc.returncode == 0
    assert '"decision": "block"' in proc.stdout

    audit_path = workspace / ".gran-maestro" / "agile" / "AGI-012" / "stop-audit.ndjson"
    assert audit_path.exists()

    rows = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    entry = json.loads(rows[0])

    assert entry["event_id"].startswith("SAT-")
    assert entry["classification"] == "blocked"
    assert entry["agi_id"] == "AGI-012"
    assert entry["hook_stage"] == "Stop"
    assert entry["pm_last_turn_snippet"] == "continue sprint execution"
    assert len(entry["pm_last_turn_snippet"]) <= 200
    assert entry["declared_reason"] is None
    assert entry["sentinel_raw"] is None


def test_stop_audit_list_cli(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_audit_entries(workspace, "AGI-012", _sample_entries())

    proc = _run_mst(workspace, "agile", "stop-audit", "list", "--agi", "AGI-012")

    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines[0] == "event_id | timestamp | classification | declared_reason"
    assert len(lines) == 4
    assert lines[1].startswith("SAT-000001 | 2026-04-12T00:00:00Z | blocked | null")
    assert lines[3].startswith("SAT-000003 | 2026-04-12T00:02:00Z | allowed | null")


def test_stop_audit_list_filter_json(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_audit_entries(workspace, "AGI-012", _sample_entries())

    proc = _run_mst(
        workspace,
        "agile",
        "stop-audit",
        "list",
        "--agi",
        "AGI-012",
        "--classification",
        "blocked",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload) == 2
    assert all(item.get("classification") == "blocked" for item in payload)


def test_stop_audit_aggregate_group_by(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_audit_entries(workspace, "AGI-012", _sample_entries())

    proc = _run_mst(
        workspace,
        "agile",
        "stop-audit",
        "aggregate",
        "--agi",
        "AGI-012",
        "--group-by",
        "declared_reason",
    )

    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert "null: 2" in lines
    assert "unrecoverable_external_failure: 1" in lines


def test_stop_audit_write_failure_does_not_break_hook(tmp_path):
    workspace = _make_workspace(tmp_path)
    session_path = _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-605",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    agi_dir = session_path.parent
    os.chmod(agi_dir, 0o555)
    try:
        proc = _run_stop_hook(
            workspace,
            {
                "stop_hook_active": False,
                "last_assistant_message": "continue sprint execution",
            },
        )
    finally:
        os.chmod(agi_dir, 0o755)

    assert proc.returncode == 0
    assert '"decision": "block"' in proc.stdout
    assert "[stop-audit] append failed:" in proc.stderr

    state_payload = json.loads(_state_path(workspace).read_text(encoding="utf-8"))
    assert state_payload["block_count"] == 1
    assert state_payload["last_block_reason"]


def test_sentinel_allowed_enum_passes(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_gate_reasons(workspace)
    _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-609",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    proc = _run_stop_hook(
        workspace,
        {
            "stop_hook_active": False,
            "last_assistant_message": "Should I overwrite production DB? [MST stop_intent reason=fatal_user_judgment_required detail=\"prod DB\"]",
        },
    )

    assert proc.returncode == 0
    assert '"decision": "block"' not in proc.stdout

    audit_path = workspace / ".gran-maestro" / "agile" / "AGI-012" / "stop-audit.ndjson"
    rows = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    entry = json.loads(rows[0])
    assert entry["classification"] == "allowed"
    assert entry["declared_reason"] == "fatal_user_judgment_required"
    assert entry["block_reason"] is None


def test_sentinel_arbitrary_reason_blocks(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_gate_reasons(workspace)
    _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-609",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    proc = _run_stop_hook(
        workspace,
        {
            "stop_hook_active": False,
            "last_assistant_message": "[MST stop_intent reason=context_too_large detail=\"ctx\"]",
        },
    )

    assert proc.returncode == 0
    assert '"decision": "block"' in proc.stdout

    audit_path = workspace / ".gran-maestro" / "agile" / "AGI-012" / "stop-audit.ndjson"
    entry = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["classification"] == "blocked"
    assert entry["declared_reason"] == "context_too_large"
    assert entry["block_reason"] == "arbitrary_stop"


def test_sentinel_fatal_without_question_blocks(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_gate_reasons(workspace)
    _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-609",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    proc = _run_stop_hook(
        workspace,
        {
            "stop_hook_active": False,
            "last_assistant_message": "[MST stop_intent reason=fatal_user_judgment_required detail=\"need\"]",
        },
    )

    assert proc.returncode == 0
    assert '"decision": "block"' in proc.stdout

    audit_path = workspace / ".gran-maestro" / "agile" / "AGI-012" / "stop-audit.ndjson"
    entry = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["classification"] == "blocked"
    assert entry["declared_reason"] == "fatal_user_judgment_required"
    assert entry["block_reason"] == "ambiguous_user_question"


def test_sentinel_unrecoverable_without_retry_blocks(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_stop_gate_reasons(workspace)
    _write_active_session(workspace, "AGI-012")
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-609",
            "iteration": 1,
            "updated_at": "2026-04-12T00:00:00Z",
        },
    )

    proc = _run_stop_hook(
        workspace,
        {
            "stop_hook_active": False,
            "last_assistant_message": "[MST stop_intent reason=unrecoverable_external_failure detail=\"api 403\"]",
        },
    )

    assert proc.returncode == 0
    assert '"decision": "block"' in proc.stdout

    audit_path = workspace / ".gran-maestro" / "agile" / "AGI-012" / "stop-audit.ndjson"
    entry = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["classification"] == "blocked"
    assert entry["declared_reason"] == "unrecoverable_external_failure"
    assert entry["block_reason"] == "insufficient_recovery_attempt"
