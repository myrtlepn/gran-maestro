from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import config as config_cmds


ROOT = Path(__file__).resolve().parents[1]


def _skill_text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_approve_req_branch_name_snapshot_uses_integration_worktree() -> None:
    content = _skill_text("approve")

    assert "--role integration" in content
    assert 'branch-name --req REQ-NNN --base "$DETECTED_BASE" --role integration --agi "${AGI_ID:-}"' in content
    assert 'branch-name --req REQ-NNN --task T01 --base "$DETECTED_BASE" --agi "${AGI_ID:-}"' in content
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
    assert any("git -C \"$ACCEPT_WORKTREE\" merge --squash \"${REQ_BRANCH}\"" == command for command in commands)
    assert "git -C {PROJECT_ROOT} checkout master" not in content
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
