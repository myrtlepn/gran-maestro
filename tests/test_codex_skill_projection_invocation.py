import importlib.util
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_AGILE = REPO_ROOT / "skills" / "agile" / "SKILL.md"
SOURCE_AGILE_PLAN = REPO_ROOT / "skills" / "agile-plan" / "SKILL.md"
SOURCE_SKILLS = REPO_ROOT / "skills"
CODEX_AGILE = REPO_ROOT / "plugins" / "mst" / "skills" / "agile" / "SKILL.md"
CODEX_AGILE_PLAN = REPO_ROOT / "plugins" / "mst" / "skills" / "agile-plan" / "SKILL.md"
CODEX_SKILLS = REPO_ROOT / "plugins" / "mst" / "skills"
CODEX_PLUGIN_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
PROJECTION_SCRIPT = REPO_ROOT / "scripts" / "sync-codex-plugin-projection.py"

DELEGATION_INCLUDE = "_shared/delegation-routing.md"
DELEGATION_INCLUDE_MARKER = f"<!-- @include {DELEGATION_INCLUDE} -->"
END_INCLUDE_MARKER = "<!-- @end-include -->"

# Keep this list aligned with the canonical provider-dispatch contract test.
# Projection parity must be explicit: a newly added provider surface should not
# silently lose native-first routing when copied into plugins/mst.
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

ACTIVE_PROVIDER_CLI_RE = re.compile(
    r"(?:command:\s*['\"][^\n]*(?:codex exec|--provider claude)|"
    r"^\s*(?:--\s+(?:codex exec|claude\s+(?:-p|--print)\b)|"
    r"codex exec|claude\s+(?:-p|--print)\b))",
    re.MULTILINE,
)
NESTED_CLAUDE_INVOCATION_RE = re.compile(
    r"(?:Skill\(\s*(?:skill:\s*)?['\"]mst:claude['\"]|"
    r"^\s*/mst:claude\s+--(?:prompt-file|dir)\b)",
    re.MULTILINE,
)


