import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
DEFAULTS_PATH = REPO_ROOT / "templates" / "defaults" / "config.json"
PERSPECTIVES_DIR = REPO_ROOT / "scripts" / "adversarial_review" / "perspectives"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)

    _write_json(
        base / "agile" / "AGI-001" / "session.json",
        {"id": "AGI-001", "agi_id": "AGI-001", "status": "active"},
    )
    (base / "agile" / "AGI-001" / "objective" / "details").mkdir(parents=True)
    (base / "agile" / "AGI-001" / "objective" / "objective.md").write_text(
        "OBJECTIVE_SECRET_T01\n",
        encoding="utf-8",
    )
    (base / "agile" / "AGI-001" / "objective" / "details" / "edge.md").write_text(
        "DETAIL_SECRET_T01\n",
        encoding="utf-8",
    )

    (base / "plans" / "PLN-001").mkdir(parents=True)
    (base / "plans" / "PLN-001" / "plan.md").write_text(
        "PLAN_SECRET_T01\n",
        encoding="utf-8",
    )

    _write_json(base / "requests" / "REQ-001" / "request.json", {"id": "REQ-001"})
    (base / "requests" / "REQ-001" / "tasks" / "01").mkdir(parents=True)
    (base / "requests" / "REQ-001" / "tasks" / "01" / "spec.md").write_text(
        "REQ_SECRET_T01\n",
        encoding="utf-8",
    )
    return workspace


def _enable_all_perspectives(workspace: Path) -> None:
    _write_json(
        workspace / ".gran-maestro" / "config.json",
        {
            "agile": {
                "adversarial_review": {
                    "enabled": True,
                    "perspectives": {
                        name: {"enabled": True}
                        for name in ("edge", "flow", "integration", "persona", "nfr")
                    },
                }
            }
        },
    )


