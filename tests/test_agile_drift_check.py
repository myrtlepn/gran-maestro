import json
import subprocess
import sys
from pathlib import Path

import pytest


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


def _write_file(path: Path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _write_drift_config(
    workspace: Path,
    *,
    enabled=False,
    threshold=0.7,
    warn_streak_limit=2,
):
    _write_file(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps(
            {
                "agile": {
                    "drift": {
                        "enabled": enabled,
                        "threshold": threshold,
                        "warn_streak_limit": warn_streak_limit,
                    }
                }
            },
            ensure_ascii=False,
        ),
    )


def _write_objective(workspace: Path, agi_id: str):
    objective_path = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "objective.md"
    _write_file(
        objective_path,
        "\n".join(
            [
                "# Objective",
                "",
                "## JTBD 레이어",
                "- When I review plugin sprint outcomes",
                "- I want objective surface coverage visibility",
                "- So I can catch drift escalation early",
                "",
                "## 프로젝트 완료 기준 (DoD)",
                "- [ ] DOD-001: deterministic agile-state ledger updates",
                "<!-- dod:DOD-001 status:todo priority:must -->",
                "- [ ] DOD-002: warn streak reset behavior",
                "<!-- dod:DOD-002 status:todo priority:must -->",
                "",
            ]
        ),
    )


def _write_detail(
    workspace: Path,
    agi_id: str,
    *,
    filename: str,
    artifact_paths: list[str],
    body: str,
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
            "    entrypoint_path: src/app.py:main",
            "  runtime:",
            "    integration_smoke_id: smoke-001",
            '    verify_cmd: "python -m pytest tests/test_smoke.py -q"',
            '    expected_signal: "1 passed"',
            "---",
            "# Detail",
            "",
            body,
            "",
        ]
    )
    _write_file(details_dir / filename, "\n".join(lines))


def _prepare_workspace_with_objective(tmp_path: Path) -> tuple[Path, str]:
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_drift_config(workspace, enabled=True, threshold=0.7, warn_streak_limit=2)
    _write_objective(workspace, agi_id)
    _write_file(workspace / "src" / "app.py", "def main():\n    return 0\n")
    _write_file(workspace / "tests" / "test_smoke.py", "def test_smoke():\n    assert True\n")
    return workspace, agi_id


def _run_drift_check_json(workspace: Path, agi_id: str, sprint: int = 1) -> tuple[subprocess.CompletedProcess, dict]:
    proc = _run_mst(
        workspace,
        "agile",
        "drift-check",
        "--agi-id",
        agi_id,
        "--sprint",
        str(sprint),
        "--json",
    )
    payload = json.loads(proc.stdout)
    return proc, payload


def test_full_coverage(tmp_path):
    workspace, agi_id = _prepare_workspace_with_objective(tmp_path)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-a.md",
        artifact_paths=["src/app.py"],
        body="plugin sprint outcomes and objective surface coverage visibility are tracked here.",
    )
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-b.md",
        artifact_paths=["tests/test_smoke.py"],
        body="drift escalation early signal with deterministic agile-state ledger and warn streak reset behavior.",
    )

    proc, payload = _run_drift_check_json(workspace, agi_id)

    assert proc.returncode == 0
    assert payload["drift_score"] == pytest.approx(1.0)
    assert len(payload["covered_surface"]) == 5
    assert len(payload["uncovered_surface"]) == 0
    assert payload["warn_level"] == "PASS"


def test_partial_coverage_warn(tmp_path):
    workspace, agi_id = _prepare_workspace_with_objective(tmp_path)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py"],
        body="plugin sprint outcomes objective surface coverage visibility and drift escalation early are implemented.",
    )

    proc, payload = _run_drift_check_json(workspace, agi_id)

    assert proc.returncode == 0
    assert payload["drift_score"] == pytest.approx(0.6)
    assert len(payload["covered_surface"]) == 3
    assert len(payload["uncovered_surface"]) == 2
    assert payload["warn_level"] == "WARN"


def test_warn_streak_escalate(tmp_path):
    workspace, agi_id = _prepare_workspace_with_objective(tmp_path)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery.md",
        artifact_paths=["src/app.py"],
        body="plugin sprint outcomes objective surface coverage visibility and drift escalation early are implemented.",
    )

    ledger_path = workspace / ".gran-maestro" / "agile" / "agile-state.json"
    _write_file(
        ledger_path,
        json.dumps(
            [
                {
                    "timestamp": "2026-04-01T00:00:00Z",
                    "drift_score": 0.6,
                    "covered_surface": ["seed"],
                    "uncovered_surface": ["missing"],
                    "warn_level": "WARN",
                    "warn_streak": 1,
                    "escalate_flag": False,
                }
            ],
            ensure_ascii=False,
        ),
    )

    proc = _run_mst(
        workspace,
        "agile",
        "drift-check",
        "--agi-id",
        agi_id,
        "--sprint",
        "1",
    )

    assert proc.returncode == 0
    assert "ESCALATE" in proc.stdout

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    latest = ledger[-1]
    assert latest["warn_streak"] == 2
    assert latest["escalate_flag"] is True


def test_warn_streak_reset(tmp_path):
    workspace, agi_id = _prepare_workspace_with_objective(tmp_path)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-a.md",
        artifact_paths=["src/app.py"],
        body="plugin sprint outcomes and objective surface coverage visibility are tracked here.",
    )
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-b.md",
        artifact_paths=["tests/test_smoke.py"],
        body="drift escalation early signal with deterministic agile-state ledger and warn streak reset behavior.",
    )

    ledger_path = workspace / ".gran-maestro" / "agile" / "agile-state.json"
    _write_file(
        ledger_path,
        json.dumps(
            [
                {
                    "timestamp": "2026-04-01T00:00:00Z",
                    "drift_score": 0.6,
                    "covered_surface": ["seed"],
                    "uncovered_surface": ["missing"],
                    "warn_level": "WARN",
                    "warn_streak": 1,
                    "escalate_flag": False,
                }
            ],
            ensure_ascii=False,
        ),
    )

    proc, payload = _run_drift_check_json(workspace, agi_id)

    assert proc.returncode == 0
    assert payload["warn_level"] == "PASS"
    assert payload["warn_streak"] == 0
    assert payload["escalate_flag"] is False


def test_ledger_init(tmp_path):
    workspace, agi_id = _prepare_workspace_with_objective(tmp_path)
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-a.md",
        artifact_paths=["src/app.py"],
        body="plugin sprint outcomes and objective surface coverage visibility are tracked here.",
    )
    _write_detail(
        workspace,
        agi_id,
        filename="delivery-b.md",
        artifact_paths=["tests/test_smoke.py"],
        body="drift escalation early signal with deterministic agile-state ledger and warn streak reset behavior.",
    )

    ledger_path = workspace / ".gran-maestro" / "agile" / "agile-state.json"
    assert not ledger_path.exists()

    proc, payload = _run_drift_check_json(workspace, agi_id)

    assert proc.returncode == 0
    assert payload["warn_streak"] == 0
    assert ledger_path.exists()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert isinstance(ledger, list)
    assert len(ledger) == 1


def test_disabled_graceful(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_drift_config(workspace, enabled=False)
    _write_objective(workspace, agi_id)

    proc = _run_mst(
        workspace,
        "agile",
        "drift-check",
        "--agi-id",
        agi_id,
        "--sprint",
        "1",
    )

    assert proc.returncode == 0
    assert "skipped" in proc.stdout.lower()
