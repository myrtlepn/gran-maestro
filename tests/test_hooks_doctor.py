import argparse
import json
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


def test_doctor_reports_lineage_unknown_candidates_read_only(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    meta_path = tmp_path / "workspace" / ".gran-maestro" / "worktrees" / "REQ-801-T03.meta.json"
    _write(meta_path, json.dumps({"taskId": "REQ-801-T03", "state": "cleaned"}))
    before = meta_path.read_text(encoding="utf-8")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "stale meta lineage=unknown candidates=1" in captured.out
    assert "mst.py worktree migrate-archive --dry-run" in captured.out
    assert "mst.py worktree migrate-archive --apply" in captured.out
    assert "mst.py worktree migrate-archive --delete --apply" in captured.out
    assert meta_path.read_text(encoding="utf-8") == before
    assert not (meta_path.parent / ".archive").exists()


def test_doctor_reports_zero_candidate_clean_state(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(
        tmp_path / "workspace" / ".gran-maestro" / "worktrees" / "REQ-801-ok.meta.json",
        json.dumps({"taskId": "REQ-801-ok", "session_id": "session-ok"}),
    )

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "stale meta lineage=unknown candidates=0" in captured.out
    assert "clean: lineage=unknown candidate 없음" in captured.out


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


def test_doctor_fixtures_model_project_legacy_not_canonical(tmp_path, monkeypatch, capsys):
    """Doctor inspects project-local hook copies as legacy/source-dev diagnostics."""
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert installed_path == tmp_path / "workspace" / ".claude" / "hooks"
    assert source_path == tmp_path / "plugin" / "hooks"
    assert "${CLAUDE_PLUGIN_ROOT}" not in captured.out
    assert "Installed hooks:" in captured.out
    assert "Source hooks:" in captured.out


def test_doctor_output_contains_legacy_env_alias_migration_tokens(tmp_path, monkeypatch, capsys):
    """DOD-010: doctor exposes deprecated legacy alias migration signal."""
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("MST_STATE_PPID", "12345")
    monkeypatch.setenv("MST_SNAPSHOT_SESSION_ID", "legacy-snapshot-session")
    monkeypatch.setenv("MST_SESSION_ID", "canonical-session")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()
    output = f"{captured.out}\n{captured.err}"

    assert return_code == 0
    assert "legacy-env-alias" in output
    assert "MST_SESSION_ID" in output
    assert "deprecated" in output
    assert "migration" in output
