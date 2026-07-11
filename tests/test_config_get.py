import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_resolved_config(workspace: Path, data: dict) -> None:
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.resolved.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sample_config() -> dict:
    return {
        "workflow": {
            "default_agent": "codex-dev",
            "high_pass_guard": {
                "enabled": True,
                "confidence_supporting_only": True,
            },
        },
        "auto_mode": {"request": False},
        "reference": {"auto_search": True},
    }


def test_single_key(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(workspace, "config", "get", "workflow.default_agent")

    assert proc.returncode == 0
    assert proc.stdout == "codex-dev\n"
    assert proc.stderr == ""


def test_multi_key_plain(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "workflow.default_agent",
        "auto_mode.request",
        "reference.auto_search",
    )

    assert proc.returncode == 0
    assert proc.stdout == "codex-dev\nFalse\nTrue\n"
    assert proc.stderr == ""


def test_multi_key_json(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "workflow.default_agent",
        "auto_mode.request",
        "--json",
    )

    assert proc.returncode == 0
    assert json.loads(proc.stdout) == [
        {"key": "workflow.default_agent", "value": "codex-dev"},
        {"key": "auto_mode.request", "value": False},
    ]
    assert proc.stderr == ""


def test_missing_key_error(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(workspace, "config", "get", "nonexistent.key")

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Error: key not found: nonexistent.key" in proc.stderr


def test_multi_key_partial_missing(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "workflow.default_agent",
        "nonexistent.key",
    )

    assert proc.returncode == 1
    assert proc.stdout == "codex-dev\n"
    assert "Error: key not found: nonexistent.key" in proc.stderr


def test_default_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    _write_resolved_config(workspace, _sample_config())

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "nonexistent.key",
        "--default",
        "fallback",
    )

    assert proc.returncode == 0
    assert proc.stdout == "fallback\n"
    assert proc.stderr == ""


def test_nested_object_key(tmp_path):
    workspace = tmp_path / "workspace"
    config = _sample_config()
    _write_resolved_config(workspace, config)

    proc = _run_mst(workspace, "config", "get", "workflow.high_pass_guard")

    assert proc.returncode == 0
    assert json.loads(proc.stdout) == config["workflow"]["high_pass_guard"]
    assert proc.stderr == ""


def test_legacy_native_opt_out_has_canonical_read_alias(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "delegation": {
                    "native_codex_subagents": {
                        "enabled": False,
                        "scope": "review-and-exploration-only",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "delegation.transport_policy",
        "delegation.native.enabled",
        "delegation.native.scope",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [
        {"key": "delegation.transport_policy", "value": "external-only"},
        {"key": "delegation.native.enabled", "value": False},
        {"key": "delegation.native.scope", "value": "review-and-exploration-only"},
    ]


def test_partial_canonical_scope_preserves_legacy_execution_opt_out(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "delegation": {
                    "native": {"scope": "all"},
                    "native_codex_subagents": {"enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )

    proc = _run_mst(
        workspace,
        "config",
        "get",
        "delegation.transport_policy",
        "delegation.native.enabled",
        "delegation.native.scope",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    values = {item["key"]: item["value"] for item in json.loads(proc.stdout)}
    assert values == {
        "delegation.transport_policy": "external-only",
        "delegation.native.enabled": False,
        "delegation.native.scope": "all",
    }

    migrated = _run_mst(workspace, "config", "migrate", "--apply")
    assert migrated.returncode == 0, migrated.stderr
    persisted = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert persisted["delegation"] == {
        "transport_policy": "external-only",
        "native": {"enabled": False, "scope": "all"},
    }
