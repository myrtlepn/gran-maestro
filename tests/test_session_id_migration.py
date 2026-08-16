"""REQ-696/T01 T3: session_id snapshot isolation regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from tests.fixtures.hook_harness import run_hook, stdout_json
from tests.fixtures.session_helper import pair_sessions
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MST_SESSION_RE = re.compile(r"^MST-AGI-039-\d{8}T\d{9}Z-[a-z0-9]{8,}$")
VALID_SESSION_ID = "MST-AGI-039-20260519T130000000Z-validsid"


def _hook_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": "Stop",
    }


def _snapshot_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"


def test_session_b_sees_no_a_snapshot(tmp_path):
    project_root, session_a, session_b = pair_sessions(tmp_path)
    write_snapshot(project_root, session_a, build_snapshot("agile-plan", 1, 3))

    result = run_hook(project_root, _hook_payload(session_b))

    payload = stdout_json(result)
    assert payload["decision"] == "approve"
    assert "workflow_inactive" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]


def test_session_a_snapshot_integrity_after_b_hook(tmp_path):
    project_root, session_a, session_b = pair_sessions(tmp_path)
    write_snapshot(project_root, session_a, build_snapshot("agile-plan", 1, 3))
    a_path = _snapshot_path(project_root, session_a)
    pre_hash = hashlib.sha256(a_path.read_bytes()).hexdigest()
    pre_content = a_path.read_text(encoding="utf-8")

    run_hook(project_root, _hook_payload(session_b))

    post_hash = hashlib.sha256(a_path.read_bytes()).hexdigest()
    post_content = a_path.read_text(encoding="utf-8")
    assert pre_hash == post_hash
    assert pre_content == post_content


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        merged_env.pop(key, None)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
        timeout=30,
    )


def _workspace_files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*")}


def test_session_resolve_returns_existing_env_without_writes(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    before = _workspace_files(tmp_path)

    result = _run_mst(tmp_path, "session", "resolve", env={"MST_SESSION_ID": VALID_SESSION_ID})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VALID_SESSION_ID
    assert _workspace_files(tmp_path) == before


def test_session_resolve_generates_structured_id_without_state_side_effects(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    before = _workspace_files(tmp_path)

    result = _run_mst(tmp_path, "session", "resolve", "--root-mst-id", "AGI-039", env={"MST_SESSION_ID": ""})

    assert result.returncode == 0, result.stderr
    assert MST_SESSION_RE.match(result.stdout.strip())
    assert _workspace_files(tmp_path) == before


def test_session_resolve_json_output_is_side_effect_free(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_mst(tmp_path, "session", "resolve", "--json", env={"MST_SESSION_ID": VALID_SESSION_ID})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mst_session_id"] == VALID_SESSION_ID
    assert payload["session_id"] == VALID_SESSION_ID
    assert payload["source"] == "env:MST_SESSION_ID"
    assert payload["valid"] is True


def test_shell_wrapper_repeated_resolve_keeps_same_exported_sid(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    script = (
        'export MST_SESSION_ID="${MST_SESSION_ID:-$(python3 '
        + str(MST_SCRIPT)
        + ' session resolve --root-mst-id AGI-039)}"; '
        'first="$MST_SESSION_ID"; '
        'export MST_SESSION_ID="${MST_SESSION_ID:-$(python3 '
        + str(MST_SCRIPT)
        + ' session resolve --root-mst-id AGI-039)}"; '
        'printf "%s\\n%s\\n" "$first" "$MST_SESSION_ID"'
    )

    test_env = os.environ.copy()
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW", "MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID"):
        test_env.pop(key, None)

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=test_env,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    first, second = result.stdout.strip().splitlines()
    assert MST_SESSION_RE.match(first)
    assert second == first


def test_session_resolve_prefers_mst_session_id_over_legacy_aliases(tmp_path: Path) -> None:
    """DOD-010: MST_SESSION_ID is canonical when legacy aliases conflict."""
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_mst(
        tmp_path,
        "session",
        "resolve",
        env={
            "MST_SESSION_ID": VALID_SESSION_ID,
            "MST_STATE_PPID": "legacy-ppid-session",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VALID_SESSION_ID
    assert "legacy" not in result.stdout.strip()


def test_session_resolve_legacy_only_snapshot_alias_is_diagnostic_only(tmp_path: Path) -> None:
    """DOD-007: MST_SNAPSHOT_SESSION_ID is diagnostic-only for canonical identity."""
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_mst(
        tmp_path,
        "session",
        "resolve",
        "--json",
        env={
            "MST_SESSION_ID": "",
            "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session",
        },
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["code"] == "legacy_identity_not_canonical_source"
    assert payload["canonical_mst_session_id"] is None
    assert payload["mutation_performed"] is False
    assert payload["legacy_diagnostics"] == {"MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-session"}


def test_session_resolve_legacy_only_state_ppid_alias_is_diagnostic_only(tmp_path: Path) -> None:
    """DOD-007: MST_STATE_PPID is diagnostic-only for canonical identity."""
    (tmp_path / ".gran-maestro").mkdir()

    result = _run_mst(
        tmp_path,
        "session",
        "resolve",
        "--json",
        env={
            "MST_SESSION_ID": "",
            "MST_STATE_PPID": "424242",
        },
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["code"] == "legacy_identity_not_canonical_source"
    assert payload["canonical_mst_session_id"] is None
    assert payload["mutation_performed"] is False
    assert payload["legacy_diagnostics"] == {"MST_STATE_PPID": "424242"}
