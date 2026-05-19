from pathlib import Path
import json

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGILE_SKILL_MD = PROJECT_ROOT / "skills" / "agile" / "SKILL.md"
DISPOSITION_JSON = PROJECT_ROOT / ".gran-maestro" / "agile" / "AGI-040" / "sprints" / "S02" / "dod-002-disposition.json"
DISPOSITION_SKIP_REASON = (
    "requires local workflow evidence: "
    ".gran-maestro/agile/AGI-040/sprints/S02/dod-002-disposition.json "
    "is ignored and may be absent in clean checkouts"
)


def _skill_text() -> str:
    return AGILE_SKILL_MD.read_text(encoding="utf-8")


def _disposition_rows() -> dict[str, dict]:
    if not DISPOSITION_JSON.exists():
        pytest.skip(DISPOSITION_SKIP_REASON)
    data = json.loads(DISPOSITION_JSON.read_text(encoding="utf-8"))
    return {row["stable_id"]: row for row in data["rows"]}


def test_dispatch_d_uses_managed_claude_delegation():
    text = _skill_text()
    forbidden_print_mode = " ".join(("claude", "-p"))

    assert "MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model claude default" in text
    assert 'Skill(skill: "mst:claude", args: "--prompt-file sprint-prompt.md --dir {PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/ --trace {AGI_ID}/S{NN}/dispatch")' in text
    assert "python3 {PLUGIN_ROOT}/scripts/mst.py run" in text
    assert '--task-id "{AGI_ID}-S{NN}"' in text
    assert "--provider claude" in text
    assert '--model "$MODEL"' in text
    assert '--log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/"' in text
    assert "prompt source: `sprint-prompt.md`" in text
    assert "cwd/worktree: `{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/`" in text
    assert "running log tee / trace path / session metadata / output-failure contract / exit code propagation" in text
    assert forbidden_print_mode not in text


def test_dispatch_d_exit_handling_preserved():
    text = _skill_text()

    assert "4. 종료 신호 수신:" in text
    assert "Claude provider exit code를 확인" in text
    assert "dispatch-result.json" in text
    assert "실패 조건: `exit_code != 0` 또는 `dispatch-result.json` 미생성." in text
    assert (
        "python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} --status failed --summary "
        "\"{failure_reason}\""
    ) in text


def test_inline_marker_directive_present():
    text = _skill_text()

    assert "**추가: inline 경로 경량 추적 마커 (MANDATORY)**" in text
    assert "{PROJECT_ROOT}/.gran-maestro/run/{AGI_ID}-S{NN}.json" in text
    assert '"task_id": "{AGI_ID}-S{NN}"' in text
    assert '"phase": "running"' in text
    assert '"inline": true' in text
    assert "`terminated_at`, `exit_code`, `last_heartbeat`" in text
    assert "inline 경로는 `dispatch-result.json`을 **생성하지 않는다** (ADR-007 하위 호환 유지)." in text


def test_dod002_disposition_covers_target_rows():
    rows = _disposition_rows()

    expected_ids = {
        "DOD001-P010",
        "DOD001-P053",
        "DOD001-P054",
        "DOD001-P062",
        "DOD001-P063",
        "DOD001-P064",
        "DOD001-P067",
        "DOD001-P068",
        "DOD001-P069",
        "DOD001-P070",
        "DOD001-P108",
        "DOD001-S004",
        "DOD001-S009",
    }

    assert set(rows) == expected_ids
    for row in rows.values():
        assert row["disposition"] in {
            "remove_runtime",
            "rewrite_guidance_to_new_contract",
            "temporary_exception",
            "reclassify_nonruntime",
        }
        assert row["reason"]
        assert row["replacement_contract"]
        assert row["verification_status"]


def test_dod002_continuation_and_agile_rows_use_expected_contracts():
    rows = _disposition_rows()

    for stable_id in ("DOD001-P053", "DOD001-P054"):
        row = rows[stable_id]
        assert row["disposition"] == "temporary_exception"
        assert row["reason"] == "continuation_exception_until_lifecycle_runner"
        assert row["expiry_dod"] == "DOD-003-or-lifecycle-runner"
        assert row["allowed_active_state"] == "active"
        assert row["allowed_runtime_boundary"] == "plugin_canonical"

    agile_row = rows["DOD001-P108"]
    assert agile_row["disposition"] == "rewrite_guidance_to_new_contract"
    assert "mst:claude" in agile_row["replacement_contract"]
    assert "lifecycle contract preserved" in agile_row["verification_status"]
