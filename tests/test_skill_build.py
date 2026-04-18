import argparse
from pathlib import Path

from scripts.mst_cmds import hooks
from scripts.mst_cmds import skill as skill_cmd


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_plugin(
    tmp_path: Path,
    *,
    include_target: str = "_shared/shared.md",
    shared_content: str = "shared line 1\nshared line 2\n",
    inner_content: str = "stale content\n",
    prefix: str = "before\n",
    suffix: str = "after\n",
) -> tuple[Path, Path, Path]:
    plugin_root = tmp_path / "plugin"
    shared_path = plugin_root / "skills" / "_shared" / "shared.md"
    skill_path = plugin_root / "skills" / "demo" / "SKILL.md"

    _write(shared_path, shared_content)
    _write(
        skill_path,
        (
            f"{prefix}"
            f"<!-- @include {include_target} -->\n"
            f"{inner_content}"
            f"<!-- @end-include -->\n"
            f"{suffix}"
        ),
    )
    return plugin_root, shared_path, skill_path


def test_build_resolves_include(tmp_path):
    plugin_root, shared_path, skill_path = _make_plugin(tmp_path)

    return_code = skill_cmd.build_all(plugin_root / "skills")

    assert return_code == 0
    expected = (
        "before\n"
        "<!-- @include _shared/shared.md -->\n"
        f"{shared_path.read_text(encoding='utf-8')}"
        "<!-- @end-include -->\n"
        "after\n"
    )
    assert skill_path.read_text(encoding="utf-8") == expected


def test_check_mode_passes(tmp_path, monkeypatch, capsys):
    plugin_root, _, _ = _make_plugin(tmp_path)
    skill_cmd.build_all(plugin_root / "skills", silent=True)
    monkeypatch.setattr(skill_cmd._common, "_plugin_root", lambda: plugin_root)

    return_code = skill_cmd.cmd_skill_build(argparse.Namespace(check=True, silent=False))
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.out == "all includes up-to-date\n"
    assert captured.err == ""


def test_check_mode_detects_stale(tmp_path, monkeypatch, capsys):
    plugin_root, shared_path, skill_path = _make_plugin(tmp_path)
    skill_cmd.build_all(plugin_root / "skills", silent=True)
    _write(shared_path, "updated shared content\n")
    monkeypatch.setattr(skill_cmd._common, "_plugin_root", lambda: plugin_root)

    return_code = skill_cmd.cmd_skill_build(argparse.Namespace(check=True, silent=False))
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert skill_path.as_posix() in captured.err


def test_missing_include_error(tmp_path, monkeypatch, capsys):
    plugin_root, _, _ = _make_plugin(tmp_path, include_target="_shared/missing.md")
    monkeypatch.setattr(skill_cmd._common, "_plugin_root", lambda: plugin_root)

    return_code = skill_cmd.cmd_skill_build(argparse.Namespace(check=False, silent=False))
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "include file not found" in captured.err
    assert "_shared/missing.md" in captured.err


def test_hooks_sync_integration(tmp_path, monkeypatch):
    plugin_root, _, skill_path = _make_plugin(tmp_path)
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"version":"1.2.3"}\n')
    _write(plugin_root / "hooks" / "example.sh", "#!/bin/sh\nexit 0\n")
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(
        hooks._common,
        "_mst_script_path",
        lambda: plugin_root / "scripts" / "mst.py",
    )

    return_code = hooks.cmd_hooks_sync(argparse.Namespace(silent=True))

    assert return_code == 0
    assert (project_root / ".claude" / "hooks" / "example.sh").exists()
    assert (project_root / ".claude" / "hooks" / ".mst-hook-version").read_text(
        encoding="utf-8"
    ).strip() == "1.2.3"
    assert "shared line 1" in skill_path.read_text(encoding="utf-8")
    assert "stale content" not in skill_path.read_text(encoding="utf-8")


def test_marker_preservation(tmp_path):
    plugin_root, _, skill_path = _make_plugin(
        tmp_path,
        prefix="front matter\n\n",
        suffix="\ntrailing notes\n",
    )

    return_code = skill_cmd.build_all(plugin_root / "skills", silent=True)
    content = skill_path.read_text(encoding="utf-8")

    assert return_code == 0
    assert content.startswith("front matter\n\n<!-- @include _shared/shared.md -->\n")
    assert content.endswith("<!-- @end-include -->\n\ntrailing notes\n")
