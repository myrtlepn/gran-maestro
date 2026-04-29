from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_state_validate(workspace: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "state", "validate", "--json", *extra_args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_legacy_normalize(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    _write_json(
        base_dir / "requests" / "REQ-001" / "request.json",
        {"id": "REQ-001", "status": "completed"},
    )
    _write_json(
        base_dir / "requests" / "REQ-002" / "request.json",
        {"id": "REQ-002", "status": "done"},
    )

    result = _run_state_validate(tmp_path)
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["summary"]["normalized_count"] >= 1
    assert payload["summary"]["invalid_count"] == 0


def test_invalid_exit_1(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    _write_json(
        base_dir / "requests" / "REQ-010" / "request.json",
        {"id": "REQ-010", "status": "xyz_invalid_value"},
    )

    result = _run_state_validate(tmp_path)
    assert result.returncode == 1

    payload = json.loads(result.stdout)
    assert payload["summary"]["invalid_count"] >= 1
    assert any(item["status"] == "xyz_invalid_value" for item in payload["invalid"])


def test_auto_fix(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    request_path = base_dir / "requests" / "REQ-020" / "request.json"
    _write_json(request_path, {"id": "REQ-020", "status": "completed"})

    result = _run_state_validate(tmp_path, "--auto-fix")
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["summary"]["invalid_count"] == 0
    assert payload["summary"]["normalized_count"] >= 1
    assert len(payload["backups_created"]) == 1

    backup_path = Path(payload["backups_created"][0])
    assert backup_path.exists()

    backup_payload = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backup_payload["status"] == "completed"

    normalized_payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert normalized_payload["status"] == "done"


def test_auto_fix_noop(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    _write_json(
        base_dir / "requests" / "REQ-030" / "request.json",
        {"id": "REQ-030", "status": "done"},
    )

    result = _run_state_validate(tmp_path, "--auto-fix")
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["summary"]["normalized_count"] == 0
    assert payload["summary"]["invalid_count"] == 0
    assert payload["backups_created"] == []
