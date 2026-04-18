import json
import subprocess
from pathlib import Path


PLUGIN_ROOT = "/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.58.3"
MST_CLI = f"{PLUGIN_ROOT}/scripts/mst.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_MST_CLI = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-101"


def _resolve_mst_cli() -> str:
    for candidate in (Path(MST_CLI), REPO_MST_CLI):
        if not candidate.exists():
            continue
        help_result = subprocess.run(
            ["python3", str(candidate), "agile", "-h"],
            capture_output=True,
            text=True,
        )
        if "dispatch-result" in (help_result.stdout + help_result.stderr):
            return str(candidate)
    raise AssertionError("No mst.py with 'agile dispatch-result' support was found.")


MST = _resolve_mst_cli()


def _seed_agile_session(project: Path, agi_id: str) -> None:
    session_dir = project / ".gran-maestro" / "agile" / agi_id
    (session_dir / "sprints").mkdir(parents=True, exist_ok=True)
    (session_dir / "index").mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"id": agi_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_dispatch_result_schema_preserved(tmp_path, monkeypatch):
    project = tmp_path
    _seed_agile_session(project, AGI_ID)
    monkeypatch.chdir(project)

    result = subprocess.run(
        [
            "python3",
            MST,
            "agile",
            "dispatch-result",
            AGI_ID,
            "--sprint",
            "1",
            "--status",
            "success",
            "--exit-code",
            "0",
            "--pln",
            "PLN-SMOKE",
            "--req",
            "REQ-SMOKE",
            "--commit-sha",
            "abc1234",
            "--sprint-kind",
            "user_observable",
            "--result-recorded",
            "true",
            "--retrospective-recorded",
            "true",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=project,
    )

    assert result.returncode == 0, result.stderr
    dispatch_result = project / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S01" / "dispatch-result.json"
    assert dispatch_result.exists()

    data = json.loads(dispatch_result.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["exit_code"] == 0
    assert data["pln_id"] == "PLN-SMOKE"
    assert data["req_id"] == "REQ-SMOKE"
    assert data["commit_sha"] == "abc1234"
    assert data["sprint_kind"] == "user_observable"
    assert data["result_recorded"] is True
    assert data["retrospective_recorded"] is True


def test_inline_path_no_dispatch_result(tmp_path):
    project = tmp_path
    _seed_agile_session(project, AGI_ID)

    sprint_dir = project / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S02"
    sprint_dir.mkdir(parents=True, exist_ok=True)

    dispatch_result = sprint_dir / "dispatch-result.json"
    assert not dispatch_result.exists()


def test_dispatch_result_failure_schema_preserved(tmp_path, monkeypatch):
    project = tmp_path
    _seed_agile_session(project, AGI_ID)
    monkeypatch.chdir(project)

    result = subprocess.run(
        [
            "python3",
            MST,
            "agile",
            "dispatch-result",
            AGI_ID,
            "--sprint",
            "2",
            "--status",
            "failed",
            "--exit-code",
            "137",
            "--failure-reason",
            "simulated dispatch chain exit 137",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=project,
    )

    assert result.returncode == 0, result.stderr
    dispatch_result = project / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S02" / "dispatch-result.json"
    assert dispatch_result.exists()

    data = json.loads(dispatch_result.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["exit_code"] == 137
    assert data["failure_reason"] == "simulated dispatch chain exit 137"
