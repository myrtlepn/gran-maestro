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


def _write_file(path: Path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_agi(workspace: Path) -> str:
    proc = _run_mst(workspace, "agile", "init", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return payload["agi_id"]


def _set_current_sprint(workspace: Path, agi_id: str, sprint: int):
    proc = _run_mst(
        workspace,
        "agile",
        "update",
        agi_id,
        "--current-sprint",
        str(sprint),
        "--json",
    )
    assert proc.returncode == 0, proc.stderr


def _write_config(
    workspace: Path,
    *,
    recall_enabled: bool = True,
    auto_mode_request: bool = False,
    cooldown_ratio: float = 0.10,
    cap_ratio: float = 0.10,
):
    _write_file(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps(
            {
                "agile": {
                    "recall": {
                        "enabled": recall_enabled,
                        "cooldown_ratio": cooldown_ratio,
                        "cap_ratio": cap_ratio,
                    }
                },
                "auto_mode": {
                    "request": auto_mode_request,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _objective_path(workspace: Path, agi_id: str) -> Path:
    return workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "objective.md"


def _history_dir(workspace: Path, agi_id: str) -> Path:
    return workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "history"


def _recall_dir(workspace: Path, agi_id: str) -> Path:
    return workspace / ".gran-maestro" / "agile" / agi_id / "recall"


def _write_objective(workspace: Path, agi_id: str):
    _write_file(
        _objective_path(workspace, agi_id),
        "\n".join(
            [
                "---",
                "version: 1",
                "last_event_id: EVT-INIT",
                "semantic_hash: hash-init",
                "---",
                "# Objective",
                "",
                "## JTBD",
                "",
                "- When I manage routine work, I want to automate status reporting.",
                "- So I can reduce manual coordination.",
                "",
                "## Project DoD",
                "",
                "- [x] DOD-001: Ship reporting dashboard",
                "<!-- dod:DOD-001 status:done priority:must -->",
                "- [ ] DOD-002: Keep approval audit trail",
                "<!-- dod:DOD-002 status:todo priority:should -->",
                "",
            ]
        )
        + "\n",
    )


def _write_detail(workspace: Path, agi_id: str, dod_id: str, *, status: str = "done", unlocked: bool = False):
    lines = [
        "---",
        f"status: {status}",
    ]
    if unlocked:
        lines.extend(
            [
                "unlock_history:",
                "  - timestamp: 2026-04-01T00:00:00Z",
                "    category: objective_precision_fix",
                "    reason: objective wording precision improved to remove ambiguity in user-visible acceptance",
                "    evidence: objective.diff",
            ]
        )
        if status != "in_progress":
            lines[1] = "status: in_progress"
    lines.extend(
        [
            "evidence:",
            "  plan:",
            "    artifact_paths:",
            "      - src/app.py",
            "    entrypoint_path: src/app.py:main",
            "  runtime:",
            "    integration_smoke_id: smoke-001",
            "    verify_cmd: \"python -m pytest tests/test_smoke.py -q\"",
            "    expected_signal: \"1 passed\"",
            "---",
            f"# {dod_id}",
            "",
        ]
    )
    _write_file(
        workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "details" / f"{dod_id}.md",
        "\n".join(lines),
    )


def _write_level3_manifest(
    workspace: Path,
    agi_id: str,
    *,
    mixed: bool = False,
    touch_done_dod: bool = False,
):
    objective_before = "When I manage routine work, I want to automate status reporting."
    objective_after = (
        "When I redefine hiring operations, I want to orchestrate candidate decision workflows."
        if not mixed
        else "When I manage routine work, I want to automate status reporting with clearer audit wording."
    )
    manifest = {
        "level": 3,
        "reason": "drift",
        "trigger": "jtbd-drift",
        "objective_refinements": [
            {
                "field": "jtbd",
                "change_type": "jtbd_core_redefinition" if not mixed else "precision",
                "before": objective_before,
                "after": objective_after,
                "semantic_change": not mixed,
            }
        ],
        "dod_patch": {
            "reorder": [
                {
                    "dod_id": "DOD-002",
                    "target_index": 1,
                }
            ]
        },
        "affected_dods": ["DOD-001", "DOD-002"] if touch_done_dod else ["DOD-002"],
        "drift_evidence": [
            "Recent sprint output shifted from reporting to approval-heavy workflow changes.",
            "Objective JTBD no longer matches dominant implementation direction.",
        ],
    }
    if mixed:
        manifest["dod_patch"]["reorder"].append({"dod_id": "DOD-001", "target_index": 2})
    if touch_done_dod:
        manifest["dod_patch"]["reorder"].append({"dod_id": "DOD-001", "target_index": 2})
    _write_file(
        _recall_dir(workspace, agi_id) / "pending-level3-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    return manifest


def _write_classify_manifest(workspace: Path, name: str, payload: dict) -> Path:
    path = workspace / name
    _write_file(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def _combined_output(proc: subprocess.CompletedProcess) -> str:
    return f"{proc.stdout}\n{proc.stderr}"


def _approval_payload(stdout: str) -> dict:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"approval payload not found in stdout: {stdout}")


def _run_level3(workspace: Path, agi_id: str, *extra: str) -> subprocess.CompletedProcess:
    return _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--level",
        "3",
        "--reason",
        "drift",
        "--trigger",
        "jtbd-drift",
        *extra,
    )


def test_level3_requires_approval(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    proc = _run_level3(workspace, agi_id)

    assert proc.returncode == 1
    assert "Level 3 requires --approval-ticket (user approval required)" in _combined_output(proc)


def test_level3_objective_version_bump(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    proc = _run_level3(workspace, agi_id, "--approval-ticket", "APRV-001")

    assert proc.returncode == 0, _combined_output(proc)
    content = _objective_path(workspace, agi_id).read_text(encoding="utf-8")
    assert "version: 2" in content
    assert "last_event_id:" in content
    assert "semantic_hash:" in content
    assert "semantic_hash: hash-init" not in content


def test_history_log_append(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    proc = _run_level3(workspace, agi_id, "--approval-ticket", "APRV-001")

    assert proc.returncode == 0, _combined_output(proc)
    history_files = sorted(_history_dir(workspace, agi_id).glob("*_L3_*.json"))
    assert len(history_files) == 1
    payload = json.loads(history_files[0].read_text(encoding="utf-8"))
    assert payload["before_hash"]
    assert payload["after_hash"]
    assert payload["diff"]
    assert payload["affected_dods"]
    assert payload["drift_evidence"]


def test_history_append_only(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    first = _run_level3(workspace, agi_id, "--approval-ticket", "APRV-001")
    assert first.returncode == 0, _combined_output(first)
    history_files = sorted(_history_dir(workspace, agi_id).glob("*_L3_*.json"))
    assert len(history_files) == 1
    first_path = history_files[0]
    first_content = first_path.read_text(encoding="utf-8")

    _set_current_sprint(workspace, agi_id, sprint=12)
    _write_level3_manifest(workspace, agi_id, mixed=True)
    second = _run_level3(workspace, agi_id, "--approval-ticket", "APRV-002")
    assert second.returncode == 0, _combined_output(second)

    history_files = sorted(_history_dir(workspace, agi_id).glob("*_L3_*.json"))
    assert len(history_files) == 2
    assert first_path.read_text(encoding="utf-8") == first_content


def test_auto_mode_waits_for_approval(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace, auto_mode_request=True)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    proc = _run_level3(workspace, agi_id)

    assert proc.returncode == 1
    assert "USER APPROVAL REQUIRED" in proc.stdout
    payload = _approval_payload(proc.stdout)
    assert payload["approval_required"] is True


def test_approval_payload_schema(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_config(workspace)
    _set_current_sprint(workspace, agi_id, sprint=8)
    _write_objective(workspace, agi_id)
    _write_detail(workspace, agi_id, "DOD-001", unlocked=True)
    _write_level3_manifest(workspace, agi_id)

    proc = _run_level3(workspace, agi_id)

    assert proc.returncode == 1
    payload = _approval_payload(proc.stdout)
    for key in ("before_hash", "after_hash", "diff", "affected_dods", "drift_evidence"):
        assert key in payload


def test_level3_cooldown_double(tmp_path):
    workspace = _make_workspace(tmp_path)
    manifest_path = _write_classify_manifest(
        workspace,
        "mixed-level2.json",
        {
            "level": 2,
            "project_size": 30,
            "level2_cooldown": 2,
            "objective_refinements": [
                {
                    "before": "Keep reporting workflow aligned.",
                    "after": "Keep reporting workflow aligned with clearer wording.",
                    "semantic_change": False,
                }
            ],
        },
    )

    proc = _run_mst(workspace, "agile", "classify-change", str(manifest_path))

    assert proc.returncode == 0, _combined_output(proc)
    assert "cooldown: 4" in proc.stdout


def test_classify_level2(tmp_path):
    workspace = _make_workspace(tmp_path)
    manifest_path = _write_classify_manifest(
        workspace,
        "classify-level2.json",
        {
            "objective_refinements": [
                {
                    "before": "Keep reporting workflow aligned.",
                    "after": "Keep reporting workflow aligned with clearer wording.",
                    "semantic_change": False,
                }
            ],
            "dod_patch": {
                "reorder": [
                    {"dod_id": "DOD-001", "target_index": 2},
                    {"dod_id": "DOD-002", "target_index": 1},
                ]
            },
        },
    )

    proc = _run_mst(workspace, "agile", "classify-change", str(manifest_path))

    assert proc.returncode == 0, _combined_output(proc)
    assert "Level 2" in proc.stdout
    confidence_line = next(line for line in proc.stdout.splitlines() if line.startswith("confidence:"))
    confidence = float(confidence_line.split(":", 1)[1].strip())
    assert confidence >= 0.7
    assert "summary:" in proc.stdout


def test_classify_level3(tmp_path):
    workspace = _make_workspace(tmp_path)
    manifest_path = _write_classify_manifest(
        workspace,
        "classify-level3.json",
        {
            "objective_refinements": [
                {
                    "before": "When I manage routine work, I want to automate status reporting.",
                    "after": "When I redefine hiring operations, I want to orchestrate candidate decision workflows.",
                    "semantic_change": True,
                }
            ],
            "drift_evidence": ["JTBD 핵심 단어가 보고/reporting에서 채용/hiring으로 바뀌었다."],
        },
    )

    proc = _run_mst(workspace, "agile", "classify-change", str(manifest_path))

    assert proc.returncode == 0, _combined_output(proc)
    assert "Level 3" in proc.stdout
    confidence_line = next(line for line in proc.stdout.splitlines() if line.startswith("confidence:"))
    confidence = float(confidence_line.split(":", 1)[1].strip())
    assert confidence >= 0.7
