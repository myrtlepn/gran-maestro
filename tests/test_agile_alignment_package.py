import json
import subprocess
import sys
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


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _seed_sprint_files(workspace: Path, agi_id: str, sprint: int):
    sprint_id = f"S{sprint:02d}"
    sprint_dir = workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / sprint_id
    _write(sprint_dir / "result.json", json.dumps({"sprint_id": sprint_id, "status": "done"}))
    _write(sprint_dir / "retrospective.json", json.dumps({"sprint_id": sprint_id, "status": "done"}))


def test_alignment_payload_normal_and_missing_objective(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)

    objective_path = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "objective.md"
    _write(
        objective_path,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- dod:DOD-001 status:todo priority:must -->\n"
            "- [ ] DOD-002\n"
            "<!-- dod:DOD-002 status:done priority:should -->\n"
        ),
    )

    for sprint in (3, 4, 5):
        _seed_sprint_files(workspace, agi_id, sprint)

    integration_context_path = (
        workspace
        / ".gran-maestro"
        / "agile"
        / agi_id
        / "sprints"
        / "S05"
        / "integration-context.md"
    )
    _write(integration_context_path, "# Integration Context\n")

    proc = _run_mst(
        workspace,
        "agile",
        "alignment-package",
        agi_id,
        "--sprint",
        "5",
        "--depth",
        "3",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    assert payload["agi_id"] == agi_id
    assert payload["sprint"] == "S05"
    assert payload["depth"] == 3
    assert payload["integration_context_path"] == str(integration_context_path)
    assert [item["id"] for item in payload["objective_dods"]] == ["DOD-001", "DOD-002"]
    assert len(payload["recent_results"]) == 3
    assert len(payload["recent_retrospectives"]) == 3

    objective_path.unlink()

    missing_proc = _run_mst(
        workspace,
        "agile",
        "alignment-package",
        agi_id,
        "--sprint",
        "5",
        "--depth",
        "3",
        "--json",
    )
    assert missing_proc.returncode == 0, missing_proc.stderr
    missing_payload = json.loads(missing_proc.stdout)

    assert missing_payload["objective_dods"] == []
    assert missing_payload["warning"] == "objective file missing"


def test_alignment_package_depth_argument(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)

    for sprint in (3, 4, 5):
        _seed_sprint_files(workspace, agi_id, sprint)

    proc = _run_mst(
        workspace,
        "agile",
        "alignment-package",
        agi_id,
        "--sprint",
        "5",
        "--depth",
        "1",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    assert payload["depth"] == 1
    assert payload["recent_results"] == [
        str(workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / "S05" / "result.json")
    ]
    assert payload["recent_retrospectives"] == [
        str(workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / "S05" / "retrospective.json")
    ]
