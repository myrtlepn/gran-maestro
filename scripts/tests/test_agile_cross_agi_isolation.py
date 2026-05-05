from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
PROTECTED_AGI_ID = "AGI-030"
TARGET_AGI_ID = "AGI-001"
TARGET_REQ_ID = "REQ-001"
PROTECTED_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
TARGET_SESSION_ID = "MST-AGI-001-20260503T130813382Z-a1b2c3d4"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_fingerprint(path: Path) -> str:
    return _sha256(path) if path.exists() else "<missing>"


def _tree_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {"": "<missing>"}
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _protected_fingerprint(repo_root: Path) -> dict[str, object]:
    base = repo_root / ".gran-maestro"
    agile_dir = base / "agile" / PROTECTED_AGI_ID
    state_dir = base / "state" / PROTECTED_SESSION_ID
    session_dir = base / "sessions" / PROTECTED_SESSION_ID
    protected_files = [
        agile_dir / "session.json",
        agile_dir / "events.ndjson",
        state_dir / "snapshot.json",
        session_dir / "session.json",
        session_dir / "history.ndjson",
        session_dir / "history.head",
        session_dir / "history.verify",
    ]
    return {
        "objective": _tree_fingerprint(agile_dir / "objective"),
        "files": {str(path.relative_to(base)): _file_fingerprint(path) for path in protected_files},
    }


