from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import config as config_cmds
from scripts.mst_cmds import transition_graph


ROOT = Path(__file__).resolve().parents[1]


def _skill_text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_approve_req_branch_name_snapshot_uses_integration_worktree() -> None:
    content = _skill_text("approve")

    assert "--role integration" in content
    assert 'branch-name --req REQ-NNN --base "$SESSION_BASE_BRANCH" --role integration --agi "${AGI_ID:-}"' in content
    assert 'branch-name --req REQ-NNN --task T01 --base "$SESSION_BASE_BRANCH" --agi "${AGI_ID:-}"' in content
    assert "INTEGRATION_WORKTREE" in content
    assert "git checkout -b \"$REQ_BRANCH\"" not in content
    assert "git checkout -b gran-maestro/REQ-NNN" not in content
    assert re.search(r"worktree create --path \"\$INTEGRATION_WORKTREE\" --branch \"\$REQ_BRANCH\"", content)


def test_accept_squash_merge_snapshot_uses_accept_worktree() -> None:
    content = _skill_text("accept")

    match = re.search(
        r"\*\*3-2\..*?```bash\n(?P<commands>.*?)\n\s*```",
        content,
        flags=re.S,
    )

    assert match is not None
    commands = [line.strip() for line in match.group("commands").splitlines() if line.strip()]

    assert any("--role accept" in command for command in commands)
    assert any('--role accept --agi "${AGI_ID:-}"' in command for command in commands)
    assert '--role integration --agi "${AGI_ID:-}"' in content
    assert '--task T --agi "${AGI_ID:-}"' in content
    assert any("worktree create --path \"$ACCEPT_WORKTREE\"" in command for command in commands)
    assert any("TARGET_BEFORE=$(git -C \"$ACCEPT_WORKTREE\" rev-parse --verify \"refs/heads/${BASE_BRANCH}\")" == command for command in commands)
    assert any("git -C \"$ACCEPT_WORKTREE\" merge --squash \"${REQ_BRANCH}\"" == command for command in commands)
    assert "worktree child-merge-queue" in content
    assert "--children-json \"@$CHILDREN_QUEUE_FILE\"" in content
    assert "merge_queue_state" in content
    assert "session_final_merge_blocked" in content
    assert "idempotency_key" in content
    assert 'git -C "$INTEGRATION_WORKTREE" merge --no-ff "${TASK_BRANCH_PREFIX}01"' not in content
    assert 'git -C "$INTEGRATION_WORKTREE" merge --no-ff "${TASK_BRANCH_PREFIX}02"' not in content
    assert "worktree reflect-accept" in content
    assert "--target-before \"$TARGET_BEFORE\"" in content
    assert "ACCEPT_REFLECTION_GATE_OK=true" in content
    assert "target_reflected_ff_only" in content
    assert "accepted_commit_is_ancestor_of_target" in content
    assert "cleanup_performed" in content
    assert "target branch reflection evidence 없이 cleanup 또는 Phase 5 완료 처리를 진행한다" in content
    assert "ACCEPT_REFLECTION.merge_state==\"target_reflected_ff_only\"" in content
    assert ("git -C {PROJECT_ROOT} checkout " + "master") not in content
    assert "git -C {PROJECT_ROOT} merge --squash gran-maestro/REQ-NNN" not in content