def load_projection_script_module():
    spec = importlib.util.spec_from_file_location("sync_codex_plugin_projection", PROJECTION_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_source_skill(name: str) -> str:
    return (SOURCE_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def read_projected_skill(name: str) -> str:
    return (CODEX_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def delegation_include_body(text: str) -> str:
    pattern = re.compile(
        rf"{re.escape(DELEGATION_INCLUDE_MARKER)}\n(.*?){re.escape(END_INCLUDE_MARKER)}",
        re.DOTALL,
    )
    match = pattern.search(text)
    assert match is not None, f"missing {DELEGATION_INCLUDE} include"
    return match.group(1).rstrip("\n")


def assert_external_gate_is_local(skill_name: str, text: str, match: re.Match[str]) -> None:
    nearby_contract = text[max(0, match.start() - 2_500) : match.start()].lower()
    assert "route=external" in nearby_contract or "external lane" in nearby_contract, (
        f"{skill_name} has an unconditional external provider path: {match.group(0)!r}"
    )


def test_claude_source_keeps_claude_style_agile_plan_delegation() -> None:
    source = SOURCE_AGILE.read_text(encoding="utf-8")

    assert (
        'Skill(skill: "mst:agile-plan", args: "{PROJECT_GOAL_OR_DOC} '
        '{DOC_FLAG_IF_ANY} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")'
    ) in source
    assert (
        'Skill(skill: "mst:agile-plan", args: "--resume {AGI_ID} '
        '--return-to agile/1 {AUTO_FLAG_IF_TRUE}")'
    ) in source
    assert "MST_PARENT_BINDING" not in source


def test_codex_projection_uses_codex_native_agile_plan_invocation() -> None:
    projected = CODEX_AGILE.read_text(encoding="utf-8")

    assert "### Codex Projection Invocation Contract" in projected
    assert (
        "$mst:agile-plan {PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} "
        "--return-to agile/1 {AUTO_FLAG_IF_TRUE}"
    ) in projected
    assert (
        "$mst:agile-plan --resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}"
    ) in projected
    assert 'Skill(skill: "mst:agile-plan"' not in projected
    assert "MST_PARENT_BINDING" not in projected


def test_codex_projection_declares_agile_plan_command_identity() -> None:
    source = SOURCE_AGILE_PLAN.read_text(encoding="utf-8")
    projected = CODEX_AGILE_PLAN.read_text(encoding="utf-8")

    assert "**목적**: `/mst:agile-plan`" in source
    assert "### Codex Projection Invocation Contract" in projected
    assert "explicit `$mst:agile-plan` invocation is the command identity" in projected
    assert (
        "원시 입력의 command identity가 `$mst:agile-plan`(Codex) 또는 "
        "`/mst:agile-plan`(Claude)로 확정된 경우"
    ) in projected
    assert (
        "재현 fixture `$mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`"
    ) in projected
    assert "command identity가 `/mst:agile-plan`으로" not in projected


def test_codex_projection_rewriter_reproduces_agile_plan_invocation_contract() -> None:
    module = load_projection_script_module()

    source_agile = SOURCE_AGILE.read_text(encoding="utf-8")
    rewritten = module.rewrite_agile_skill_for_codex(source_agile, Path("skills/agile/SKILL.md"))

    assert (
        "$mst:agile-plan {PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} "
        "--return-to agile/1 {AUTO_FLAG_IF_TRUE}"
    ) in rewritten
    assert (
        "$mst:agile-plan --resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}"
    ) in rewritten
    assert 'Skill(skill: "mst:agile-plan"' not in rewritten
    assert "MST_PARENT_BINDING" not in rewritten


def test_codex_projection_rewriter_reproduces_agile_plan_identity_guard() -> None:
    module = load_projection_script_module()

    source_agile_plan = SOURCE_AGILE_PLAN.read_text(encoding="utf-8")
    rewritten = module.rewrite_agile_plan_skill_for_codex(
        source_agile_plan,
        Path("skills/agile-plan/SKILL.md"),
    )

    assert "**목적**: `$mst:agile-plan`(Codex) 또는 `/mst:agile-plan`(Claude)" in rewritten
    assert "`$mst:agile-plan --doc spec.md`(Codex)" in rewritten
    assert (
        "원시 입력의 command identity가 `$mst:agile-plan`(Codex) 또는 "
        "`/mst:agile-plan`(Claude)로 확정된 경우"
    ) in rewritten
    assert (
        "재현 fixture `$mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`"
    ) in rewritten
    assert "command identity가 `/mst:agile-plan`으로" not in rewritten


def test_codex_projection_preserves_canonical_native_first_delegation_protocol() -> None:
    canonical = (SOURCE_SKILLS / DELEGATION_INCLUDE).read_text(encoding="utf-8").rstrip(
        "\n"
    )

    required_tokens = (
        "mst.py delegation route",
        "route=native_candidate",
        "route=external",
        "route=blocked",
        "phase=reconciling",
        "delegation start",
        "delegation claim-spawn",
        "delegation acknowledge",
        "delegation attach",
        "delegation heartbeat",
        "delegation complete",
        "DELEGATION BOUNDARY (MANDATORY)",
        "spawn_allowed=true",
        '--claim-token-file "{claim_token_file}"',
    )

    for name in PROVIDER_DISPATCH_SKILLS:
        source = read_source_skill(name)
        projected = read_projected_skill(name)

        assert source.count(DELEGATION_INCLUDE_MARKER) == 1, name
        assert projected.count(DELEGATION_INCLUDE_MARKER) == 1, name
        assert delegation_include_body(source) == canonical, name
        assert delegation_include_body(projected) == canonical, name
        for token in required_tokens:
            assert token in projected, f"{name} projection is missing {token!r}"


def test_projection_rewriters_do_not_erase_native_first_delegation_protocol() -> None:
    module = load_projection_script_module()
    canonical = (SOURCE_SKILLS / DELEGATION_INCLUDE).read_text(encoding="utf-8").rstrip(
        "\n"
    )

    for rel_path, rewrite in module.CODEX_SKILL_REWRITES.items():
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        rewritten = rewrite(source, rel_path)

        assert delegation_include_body(rewritten) == canonical, rel_path


def test_claude_source_and_codex_projection_use_their_same_host_native_bridges() -> None:
    source_claude = read_source_skill("claude")
    projected_codex = read_projected_skill("codex")

    assert "같은 Claude host에서는 Task/Agent native bridge" in source_claude
    assert "`native_candidate`면 Claude `Task(...)`/`Agent(...)`" in source_claude
    assert "TaskOutput`/resume result" in source_claude

    assert "같은 Codex host에서는 collaboration native agent" in projected_codex
    assert (
        "`native_candidate`면 Codex collaboration spawn/attach/wait/result"
        in projected_codex
    )
    assert "collaboration.spawn_agent" in projected_codex
    assert "collaboration.wait_agent" in projected_codex


def test_projected_provider_skills_do_not_expose_unconditional_external_paths() -> None:
    cli_match_count = 0
    nested_claude_match_count = 0

    for name in PROVIDER_DISPATCH_SKILLS:
        projected = read_projected_skill(name)
        protocol = delegation_include_body(projected)

        assert (
            "`route=native_candidate`: 같은 host/provider의 native bridge만 사용"
            in protocol
        )
        assert "`route=external`: 이 경우에만" in protocol
        assert "정상 same-host 경로에서" in protocol
        assert "nested `/mst:claude`/`/mst:codex`를 호출하지 않는다" in protocol

        for match in ACTIVE_PROVIDER_CLI_RE.finditer(projected):
            cli_match_count += 1
            assert_external_gate_is_local(name, projected, match)

        # The claude entrypoint's own user-facing examples are command identity,
        # not nested delegation. Other skills may call it only from an external lane.
        if name != "claude":
            for match in NESTED_CLAUDE_INVOCATION_RE.finditer(projected):
                nested_claude_match_count += 1
                assert_external_gate_is_local(name, projected, match)

    assert cli_match_count > 0
    assert nested_claude_match_count > 0


def test_codex_plugin_default_prompts_use_model_visible_skill_names() -> None:
    manifest = json.loads(CODEX_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    prompts = manifest["interface"]["defaultPrompt"]

    assert prompts
    assert all(prompt.startswith("$mst:") for prompt in prompts)
    assert all(not prompt.startswith("/mst:") for prompt in prompts)


def test_session_bootstrap_conditional_inheritance_parity() -> None:
    bootstrap_skills = {
        "debug",
        "discussion",
        "explore",
        "ideation",
        "plan-doc",
        "plan",
        "request",
    }

    for name in PROVIDER_DISPATCH_SKILLS:
        if name not in bootstrap_skills:
            continue

        for read_func, label in [(read_source_skill, "source"), (read_projected_skill, "projected")]:
            content = read_func(name)

            # 1. Check for inclusion markers
            include_marker = "<!-- @include _shared/session-bootstrap.md -->"
            end_marker = "<!-- @end-include -->"

            idx = content.find(include_marker)
            assert idx != -1, f"{label} skill {name} is missing include"

            end_idx = content.find(end_marker, idx)
            assert end_idx != -1, f"{label} skill {name} is missing end-include"

            # 2. Extract content outside the session-bootstrap include block
            post_include_content = content[:idx] + content[end_idx + len(end_marker):]

            # 3. Assert no unconditional session bootstrap instructions/command blocks exist in the rest of the file
            forbidden_patterns = [
                r"session bootstrap --root-mst-id",
                r"session bootstrap` 커맨드를 실행하여 세션을 초기화",
            ]
            for pattern in forbidden_patterns:
                match = re.search(pattern, post_include_content)
                assert not match, (
                    f"Unconditional session bootstrap instruction found in {label} skill {name} post-include: "
                    f"{match.group(0) if match else ''}"
                )

            include_body = content[idx : end_idx + len(end_marker)]
            required_tokens = (
                "session resolve --json",
                "session bootstrap",
                "CANONICAL_MST_SESSION_ID",
                "CANONICAL_MST_CONTEXT_JSON",
                "모든 별도",
                "한 `export`에 의존하면 안 됩니다",
            )
            for token in required_tokens:
                assert token in include_body, f"{label} skill {name} is missing {token!r}"
