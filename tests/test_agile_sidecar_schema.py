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


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_agile_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    agi_dir = workspace / ".gran-maestro" / "agile" / "AGI-001"
    _write_json(
        agi_dir / "session.json",
        {"id": "AGI-001", "agi_id": "AGI-001", "status": "active"},
    )
    (agi_dir / "objective").mkdir(parents=True, exist_ok=True)
    return workspace


def test_agile_sidecar_schema_outputs_canonical_contract(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)

    proc = _run_mst(workspace, "agile", "sidecar-schema", "AGI-001", "--json")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == 1
    assert payload["agi_id"] == "AGI-001"
    sidecars = {item["name"]: item for item in payload["sidecars"]}
    assert "objective_anchor_manifest" in sidecars
    assert "handoff_manifest" in sidecars
    assert "finding_trace_manifest" in sidecars
    assert "state_snapshot" in sidecars
    assert sidecars["objective_anchor_manifest"]["required_fields"] == [
        "id",
        "source_file",
        "text",
        "kind",
        "grade",
        "domain_slug",
        "dod_refs",
    ]
    for sidecar in sidecars.values():
        assert sidecar["producer"]
        assert sidecar["consumer"]
        assert sidecar["missing_behavior"]
        assert sidecar["invalid_behavior"]


def test_agile_sidecar_schema_validation_fails_missing_required_sidecars(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)

    proc = _run_mst(
        workspace,
        "agile",
        "sidecar-schema",
        "AGI-001",
        "--mst-session-id",
        "MST-AGI-001-test",
        "--validate-existing",
        "--json",
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["valid"] is False
    assert any("objective_anchor_manifest" in error for error in payload["errors"])
    assert any(item["name"] == "state_snapshot" for item in payload["validations"])


def test_agile_sidecar_schema_validation_accepts_valid_anchor_manifest(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    _write_json(
        workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective" / "objective.ids.json",
        [
            {
                "id": "OAC-001",
                "source_file": "details/domain.md",
                "text": "must preserve traceability",
                "kind": "detail",
                "grade": "MUST",
                "domain_slug": "domain",
                "dod_refs": ["DOD-001"],
            }
        ],
    )

    proc = _run_mst(
        workspace,
        "agile",
        "sidecar-schema",
        "AGI-001",
        "--validate-existing",
        "--json",
    )

    payload = json.loads(proc.stdout)
    anchor_validation = next(
        item for item in payload["validations"] if item["name"] == "objective_anchor_manifest"
    )
    assert anchor_validation["valid"] is True
    assert any("handoff_manifest" in error for error in payload["errors"])


def test_agile_sidecar_build_writes_required_objective_sidecars(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    (objective_dir / "objective.md").write_text(
        "# Objective\n\n"
        "- [ ] DOD-001\n"
        "<!-- dod:DOD-001 status:todo priority:must -->\n",
        encoding="utf-8",
    )
    details_dir = objective_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    (details_dir / "review-evidence-and-gates.md").write_text(
        "<!-- source-mapping: original=objective.md sections=[\"Objective\"] -->\n"
        "# Review Evidence and Gates\n\n"
        "> 관련 DoD: DOD-001\n\n"
        "- **F-INTEGRATION-001 critical trace_gap**: DOD-001 must be traceable.\n"
        "- 반드시 DOD-001 evidence is preserved.\n",
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "agile", "sidecar-build", "AGI-001", "--json")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["valid"] is True
    written_names = {item["name"] for item in payload["written"]}
    assert {
        "objective_anchor_manifest",
        "handoff_manifest",
        "review_findings",
        "finding_trace_manifest",
        "section_review_inventory",
        "d3_detail_results",
    } <= written_names

    validate_proc = _run_mst(
        workspace,
        "agile",
        "sidecar-schema",
        "AGI-001",
        "--validate-existing",
        "--json",
    )
    validation = json.loads(validate_proc.stdout)
    assert validate_proc.returncode == 1
    assert validation["valid"] is False
    assert validation["errors"] == [
        "state_snapshot: cannot validate unresolved path: .gran-maestro/state/{mst_session_id}/snapshot.json"
    ]

    finding_trace = json.loads((objective_dir / "finding-trace.json").read_text(encoding="utf-8"))
    assert finding_trace["unmapped_major_or_higher_count"] == 0
    assert finding_trace["findings"][0]["trace_status"] == "mapped"


def test_agile_sidecar_schema_rejects_nonzero_blocking_counts(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    _write_json(
        objective_dir / "section-review-inventory.json",
        {
            "schema_version": 1,
            "agi_id": "AGI-001",
            "sections": [],
            "unreviewed_required_count": 1,
        },
    )

    proc = _run_mst(
        workspace,
        "agile",
        "sidecar-schema",
        "AGI-001",
        "--validate-existing",
        "--json",
    )
    payload = json.loads(proc.stdout)
    section_validation = next(
        item for item in payload["validations"] if item["name"] == "section_review_inventory"
    )
    assert proc.returncode == 1
    assert section_validation["valid"] is False
    assert "unreviewed_required_count must be 0" in section_validation["errors"]


def test_agile_sidecar_build_d3_does_not_flag_jtbd_or_ambiguity_topic(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    details_dir = objective_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    (details_dir / "downstream-handoff-contracts.md").write_text(
        "<!-- source-mapping: original=objective.md sections=[\"JTBD\"] -->\n"
        "# Downstream Handoff Contracts\n\n"
        "> 관련 DoD: DOD-001\n\n"
        "- **결정**: JTBD 질문과 모호성 해소 질문은 분리한다.\n"
        "- 반드시 DOD-001 evidence is preserved.\n",
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "agile", "sidecar-build", "AGI-001", "--json")

    assert proc.returncode == 0, proc.stderr
    d3 = json.loads((objective_dir / "d3-findings.json").read_text(encoding="utf-8"))
    assert d3["blocking_count"] == 0
    assert d3["details"][0]["pass"] is True
