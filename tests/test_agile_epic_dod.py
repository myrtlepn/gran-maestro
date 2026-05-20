import json
import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _load_mst_module():
    spec = importlib.util.spec_from_file_location("mst_module", MST_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MST_MODULE = _load_mst_module()


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


def _sprint_paths(workspace: Path, agi_id: str, sprint: int) -> dict[str, Path]:
    sprint_id = f"S{sprint:02d}"
    root = workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / sprint_id
    return {
        "result_json": root / "result.json",
        "result_md": root / "result.md",
    }


def _init_agile(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write_objective(workspace: Path, agi_id: str, content: str):
    paths = _agile_paths(workspace, agi_id)
    paths["objective"].write_text(content, encoding="utf-8")


def test_objective_check_dod_partial(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- dod:DOD-001 status:todo priority:must -->\n"
            "- [x] DOD-002\n"
            "<!-- dod:DOD-002 status:done priority:should -->\n"
        ),
    )

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["all_done"] is False
    assert payload["incomplete"] == ["DOD-001"]
    assert payload["dods"]["DOD-001"] == {
        "status": "todo",
        "priority": "must",
        "domain": "unknown",
    }
    assert payload["stories"]["DOD-002"] == "done"


def test_collect_objective_dod_items_structured_multiline_format():
    content = (
        "# Objective\n\n"
        "## Project DoD\n\n"
        "- [ ] DOD-001: API 응답 성능 안정화\n"
        "  - Direction: 최소화\n"
        "  - Measure: p95 응답 시간\n"
        "  - Object: API read endpoint\n"
        "  - Context: 평시 트래픽(동시 1,000)에서\n"
        "  - Target: 250ms 이하\n"
        "  > detail:\n"
        "  > - PERF-01 시나리오 기준\n"
        "<!-- dod:DOD-001 status:todo priority:must -->\n"
        "- [x] DOD-002: 오류율 제어\n"
        "  - Direction: 보장\n"
        "  - Measure: 5xx 비율\n"
        "  - Object: API gateway\n"
        "  - Context: 일일 배치 실행 구간에서\n"
        "  - Target: 0.1% 이하\n"
        "<!-- dod:DOD-002 status:done priority:should -->\n"
    )

    items = MST_MODULE._collect_objective_dod_items(content)
    assert items == {
        "DOD-001": {"status": "todo", "priority": "must", "domain": "unknown"},
        "DOD-002": {"status": "done", "priority": "should", "domain": "unknown"},
    }


def test_collect_objective_dod_items_supports_spaced_marker_tokens():
    content = (
        "# Objective\n\n"
        "- [ ] DOD-010: 한 줄 포맷 호환\n"
        "<!-- dod: DOD-010 status: TODO priority: MUST -->\n"
        "- [ ] DOD-011: 다중행 포맷 호환\n"
        "<!-- dod:DOD-011 status:done priority:should -->\n"
    )

    items = MST_MODULE._collect_objective_dod_items(content)
    assert items == {
        "DOD-010": {"status": "todo", "priority": "must", "domain": "unknown"},
        "DOD-011": {"status": "done", "priority": "should", "domain": "unknown"},
    }


def test_update_objective_dod_status_supports_spaced_marker_tokens():
    content = (
        "# Objective\n\n"
        "- [ ] DOD-010: 상태 전이\n"
        "<!-- dod: DOD-010 status: todo priority: MUST -->\n"
    )

    updated, found, changed = MST_MODULE._update_objective_dod_status(content, "DOD-010", "done")

    assert found is True
    assert changed is True
    assert "<!-- dod: DOD-010 status: done priority: MUST -->" in updated


def test_objective_check_dod_all_done(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [x] DOD-001\n"
            "<!-- dod:DOD-001 status:done priority:must -->\n"
            "- [x] DOD-002\n"
            "<!-- dod:DOD-002 status:completed priority:should -->\n"
        ),
    )

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["all_done"] is True
    assert payload["incomplete"] == []