def test_worktree_base_branch_config_read_write_snapshot(monkeypatch, capsys) -> None:
    base_dir = Path("/mock/project/.gran-maestro")
    plugin_root = Path("/mock/plugin")
    defaults_path = plugin_root / "templates" / "defaults" / "config.json"
    config_path = base_dir / "config.json"
    resolved_path = base_dir / "config.resolved.json"
    store = {
        defaults_path: {"worktree": {"base_branch": "main"}},
        config_path: {"worktree": {"base_branch": "main"}},
    }

    def fake_load_json(path: Path):
        value = store.get(path)
        return copy.deepcopy(value)

    def fake_save_json(path: Path, value) -> None:
        store[path] = copy.deepcopy(value)

    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    monkeypatch.setattr(_common, "_plugin_root", lambda: plugin_root)
    monkeypatch.setattr(config_cmds, "load_json", fake_load_json)
    monkeypatch.setattr(config_cmds, "save_json", fake_save_json)

    assert config_cmds.cmd_config_resolve(argparse.Namespace()) == 0
    capsys.readouterr()
    assert store[resolved_path]["worktree"]["base_branch"] == "main"

    monkeypatch.setattr(
        config_cmds,
        "_load_config_for_get",
        lambda: copy.deepcopy(store[resolved_path]),
    )
    assert config_cmds.cmd_config_get(
        argparse.Namespace(key_path=["worktree.base_branch"], default_value=None, json=False)
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == "main\n"
    assert captured.err == ""

    store[config_path]["worktree"]["base_branch"] = "feature/release"
    assert config_cmds.cmd_config_resolve(argparse.Namespace()) == 0
    capsys.readouterr()
    assert store[resolved_path]["worktree"]["base_branch"] == "feature/release"

    on_content = _skill_text("on")
    assert 'd.setdefault("worktree", {})["base_branch"] = "{BASE_BRANCH_VALUE}"' in on_content
    assert 'v = d.get(\'worktree\', {}).get(\'base_branch\', \'\')' in on_content
    assert "os.replace(tmp, path)" in on_content


def test_lifecycle_contract_alignment_across_docs_graph_and_dashboard() -> None:
    expected_order = [
        "worktree_create",
        "worktree_work",
        "commit_intended_changes",
        "accept_child_to_session",
        "target_branch_reflection",
        "post_merge_cleanup",
        "phase5_done",
    ]
    graph_path = ROOT / "templates" / "state-machine" / "mst-transition-graph.json"
    dashboard_path = ROOT / "dashboard" / "mst-transition-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    lifecycle = graph["lifecycle_contract"]
    ordered_steps = lifecycle["ordered_steps"]

    assert [step["id"] for step in ordered_steps] == expected_order
    assert [step["order"] for step in ordered_steps] == list(range(1, len(expected_order) + 1))
    assert "child_to_session" in lifecycle["scope_vocabulary"]
    assert "session_to_original" in lifecycle["scope_vocabulary"]
    assert lifecycle["cleanup_boundary"]["after"] == ["target_branch_reflection"]
    assert {"commit", "merge", "target_ref_update"}.issubset(
        set(lifecycle["cleanup_boundary"]["not_responsibility"])
    )
    assert graph["hash"] == transition_graph.compute_graph_hash(graph)
    assert dashboard["source_graph"]["hash"] == graph["hash"]
    assert dashboard["lifecycle_contract"] == lifecycle

    docs_claude = (ROOT / "docs" / "CLAUDE.md").read_text(encoding="utf-8")
    skills_ref = (ROOT / "docs" / "skills-reference.md").read_text(encoding="utf-8")
    skills_ref_en = (ROOT / "docs" / "skills-reference.en.md").read_text(encoding="utf-8")
    assert "task worktree commit evidence 확인 → deterministic child merge queue" in docs_claude
    assert "selected target branch reflection evidence 확인 → post-merge cleanup" in docs_claude
    assert "main 브랜치에 머지합니다" not in skills_ref
    assert "deterministic child merge queue" in skills_ref
    assert "Merges Phase 3 PASS worktrees into main branch" not in skills_ref_en
    assert "selected target branch reflection evidence" in skills_ref_en
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8") == (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_config_get_backward_compatibility_contract(monkeypatch, capsys) -> None:
    resolved = {
        "workflow": {
            "default_agent": "codex-dev",
            "high_pass_guard": {"enabled": True},
        },
        "auto_mode": {"plan": False},
    }

    monkeypatch.setattr(config_cmds, "_load_config_for_get", lambda: copy.deepcopy(resolved))

    assert config_cmds.cmd_config_get(
        argparse.Namespace(
            key_path=["workflow.default_agent"],
            default_value=None,
            json=False,
        )
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == "codex-dev\n"
    assert captured.err == ""

    assert config_cmds.cmd_config_get(
        argparse.Namespace(
            key_path=["workflow.default_agent"],
            default_value=None,
            json=True,
        )
    ) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "key": "workflow.default_agent",
        "value": "codex-dev",
    }
    assert captured.err == ""

    assert config_cmds.cmd_config_get(
        argparse.Namespace(
            key_path=["workflow.default_agent", "auto_mode.plan"],
            default_value=None,
            json=True,
        )
    ) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [
        {"key": "workflow.default_agent", "value": "codex-dev"},
        {"key": "auto_mode.plan", "value": False},
    ]
    assert captured.err == ""

    assert config_cmds.cmd_config_get(
        argparse.Namespace(
            key_path=["workflow.default_agent", "auto_mode.plan"],
            default_value="fallback",
            json=True,
        )
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: --default is only supported for a single key" in captured.err


def test_skill_docs_prefer_batched_config_preload_patterns() -> None:
    request_content = _skill_text("request")
    plan_content = _skill_text("plan")
    agile_content = _skill_text("agile")

    assert "config get workflow.default_agent auto_mode.request --json" in request_content
    assert "config get workflow.arch_gate_threshold workflow.high_pass_guard --json" in request_content
    assert "config get auto_mode.plan auto_mode.confidence_threshold --json" in plan_content
    assert "config get plan_qa_presets --json" in plan_content
    assert "config get auto_mode.agile agile.steering_every --json" in agile_content
