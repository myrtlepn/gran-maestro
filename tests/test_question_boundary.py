from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hooks.lib import pre_tool_use_fast


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-REQ-851-20260510T104009000Z-a1b2c3d4"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".gran-maestro" / "tmp").mkdir(parents=True)
    return project


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "MST_SESSION_ID": SID,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if extra:
        env.update(extra)
    return env


def _run(project: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=project,
        env=_env(env_extra),
        text=True,
        capture_output=True,
        check=False,
    )


def _payload_file(project: Path, payload: dict | None = None) -> Path:
    payload = payload or {
        "question": "이 요청을 objective 생성으로 진행할까요?",
        "options": [
            {
                "label": "A. objective 생성",
                "description": "[장점] agile 흐름 유지 [단점] 구현은 아직 시작하지 않음 [적합] 목표 정제",
            },
            {
                "label": "B. 다른 의도",
                "description": "[장점] 라우팅 오류 방지 [단점] 추가 설명 필요 [적합] 메타 질문",
            },
        ],
    }
    path = project / "question.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _state(project: Path) -> dict:
    path = project / ".gran-maestro" / "tmp" / f"mst-state-{SID}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare(
    project: Path,
    host: str,
    *,
    payload: dict | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict:
    result = _run(
        project,
        "question",
        "prepare",
        "--host",
        host,
        "--skill",
        "mst:agile-plan",
        "--step",
        "0.5.2",
        "--resume-skill",
        "mst:agile-plan",
        "--resume-args",
        "--resume AGI-001",
        "--payload-file",
        str(_payload_file(project, payload)),
        "--json",
        env_extra=env_extra,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def _multiple_questions() -> dict:
    return {
        "questions": [
            {
                "id": "scope",
                "header": "범위",
                "prompt": "어느 범위로 진행할까요?",
                "options": [
                    {"label": "핵심만", "description": "필수 동작만 반영합니다."},
                    {"label": "문서도", "description": "문서까지 정리합니다."},
                ],
            },
            {
                "id": "delivery",
                "header": "완료",
                "question": "어떤 상태로 마무리할까요?",
                "options": [
                    {"label": "커밋까지", "description": "로컬 커밋을 남깁니다."},
                    {"label": "검증만", "description": "테스트 결과만 보고합니다."},
                ],
            },
        ]
    }


def _codex_caller_context(*, execution_mode: str, agent_role: str) -> dict[str, str]:
    return {
        "MST_CONTEXT_JSON": json.dumps(
            {
                "mst_session_id": SID,
                "execution_mode": execution_mode,
                "agent_role": agent_role,
                "available_tools": ["request_user_input"],
            },
            ensure_ascii=False,
        )
    }


def test_codex_prepare_creates_pending_artifact_and_user_wait_state(tmp_path: Path) -> None:
    project = _project(tmp_path)

    prepared = _prepare(project, "codex")

    assert prepared["mode"] == "pending_artifact"
    assert prepared["question_id"].startswith("Q-")
    assert "/mst:resume --answer" in prepared["resume_command"]
    artifact = Path(prepared["path"])
    assert artifact.is_file()
    artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact_payload["status"] == "pending"
    assert artifact_payload["payload_hash"] == prepared["payload_hash"]
    assert artifact_payload["host_context"]["host"] == "codex"

    state = _state(project)
    assert state["awaiting_user_input"] is True
    assert state["question_id"] == prepared["question_id"]
    assert state["expected_question_hash"] == prepared["payload_hash"]
    assert state["user_input"]["resume_skill"] == "mst:agile-plan"


def test_root_plan_codex_capability_maps_native_request_user_input_payload(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = _multiple_questions()

    prepared = _prepare(
        project,
        "codex",
        payload=source,
        env_extra=_codex_caller_context(execution_mode="plan", agent_role="root"),
    )

    assert prepared["mode"] == "codex_tool"
    assert prepared["tool"] == "request_user_input"
    expected_questions = [dict(question) for question in source["questions"]]
    expected_questions[0]["question"] = expected_questions[0].pop("prompt")
    assert prepared["payload"] == {"questions": expected_questions}


@pytest.mark.parametrize(
    ("host", "execution_mode", "agent_role"),
    [
        pytest.param("codex", "default", "root", id="default"),
        pytest.param("codex", "plan", "subagent", id="subagent"),
        pytest.param("headless", "plan", "root", id="headless"),
    ],
)
def test_non_root_plan_lanes_render_complete_nested_fallback(
    tmp_path: Path,
    host: str,
    execution_mode: str,
    agent_role: str,
) -> None:
    project = _project(tmp_path)
    prepared = _prepare(
        project,
        host,
        payload=_multiple_questions(),
        env_extra=_codex_caller_context(execution_mode=execution_mode, agent_role=agent_role),
    )

    assert prepared["mode"] == "pending_artifact"
    message = prepared["user_message"]
    first_question = message.index("1. 어느 범위로 진행할까요?")
    second_question = message.index("2. 어떤 상태로 마무리할까요?")
    first_block = message[first_question:second_question]
    second_block = message[second_question:]

    assert "핵심만: 필수 동작만 반영합니다." in first_block
    assert "문서도: 문서까지 정리합니다." in first_block
    assert "커밋까지" not in first_block
    assert "커밋까지: 로컬 커밋을 남깁니다." in second_block
    assert "검증만: 테스트 결과만 보고합니다." in second_block
    assert prepared["resume_command"] == f"/mst:resume --answer {prepared['question_id']}"
    assert message.count(prepared["resume_command"]) == 1


def test_prepared_claude_question_is_allowed_but_hash_mismatch_blocks(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    set_state = _run(
        project,
        "state",
        "set-workflow",
        "--active",
        "true",
        "--skill",
        "mst:agile-plan",
        "--auto",
        "false",
    )
    assert set_state.returncode == 0, set_state.stderr
    prepared = _prepare(project, "claude")
    assert prepared["mode"] == "claude_tool"

    allowed = pre_tool_use_fast.hardcoded_core_check(
        project,
        home,
        {
            "mst_session_id": SID,
            "tool_name": "AskUserQuestion",
            "tool_input": prepared["payload"],
        },
    )
    assert allowed == 0

    blocked = pre_tool_use_fast.hardcoded_core_check(
        project,
        home,
        {
            "mst_session_id": SID,
            "tool_name": "AskUserQuestion",
            "tool_input": {"question": "다른 질문입니다", "options": ["A", "B"]},
        },
    )
    assert blocked == 2
    assert "MST-ASK-USER-QUESTION-BLOCK" in capsys.readouterr().err


def test_unprepared_question_still_blocks_when_workflow_active(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    set_state = _run(
        project,
        "state",
        "set-workflow",
        "--active",
        "true",
        "--skill",
        "mst:agile-plan",
        "--auto",
        "false",
    )
    assert set_state.returncode == 0, set_state.stderr

    result = pre_tool_use_fast.hardcoded_core_check(
        project,
        home,
        {
            "mst_session_id": SID,
            "tool_name": "AskUserQuestion",
            "tool_input": {"question": "Continue?", "options": ["A", "B"]},
        },
    )

    assert result == 2
    assert "MST-ASK-USER-QUESTION-BLOCK" in capsys.readouterr().err


def test_question_answer_and_consume_clear_user_wait_state(tmp_path: Path) -> None:
    project = _project(tmp_path)
    prepared = _prepare(project, "codex")

    answer = _run(
        project,
        "question",
        "answer",
        prepared["question_id"],
        "--answer",
        "A",
        "--json",
    )
    assert answer.returncode == 0, answer.stderr + answer.stdout
    assert json.loads(answer.stdout)["status"] == "answered"

    consumed = _run(project, "question", "consume", prepared["question_id"], "--json")
    assert consumed.returncode == 0, consumed.stderr + consumed.stdout
    payload = json.loads(consumed.stdout)
    assert payload["status"] == "consumed"
    assert payload["answer"] == "A"

    state = _state(project)
    assert state["awaiting_user_input"] is False
    assert state["question_id"] == ""


def test_answer_then_consume_queues_stored_resume_target_once(tmp_path: Path) -> None:
    project = _project(tmp_path)
    prepared = _prepare(project, "codex")

    answer = _run(
        project,
        "question",
        "answer",
        prepared["question_id"],
        "--answer",
        "A",
        "--json",
    )
    assert answer.returncode == 0, answer.stderr + answer.stdout
    assert json.loads(answer.stdout)["status"] == "answered"

    consumed = _run(project, "question", "consume", prepared["question_id"], "--json")
    assert consumed.returncode == 0, consumed.stderr + consumed.stdout
    assert json.loads(consumed.stdout)["status"] == "consumed"

    queued = _run(project, "queue", "list", "--status", "queued", "--json")
    assert queued.returncode == 0, queued.stderr + queued.stdout
    actions = json.loads(queued.stdout)
    assert len(actions) == 1
    assert actions[0]["skill"] == "mst:agile-plan"
    assert actions[0]["args"] == "--resume AGI-001"
