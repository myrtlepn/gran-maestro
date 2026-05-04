from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_START_HOOK = REPO_ROOT / "hooks" / "mst-session-init.sh"
PRE_TOOL_USE_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEGACY_PPID = "818181"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(workspace: Path) -> None:
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    for name in ("scripts", "templates"):
        target = workspace / name
        if not target.exists():
            target.symlink_to(REPO_ROOT / name, target_is_directory=True)


def _env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["HOME"] = str(workspace / "home")
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["CLAUDE_CONFIG_DIR"] = str(workspace / "home" / ".claude")
    env["MST_SESSION_ID"] = SID
    env["MST_PRE_TOOL_USE_TEST_BOOTSTRAP"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def _payload(event_name: str) -> dict:
    payload = {
        "hook_event_name": event_name,
        "mst_session_id": SID,
        "session_id": CLAUDE_SESSION_ID,
        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        "owner_ppid": int(LEGACY_PPID),
        "owner_session_id": "owner-diagnostic-only",
    }
    if event_name == "PreToolUse":
        payload.update(
            {
                "tool_name": "Skill",
                "tool_input": {"skill_name": "mst:request", "args": "REQ-808"},
            }
        )
    return payload


def _run_hook(workspace: Path, hook_path: Path, payload: dict, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(hook_path)],
        cwd=workspace,
        input=json.dumps(payload, ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        env=_env(workspace, extra_env),
        check=False,
        timeout=30,
    )


def _history_rows(workspace: Path) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(MST_SCRIPT), "history", "log", "--session", SID, "--json"],
        cwd=workspace,
        env=_env(workspace),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_hook_boundaries_append_canonical_events_to_parent_session_ledger() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        _init_workspace(workspace)

        session_start = _run_hook(workspace, SESSION_START_HOOK, _payload("SessionStart"))
        pre_tool = _run_hook(workspace, PRE_TOOL_USE_HOOK, _payload("PreToolUse"))
        stop = _run_hook(
            workspace,
            STOP_HOOK,
            _payload("Stop"),
            {"MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        )

        assert session_start.returncode == 0, session_start.stderr
        assert pre_tool.returncode == 0, pre_tool.stderr
        assert stop.returncode == 0, stop.stderr

        rows = _history_rows(workspace)
        event_types = [row["event_type"] for row in rows]
        assert "hook.SessionStart.start" in event_types
        assert "hook.SessionStart.complete" in event_types
        assert "hook.PreToolUse.start" in event_types
        assert "hook.PreToolUse.complete" in event_types
        assert "hook.Stop.start" in event_types
        assert "hook.Stop.complete" in event_types
        assert all(row["mst_session_id"] == SID for row in rows)
        assert all(row["root_mst_id"] == "AGI-030" for row in rows)
        assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))

        identity_paths = "\n".join(
            str(path.relative_to(workspace / ".gran-maestro"))
            for path in (workspace / ".gran-maestro").rglob("*")
            if path.is_file()
        )
        assert CLAUDE_SESSION_ID not in identity_paths
        assert TRANSCRIPT_UUID not in identity_paths
        assert LEGACY_PPID not in identity_paths
        assert "/default/" not in f"/{identity_paths}/"


def main() -> int:
    test_hook_boundaries_append_canonical_events_to_parent_session_ledger()
    print("PASS test_hook_boundaries_append_canonical_events_to_parent_session_ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
