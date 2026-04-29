"""Tests for AD-005: ledger lock contention fallback (stderr + overflow file)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_LIB = REPO_ROOT / "hooks" / "lib" / "ledger.bash"


def _run_ledger(workspace: Path, payload: str, event: str = "SessionStart") -> subprocess.CompletedProcess:
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    script = f"""
set -euo pipefail
PROJECT_ROOT={json.dumps(str(workspace))}
STDIN_RAW={json.dumps(payload)}
source {json.dumps(str(LEDGER_LIB))}
emit_ledger_start {json.dumps(event)}
emit_ledger_complete {json.dumps(event)} 0
"""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(workspace / "home")},
    )


def test_lock_failure_writes_overflow_and_stderr_warning(tmp_path: Path) -> None:
    """When lock cannot be acquired, ledger emits stderr warning and writes to overflow file."""
    workspace = tmp_path / "workspace"
    ledger_dir = workspace / ".gran-maestro"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    # Pre-occupy the lock as a regular file so `mkdir` will always fail.
    (ledger_dir / "hooks-ledger.ndjson.lock").write_text("not a directory\n", encoding="utf-8")

    result = _run_ledger(workspace, json.dumps({"session_id": "sess-overflow"}))

    assert result.returncode == 0, result.stderr
    assert "[mst-ledger] lock contention skipped:" in result.stderr

    overflow_path = ledger_dir / "hooks-ledger.overflow.ndjson"
    assert overflow_path.exists()
    rows = [
        json.loads(line)
        for line in overflow_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 1
    # Both start + complete should land in overflow when lock never frees.
    phases = [row.get("phase") for row in rows]
    assert "start" in phases
    assert "complete" in phases
    for row in rows:
        assert row.get("hook_event") == "SessionStart"


def test_lock_failure_does_not_write_main_ledger(tmp_path: Path) -> None:
    """Lock failure must NOT write to the main ledger file (only overflow)."""
    workspace = tmp_path / "workspace"
    ledger_dir = workspace / ".gran-maestro"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "hooks-ledger.ndjson.lock").write_text("blocker\n", encoding="utf-8")

    result = _run_ledger(workspace, json.dumps({"session_id": "sess-no-main"}))

    assert result.returncode == 0
    main_ledger = ledger_dir / "hooks-ledger.ndjson"
    assert not main_ledger.exists() or main_ledger.read_text(encoding="utf-8") == ""


def test_normal_path_no_overflow_no_stderr(tmp_path: Path) -> None:
    """Successful lock acquisition writes only to main ledger, with no stderr or overflow."""
    workspace = tmp_path / "workspace"

    result = _run_ledger(workspace, json.dumps({"session_id": "sess-normal"}))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""

    ledger_dir = workspace / ".gran-maestro"
    main_ledger = ledger_dir / "hooks-ledger.ndjson"
    overflow = ledger_dir / "hooks-ledger.overflow.ndjson"

    assert main_ledger.exists()
    rows = [json.loads(line) for line in main_ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["phase"] for row in rows] == ["start", "complete"]
    assert not overflow.exists()


def test_overflow_summary_truncated_to_100_chars(tmp_path: Path) -> None:
    """Stderr summary line truncates the row JSON to 100 chars (PID/event identifiable)."""
    workspace = tmp_path / "workspace"
    ledger_dir = workspace / ".gran-maestro"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "hooks-ledger.ndjson.lock").write_text("blocker\n", encoding="utf-8")

    result = _run_ledger(workspace, json.dumps({"session_id": "sess-summary"}))

    assert "[mst-ledger] lock contention skipped:" in result.stderr
    # Each warning line: prefix + 100-char-or-less summary slice + ", see ..."
    for line in result.stderr.strip().splitlines():
        if not line.startswith("[mst-ledger] lock contention skipped:"):
            continue
        prefix = "[mst-ledger] lock contention skipped: "
        # Find ', see ' suffix
        suffix_idx = line.rfind(", see ")
        assert suffix_idx > 0, line
        summary_slice = line[len(prefix):suffix_idx]
        assert len(summary_slice) <= 100, (len(summary_slice), summary_slice)
