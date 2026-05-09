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
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3","hooks":"./hooks/hooks.json"}\n')
    _write(plugin_root / "hooks" / "hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"}]}]}}))

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Installed hooks:" in captured.out
    assert "Source hooks:" in captured.out
    assert "Installed version:" in captured.out
    assert "Expected version:" in captured.out
    for label in (
        "skill_base_dir:",
        "enabled_plugin:",
        "active_plugin_root:",
        "active_plugin_version:",
        "active_manifest_hooks_field:",
        "active_hooks_json_exists:",
        "active_stop_registration:",
        "active_stop_command:",
    ):
        assert label in captured.out


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


def test_doctor_reports_enabled_plugin_from_user_global_settings(tmp_path, monkeypatch, capsys):
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write(Path.home() / ".claude" / "settings.json", json.dumps({"enabledPlugins": {"mst@gran-maestro": True}}))
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3","hooks":"./hooks/hooks.json"}\n')
    _write(plugin_root / "hooks" / "hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"}]}]}}))

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "enabled_plugin: true" in captured.out


def test_doctor_reports_user_global_stop_without_canonical_guarantee(tmp_path, monkeypatch, capsys):
    installed_path, source_path, _ = _arrange_hooks(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write(
        Path.home() / ".claude" / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/tmp/user-global/mst-stop-hook.sh",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    )
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "user_global_environment_hook:" in captured.out
    assert "stop_registration: True" in captured.out
    assert "mst_core_stop_guarantee: false (user-global is not MST core canonical)" in captured.out


def test_doctor_reports_hook_responsibility_layers(tmp_path, monkeypatch, capsys):
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(installed_path / "mst-stop-hook.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-stop-hook.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3","hooks":"./hooks/hooks.json"}\n')
    _write(plugin_root / "hooks" / "hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"}]}]}}))

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "canonical_plugin_hook:" in captured.out
    assert "project_local_legacy_source_dev_hook:" in captured.out
    assert "user_global_environment_hook:" in captured.out
    assert "mst_core_stop_guarantee: true" in captured.out
    assert "mst_core_stop_guarantee: false (legacy/source-dev is not canonical)" in captured.out
    assert "mst_core_stop_guarantee: false (user-global is not MST core canonical)" in captured.out


def test_doctor_warns_when_active_manifest_has_no_hooks_field(tmp_path, monkeypatch, capsys):
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3"}\n')

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "canonical_stop_registration_status: WARNING" in captured.out
    assert "active plugin cache manifest/registry lacks canonical Stop registration" in captured.out


def test_doctor_warns_when_hooks_registry_missing(tmp_path, monkeypatch, capsys):
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3","hooks":"./hooks/missing.json"}\n')

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "active_hooks_json_exists: False" in captured.out
    assert "canonical_stop_registration_status: WARNING" in captured.out


def test_doctor_warns_when_registry_lacks_stop(tmp_path, monkeypatch, capsys):
    installed_path, source_path, plugin_root = _arrange_hooks(tmp_path, monkeypatch)
    _write(installed_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(source_path / "mst-example.sh", "#!/bin/sh\nexit 0\n")
    _write(plugin_root / ".claude-plugin" / "plugin.json", '{"name":"mst","version":"1.2.3","hooks":"./hooks/hooks.json"}\n')
    _write(plugin_root / "hooks" / "hooks.json", json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh"}]}]}}))

    return_code = hooks.doctor(argparse.Namespace())
    captured = capsys.readouterr()

    assert return_code == 0
    assert "active_stop_registration: False" in captured.out
    assert "canonical_stop_registration_status: WARNING" in captured.out


def test_stop_dispatcher_smoke_requires_event_dispatch_evidence():
    result = hooks.evaluate_stop_dispatcher_smoke(True, None)

    assert result["script_direct_execution"] == "PASS"
    assert result["claude_code_stop_event_dispatch"] == "INCONCLUSIVE"
    assert result["overall"] != "PASS"


def test_stop_dispatcher_smoke_passes_with_complete_event_evidence():
    result = hooks.evaluate_stop_dispatcher_smoke(
        True,
        {
            "event_type": "Stop",
            "hook_command_path": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
            "timestamp": "2026-05-09T00:00:00Z",
            "test_sentinel": "sentinel",
        },
    )

    assert result["claude_code_stop_event_dispatch"] == "PASS"
    assert result["overall"] == "PASS"


def test_stop_dispatcher_smoke_rejects_incomplete_event_evidence():
    result = hooks.evaluate_stop_dispatcher_smoke(
        True,
        {
            "event_type": "Stop",
            "hook_command_path": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
            "timestamp": "2026-05-09T00:00:00Z",
        },
    )

    assert result["claude_code_stop_event_dispatch"] == "INCONCLUSIVE"
    assert result["overall"] != "PASS"


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
