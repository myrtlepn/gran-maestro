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


def _write_recall_config(
    workspace: Path,
    *,
    enabled: bool,
    cooldown_ratio: float = 0.10,
    cap_ratio: float = 0.10,
):
    _write_file(
        workspace / ".gran-maestro" / "config.resolved.json",
        json.dumps(
            {
                "agile": {
                    "recall": {
                        "enabled": enabled,
                        "cooldown_ratio": cooldown_ratio,
                        "cap_ratio": cap_ratio,
                    }
                }
            },
            ensure_ascii=False,
        ),
    )


def _write_objective_done_dods(workspace: Path, agi_id: str, done_count: int):
    objective_path = workspace / ".gran-maestro" / "agile" / agi_id / "objective" / "objective.md"
    lines = ["# Objective", "", "## Project DoD", ""]
    for idx in range(1, done_count + 1):
        dod_id = f"DOD-{idx:03d}"
        lines.append(f"- [x] {dod_id}: done item {idx}")
        lines.append(f"<!-- dod:{dod_id} status:done priority:must -->")
    _write_file(objective_path, "\n".join(lines) + "\n")


def _recall_dir(workspace: Path, agi_id: str) -> Path:
    return workspace / ".gran-maestro" / "agile" / agi_id / "recall"


def _write_pending_manifest(workspace: Path, agi_id: str, manifest: dict):
    _write_file(
        _recall_dir(workspace, agi_id) / "pending-level2-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )


def _write_recall_history(workspace: Path, agi_id: str, rows: list[dict]):
    _write_file(
        _recall_dir(workspace, agi_id) / "history.json",
        json.dumps(rows, ensure_ascii=False, indent=2),
    )


def _run_recall_json(workspace: Path, agi_id: str, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
    proc = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
        "--json",
        *extra,
    )
    payload = json.loads(proc.stdout)
    return proc, payload


def test_recall_on_evidence_fail(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=8)

    proc, payload = _run_recall_json(workspace, agi_id)

    assert proc.returncode == 0, proc.stderr
    assert payload["status"] == "PASS"
    assert Path(payload["manifest_path"]).exists()
    assert payload["agile_plan_patch"]["called"] is True


def test_cooldown_blocks_small(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=8)

    first = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )
    assert first.returncode == 0, first.stderr

    second = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )
    assert second.returncode == 1
    assert "Cooldown active" in second.stdout


def test_cooldown_bypass_hard_fail(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=8)

    first = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )
    assert first.returncode == 0, first.stderr

    proc, payload = _run_recall_json(
        workspace,
        agi_id,
        "--trigger",
        "evidence-hard-fail",
        "--bypass-cooldown",
        "--fingerprint",
        "fp-hard-001",
    )

    assert proc.returncode == 0, proc.stderr
    assert payload["status"] == "PASS"
    assert payload["bypass"]["used"] is True
    assert payload["bypass"]["fingerprint"] == "fp-hard-001"


def test_duplicate_fingerprint_rejected(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=8)

    first = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )
    assert first.returncode == 0, first.stderr

    bypass = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence-hard-fail",
        "--bypass-cooldown",
        "--fingerprint",
        "fp-hard-001",
    )
    assert bypass.returncode == 0, bypass.stderr

    duplicate = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence-hard-fail",
        "--bypass-cooldown",
        "--fingerprint",
        "fp-hard-001",
    )

    assert duplicate.returncode == 1
    assert "fingerprint already bypassed in cooldown" in duplicate.stdout


def test_cap_exceeded(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=30)
    _write_recall_history(
        workspace,
        agi_id,
        [
            {"status": "PASS", "sprint_index": 10},
            {"status": "PASS", "sprint_index": 20},
            {"status": "PASS", "sprint_index": 30},
        ],
    )

    proc = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )

    assert proc.returncode == 1
    assert "Cap exceeded, steering checkpoint required" in proc.stdout


def test_patch_budget(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=12)
    _write_objective_done_dods(workspace, agi_id, done_count=10)
    _write_pending_manifest(
        workspace,
        agi_id,
        {
            "level": 2,
            "reason": "fail",
            "dod_patch": {
                "reorder": [
                    {
                        "dod_id": "DOD-001",
                        "affects_done": True,
                        "count": 5,
                    }
                ]
            },
            "stats": {"done_dod_modifications": 5},
        },
    )

    proc = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )

    assert proc.returncode == 1
    assert "Patch budget exceeded (max 3 or 20%)" in proc.stdout


def test_rollback_token_created(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=8)

    ledger = [
        {
            "timestamp": "2026-04-01T00:00:00Z",
            "warn_level": "WARN",
            "warn_streak": 1,
        }
    ]
    _write_file(
        workspace / ".gran-maestro" / "agile" / "agile-state.json",
        json.dumps(ledger, ensure_ascii=False, indent=2),
    )

    proc, payload = _run_recall_json(workspace, agi_id)

    assert proc.returncode == 0, proc.stderr
    snapshot_path = Path(payload["rollback_token"])
    assert snapshot_path.exists()
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_data == ledger


def test_level2_scope_guard(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=True)
    _set_current_sprint(workspace, agi_id, sprint=9)
    _write_pending_manifest(
        workspace,
        agi_id,
        {
            "level": 2,
            "reason": "drift",
            "objective_refinements": [
                {
                    "field": "jtbd",
                    "before": "I want to improve integration reliability.",
                    "after": "I want to pivot to multi-tenant billing product.",
                    "semantic_change": True,
                }
            ],
        },
    )

    proc = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "drift",
        "--trigger",
        "warn-streak",
    )

    assert proc.returncode == 1
    assert "Level 2 scope exceeded, use Level 3 with user approval" in proc.stdout


def test_disabled_graceful(tmp_path):
    workspace = _make_workspace(tmp_path)
    agi_id = _init_agi(workspace)
    _write_recall_config(workspace, enabled=False)

    proc = _run_mst(
        workspace,
        "agile",
        "recall",
        "--agi-id",
        agi_id,
        "--reason",
        "fail",
        "--trigger",
        "evidence",
    )

    assert proc.returncode == 0
    assert "recall disabled" in proc.stdout.lower()