def _write_agile_fixture(repo_root: Path, agi_id: str, mst_session_id: str, *, status: str = "active") -> None:
    agile_dir = repo_root / ".gran-maestro" / "agile" / agi_id
    objective_text = f"""# Objective: {agi_id}

## Project DoD

- [ ] DOD-010: Cross-AGI isolation remains stable.
<!-- dod:DOD-010 status:todo priority:must domain:state-history-recovery evidence_refs:[] -->
"""
    (agile_dir / "objective" / "details").mkdir(parents=True, exist_ok=True)
    (agile_dir / "objective" / "objective.md").write_text(objective_text, encoding="utf-8")
    (agile_dir / "objective" / "details" / "state-history-recovery.md").write_text(
        f"# State History Recovery\n\nAGI: {agi_id}\n",
        encoding="utf-8",
    )
    (agile_dir / "objective" / "changelog.ndjson").write_text(
        json.dumps({"event": "objective.seed", "agi_id": agi_id}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (agile_dir / "events.ndjson").write_text(
        json.dumps({"event": "agile.seed", "agi_id": agi_id}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_json(agile_dir / "index" / "links.json", {"agi_id": agi_id, "pln": [], "req": []})
    _write_json(
        agile_dir / "session.json",
        {
            "id": agi_id,
            "agi_id": agi_id,
            "status": status,
            "auto_mode": True,
            "current_sprint": 0,
            "steering_every": 3,
            "mst_session_id": mst_session_id,
            "objective": {"path": "objective/objective.md", "version": 1},
            "created_at": "2026-05-03T13:08:13Z",
            "updated_at": "2026-05-03T13:08:13Z",
        },
    )


def _write_state_history_fixture(repo_root: Path) -> None:
    base = repo_root / ".gran-maestro"
    history_head = "f" * 64
    _write_json(
        base / "state" / PROTECTED_SESSION_ID / "snapshot.json",
        {
            "schema_version": 1,
            "mst_session_id": PROTECTED_SESSION_ID,
            "root_mst_id": PROTECTED_AGI_ID,
            "status": "active",
            "history": {
                "ledger_path": f".gran-maestro/sessions/{PROTECTED_SESSION_ID}/history.ndjson",
                "last_event_id": history_head,
            },
            "updated_at": "2026-05-03T13:08:13Z",
        },
    )
    _write_json(
        base / "sessions" / PROTECTED_SESSION_ID / "session.json",
        {
            "schema_version": 1,
            "mst_session_id": PROTECTED_SESSION_ID,
            "root_mst_id": PROTECTED_AGI_ID,
            "created_at": "2026-05-03T13:08:13Z",
        },
    )
    session_dir = base / "sessions" / PROTECTED_SESSION_ID
    (session_dir / "history.ndjson").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_id": "protected-seed",
                "mst_session_id": PROTECTED_SESSION_ID,
                "root_mst_id": PROTECTED_AGI_ID,
                "event_type": "fixture.seed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (session_dir / "history.head").write_text(history_head + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(
        json.dumps({"ok": True, "head": history_head}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_target_request(repo_root: Path) -> None:
    _write_json(
        repo_root / ".gran-maestro" / "requests" / TARGET_REQ_ID / "request.json",
        {
            "id": TARGET_REQ_ID,
            "title": "Target AGI request",
            "status": "accepted",
            "current_phase": 4,
        },
    )


@pytest.fixture
def cross_agi_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    (repo_root / "app.txt").write_text("base\n", encoding="utf-8")
    assert _run_git(repo_root, "add", "app.txt").returncode == 0
    commit = _run_git(repo_root, "commit", "-m", "initial commit")
    assert commit.returncode == 0, commit.stderr
    assert _run_git(repo_root, "branch", "-M", "master").returncode == 0

    _write_agile_fixture(repo_root, PROTECTED_AGI_ID, PROTECTED_SESSION_ID)
    _write_state_history_fixture(repo_root)
    _write_agile_fixture(repo_root, TARGET_AGI_ID, TARGET_SESSION_ID)
    _write_target_request(repo_root)
    return repo_root


def test_other_agi_transitions_do_not_mutate_agi_030_artifacts(cross_agi_repo: Path) -> None:
    before = _protected_fingerprint(cross_agi_repo)

    sprint_update = _run_mst(cross_agi_repo, "agile", "update", TARGET_AGI_ID, "--current-sprint", "1")
    assert sprint_update.returncode == 0, sprint_update.stderr

    result = _run_mst(
        cross_agi_repo,
        "agile",
        "result",
        TARGET_AGI_ID,
        "--sprint",
        "1",
        "--status",
        "done",
        "--planned",
        "target-only",
        "--completed",
        "target-only",
        "--req",
        TARGET_REQ_ID,
        "--summary",
        "Target AGI transition only.",
        "--json",
    )
    assert result.returncode == 0, result.stderr

    finalize = _run_mst(cross_agi_repo, "agile", "finalize", TARGET_AGI_ID, "--json")
    assert finalize.returncode == 0, finalize.stderr

    completed = _run_mst(
        cross_agi_repo,
        "agile",
        "update",
        TARGET_AGI_ID,
        "--status",
        "completed",
        "--json",
    )
    assert completed.returncode == 0, completed.stderr

    after = _protected_fingerprint(cross_agi_repo)
    assert after == before

    protected_session = _read_json(cross_agi_repo / ".gran-maestro" / "agile" / PROTECTED_AGI_ID / "session.json")
    assert protected_session["mst_session_id"] == PROTECTED_SESSION_ID
    assert protected_session["status"] == "active"

    protected_objective = (
        cross_agi_repo
        / ".gran-maestro"
        / "agile"
        / PROTECTED_AGI_ID
        / "objective"
        / "objective.md"
    ).read_text(encoding="utf-8")
    assert "status:todo" in protected_objective
    assert TARGET_AGI_ID not in protected_objective
    assert TARGET_REQ_ID not in protected_objective

    target_session = _read_json(cross_agi_repo / ".gran-maestro" / "agile" / TARGET_AGI_ID / "session.json")
    assert target_session["status"] == "completed"
    assert target_session["current_sprint"] == 1
    assert (
        cross_agi_repo
        / ".gran-maestro"
        / "agile"
        / TARGET_AGI_ID
        / "sprints"
        / "S01"
        / "result.json"
    ).is_file()
    assert (cross_agi_repo / ".gran-maestro" / "agile" / TARGET_AGI_ID / "final-report.md").is_file()

    target_events_path = cross_agi_repo / ".gran-maestro" / "agile" / TARGET_AGI_ID / "events.ndjson"
    target_events = [
        json.loads(line)["event"]
        for line in target_events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "agile.result" in target_events
    assert "agile.finalize.ok" in target_events
    assert target_events[-1] == "agile.update"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
