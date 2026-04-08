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


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write_file(path: Path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_gate_config(
    workspace: Path,
    *,
    enabled: bool,
    required_globs=None,
    project_type: str = "plugin",
):
    evidence_gate = {
        "enabled": enabled,
        "project_type": project_type,
    }
    if required_globs is not None:
        evidence_gate["required_globs"] = required_globs

    _write_file(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps({"agile": {"evidence_gate": evidence_gate}}, ensure_ascii=False),
    )


def _write_detail(
    workspace: Path,
    agi_id: str,
    *,
    filename: str,
    artifact_paths: list[str],
    integration_smoke_id: str = "smoke-001",
    verify_cmd: str = "python -m pytest tests/test_smoke.py -q",
    expected_signal: str = "1 passed",
    entrypoint_path: str = "src/app.py:main",
):
    details_dir = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "details"
    lines = [
        "<!-- source-mapping: original=docs/spec.md sections=[\"Delivery\"] -->",
        "---",
        "evidence:",
        "  plan:",
        "    artifact_paths:",
    ]
    for artifact in artifact_paths:
        lines.append(f"      - {artifact}")
    lines.extend(
        [
            f"    entrypoint_path: {entrypoint_path}",
            "  runtime:",
            f"    integration_smoke_id: {integration_smoke_id}",
            f"    verify_cmd: \"{verify_cmd}\"",
            f"    expected_signal: \"{expected_signal}\"",
            "---",
            "# Detail",
            "",
        ]
    )
    _write_file(details_dir / filename, "\n".join(lines))


def _prepare_valid_baseline(workspace: Path) -> str:
    agi_id = _init_agi(workspace)
    _write_file(workspace / "skills" / "demo" / "SKILL.md", "# Demo\n")
    _write_file(workspace / "src" / "app.py", "def main():\n    return 0\n")
    _write_file(workspace / "tests" / "test_smoke.py", "def test_smoke():\n    assert True\n")
    return agi_id


def test_pass_case(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _prepare_valid_baseline(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=["skills/*/SKILL.md"])
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py", "tests/test_smoke.py"],
    )

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1")

    assert proc.returncode == 0
    assert "PASS" in proc.stdout
    assert "violations: 0" in proc.stdout


def test_fail_missing_artifact(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _prepare_valid_baseline(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=["skills/*/SKILL.md"])
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/missing.py"],
    )

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1")

    assert proc.returncode == 1
    assert "FAIL" in proc.stdout
    assert "src/missing.py" in proc.stderr


def test_warn_tbd(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _prepare_valid_baseline(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=["skills/*/SKILL.md"])
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py"],
        integration_smoke_id="TBD",
    )

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1")

    assert proc.returncode == 0
    assert "WARN" in proc.stdout
    assert "integration_smoke_id" in proc.stderr


def test_required_globs_fail(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=["skills/*/SKILL.md"])
    _write_file(workspace / "src" / "app.py", "def main():\n    return 0\n")
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py"],
    )

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1")

    assert proc.returncode == 1
    assert "FAIL: required_globs unsatisfied" in proc.stdout


def test_bypass_reason_logged(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _prepare_valid_baseline(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=["skills/*/SKILL.md"])
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/missing.py"],
    )

    proc = _run_mst(
        workspace,
        "agile",
        "evidence-check",
        "--sprint",
        "1",
        "--accept-evidence-gap",
        "temporary placeholder",
    )

    assert proc.returncode == 0
    assert "BYPASSED: temporary placeholder" in proc.stdout

    sprint_log_path = workspace / ".gran-maestro" / "agile" / "sprint-log.json"
    assert sprint_log_path.exists()
    payload = json.loads(sprint_log_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload
    latest = payload[-1]
    assert latest["event"] == "evidence-gap-accepted"
    assert latest["reason"] == "temporary placeholder"


def test_gate_disabled_graceful(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_gate_config(workspace, enabled=False)

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1")

    assert proc.returncode == 0
    assert "WARN" in proc.stdout
    assert "disabled" in proc.stdout.lower()


def test_required_globs_fallback(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _prepare_valid_baseline(workspace)
    _write_gate_config(workspace, enabled=True, required_globs=None)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py"],
    )

    proc = _run_mst(workspace, "agile", "evidence-check", "--sprint", "1", "--json")
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["required_globs"]["patterns"] == ["skills/*/SKILL.md"]
