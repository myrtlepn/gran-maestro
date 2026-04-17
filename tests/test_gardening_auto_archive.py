import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _iso_days_ago(days: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _init_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    (gm / "requests").mkdir(parents=True, exist_ok=True)
    (gm / "plans").mkdir(parents=True, exist_ok=True)
    return workspace, gm


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _configure_enabled(gm: Path, *, dry_run: bool = True) -> None:
    _write_json(
        gm / "config.json",
        {
            "gardening": {
                "auto_archive": {
                    "enabled": True,
                    "dry_run": dry_run,
                    "thresholds": {
                        "req_stale_days": 14,
                        "plan_stale_days": 30,
                        "plan_active_stale_days": 14,
                    },
                }
            }
        },
    )


def _read_request(gm: Path, req_id: str) -> dict:
    return json.loads((gm / "requests" / req_id / "request.json").read_text(encoding="utf-8"))


def _read_plan(gm: Path, plan_id: str) -> dict:
    return json.loads((gm / "plans" / plan_id / "plan.json").read_text(encoding="utf-8"))


def _read_log(gm: Path) -> list[dict]:
    log_path = gm / "gardening" / "auto-archive.ndjson"
    if not log_path.exists():
        return []
    rows = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_dry_run_no_change(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    req_id = "REQ-100"
    _write_json(
        gm / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "title": "stale req",
            "status": "phase1_analysis",
            "updated_at": _iso_days_ago(16),
        },
    )

    proc = _run_mst(workspace, "gardening", "auto-archive", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert req_id in proc.stdout

    req_after = _read_request(gm, req_id)
    assert req_after["status"] == "phase1_analysis"

    rows = _read_log(gm)
    assert any(row["action"] == "dry_run_candidate" and row["id"] == req_id for row in rows)


def test_apply_cancels(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    req_id = "REQ-101"
    _write_json(
        gm / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "title": "stale req",
            "status": "phase1_analysis",
            "updated_at": _iso_days_ago(20),
        },
    )

    proc = _run_mst(workspace, "gardening", "auto-archive", "--apply")

    assert proc.returncode == 0, proc.stderr

    req_after = _read_request(gm, req_id)
    assert req_after["status"] == "cancelled"
    assert "cancelled_at" in req_after
    assert req_after["cancelled_reason"].startswith("auto-gardening: stale")

    rows = _read_log(gm)
    assert any(
        row["action"] == "cancel"
        and row["id"] == req_id
        and row["prev_status"] == "phase1_analysis"
        and row["new_status"] == "cancelled"
        for row in rows
    )


def test_restore_roundtrip(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    req_id = "REQ-102"
    _write_json(
        gm / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "title": "stale req",
            "status": "spec_ready",
            "updated_at": _iso_days_ago(18),
        },
    )

    cancel_proc = _run_mst(workspace, "gardening", "auto-archive", "--apply")
    assert cancel_proc.returncode == 0, cancel_proc.stderr

    restore_proc = _run_mst(workspace, "gardening", "restore", "--id", req_id)
    assert restore_proc.returncode == 0, restore_proc.stderr

    req_after = _read_request(gm, req_id)
    assert req_after["status"] == "spec_ready"
    assert "restored_at" in req_after

    rows = _read_log(gm)
    assert rows[-1]["action"] == "restore"
    assert rows[-1]["id"] == req_id


def test_exempt_skipped(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    req_id = "REQ-103"
    _write_json(
        gm / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "title": "protected req",
            "status": "phase1_analysis",
            "gardening_exempt": True,
            "updated_at": _iso_days_ago(30),
        },
    )

    proc = _run_mst(workspace, "gardening", "auto-archive", "--apply")

    assert proc.returncode == 0, proc.stderr
    req_after = _read_request(gm, req_id)
    assert req_after["status"] == "phase1_analysis"

    rows = _read_log(gm)
    assert any(
        row["action"] == "skipped"
        and row["id"] == req_id
        and "gardening_exempt" in str(row.get("reason", ""))
        for row in rows
    )
    assert not any(row["action"] == "cancel" and row["id"] == req_id for row in rows)


def test_plan_cascade(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    req_done = "REQ-201"
    req_cancelled = "REQ-202"
    _write_json(
        gm / "requests" / req_done / "request.json",
        {
            "id": req_done,
            "title": "done req",
            "status": "completed",
            "updated_at": _iso_days_ago(1),
        },
    )
    _write_json(
        gm / "requests" / req_cancelled / "request.json",
        {
            "id": req_cancelled,
            "title": "cancelled req",
            "status": "cancelled",
            "updated_at": _iso_days_ago(1),
        },
    )

    plan_id = "PLN-200"
    _write_json(
        gm / "plans" / plan_id / "plan.json",
        {
            "id": plan_id,
            "title": "linked plan",
            "status": "active",
            "linked_requests": [req_done, req_cancelled],
            "updated_at": _iso_days_ago(1),
        },
    )

    proc = _run_mst(workspace, "gardening", "auto-archive", "--apply")

    assert proc.returncode == 0, proc.stderr

    plan_after = _read_plan(gm, plan_id)
    assert plan_after["status"] == "completed"
    assert "completed_at" in plan_after

    rows = _read_log(gm)
    assert any(
        row["action"] == "plan_cascade"
        and row["id"] == plan_id
        and row["new_status"] == "completed"
        for row in rows
    )


def test_scan_unchanged(tmp_path):
    workspace, gm = _init_workspace(tmp_path)
    _configure_enabled(gm, dry_run=True)

    proc = _run_mst(workspace, "gardening", "scan")

    assert proc.returncode == 0, proc.stderr
    assert "Gran Maestro -- Gardening Report" in proc.stdout
    assert "[Plans]" in proc.stdout
    assert "[Requests]" in proc.stdout
    assert "[Intents]" in proc.stdout
