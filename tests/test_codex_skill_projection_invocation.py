import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_AGILE = REPO_ROOT / "skills" / "agile" / "SKILL.md"
SOURCE_AGILE_PLAN = REPO_ROOT / "skills" / "agile-plan" / "SKILL.md"
CODEX_AGILE = REPO_ROOT / "plugins" / "mst" / "skills" / "agile" / "SKILL.md"
CODEX_AGILE_PLAN = REPO_ROOT / "plugins" / "mst" / "skills" / "agile-plan" / "SKILL.md"
CODEX_PLUGIN_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
PROJECTION_SCRIPT = REPO_ROOT / "scripts" / "sync-codex-plugin-projection.py"


def load_projection_script_module():
    spec = importlib.util.spec_from_file_location("sync_codex_plugin_projection", PROJECTION_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_codex_plugin_default_prompts_use_model_visible_skill_names() -> None:
    manifest = json.loads(CODEX_PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    prompts = manifest["interface"]["defaultPrompt"]

    assert prompts
    assert all(prompt.startswith("$mst:") for prompt in prompts)
    assert all(not prompt.startswith("/mst:") for prompt in prompts)
