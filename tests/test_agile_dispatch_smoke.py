import json, subprocess
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


def test_dispatch_smoke_success(tmp_path, monkeypatch):
    """dispatch-result success 경로 + 스키마 검증"""
    project = tmp_path
    _seed_agile_session(project, AGI_ID)
    monkeypatch.chdir(project)
    r = subprocess.run(
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
    assert r.returncode == 0, r.stderr
    out = project / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S01" / "dispatch-result.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["status"] == "success"
    assert data["exit_code"] == 0
    assert data["pln_id"] == "PLN-SMOKE"
    assert data["req_id"] == "REQ-SMOKE"
    assert data["commit_sha"] == "abc1234"
    assert data["sprint_kind"] == "user_observable"
    assert data["result_recorded"] is True
    assert data["retrospective_recorded"] is True


def test_dispatch_smoke_failure(tmp_path, monkeypatch):
    """dispatch-result failed 경로 + failure_reason 포함"""
    project = tmp_path
    _seed_agile_session(project, AGI_ID)
    monkeypatch.chdir(project)
    r = subprocess.run(
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
            "dispatch chain exited with SIGKILL",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=project,
    )
    assert r.returncode == 0, r.stderr
    out = project / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S02" / "dispatch-result.json"
    data = json.loads(out.read_text())
    assert data["status"] == "failed"
    assert data["exit_code"] == 137
    assert data["failure_reason"] == "dispatch chain exited with SIGKILL"
