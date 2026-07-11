from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
INCLUDE_TARGET = "_shared/delegation-routing.md"
INCLUDE_MARKER = f"<!-- @include {INCLUDE_TARGET} -->"
END_MARKER = "<!-- @end-include -->"

# These skills directly choose or launch Codex/Claude providers.  Keep this
# list explicit so adding another dispatch surface requires an intentional
# contract decision instead of silently bypassing native-first routing.
PROVIDER_DISPATCH_SKILLS = (
    "codex",
    "claude",
    "approve",
    "review",
    "agile",
    "request",
    "ideation",
    "discussion",
    "debug",
    "explore",
    "plan",
    "plan-doc",
    "agile-plan",
    "feedback",
)

ACTIVE_SAME_PROVIDER_CLI_RE = re.compile(
    r"(?:command:\s*['\"][^\n]*(?:codex exec|--provider claude)|"
    r"^\s*(?:--\s+codex exec|codex exec|claude\s+--print)|"
    r"^\s*/mst:claude\s+--prompt-file)",
    re.MULTILINE,
)


def _skill_text(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def _include_body(content: str) -> str:
    pattern = re.compile(
        rf"{re.escape(INCLUDE_MARKER)}\n(.*?){re.escape(END_MARKER)}",
        re.DOTALL,
    )
    match = pattern.search(content)
    assert match is not None, f"missing {INCLUDE_TARGET} include"
    return match.group(1).rstrip("\n")


def test_shared_route_contract_is_executable_and_fail_closed() -> None:
    shared = (SKILLS_DIR / "_shared" / "delegation-routing.md").read_text(
        encoding="utf-8"
    )

    required_tokens = (
        "mst.py host context --json",
        "mst.py delegation route",
        "route=native_candidate",
        "route=external",
        "route=blocked",
        "phase=reconciling",
        "collaboration.spawn_agent",
        "collaboration.wait_agent",
        "Task(...)",
        "Agent(...)",
        "delegation start",
        "delegation claim-spawn",
        "delegation acknowledge",
        "delegation attach",
        "delegation heartbeat",
        "delegation complete",
        "spawn-status=definitive_not_created",
        "DELEGATION BOUNDARY (MANDATORY)",
    )
    for token in required_tokens:
        assert token in shared, f"shared delegation contract is missing {token!r}"

    assert "`route=external`: 이 경우에만" in shared
    assert "nested `/mst:claude`/`/mst:codex`" in shared
    assert "do not delegate or spawn another provider agent" in shared
    assert "즉시 fail closed" in shared
    assert "spawn_allowed=true" in shared
    assert "claim exact replay는 bearer token/파일을 다시 발급하지 않는다" in shared
    assert '--claim-token-file "{claim_token_file}"' in shared
    assert "atomic replace" in shared


def test_every_provider_dispatch_skill_uses_canonical_include_before_execution() -> None:
    shared = (SKILLS_DIR / "_shared" / "delegation-routing.md").read_text(
        encoding="utf-8"
    ).rstrip("\n")

    for name in PROVIDER_DISPATCH_SKILLS:
        content = _skill_text(name)
        assert content.count(INCLUDE_MARKER) == 1, name
        assert _include_body(content) == shared, name

        include_index = content.index(INCLUDE_MARKER)
        protocol_index = content.index("## 실행 프로토콜")
        assert protocol_index < include_index, name

        # A direct same-provider process may exist only as a legacy external
        # example *after* the native-first contract has established precedence.
        executable = ACTIVE_SAME_PROVIDER_CLI_RE.search(content)
        if executable is not None:
            assert include_index < executable.start(), name
            assert "아래 skill별 dispatch 예시는 이 protocol의 route로 gate" in content[: executable.start()], name


def test_direct_provider_process_examples_are_locally_external_gated() -> None:
    for name in PROVIDER_DISPATCH_SKILLS:
        content = _skill_text(name)
        for match in ACTIVE_SAME_PROVIDER_CLI_RE.finditer(content):
            nearby_contract = content[max(0, match.start() - 1_200) : match.start()].lower()
            assert (
                "route=external" in nearby_contract or "external lane" in nearby_contract
            ), f"{name} has an unconditional same-provider CLI example: {match.group(0)!r}"


def test_provider_entrypoints_do_not_make_same_host_cli_unconditional() -> None:
    codex = _skill_text("codex")
    claude = _skill_text("claude")

    assert "같은 Codex host에서는 collaboration native agent를 우선" in codex
    assert "**External lane only**" in codex
    assert codex.index("**External lane only**") < codex.index("-- codex exec")
    assert "같은 Codex host의 native lane에는 Codex CLI가 필요하지 않다" in codex

    assert "같은 Claude host에서는 Task/Agent native bridge" in claude
    assert "**External lane only**" in claude
    assert claude.index("**External lane only**") < claude.index(
        "required wrapper fields:"
    )
    assert "nested `/mst:claude`" in _include_body(claude)


def test_parent_and_child_agent_surfaces_preserve_routing_boundary() -> None:
    conductor = (REPO_ROOT / "agents" / "pm-conductor.md").read_text(
        encoding="utf-8"
    )
    brief = (REPO_ROOT / "agents" / "outsource-brief.md").read_text(
        encoding="utf-8"
    )

    for token in (
        "mst.py host context --json",
        "mst.py delegation route",
        "route=native_candidate",
        "route=external",
        "route=blocked",
        "phase=reconciling",
        "start → acknowledge → attach → heartbeat → complete",
    ):
        assert token in conductor

    for token in (
        "DELEGATION BOUNDARY (MANDATORY)",
        "do not delegate or spawn another provider agent",
        "Do NOT invoke codex/claude provider CLIs",
        "Do NOT call `mst.py delegation` lifecycle commands",
    ):
        assert token in brief
