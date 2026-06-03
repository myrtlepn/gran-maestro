import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_agile_review_uses_draft_context_when_draft_dir_is_provided(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    init = _run_mst(workspace, "agile", "init", "--json")
    assert init.returncode == 0, init.stderr
    agi_id = json.loads(init.stdout)["agi_id"]

    objective_dir = workspace / ".gran-maestro" / "agile" / agi_id / "objective"
    objective_dir.mkdir(parents=True, exist_ok=True)
    (objective_dir / "objective.md").write_text("# Accepted Objective\n", encoding="utf-8")

    draft_dir = objective_dir / "draft"
    (draft_dir / "details").mkdir(parents=True, exist_ok=True)
    (draft_dir / "objective.md").write_text("# Draft Objective\n", encoding="utf-8")
    (draft_dir / "details" / "flow.md").write_text(
        "<!-- source-mapping: source=conversation evidence=clarification-context.md sections=[Flow] -->\n"
        "# Flow\n",
        encoding="utf-8",
    )

    proc = _run_mst(
        workspace,
        "agile",
        "review",
        "--agi",
        agi_id,
        "--perspective",
        "edge",
        "--draft-dir",
        str(draft_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["context_source"] == "draft"
    assert payload["draft_dir"] == str(draft_dir.resolve())
    assert str((draft_dir / "objective.md").resolve()) in payload["context_files"]
    assert str((draft_dir / "details" / "flow.md").resolve()) in payload["context_files"]
    assert str((objective_dir / "objective.md").resolve()) not in payload["context_files"]


def test_agile_review_resolves_session_from_absolute_draft_dir_when_cwd_differs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runner = tmp_path / "runner"
    workspace.mkdir()
    runner.mkdir()
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    (runner / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    init = _run_mst(workspace, "agile", "init", "--json")
    assert init.returncode == 0, init.stderr
    agi_id = json.loads(init.stdout)["agi_id"]

    objective_dir = workspace / ".gran-maestro" / "agile" / agi_id / "objective"
    draft_dir = objective_dir / "draft"
    (draft_dir / "details").mkdir(parents=True, exist_ok=True)
    (draft_dir / "objective.md").write_text("# Draft Objective\n", encoding="utf-8")

    proc = _run_mst(
        runner,
        "agile",
        "review",
        "--agi",
        agi_id,
        "--perspective",
        "edge",
        "--draft-dir",
        str(draft_dir),
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["context_source"] == "draft"
    assert payload["draft_dir"] == str(draft_dir.resolve())
