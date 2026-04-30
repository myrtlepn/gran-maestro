"""Tests for AD-004: gardening scan must not flag in-progress requests as stale."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


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


def _write_request(gm: Path, req_id: str, *, status: str, age_days: int) -> None:
    payload = {
        "id": req_id,
        "title": f"{status} req",
        "status": status,
        "created_at": _iso_days_ago(age_days),
    }
    path = gm / "requests" / req_id / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_scan_json(workspace: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(MST_SCRIPT), "gardening", "scan", "--json"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    # stdout may include leading non-JSON lines; find the JSON block.
    text = proc.stdout.strip()
    # Try parsing the whole stdout first; fall back to last JSON object.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Find first '{' and last '}'
        first = text.find("{")
        last = text.rfind("}")
        assert first != -1 and last != -1, f"no JSON in stdout: {text!r}"
        return json.loads(text[first:last + 1])


@pytest.mark.parametrize(
    "active_status",
    [
        "executing",
        "phase1_analysis",
        "phase2_execution",
        "reviewing",
        "phase3_review",
        "merge_conflict",
        "merging",
    ],
)
def test_active_phase_request_not_flagged_as_stale(tmp_path: Path, active_status: str) -> None:
    """Requests in any ACTIVE_PHASE_STATUSES must not appear in stale_requests
    even when they are older than the stale-days threshold.
    """
    workspace, gm = _init_workspace(tmp_path)
    req_id = "REQ-900"
    _write_request(gm, req_id, status=active_status, age_days=200)

    result = _run_scan_json(workspace)

    stale_ids = {row["id"] for row in result.get("stale_requests", [])}
    assert req_id not in stale_ids, (
        f"In-progress status '{active_status}' must not be stale candidate "
        f"(stale_requests={stale_ids}, summary={result.get('summary')})"
    )

    summary = result.get("summary", {})
    assert summary.get("protected_active_requests", 0) >= 1, (
        f"protected_active_requests should count the active req (got summary={summary})"
    )


def test_terminal_status_request_excluded(tmp_path: Path) -> None:
    """Terminal status (done) requests must remain excluded from stale_requests."""
    workspace, gm = _init_workspace(tmp_path)
    _write_request(gm, "REQ-901", status="done", age_days=200)

    result = _run_scan_json(workspace)

    stale_ids = {row["id"] for row in result.get("stale_requests", [])}
    assert "REQ-901" not in stale_ids


def test_unknown_status_old_request_is_stale(tmp_path: Path) -> None:
    """A request with an unknown status (neither inactive nor active phase)
    that is older than the stale threshold must remain a stale candidate so
    cleanup can surface it.
    """
    workspace, gm = _init_workspace(tmp_path)
    _write_request(gm, "REQ-902", status="idle", age_days=200)

    result = _run_scan_json(workspace)

    stale_ids = {row["id"] for row in result.get("stale_requests", [])}
    assert "REQ-902" in stale_ids, (
        f"unknown 'idle' status must remain a stale candidate (stale_ids={stale_ids})"
    )
