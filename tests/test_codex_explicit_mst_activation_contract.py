from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SKILLS = (
    "debug",
    "ideation",
    "discussion",
    "explore",
    "plan",
    "plan-doc",
    "request",
)
EXPLICIT_GATE = "<!-- @include _shared/explicit-invocation-gate.md -->"
SESSION_BOOTSTRAP = "<!-- @include _shared/session-bootstrap.md -->"
DELEGATION_ROUTING = "<!-- @include _shared/delegation-routing.md -->"


def _skill(root: Path, name: str) -> str:
    return (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _description(text: str) -> str:
    match = re.search(r'^description:\s*"([^"]+)"$', text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_root_skill_discovery_is_explicit_only_in_source_and_projection() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for name in ROOT_SKILLS:
            description = _description(_skill(root, name))
            assert f"$mst:{name}" in description, (root, name)
            assert f"/mst:{name}" in description, (root, name)
            assert "명시적으로" in description, (root, name)
            assert "일반 요청에는 자동 활성화하지 않습니다" in description, (root, name)


def test_explicit_gate_is_the_first_executable_contract() -> None:
    forbidden_before_gate = (
        ".gran-maestro/",
        "python3 ",
        "PROJECT_ROOT=",
        "mode.json",
        "counter next",
        "config get",
        "delegation route",
        "Write(",
        "Edit(",
    )
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for name in ROOT_SKILLS:
            text = _skill(root, name)
            gate_index = text.index(EXPLICIT_GATE)
            bootstrap_index = text.index(SESSION_BOOTSTRAP)
            delegation_index = text.index(DELEGATION_ROUTING)
            assert gate_index < bootstrap_index < delegation_index, (root, name)
            prefix = text[:gate_index]
            for token in forbidden_before_gate:
                assert token not in prefix, (root, name, token)

            gate_end = text.index("<!-- @end-include -->", gate_index)
            gate_body = text[gate_index:gate_end]
            assert "도구 호출, 파일 읽기, 상태 생성" in gate_body
            assert "즉시 일반 요청 처리로 반환" in gate_body


def test_bootstrap_precedes_counter_config_mode_and_delegation() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for name in ROOT_SKILLS:
            text = _skill(root, name)
            bootstrap_index = text.index(SESSION_BOOTSTRAP)
            bootstrap_end = text.index("<!-- @end-include -->", bootstrap_index)
            tail = text[bootstrap_end:]
            for token in ("counter next", "config get", "mode.json", "delegation route"):
                if token in text:
                    assert bootstrap_index < text.index(token), (root, name, token)
            assert "MST_BOUND_SUBPROCESS" in text[bootstrap_index:bootstrap_end]
            assert "first protected mutation" in text[bootstrap_index:bootstrap_end]
            assert "counter next" in tail


def test_request_resume_and_plan_debug_ordering_are_explicit() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        request = _skill(root, "request")
        plan = _skill(root, "plan")
        assert "resume root를 mutation 없이 먼저 식별" in request
        assert "session bootstrap --root-type req" in request
        assert "CANONICAL_ROOT_MST_ID`를 요청 ID로 그대로 사용" in request
        assert request.index(SESSION_BOOTSTRAP) < request.index("### Step 0: 아카이브 체크")
        assert plan.index(SESSION_BOOTSTRAP) < plan.index("### Step 0.5: 디버그 의도 감지")
        assert "bootstrap/resolve가 성공한 뒤에만 `mst:debug`를 호출" in plan
        debug_call = plan[plan.index('Skill(skill: "mst:debug"') :]
        assert "MST_PARENT_BINDING" not in debug_call
