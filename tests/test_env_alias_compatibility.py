from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
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


def test_mixed_env_always_prefers_mst_session_id(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_session_resolve(
        tmp_path,
        {
            "MST_SESSION_ID": "canonical-session",
            "MST_STATE_PPID": "legacy-ppid-session",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "canonical-session"
    assert "deprecated" not in result.stderr.lower()


def test_legacy_only_fallbacks_emit_alias_deprecation_warning_once_per_process(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    script = f"""
import os
from scripts.mst_cmds import session
os.chdir({str(tmp_path)!r})
os.environ.pop('MST_SESSION_ID', None)
os.environ['MST_STATE_PPID'] = '11111'
print(session.resolve_session_id_value())
print(session.resolve_session_id_value())
os.environ.pop('MST_STATE_PPID', None)
os.environ['MST_SNAPSHOT_SESSION_ID'] = 'legacy-snapshot-session'
print(session.resolve_session_id_value())
print(session.resolve_session_id_value())
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == [
        "11111",
        "11111",
        "legacy-snapshot-session",
        "legacy-snapshot-session",
    ]
    warnings = result.stderr.lower()
    assert warnings.count("legacy-env-alias") == 2
    assert warnings.count("mst_state_ppid") == 1
    assert warnings.count("mst_snapshot_session_id") == 1
    assert "deprecated" in warnings
    assert "migration" in warnings


def test_legacy_alias_warning_marker_rate_limited_by_project_alias_and_date(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    env = {"MST_STATE_PPID": "22222", "MST_SESSION_ID": ""}

    first = _run_session_resolve(tmp_path, env)
    second = _run_session_resolve(tmp_path, env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout.strip() == "22222"
    assert second.stdout.strip() == "22222"
    assert "legacy-env-alias" in first.stderr
    assert "legacy-env-alias" not in second.stderr
    marker = (
        tmp_path
        / ".gran-maestro"
        / "tmp"
        / "legacy-env-alias-warnings"
        / f"{date.today().isoformat()}-MST_STATE_PPID.warned"
    )
    assert marker.exists()


def test_direct_legacy_alias_runtime_references_are_allowlisted() -> None:
    """DOD-010: production direct alias usage must stay isolated to compatibility/reporting surfaces."""
    production_roots = [REPO_ROOT / "scripts", REPO_ROOT / "hooks", REPO_ROOT / "src"]
    allowlist = {
        "scripts/mst_cmds/env_alias_compat.py",
        "scripts/mst_cmds/hooks.py",
        "scripts/mst_cmds/state.py",
        "scripts/mst_cmds/_common.py",
        "scripts/mst_cmds/dispatch.py",
        "scripts/_flow_logger.py",
        "scripts/mst-statusline.sh",
        "hooks/mst-auto-chain-context.sh",
        "hooks/lib/pre_tool_use_fast.py",
    }
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
            if any(alias in text for alias in LEGACY_ALIASES) and rel not in allowlist:
                violations.append(rel)

    assert not violations, "unexpected direct legacy env alias references: " + ", ".join(sorted(violations))
