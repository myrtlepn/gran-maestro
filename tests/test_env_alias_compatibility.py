from __future__ import annotations

import os
import subprocess
import sys
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
LEGACY_ALIASES = ("MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID")


def _run_session_resolve(workspace: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    for alias in LEGACY_ALIASES:
        merged_env.pop(alias, None)
    merged_env.update(env)
    merged_env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "session", "resolve"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=merged_env,
        timeout=30,
    )


def test_mixed_env_requires_structured_mst_session_id(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_session_resolve(
        tmp_path,
        {
            "MST_SESSION_ID": "MST-AGI-036-20260513T000000000Z-abcdefgh",
            "MST_STATE_PPID": "legacy-ppid-session",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "MST-AGI-036-20260513T000000000Z-abcdefgh"
    assert "deprecated" not in result.stderr.lower()


def test_legacy_only_aliases_are_diagnostic_only_non_success(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    result = _run_session_resolve(
        tmp_path,
        {
            "MST_STATE_PPID": "11111",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session",
        },
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "missing MST_SESSION_ID" in result.stderr


def test_legacy_alias_json_result_is_non_mutating(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    merged_env = os.environ.copy()
    for alias in LEGACY_ALIASES:
        merged_env.pop(alias, None)
    merged_env.update({"MST_STATE_PPID": "22222", "MST_SESSION_ID": ""})
    merged_env["MST_FLOW_DISABLE_ATEXIT"] = "1"

    result = subprocess.run(
        [sys.executable, str(MST_SCRIPT), "session", "resolve", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=merged_env,
        timeout=30,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["code"] == "legacy_identity_not_canonical_source"
    assert payload["canonical_mst_session_id"] is None
    assert payload["mutation_performed"] is False
    assert payload["legacy_diagnostics"] == {"MST_STATE_PPID": "22222"}


def test_direct_legacy_alias_runtime_references_are_allowlisted() -> None:
    """DOD-010: production direct alias usage must stay isolated to compatibility/reporting surfaces."""
    production_roots = [REPO_ROOT / "scripts", REPO_ROOT / "hooks", REPO_ROOT / "src"]
    allowlist = {
        "scripts/mst_cmds/env_alias_compat.py",
        "scripts/mst_cmds/hooks.py",
        "scripts/mst_cmds/state.py",
        "scripts/mst_cmds/_common.py",
        "scripts/mst_cmds/_state_manager.py",
        "scripts/mst_cmds/current_work_handoff.py",
        "scripts/mst_cmds/dispatch.py",
        "scripts/mst_cmds/prompt_correlation.py",
        "scripts/mst_cmds/session_debug.py",
        "scripts/mst_cmds/state_machine_health.py",
        "scripts/mst_cmds/writer_coverage.py",
        "scripts/_flow_logger.py",
        "scripts/mst-statusline.sh",
        "hooks/mst-auto-chain-context.sh",
        "hooks/lib/pre_tool_use_fast.py",
        "src/routes/debug.ts",
    }
    allowlist_prefixes = (
        "scripts/mst_cmds/_common_shards/",
        "scripts/mst_cmds/dispatch_shards/",
        "scripts/mst_cmds/execution_flow_shards/",
        "scripts/mst_cmds/state_shards/",
    )
    violations: list[str] = []

    for root in production_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".svg"}:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if rel.startswith("scripts/tests/"):
                continue
            if any(alias in text for alias in LEGACY_ALIASES) and rel not in allowlist and not rel.startswith(allowlist_prefixes):
                violations.append(rel)

    assert not violations, "unexpected direct legacy env alias references: " + ", ".join(sorted(violations))