def test_objective_transition_dod(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- dod:DOD-001 status:todo priority:must -->\n"
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
    assert "<!-- dod:DOD-001 status:done priority:must -->" in updated_objective

    check_proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    check_payload = json.loads(check_proc.stdout)
    assert check_proc.returncode == 0
    assert check_payload["dods"]["DOD-001"]["status"] == "done"

    changelog_entries = [
        json.loads(line)
        for line in paths["changelog"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert changelog_entries, "objective changelog should not be empty"
    last = changelog_entries[-1]
    assert last["event"] == "objective-transition"
    assert last["dod"] == "DOD-001"
    assert last["to_status"] == "done"
    assert last["priority"] == "must"


def test_objective_check_init_default_dod_pending(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["all_done"] is False
    assert payload["stories"]["DOD-001"] == "todo"
    assert payload["dods"]["DOD-001"]["priority"] == "must"
    assert payload["incomplete"] == ["DOD-001"]


def test_agile_init_seeds_dod_objective_template(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(workspace, "agile", "init", "--steering-every", "3", "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert "objective_mode" not in payload
    assert payload["steering_every"] == 3
    assert payload["objective"]["path"] == "objective/objective.md"
    assert payload["objective"]["version"] == 1

    objective_path = _agile_paths(workspace, payload["agi_id"])["objective"]
    objective = objective_path.read_text(encoding="utf-8")
    assert "<!-- dod:DOD-001 status:todo priority:must -->" in objective


def test_objective_check_warns_when_no_dod_markers(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    _write_objective(
        workspace,
        agi_id,
        (
            "# Objective\n\n"
            "- [ ] Placeholder only\n"
        ),
    )

    proc = _run_mst(workspace, "agile", "objective-check", agi_id, "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["all_done"] is False
    assert payload["dods"] == {}
    assert payload["incomplete"] == []
    assert payload["warning"] == "no DoD items found"


def test_agile_result_saves_sprint_goals_and_renders_goal_section(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)
    sprint_goals = json.dumps(
        [
            {
                "goal": "설정 저장 시 서버 재시작 없이 반영",
                "status": "achieved",
                "change_summary": "config 핫리로드 구현 완료",
                "evidence": {
                    "screenshots": ["path/to/shot.webp"],
                    "test_results": {"passed": 2, "failed": 0, "summary": "2/2 통과"},
                    "diff": {"files_changed": 3, "insertions": 15, "deletions": 3, "commits": ["abc123"]},
                },
            }
        ],
        ensure_ascii=False,
    )

    proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "5",
        "--status",
        "done",
        "--planned",
        "JT-S001",
        "--completed",
        "JT-S001",
        "--sprint-goals",
        sprint_goals,
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["sprint_goals"][0]["goal"] == "설정 저장 시 서버 재시작 없이 반영"
    assert payload["sprint_goals"][0]["status"] == "achieved"
    assert payload["sprint_goals"][0]["change_summary"] == "config 핫리로드 구현 완료"

    paths = _sprint_paths(workspace, agi_id, 5)
    saved = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert saved["sprint_goals"][0]["evidence"]["screenshots"] == ["path/to/shot.webp"]

    result_md = paths["result_md"].read_text(encoding="utf-8")
    assert "## 목표 달성 현황" in result_md
    assert "설정 저장 시 서버 재시작 없이 반영" in result_md
    assert "achieved" in result_md
    assert "config 핫리로드 구현 완료" in result_md


def test_agile_result_defaults_sprint_goals_to_empty_array(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "1",
        "--status",
        "done",
        "--planned",
        "JT-S001",
        "--completed",
        "JT-S001",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["planned"] == ["JT-S001"]
    assert payload["completed"] == ["JT-S001"]
    assert payload["sprint_goals"] == []

    paths = _sprint_paths(workspace, agi_id, 1)
    saved = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert saved["generated"] == {"pln": [], "req": []}
    assert saved["sprint_goals"] == []


def test_agile_result_persists_generated_links_and_dod_ref(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agile(workspace)

    proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "7",
        "--status",
        "done",
        "--planned",
        "JT-S007",
        "--completed",
        "JT-S007",
        "--pln",
        "PLN-737",
        "--req",
        "REQ-913",
        "--dod-ref",
        "DOD-007",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "done"
    assert payload["generated"] == {"pln": ["PLN-737"], "req": ["REQ-913"]}
    assert payload["dod_ref"] == "DOD-007"

    saved = json.loads(_sprint_paths(workspace, agi_id, 7)["result_json"].read_text(encoding="utf-8"))
    assert saved["status"] == "done"
    assert saved["generated"] == {"pln": ["PLN-737"], "req": ["REQ-913"]}
    assert saved["dod_ref"] == "DOD-007"
