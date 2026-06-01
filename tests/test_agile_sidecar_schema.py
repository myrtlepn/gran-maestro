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
        "reference_links",
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

    reference_links = json.loads((objective_dir / "reference-links.json").read_text(encoding="utf-8"))
    assert reference_links["references"] == []
    assert reference_links["unlinked_reference_count"] == 0
    assert reference_links["skip_reasons"][0]["reason"] == "no_explicit_reference_ids_in_objective_context"


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


def test_agile_sidecar_schema_rejects_unlinked_reference_count(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    _write_json(
        objective_dir / "reference-links.json",
        {
            "schema_version": 1,
            "agi_id": "AGI-001",
            "references": [{"ref_id": "REF-001", "status": "missing_reference"}],
            "unlinked_reference_count": 1,
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
    reference_validation = next(
        item for item in payload["validations"] if item["name"] == "reference_links"
    )

    assert proc.returncode == 1
    assert reference_validation["valid"] is False
    assert "unlinked_reference_count must be 0" in reference_validation["errors"]


def test_agile_sidecar_schema_validates_handoff_manifest_paths_and_skips(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    _write_json(
        objective_dir / "handoff-manifest.json",
        {
            "schema_version": 1,
            "agi_id": "AGI-001",
            "context_files": [
                {"path": ".gran-maestro/agile/AGI-001/objective/missing.md", "kind": "objective_context"}
            ],
            "skip_reasons": [
                {"kind": "design", "reason": "not_applicable_or_missing"},
            ],
            "created_at": "2026-06-01T00:00:00Z",
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
    handoff_validation = next(
        item for item in payload["validations"] if item["name"] == "handoff_manifest"
    )

    assert proc.returncode == 1
    assert handoff_validation["valid"] is False
    assert any("path not found" in error for error in handoff_validation["errors"])
    assert "handoff manifest missing objective.md context file" in handoff_validation["errors"]
    assert "handoff manifest missing context or skip reason for references" in handoff_validation["errors"]


def test_agile_sidecar_schema_rejects_empty_handoff_context_and_skip_reason_without_reason(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    objective_dir = workspace / ".gran-maestro" / "agile" / "AGI-001" / "objective"
    _write_json(
        objective_dir / "handoff-manifest.json",
        {
            "schema_version": 1,
            "agi_id": "AGI-001",
            "context_files": [],
            "skip_reasons": [
                {"kind": "design", "reason": "not_applicable_or_missing"},
                {"kind": "references"},
                {"kind": "previous_feedback", "reason": "not_applicable_or_missing"},
            ],
            "created_at": "2026-06-01T00:00:00Z",
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
    handoff_validation = next(
        item for item in payload["validations"] if item["name"] == "handoff_manifest"
    )

    assert proc.returncode == 1
    assert handoff_validation["valid"] is False
    assert "context_files must not be empty" in handoff_validation["errors"]
    assert "skip_reasons item 1 missing reason" in handoff_validation["errors"]


def test_agile_sidecar_schema_uses_agile_session_mst_session_id(tmp_path: Path) -> None:
    workspace = _make_agile_workspace(tmp_path)
    agi_id = "AGI-001"
    mst_session_id = "MST-AGI-001-20260601T000000000Z-testabcd"
    agi_dir = workspace / ".gran-maestro" / "agile" / agi_id
    session_payload = json.loads((agi_dir / "session.json").read_text(encoding="utf-8"))
    session_payload["mst_session_id"] = mst_session_id
    _write_json(agi_dir / "session.json", session_payload)
    _write_json(
        workspace / ".gran-maestro" / "state" / mst_session_id / "snapshot.json",
        {
            "schema_version": 1,
            "mst_session_id": mst_session_id,
            "root_mst_id": agi_id,
            "workflow": {"current_skill": "mst:agile", "current_step": 2, "status": "active"},
            "history": {"last_event_id": "a" * 64},
        },
    )

    proc = _run_mst(workspace, "agile", "sidecar-schema", agi_id, "--validate-existing", "--json")
    payload = json.loads(proc.stdout)

    state_validation = next(item for item in payload["validations"] if item["name"] == "state_snapshot")
    assert payload["mst_session_id"] == mst_session_id
    assert state_validation["path"].endswith(f"/.gran-maestro/state/{mst_session_id}/snapshot.json")
    assert state_validation["valid"] is True


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
        "- **High - placeholder objective와 계약 불명확 사례**: 문제 설명으로만 기록한다.\n"
        "- 반드시 DOD-001 evidence is preserved.\n",
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "agile", "sidecar-build", "AGI-001", "--json")

    assert proc.returncode == 0, proc.stderr
    d3 = json.loads((objective_dir / "d3-findings.json").read_text(encoding="utf-8"))
    assert d3["blocking_count"] == 0
    assert d3["details"][0]["pass"] is True
