from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_START_HOOK = REPO_ROOT / "hooks" / "mst-session-init.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
USER_PROMPT_HOOK = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"
SID = "MST-AGI-030-20260504T160133000Z-dod006a1"
OTHER_SID = "MST-AGI-030-20260504T160133000Z-dod006b2"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


def _clean_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["HOME"] = str(workspace / "home")
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["CLAUDE_CONFIG_DIR"] = str(workspace / "home" / ".claude")
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW", "MST_STATE_PPID"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _run_hook(
    workspace: Path,
    hook_path: Path,
    payload: dict,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(hook_path)],
        cwd=workspace,
        input=json.dumps(payload, ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        env=_clean_env(workspace, env),
        check=False,
        timeout=30,
    )


def _payload(event_name: str, *, sid: str = SID) -> dict:
    return {
        "hook_event_name": event_name,
        "mst_session_id": sid,
        "session_id": CLAUDE_SESSION_ID,
        "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
        "owner_ppid": 818181,
        "owner_session_id": "diagnostic-only",
    }


def test_hook_stdin_mst_session_id_without_env_is_diagnostic_only_no_mutation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        _init_workspace(workspace)
        before = _hashes(workspace)

        session_start = _run_hook(workspace, SESSION_START_HOOK, _payload("SessionStart"))
        stop = _run_hook(
            workspace,
            STOP_HOOK,
            _payload("Stop"),
            env={"MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        )
        user_prompt = _run_hook(workspace, USER_PROMPT_HOOK, _payload("UserPromptSubmit"))

        combined = "\n".join(
            result.stdout + "\n" + result.stderr for result in (session_start, stop, user_prompt)
        )
        assert session_start.returncode == 0, session_start.stderr
        assert stop.returncode == 0, stop.stderr
        assert user_prompt.returncode == 0, user_prompt.stderr
        assert _hashes(workspace) == before
        assert "ignored without inherited MST_SESSION_ID" in combined
        assert not (workspace / ".gran-maestro" / "sessions" / SID).exists()
        assert not (workspace / ".gran-maestro" / "state" / SID).exists()


def test_hook_env_stdin_mismatch_still_fails_closed() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        _init_workspace(workspace)
        before = _hashes(workspace)

        result = _run_hook(workspace, SESSION_START_HOOK, _payload("SessionStart", sid=OTHER_SID), env={"MST_SESSION_ID": SID})

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _hashes(workspace) == before
        assert "mismatch" in combined


def main() -> int:
    test_hook_stdin_mst_session_id_without_env_is_diagnostic_only_no_mutation()
    test_hook_env_stdin_mismatch_still_fails_closed()
    print("PASS test_hook_stdin_mst_session_id_without_env_is_diagnostic_only_no_mutation")
    print("PASS test_hook_env_stdin_mismatch_still_fails_closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