def _load_json_stdout(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert proc.stdout.strip().startswith("{")
    assert proc.stdout.strip().endswith("}")
    return json.loads(proc.stdout)


def _assert_review_payload(payload: dict, perspective: str) -> None:
    assert set(payload) == {"context_files", "role_template", "output_schema", "perspective"}
    assert payload["perspective"] == perspective
    assert isinstance(payload["context_files"], list)
    assert payload["context_files"]
    for raw_path in payload["context_files"]:
        path = Path(raw_path)
        assert path.is_absolute()
        assert path.exists()
    role_template = Path(payload["role_template"])
    assert role_template.is_absolute()
    assert role_template.exists()
    assert payload["output_schema"] == {
        "findings": [
            {
                "type": "...",
                "description": "...",
                "suggested_dod": "...",
                "severity": "critical|major|minor",
            }
        ]
    }


def test_agile_review_returns_paths_only_json(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(workspace, "agile", "review", "--agi", "AGI-001", "--perspective", "edge", "--json")

    payload = _load_json_stdout(proc)
    _assert_review_payload(payload, "edge")
    assert len(payload["context_files"]) == 2
    assert "objective.md" in payload["context_files"][0]
    assert not any(secret in proc.stdout for secret in ("OBJECTIVE_SECRET_T01", "DETAIL_SECRET_T01"))


def test_plan_review_returns_plan_path_only_json(tmp_path):
    workspace = _make_workspace(tmp_path)
    plan_path = workspace / ".gran-maestro" / "plans" / "PLN-001" / "plan.md"

    proc = _run_mst(
        workspace,
        "plan",
        "review",
        "--plan-path",
        str(plan_path),
        "--perspective",
        "flow",
        "--json",
    )

    payload = _load_json_stdout(proc)
    _assert_review_payload(payload, "flow")
    assert payload["context_files"] == [str(plan_path.resolve())]
    assert "PLAN_SECRET_T01" not in proc.stdout


def test_request_review_is_json_only_and_returns_task_specs(tmp_path):
    workspace = _make_workspace(tmp_path)
    req_path = workspace / ".gran-maestro" / "requests" / "REQ-001"

    proc = _run_mst(
        workspace,
        "request",
        "review",
        "--req-path",
        str(req_path),
        "--perspective",
        "integration",
        "--json",
    )

    payload = _load_json_stdout(proc)
    _assert_review_payload(payload, "integration")
    assert payload["context_files"] == [str((req_path / "tasks" / "01" / "spec.md").resolve())]
    assert "REQ_SECRET_T01" not in proc.stdout


def test_all_perspectives_return_existing_templates_with_required_sections(tmp_path):
    workspace = _make_workspace(tmp_path)
    _enable_all_perspectives(workspace)
    plan_path = workspace / ".gran-maestro" / "plans" / "PLN-001" / "plan.md"

    for perspective in ("edge", "flow", "persona", "nfr", "integration"):
        proc = _run_mst(
            workspace,
            "plan",
            "review",
            "--plan-path",
            str(plan_path),
            "--perspective",
            perspective,
            "--json",
        )
        payload = _load_json_stdout(proc)
        template_text = Path(payload["role_template"]).read_text(encoding="utf-8")
        assert "## Role" in template_text
        assert "## Output Schema (JSON)" in template_text
        assert "## Instructions" in template_text


def test_disabled_perspective_exits_2_with_stderr_only(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_json(
        workspace / ".gran-maestro" / "config.json",
        {
            "agile": {
                "adversarial_review": {
                    "enabled": True,
                    "perspectives": {"edge": {"enabled": False}},
                }
            }
        },
    )

    proc = _run_mst(workspace, "agile", "review", "--agi", "AGI-001", "--perspective", "edge", "--json")

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "perspective 'edge' is disabled" in proc.stderr


def test_globally_disabled_exits_2_with_stderr_only(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_json(
        workspace / ".gran-maestro" / "config.json",
        {"agile": {"adversarial_review": {"enabled": False}}},
    )

    proc = _run_mst(workspace, "agile", "review", "--agi", "AGI-001", "--perspective", "edge", "--json")

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "adversarial_review is globally disabled" in proc.stderr


def test_default_config_has_adversarial_review_schema():
    cfg = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    review = cfg["agile"]["adversarial_review"]

    assert review["enabled"] is True
    assert review["perspectives"]["edge"]["enabled"] is True
    assert review["perspectives"]["flow"]["enabled"] is True
    assert review["perspectives"]["integration"]["enabled"] is True
    assert review["perspectives"]["persona"]["enabled"] is False
    assert review["perspectives"]["nfr"]["enabled"] is False
    assert review["agents"]["codex"] == {"count": 1, "tier": "premium"}
    assert review["agents"]["gemini"] == {"count": 0, "tier": "premium"}
    assert review["agents"]["claude"] == {"count": 0, "tier": "economy"}
    assert review["max_rounds"] == 3
    assert review["auto_apply_severity_threshold"] == "critical"
    assert review["parallel_in_auto_mode"] is True


def test_review_commands_do_not_read_context_files_before_printing():
    forbidden_calls = {"open", "read_text", "read"}
    targets = [
        (REPO_ROOT / "scripts" / "mst_cmds" / "agile.py", "cmd_agile_review"),
        (REPO_ROOT / "scripts" / "mst_cmds" / "plan.py", "cmd_plan_review"),
        (REPO_ROOT / "scripts" / "mst_cmds" / "request.py", "cmd_request_review"),
    ]

    for path, function_name in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
        calls = []
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
        assert forbidden_calls.isdisjoint(calls)


def test_perspective_template_schema_blocks_are_valid_json():
    for perspective in ("edge", "flow", "persona", "nfr", "integration"):
        text = (PERSPECTIVES_DIR / f"{perspective}.md").read_text(encoding="utf-8")
        match = re.search(r"## Output Schema \(JSON\).*?```json\n(.*?)\n```", text, re.S)
        assert match, perspective
        schema = json.loads(match.group(1))
        finding = schema["findings"][0]
        assert set(finding) == {"type", "description", "suggested_dod", "severity"}
        assert finding["severity"] == "critical|major|minor"


def test_review_cli_py_compile():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(MST_SCRIPT),
            str(REPO_ROOT / "scripts" / "mst_cmds" / "agile.py"),
            str(REPO_ROOT / "scripts" / "mst_cmds" / "plan.py"),
            str(REPO_ROOT / "scripts" / "mst_cmds" / "request.py"),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPYCACHEPREFIX": "/tmp/gran-maestro-pycache"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
