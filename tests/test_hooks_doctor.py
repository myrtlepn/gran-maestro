import argparse
from pathlib import Path

from scripts.mst_cmds import hooks


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _arrange_hooks(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "workspace"
    plugin_root = tmp_path / "plugin"
    installed_path = project_root / ".claude" / "hooks"
    source_path = plugin_root / "hooks"

    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(hooks, "_resolve_plugin_root", lambda: plugin_root)
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"version":"1.2.3"}\n')
    _write(installed_path / ".mst-hook-version", "1.2.3\n")

    return installed_path, source_path, plugin_root


def test_status_ok_all_in_sync(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Status: OK (all 1 hooks in sync)" in captured.out


def test_status_mismatch(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 1\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 1
    assert "Status: MISMATCH (1 out of 1 hooks differ)" in captured.out
    assert "- mst-example.sh" in captured.out


def test_status_source_not_found(tmp_path, monkeypatch, capsys):
    installed_path, _, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Status: SOURCE_NOT_FOUND" in captured.out
    assert "source hooks not found" in captured.err


def test_output_contains_required_fields(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Installed hooks:" in captured.out
    assert "Source hooks:" in captured.out
    assert "Installed version:" in captured.out
    assert "Expected version:" in captured.out
