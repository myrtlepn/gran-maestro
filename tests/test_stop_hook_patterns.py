"""REQ-629: stop-hook 자발 정지 문구 차단 검증.

hooks/mst-stop-hook.sh를 실제 bash 서브프로세스로 호출하여
신규 11개 패턴 block + 기존 6개 패턴 block + 정당 정지 사유 allow 보존을 검증.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
STOP_GATE_REASONS = REPO_ROOT / "hooks" / "stop-agile-gate-reasons.json"

NEW_PATTERNS = [
    "자연스러운 단락을 둡니다",
    "여기서 단락을 두고",
    "여기서 끊고 다음 턴에",
    "여기서 마무리합시다",
    "여기서 정지합니다",
    "수동 재호출이 필요합니다",
    "다시 호출해주세요",
    "세션 교체 후 이어서",
    "자연스럽게 멈추고",
    "자연스럽게 쉬고",
    "자연스럽게 끊고",
]

EXISTING_PATTERNS = [
    "계속할까요?",
    "진행할까요?",
    "멈추고 잠시",
    "요약하고 계속 진행",
    "정리하고 계속",
    "컨텍스트가 길어지고 있으므로",
]


def _run_hook(tmp_path: Path, last_msg: str, agile_auto_mode: bool = True,
              workflow_active: bool = True, agile_loop_active: bool = True,
              current_skill: str = "mst:agile", extra_state: Optional[dict] = None,
              active_agile_session: bool = False):
    """hook을 별도 프로세스로 실행. 임시 PROJECT_ROOT를 사용해 격리."""
    if not HOOK.is_file():
        pytest.skip(f"hook not found: {HOOK}")
    if shutil.which("bash") is None:
        pytest.skip("bash is required for stop-hook subprocess tests")
    if shutil.which("python3") is None:
        pytest.skip("python3 is required by mst-stop-hook.sh")

    project_root = tmp_path
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    (project_root / "hooks").mkdir(parents=True, exist_ok=True)
    (project_root / "hooks" / "stop-agile-gate-reasons.json").write_text(
        STOP_GATE_REASONS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # .git 파일 생성 (hook의 resolve_project_root가 git 저장소로 인식)
    (project_root / ".git").write_text("gitdir: .\n")

    if active_agile_session:
        session_dir = project_root / ".gran-maestro" / "agile" / "AGI-TEST"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps({
                "status": "active",
                "updated_at": "2026-04-20T00:00:00Z",
            }),
            encoding="utf-8",
        )

    ppid = "99999"
    state = {
        "workflow_active": workflow_active,
        "current_skill": current_skill,
        "active_req": "",
        "iteration": 0,
        "agile_loop_active": agile_loop_active,
    }
    if extra_state:
        state.update(extra_state)
    state_file = project_root / ".gran-maestro" / "tmp" / f"mst-state-{ppid}.json"
    state_file.write_text(json.dumps(state))

    # hooks 디렉토리도 프로젝트 루트에 복사 — resolve_project_root가 찾기 위함
    # 대신 실제 hook 파일을 그대로 사용하되 PROJECT_ROOT만 tmp_path로 강제
    # resolve_project_root는 .gran-maestro + .git 조합으로 찾으므로 위의 mkdir+write로 OK.

    stdin_payload = json.dumps({
        "last_assistant_message": last_msg,
        "agile_auto_mode": agile_auto_mode,
        "stop_hook_active": False,
    })

    # PPID를 PPID env로 주입할 수 없으므로 hook을 bash로 실행하되 state_file 이름을 맞춘다.
    # hook은 $PPID를 참조하므로 python subprocess가 부모가 되어 PPID는 python pid.
    # 대신 wrapper 스크립트를 사용해 명시적 PPID 주입.
    # 간단히: PPID를 현재 python pid로 삼고, state 파일명도 그에 맞춘다.
    import os
    actual_ppid = os.getpid()
    state_file_correct = project_root / ".gran-maestro" / "tmp" / f"mst-state-{actual_ppid}.json"
    state_file.rename(state_file_correct)

    result = subprocess.run(
        ["bash", str(HOOK)],
        input=stdin_payload,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    return result


@pytest.mark.parametrize("msg", NEW_PATTERNS)
def test_new_patterns_blocked(tmp_path, msg):
    result = _run_hook(tmp_path, msg)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"
    assert '"decision"' in result.stdout and '"block"' in result.stdout, (
        f"Expected block JSON for {msg!r}, got: {result.stdout!r}"
    )


@pytest.mark.parametrize("msg", EXISTING_PATTERNS)
def test_existing_patterns_still_blocked(tmp_path, msg):
    result = _run_hook(tmp_path, msg)
    assert '"block"' in result.stdout, (
        f"Regression: existing pattern {msg!r} no longer blocked"
    )


def test_self_pause_rationalization_regression(tmp_path):
    msg = "Sprint 3 boundary에서 stash/squash 부담이 크니 paused로 전환하겠습니다"
    result = _run_hook(tmp_path, msg)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "SELF-PAUSE-DETECTED" in payload["reason"]


def test_handoff_framing_blocked(tmp_path):
    """REQ-686 AC-006/AC-T05: Step 3 handoff framing 차단."""
    msg = (
        "스티어링 체크포인트는 사용자 검토에 자연스러운 지점이며 "
        "이후 Sprint 4는 새 세션에서 --resume으로 재개하는 것이 권장됩니다"
    )
    result = _run_hook(tmp_path, msg)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "SELF-PAUSE-DETECTED" in payload["reason"]


def test_legitimate_stop_reason_unrecoverable_allowed(tmp_path):
    msg = ("[MST stop_intent reason=unrecoverable_external_failure] "
           "API retry 3회 실패로 중단합니다.")
    result = _run_hook(tmp_path, msg)
    assert '"block"' not in result.stdout, (
        f"False positive: legitimate unrecoverable_external_failure got blocked. stdout={result.stdout!r}"
    )


def test_legitimate_stop_reason_user_judgment_allowed(tmp_path):
    msg = ("[MST stop_intent reason=fatal_user_judgment_required] "
           "사용자 결정이 필요한 상황입니다. 어떻게 진행할까요?")
    result = _run_hook(tmp_path, msg)
    assert '"block"' not in result.stdout, (
        f"False positive: legitimate fatal_user_judgment_required got blocked. stdout={result.stdout!r}"
    )


def test_agile_allow_marker_whitelist_regression(tmp_path):
    msg = (
        "[스티어링 체크포인트]\n"
        '{"tool_name":"AskUserQuestion","question":"Objective 방향 선택","options":["approve","adjust"]}'
    )
    result = _run_hook(tmp_path, msg, active_agile_session=True)
    assert result.returncode == 0, f"hook crashed: {result.stderr}"
    assert '"block"' not in result.stdout, (
        f"Regression: whitelisted agile marker got blocked. stdout={result.stdout!r}"
    )

    audit_path = tmp_path / ".gran-maestro" / "agile" / "AGI-TEST" / "stop-audit.ndjson"
    assert audit_path.is_file(), "Expected allowed whitelist decision to be audited"
    audit_entry = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert audit_entry["classification"] == "allowed"
    assert audit_entry["outcome"] == "allow"
    assert audit_entry["block_reason"] == "agile_allow_pattern_whitelisted"


def test_stop_hook_active_pass_through(tmp_path):
    # stop_hook_active=true면 재귀 방지 위해 pass_through
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").write_text("gitdir: .\n")
    stdin_payload = json.dumps({
        "last_assistant_message": "컨텍스트가 길어 여기서 끊겠습니다",
        "agile_auto_mode": True,
        "stop_hook_active": True,
    })
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=stdin_payload,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert '"block"' not in result.stdout, (
        f"stop_hook_active=true should not block. stdout={result.stdout!r}"
    )


def test_workflow_inactive_pass_through(tmp_path):
    # workflow_active=false + agile_loop_active=false이면 pass_through
    result = _run_hook(
        tmp_path,
        "자연스러운 단락을 둡니다",
        workflow_active=False,
        agile_loop_active=False,
    )
    assert '"block"' not in result.stdout


def test_agile_skill_visibility_regression():
    """T02 Anti-Rationalization 신규 항목 존재 확인 (AC-004 회귀)."""
    skill_path = REPO_ROOT / "skills" / "agile" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    assert "자연스러운 단락" in content, \
        "T02 regression: Anti-Rationalization 항목이 SKILL.md에 없음"
    assert "stop hook 미설치" in content, \
        "T02 regression: hook 파일 검증 지시가 SKILL.md에 없음"
    # 기존 NO-SELF-MOTIVATED-PAUSE도 유지
    assert "NO-SELF-MOTIVATED-PAUSE" in content, \
        "T02 regression: 기존 NO-SELF-MOTIVATED-PAUSE 규칙이 제거됨"
