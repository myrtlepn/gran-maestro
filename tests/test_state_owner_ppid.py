"""AC-004/AC-005: state set-workflow owner_ppid injection tests."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_set_workflow(workspace: Path, ppid: int, *extra_args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MST_STATE_PPID": str(ppid)}
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "state", "set-workflow", *extra_args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _setup_workspace(tmp_path: Path, req_id: str, initial_data: dict) -> tuple[Path, Path]:
    base = tmp_path / ".gran-maestro"
    req_dir = base / "requests" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    req_json = req_dir / "request.json"
    req_json.write_text(json.dumps(initial_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tmp_path, req_json


def test_owner_ppid_injected_on_active_true(tmp_path):
    """AC-004: set-workflow --active true injects owner_ppid into request.json."""
    req_id = "REQ-001"
    workspace, req_json = _setup_workspace(
        tmp_path, req_id, {"id": req_id, "status": "phase1_analysis"}
    )
    fake_ppid = 54321

    result = _run_set_workflow(
        workspace,
        fake_ppid,
        "--active", "true",
        "--skill", "mst:request",
        "--req", req_id,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(req_json.read_text(encoding="utf-8"))
    assert "owner_ppid" in data, f"owner_ppid not injected; got: {data}"
    assert data["owner_ppid"] == fake_ppid, f"expected {fake_ppid}, got {data['owner_ppid']}"


def test_owner_ppid_not_injected_on_active_false(tmp_path):
    """AC-004 boundary: set-workflow --active false should NOT inject owner_ppid."""
    req_id = "REQ-002"
    workspace, req_json = _setup_workspace(
        tmp_path, req_id, {"id": req_id, "status": "phase1_analysis"}
    )
    fake_ppid = 54321

    result = _run_set_workflow(
        workspace,
        fake_ppid,
        "--active", "false",
        "--req", req_id,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(req_json.read_text(encoding="utf-8"))
    assert "owner_ppid" not in data, f"owner_ppid should not be set on active=false; got: {data}"


def test_owner_ppid_idempotent(tmp_path):
    """AC-005: existing owner_ppid is not overwritten by re-call."""
    req_id = "REQ-003"
    original_ppid = 1111
    workspace, req_json = _setup_workspace(
        tmp_path, req_id, {"id": req_id, "status": "phase1_analysis", "owner_ppid": original_ppid}
    )
    new_ppid = 99999

    result = _run_set_workflow(
        workspace,
        new_ppid,
        "--active", "true",
        "--skill", "mst:request",
        "--req", req_id,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(req_json.read_text(encoding="utf-8"))
    assert data["owner_ppid"] == original_ppid, (
        f"owner_ppid should remain {original_ppid} (idempotent), got {data['owner_ppid']}"
    )


def test_owner_ppid_plan_injected(tmp_path):
    """AC-004 (plan variant): set-workflow --active true injects owner_ppid into plan.json."""
    pln_id = "PLN-001"
    base = tmp_path / ".gran-maestro"
    pln_dir = base / "plans" / pln_id
    pln_dir.mkdir(parents=True, exist_ok=True)
    pln_json = pln_dir / "plan.json"
    pln_json.write_text(
        json.dumps({"id": pln_id, "status": "active"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fake_ppid = 54321

    result = _run_set_workflow(
        tmp_path,
        fake_ppid,
        "--active", "true",
        "--skill", "mst:plan",
        "--next-source", pln_id,
        "--source-skill", "mst:plan",
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(pln_json.read_text(encoding="utf-8"))
    assert "owner_ppid" in data, f"owner_ppid not injected into plan.json; got: {data}"
    assert data["owner_ppid"] == fake_ppid


def test_read_owner_ppid_rejects_bool(tmp_path):
    """read_owner_ppid_field exits 1 for JSON bool owner_ppid (true or false)."""
    hook_py = textwrap.dedent("""\
        import json, sys
        path = sys.argv[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            raise SystemExit(1)
        if not isinstance(payload, dict):
            raise SystemExit(1)
        owner_ppid = payload.get("owner_ppid")
        if owner_ppid is None:
            raise SystemExit(2)
        if isinstance(owner_ppid, bool):
            raise SystemExit(1)
        try:
            print(int(owner_ppid))
        except (TypeError, ValueError):
            raise SystemExit(1)
    """)
    for bool_str in ("true", "false"):
        json_file = tmp_path / f"request_{bool_str}.json"
        json_file.write_text(
            f'{{"status": "phase1_analysis", "owner_ppid": {bool_str}}}',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-c", hook_py, str(json_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, (
            f"expected exit 1 for bool owner_ppid={bool_str}, got {result.returncode}"
        )
