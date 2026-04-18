from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGILE_SKILL_MD = PROJECT_ROOT / "skills" / "agile" / "SKILL.md"


def _skill_text() -> str:
    return AGILE_SKILL_MD.read_text(encoding="utf-8")


def test_dispatch_d_uses_wrapper():
    text = _skill_text()

    assert "MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model claude default" in text
    assert "python3 {PLUGIN_ROOT}/scripts/mst.py run" in text
    assert '--task-id "{AGI_ID}-S{NN}"' in text
    assert "--provider claude" in text
    assert '--model "$MODEL"' in text
    assert '--log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/"' in text
    assert '-- claude -p "$(cat sprint-prompt.md)" --model "$MODEL" --permission-mode bypassPermissions' in text


def test_dispatch_d_exit_handling_preserved():
    text = _skill_text()

    assert "4. 종료 신호 수신:" in text
    assert "claude` 프로세스 exit code를 확인" in text
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
