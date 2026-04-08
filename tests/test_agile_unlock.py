import json
import re
import subprocess
import sys
from typing import List, Optional
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


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


def _write_file(path: Path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write_unlock_config(workspace: Path, *, enabled: bool):
    _write_file(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps({"agile": {"unlock": {"enabled": enabled}}}, ensure_ascii=False),
    )


def _details_dir(workspace: Path, agi_id: str) -> Path:
    return workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "details"


def _write_detail(
    workspace: Path,
    agi_id: str,
    dod_id: str,
    *,
    status: str = "done",
    blocked_by: Optional[List[str]] = None,
):
    blocked_by = blocked_by or []
    lines = [
        "---",
        f"status: {status}",
    ]
    if blocked_by:
        lines.append("blocked_by:")
        for dep in blocked_by:
            lines.append(f"  - {dep}")
    lines.extend(
        [
            "evidence:",
            "  plan:",
            "    artifact_paths:",
            "      - src/app.py",
            "    entrypoint_path: src/app.py:main",
            "  runtime:",
            "    integration_smoke_id: smoke-001",
            "    verify_cmd: \"python -m pytest tests/test_smoke.py -q\"",
            "    expected_signal: \"1 passed\"",
            "---",
            f"# {dod_id}",
            "",
        ]
    )
    _write_file(_details_dir(workspace, agi_id) / f"{dod_id}.md", "\n".join(lines))


def _read_detail(workspace: Path, agi_id: str, dod_id: str) -> str:
    return (_details_dir(workspace, agi_id) / f"{dod_id}.md").read_text(encoding="utf-8")


def _combined_output(proc: subprocess.CompletedProcess) -> str:
    return f"{proc.stdout}\n{proc.stderr}"


def test_valid_unlock(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "upstream_evidence_changed",
        "--reason",
        "upstream DOD-005 evidence fingerprint changed from abc to def",
        "--evidence",
        "DOD-005,fingerprint_diff.log",
    )

    assert proc.returncode == 0, _combined_output(proc)
    updated = _read_detail(workspace, agi_id, "DOD-001")
    assert re.search(r"(?m)^status:\s*in_progress\s*$", updated)
    assert "unlock_history:" in updated
    assert "category: upstream_evidence_changed" in updated


def test_missing_reason(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "integration_regression",
        "--evidence",
        "SMK-001,logs/smoke-fail.log",
    )

    assert proc.returncode == 1
    assert "reason required (min 20 chars)" in _combined_output(proc)


def test_short_circuit_reason_rejected(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "integration_regression",
        "--reason",
        "fix bug ok",
        "--evidence",
        "SMK-001,logs/smoke-fail.log",
    )

    assert proc.returncode == 1
    assert "reason rejected (too short or forbidden pattern)" in _combined_output(proc)


def test_category_evidence_required(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "integration_regression",
        "--reason",
        "integration smoke run SMK-001 failed with deterministic repro logs attached",
    )

    assert proc.returncode == 1
    assert "evidence required for category integration_regression (smoke run ID + failure log)" in _combined_output(proc)


def test_dependent_revalidation_flag(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")
    _write_detail(workspace, agi_id, "DOD-002", status="done", blocked_by=["DOD-001"])
    _write_detail(workspace, agi_id, "DOD-003", status="done", blocked_by=["DOD-001"])

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "objective_precision_fix",
        "--reason",
        "objective wording precision improved to remove ambiguity in user-visible acceptance",
        "--evidence",
        "objective.diff",
    )

    assert proc.returncode == 0, _combined_output(proc)
    dependent_2 = _read_detail(workspace, agi_id, "DOD-002")
    dependent_3 = _read_detail(workspace, agi_id, "DOD-003")
    assert "revalidation_required: true" in dependent_2
    assert "revalidation_required: true" in dependent_3
    assert re.search(r"(?m)^status:\s*done\s*$", dependent_2)
    assert re.search(r"(?m)^status:\s*done\s*$", dependent_3)


def test_revalidate_done(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")
    _write_detail(workspace, agi_id, "DOD-002", status="done", blocked_by=["DOD-001"])

    unlock_proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "new_dependency_dod",
        "--reason",
        "new dependency DOD-010 introduced and downstream completion now requires recheck",
        "--evidence",
        "DOD-010",
    )
    assert unlock_proc.returncode == 0, _combined_output(unlock_proc)

    proc = _run_mst(
        workspace,
        "agile",
        "revalidate-done",
        "DOD-002",
        "--agi-id",
        agi_id,
    )

    assert proc.returncode == 0, _combined_output(proc)
    updated = _read_detail(workspace, agi_id, "DOD-002")
    assert "revalidation_required: true" not in updated


def test_unlock_history_append(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=True)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    first = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "upstream_evidence_changed",
        "--reason",
        "upstream DOD-005 evidence fingerprint changed from 111 to 222 with concrete diff",
        "--evidence",
        "DOD-005,fingerprint.diff",
    )
    assert first.returncode == 0, _combined_output(first)

    path = _details_dir(workspace, agi_id) / "DOD-001.md"
    content = path.read_text(encoding="utf-8")
    path.write_text(content.replace("status: in_progress", "status: done", 1), encoding="utf-8")

    second = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "integration_regression",
        "--reason",
        "integration smoke SMK-009 regressed after merge and log trace confirms reproducible fail",
        "--evidence",
        "SMK-009,logs/smk-009-fail.log",
    )
    assert second.returncode == 0, _combined_output(second)

    updated = _read_detail(workspace, agi_id, "DOD-001")
    assert updated.count("- timestamp:") == 2
    assert re.search(r"(?m)^reopened_count:\s*2\s*$", updated)

    agile_state = workspace / ".gran-maestro" / "agile" / "agile-state.json"
    payload = json.loads(agile_state.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("reopened_count") == 2


def test_disabled(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_unlock_config(workspace, enabled=False)
    _write_detail(workspace, agi_id, "DOD-001", status="done")

    proc = _run_mst(
        workspace,
        "agile",
        "unlock",
        "--agi-id",
        agi_id,
        "--dod",
        "DOD-001",
        "--category",
        "objective_precision_fix",
        "--reason",
        "objective wording precision improved to remove ambiguity in user-visible acceptance",
        "--evidence",
        "objective.diff",
    )

    assert proc.returncode == 1
    assert "unlock disabled by config" in _combined_output(proc)
