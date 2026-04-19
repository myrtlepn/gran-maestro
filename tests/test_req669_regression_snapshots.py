from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import config as config_cmds


ROOT = Path(__file__).resolve().parents[1]


def _skill_text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_approve_req_branch_name_snapshot_is_flat_req_branch() -> None:
    content = _skill_text("approve")

    match = re.search(
        r"git show-ref --verify --quiet refs/heads/(?P<branch>gran-maestro/REQ-NNN)"
        r"\s*\\\s*\n\s*\|\| git checkout -b (?P=branch) \{config\.worktree\.base_branch\}",
        content,
    )

    assert match is not None
    branch_template = match.group("branch")
    branch_name = branch_template.replace("NNN", "001")

    assert branch_name == "gran-maestro/REQ-001"
    assert re.fullmatch(r"gran-maestro/REQ-\d{3}", branch_name)
    assert "--base gran-maestro/REQ-NNN" in content


def test_accept_master_squash_merge_snapshot() -> None:
    content = _skill_text("accept")

    match = re.search(
        r"\*\*3-2\..*?```bash\n(?P<commands>.*?)\n\s*```",
        content,
        flags=re.S,
    )

    assert match is not None
    commands = [line.strip() for line in match.group("commands").splitlines() if line.strip()]

    assert commands[0] == "git -C {PROJECT_ROOT} checkout master"
    assert commands[1] == "git -C {PROJECT_ROOT} merge --squash gran-maestro/REQ-NNN"
    assert commands[0].split()[-1] == "master"
    assert "--squash" in commands[1].split()
    assert commands[1].split()[-1] == "gran-maestro/REQ-NNN"


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
