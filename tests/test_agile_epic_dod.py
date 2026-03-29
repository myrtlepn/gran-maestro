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


def _agile_paths(workspace: Path, agi_id: str) -> dict[str, Path]:
    root = workspace / ".gran-maestro" / "agile" / agi_id
    return {
        "session": root / "session.json",
        "objective": root / "objective" / "objective.md",
        "changelog": root / "objective" / "changelog.ndjson",
    }


def _init_agile(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write_session_mode(workspace: Path, agi_id: str, objective_mode):
    paths = _agile_paths(workspace, agi_id)
    session = json.loads(paths["session"].read_text(encoding="utf-8"))
    if objective_mode is None:
        session.pop("objective_mode", None)
    else:
        session["objective_mode"] = objective_mode
    paths["session"].write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_objective(workspace: Path, agi_id: str, content: str):
    paths = _agile_paths(workspace, agi_id)
    paths["objective"].write_text(content, encoding="utf-8")


def test_objective_check_epic_mode_partial(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_session_mode(workspace, agi_id, "epic")
    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- epic:EPIC-001 dod:DOD-001 status:todo -->\n"
            "- [x] DOD-002\n"
            "<!-- epic:EPIC-001 dod:DOD-002 status:done -->\n"
        ),
    )

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["all_done"] is False
    assert payload["incomplete"] == ["DOD-001"]


def test_objective_check_epic_all_done(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_session_mode(workspace, agi_id, "epic")
    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [x] DOD-001\n"
            "<!-- epic:EPIC-001 dod:DOD-001 status:done -->\n"
            "- [x] DOD-002\n"
            "<!-- epic:EPIC-001 dod:DOD-002 status:done -->\n"
        ),
    )

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["all_done"] is True
    assert payload["incomplete"] == []


def test_objective_transition_epic_dod(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_session_mode(workspace, agi_id, "epic")
    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- epic:EPIC-001 dod:DOD-001 status:todo -->\n"
        ),
    )

    proc = _run_mst(
        workspace,
        "agile",
        "objective-transition",
        agi_id,
        "--story",
        "DOD-001",
        "--status",
        "done",
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["story"] == "DOD-001"
    assert payload["status"] == "done"
    assert payload["changed"] is True

    paths = _agile_paths(workspace, agi_id)
    updated_objective = paths["objective"].read_text(encoding="utf-8")
    assert "<!-- epic:EPIC-001 dod:DOD-001 status:done -->" in updated_objective

    changelog_entries = [
        json.loads(line)
        for line in paths["changelog"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert changelog_entries, "objective changelog should not be empty"
    last = changelog_entries[-1]
    assert last["event"] == "objective-transition"
    assert last["story"] == "DOD-001"
    assert last["to_status"] == "done"


def test_objective_check_story_mode_compat(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_session_mode(workspace, agi_id, "story")

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["all_done"] is False
    assert payload["stories"]["STORY-001"] == "todo"
    assert payload["incomplete"] == ["STORY-001"]


def test_agile_init_objective_mode(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(workspace, "agile", "init", "--steering-every", "3", "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["objective_mode"] == "epic"


def test_legacy_session_fallback(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_session_mode(workspace, agi_id, None)

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["all_done"] is False
    assert payload["stories"]["STORY-001"] == "todo"
    assert payload["incomplete"] == ["STORY-001"]
