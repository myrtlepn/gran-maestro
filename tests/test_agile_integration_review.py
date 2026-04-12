import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        ["git", "init"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    for key, value in (
        ("user.email", "test@example.com"),
        ("user.name", "Test User"),
    ):
        proc = subprocess.run(
            ["git", "config", key, value],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(workspace: Path, *args: str):
    proc = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def _git_stdout(workspace: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


def _git_commit_all(workspace: Path, message: str):
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", message)


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_previous_result(workspace: Path, agi_id: str, sprint: int, payload: dict):
    _write(
        workspace
        / ".gran-maestro"
        / "agile"
        / agi_id
        / "sprints"
        / f"S{sprint:02d}"
        / "result.json",
        json.dumps(payload, ensure_ascii=False),
    )


def _prepare_base_commit(workspace: Path):
    _write(
        workspace / "src" / "app.py",
        "def app_entrypoint():\n    return 'ok'\n",
    )
    _git_commit_all(workspace, "base")


def _apply_change_set(workspace: Path, wire_count: int, island_count: int):
    app_path = workspace / "src" / "app.py"
    current = app_path.read_text(encoding="utf-8")
    import_lines = []

    for idx in range(1, wire_count + 1):
        module_name = f"wire_{idx}"
        _write(workspace / "src" / f"{module_name}.py", f"def {module_name}():\n    return {idx}\n")
        import_lines.append(f"import {module_name}")

    for idx in range(1, island_count + 1):
        module_name = f"island_{idx}"
        _write(workspace / "src" / f"{module_name}.py", f"def {module_name}():\n    return {idx}\n")

    updated = current + "\n" + "\n".join(import_lines) + "\n"
    app_path.write_text(updated, encoding="utf-8")
    _git_commit_all(workspace, "changes")


def _integration_review(
    workspace: Path,
    agi_id: str,
    sprint: int,
    *,
    depth: Optional[int] = None,
    threshold: Optional[float] = None,
    escape_reason: Optional[str] = None,
):
    args = ["agile", "integration-review", agi_id, "--sprint", str(sprint), "--json"]
    if depth is not None:
        args.extend(["--depth", str(depth)])
    if threshold is not None:
        args.extend(["--threshold", str(threshold)])
    if escape_reason is not None:
        args.extend(["--escape-reason", escape_reason])

    proc = _run_mst(workspace, *args)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize(
    "wire_count,island_count,expected_ratio,expected_exceeded",
    [
        (18, 1, 0.05, False),
        (3, 1, 0.20, False),
        (1, 2, 0.50, True),
    ],
)
def test_classification_three_ratios(
    tmp_path,
    wire_count: int,
    island_count: int,
    expected_ratio: float,
    expected_exceeded: bool,
):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)
    _apply_change_set(workspace, wire_count=wire_count, island_count=island_count)

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["sprint"] == "S05"
    assert payload["depth"] == 1
    assert payload["window_sprints"] == ["S05"]

    expected_total = 1 + wire_count + island_count
    assert payload["files"]["total"] == expected_total
    assert payload["files"]["modify"] == 1
    assert payload["files"]["wire"] == wire_count
    assert payload["files"]["new_island"] == island_count
    assert len(payload["files"]["new_island_files"]) == island_count

    assert payload["ratios"]["new_island"] == pytest.approx(expected_ratio, abs=1e-9)
    assert payload["verdict"]["new_island_threshold"] == 0.20
    assert payload["verdict"]["exceeded"] is expected_exceeded
    assert payload["verdict"]["force_wire_recommended"] is expected_exceeded


def test_integration_context_md_generated(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)
    _apply_change_set(workspace, wire_count=1, island_count=1)

    proc = _run_mst(
        workspace,
        "agile",
        "integration-review",
        agi_id,
        "--sprint",
        "5",
        "--depth",
        "1",
    )
    assert proc.returncode == 0, proc.stderr

    context_path = (
        workspace
        / ".gran-maestro"
        / "agile"
        / agi_id
        / "sprints"
        / "S05"
        / "integration-context.md"
    )
    assert context_path.exists()

    content = context_path.read_text(encoding="utf-8")
    assert "## 1. 변경 파일 트리 (분류별)" in content
    assert "## 2. Entrypoint 상태" in content
    assert "## 4. wire 파일별 통합 지점" in content


def test_tests_directory_new_file_is_wire(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "tests" / "test_new_feature.py",
        "def test_placeholder():\n    assert True\n",
    )
    _git_commit_all(workspace, "add test only")

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["total"] == 1
    assert payload["files"]["modify"] == 0
    assert payload["files"]["wire"] == 1
    assert payload["files"]["new_island"] == 0


def test_init_package_wire(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "providers" / "__init__.py",
        "def register():\n    return 'ok'\n",
    )
    _write(
        workspace / "src" / "app.py",
        "from providers import register\n\n\ndef app_entrypoint():\n    return register()\n",
    )
    _git_commit_all(workspace, "add providers package")

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["total"] == 2
    assert payload["files"]["modify"] == 1
    assert payload["files"]["wire"] == 1
    assert payload["files"]["new_island"] == 0
    assert "providers/__init__.py" not in payload["files"]["new_island_files"]


def test_register_callsite_wire(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "src" / "auth.py",
        "def register():\n    return True\n",
    )
    _write(
        workspace / "src" / "app.py",
        "import auth\n\n\ndef app_entrypoint():\n    return auth.register()\n",
    )
    _git_commit_all(workspace, "add auth register")

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["total"] == 2
    assert payload["files"]["modify"] == 1
    assert payload["files"]["wire"] == 1
    assert payload["files"]["new_island"] == 0
    assert "src/auth.py" not in payload["files"]["new_island_files"]


def test_promote_with_test_evidence_pass(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "src" / "providers" / "__init__.py",
        "def register():\n    return 'ok'\n",
    )
    _write(
        workspace / "tests" / "test_providers.py",
        "from src.providers import register\n\n\ndef test_provider_register():\n    assert register() == 'ok'\n",
    )
    _git_commit_all(workspace, "add providers and tests")

    head_commit = _git_stdout(workspace, "rev-parse", "HEAD")
    head_tree = _git_stdout(workspace, "rev-parse", "HEAD^{tree}")
    _write_previous_result(
        workspace,
        agi_id,
        4,
        {
            "sprint_id": "S04",
            "result_commit": head_commit,
            "git_tree": head_tree,
            "sprint_goals": [
                {
                    "goal": "providers coverage",
                    "status": "done",
                    "change_summary": "provider import covered",
                    "evidence": {
                        "test_results": {
                            "tests/test_providers.py::test_provider_register": "PASS",
                        }
                    },
                }
            ],
        },
    )

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["new_island"] == 0
    assert "src/providers/__init__.py" not in payload["files"]["new_island_files"]
    assert len(payload["wire_promotions"]) == 1
    promotion = payload["wire_promotions"][0]
    assert promotion["file"] == "src/providers/__init__.py"
    assert promotion["promoted_by_test"] is True
    assert promotion["evidence_source"] == "cached"
    assert promotion["freshness"] == "fresh"


def test_stale_result_triggers_fallback(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(workspace / "pytest.ini", "[pytest]\n")
    _git_commit_all(workspace, "add pytest runner config")

    _write(
        workspace / "src" / "providers" / "__init__.py",
        "def register():\n    return 'ok'\n",
    )
    _write(
        workspace / "tests" / "test_providers.py",
        "from src.providers import register\n\n\ndef test_provider_register():\n    assert register() == 'ok'\n",
    )
    _git_commit_all(workspace, "add provider tests for fallback")

    stale_commit = _git_stdout(workspace, "rev-parse", "HEAD~1")
    stale_tree = _git_stdout(workspace, "rev-parse", "HEAD~1^{tree}")
    _write_previous_result(
        workspace,
        agi_id,
        4,
        {
            "sprint_id": "S04",
            "result_commit": stale_commit,
            "git_tree": stale_tree,
            "sprint_goals": [],
        },
    )

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["new_island"] == 0
    assert len(payload["wire_promotions"]) == 1
    promotion = payload["wire_promotions"][0]
    assert promotion["file"] == "src/providers/__init__.py"
    assert promotion["evidence_source"] == "fallback"
    assert promotion["freshness"] == "stale"


def test_no_test_infra_graceful_skip(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "src" / "isolated_feature.py",
        "def isolated_feature():\n    return 'isolated'\n",
    )
    _git_commit_all(workspace, "add isolated feature")

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert payload["files"]["new_island"] == 1
    assert "src/isolated_feature.py" in payload["files"]["new_island_files"]
    assert payload["wire_promotions"] == []


def test_wire_promotions_in_payload(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)

    _write(
        workspace / "src" / "providers" / "__init__.py",
        "def register():\n    return 'ok'\n",
    )
    _write(
        workspace / "tests" / "test_providers.py",
        "from src.providers import register\n\n\ndef test_provider_register():\n    assert register() == 'ok'\n",
    )
    _git_commit_all(workspace, "add providers for payload check")

    head_commit = _git_stdout(workspace, "rev-parse", "HEAD")
    head_tree = _git_stdout(workspace, "rev-parse", "HEAD^{tree}")
    _write_previous_result(
        workspace,
        agi_id,
        4,
        {
            "sprint_id": "S04",
            "result_commit": head_commit,
            "git_tree": head_tree,
            "sprint_goals": [
                {
                    "goal": "provider smoke",
                    "status": "done",
                    "change_summary": "cache-ready",
                    "evidence": {
                        "test_results": {
                            "tests/test_providers.py::test_provider_register": {"status": "pass"},
                        }
                    },
                }
            ],
        },
    )

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1, threshold=0.20)

    assert "wire_promotions" in payload
    assert payload["wire_promotions"], "wire_promotions must record promoted files"
    promotion = payload["wire_promotions"][0]
    assert {"file", "promoted_by_test", "evidence_source", "freshness"}.issubset(set(promotion.keys()))


def test_wire_streak_counted_from_previous_reviews(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)
    _apply_change_set(workspace, wire_count=1, island_count=2)

    _write(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps({"agile": {"integration_wire_streak_max": 2, "new_island_threshold": 0.2}}),
    )

    _write(
        workspace
        / ".gran-maestro"
        / "agile"
        / agi_id
        / "sprints"
        / "S04"
        / "integration-review.json",
        json.dumps({"verdict": {"force_wire_recommended": True}}),
    )

    payload = _integration_review(workspace, agi_id, sprint=5, depth=1)

    assert payload["wire_streak"] == {
        "current": 2,
        "max": 2,
        "exceeded": True,
    }


def test_escape_hatch_reason_recorded(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _prepare_base_commit(workspace)
    _apply_change_set(workspace, wire_count=1, island_count=2)

    payload = _integration_review(
        workspace,
        agi_id,
        sprint=5,
        depth=1,
        threshold=0.20,
        escape_reason="동적 import는 grep 미감지",
    )

    assert payload["verdict"]["exceeded"] is True
    assert payload["verdict"]["force_wire_recommended"] is True
    assert payload["verdict"]["escape_hatch_used"] is True
    assert payload["verdict"]["escape_reason"] == "동적 import는 grep 미감지"


def test_result_sprint_kind_fields(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)

    default_proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "1",
        "--status",
        "done",
        "--json",
    )
    assert default_proc.returncode == 0, default_proc.stderr
    default_payload = json.loads(default_proc.stdout)
    assert default_payload["sprint_kind"] == "user_observable"
    assert "user_observable_change" in default_payload
    assert "foundational_reason" in default_payload
    assert default_payload["user_observable_change"] is None
    assert default_payload["foundational_reason"] is None

    foundational_proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "2",
        "--status",
        "done",
        "--sprint-kind",
        "foundational",
        "--foundational-reason",
        "테스트 인프라 구축",
        "--json",
    )
    assert foundational_proc.returncode == 0, foundational_proc.stderr
    foundational_payload = json.loads(foundational_proc.stdout)
    assert foundational_payload["sprint_kind"] == "foundational"
    assert foundational_payload["foundational_reason"] == "테스트 인프라 구축"
    assert foundational_payload["user_observable_change"] is None

    user_observable_proc = _run_mst(
        workspace,
        "agile",
        "result",
        agi_id,
        "--sprint",
        "3",
        "--status",
        "done",
        "--sprint-kind",
        "user_observable",
        "--user-observable-change",
        "사용자가 /sc:plan을 호출하면 Q&A가 시작된다",
        "--json",
    )
    assert user_observable_proc.returncode == 0, user_observable_proc.stderr
    user_observable_payload = json.loads(user_observable_proc.stdout)
    assert user_observable_payload["sprint_kind"] == "user_observable"
    assert user_observable_payload["user_observable_change"] == "사용자가 /sc:plan을 호출하면 Q&A가 시작된다"
    assert user_observable_payload["foundational_reason"] is None


def test_objective_transition_deferred_promote(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)

    objective_path = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "objective.md"
    _write(
        objective_path,
        (
            "# Objective\n\n"
            "- [ ] DOD-001\n"
            "<!-- dod:DOD-001 status:proposed_done priority:must -->\n"
            "- [ ] DOD-002\n"
            "<!-- dod:DOD-002 status:proposed_done priority:must -->\n"
            "- [ ] DOD-005\n"
            "<!-- dod:DOD-005 status:todo priority:must -->\n"
        ),
    )

    for sprint, dod in ((3, "DOD-001"), (4, "DOD-002")):
        proc = _run_mst(
            workspace,
            "agile",
            "result",
            agi_id,
            "--sprint",
            str(sprint),
            "--status",
            "done",
            "--completed",
            dod,
            "--sprint-kind",
            "foundational",
            "--json",
        )
        assert proc.returncode == 0, proc.stderr

    transition_proc = _run_mst(
        workspace,
        "agile",
        "objective-transition",
        agi_id,
        "--story",
        "DOD-005",
        "--status",
        "done",
        "--deferred-promote",
        "--sprint",
        "5",
        "--json",
    )
    assert transition_proc.returncode == 0, transition_proc.stderr
    transition_payload = json.loads(transition_proc.stdout)
    assert transition_payload["status"] == "done"

    updated_objective = objective_path.read_text(encoding="utf-8")
    assert "<!-- dod:DOD-001 status:done priority:must -->" in updated_objective
    assert "<!-- dod:DOD-002 status:done priority:must -->" in updated_objective
    assert "<!-- dod:DOD-005 status:done priority:must -->" in updated_objective

    changelog_path = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "changelog.ndjson"
    entries = [
        json.loads(line)
        for line in changelog_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    deferred = [entry for entry in entries if entry.get("event") == "deferred-promote"]
    assert deferred, "deferred-promote event must be recorded"
    assert deferred[-1]["sprints"] == ["S04", "S03"]
    assert deferred[-1]["dods"] == ["DOD-001", "DOD-002"]
