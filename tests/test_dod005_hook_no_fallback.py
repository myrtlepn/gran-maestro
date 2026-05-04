from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_START_HOOK = REPO_ROOT / "hooks" / "mst-session-init.sh"
PRE_TOOL_USE_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
USER_PROMPT_HOOK = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"
SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
OTHER_SID = "MST-REQ-808-20260504T010203004Z-q1w2e3r4"
INVALID_SID = "../../MST-AGI-030"
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
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _legacy_payload(event_name: str, mst_session_id: str | None = None) -> dict:
    payload = {
        "hook_event_name": event_name,
        "session_id": CLAUDE_SESSION_ID,
        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        "owner_ppid": int(LEGACY_PPID),
        "owner_session_id": "owner-diagnostic-only",
    }
    if mst_session_id is not None:
        payload["mst_session_id"] = mst_session_id
    if event_name == "PreToolUse":
        payload.update({"tool_name": "Skill", "tool_input": {"skill_name": "mst:request"}})
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


def test_missing_invalid_and_legacy_only_hook_identity_do_not_mutate_ledgers() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        _init_workspace(workspace)
        base = workspace / ".gran-maestro"
        home = workspace / "home"
        before = _snapshot(base, home)

        cases = [
            (SESSION_START_HOOK, _legacy_payload("SessionStart"), {"MST_STATE_PPID": LEGACY_PPID}, 0),
            (PRE_TOOL_USE_HOOK, _legacy_payload("PreToolUse"), {"MST_STATE_PPID": LEGACY_PPID, "MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"}, 0),
            (STOP_HOOK, _legacy_payload("Stop"), {"MST_STATE_PPID": LEGACY_PPID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"}, 0),
            (USER_PROMPT_HOOK, _legacy_payload("UserPromptSubmit"), {"MST_STATE_PPID": LEGACY_PPID}, 0),
            (SESSION_START_HOOK, _legacy_payload("SessionStart"), {"MST_SESSION_ID": INVALID_SID}, 0),
            (PRE_TOOL_USE_HOOK, _legacy_payload("PreToolUse"), {"MST_SESSION_ID": INVALID_SID, "MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"}, 0),
            (STOP_HOOK, _legacy_payload("Stop"), {"MST_SESSION_ID": INVALID_SID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"}, 0),
            (SESSION_START_HOOK, _legacy_payload("SessionStart", OTHER_SID), {"MST_SESSION_ID": SID}, 1),
            (PRE_TOOL_USE_HOOK, _legacy_payload("PreToolUse", OTHER_SID), {"MST_SESSION_ID": SID, "MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"}, 1),
            (STOP_HOOK, _legacy_payload("Stop", OTHER_SID), {"MST_SESSION_ID": SID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"}, 1),
        ]

        for hook_path, payload, env, expected in cases:
            result = _run_hook(workspace, hook_path, payload, env)
            if expected == 0:
                assert result.returncode == 0, result.stderr
            else:
                assert result.returncode != 0
            assert _snapshot(base, home) == before

        assert not (base / "sessions").exists()
        assert not (base / "hooks-ledger.ndjson").exists()
        assert not (home / ".claude" / "gran-maestro-policy" / "ledger-heads").exists()
        assert not (base / "state" / LEGACY_PPID).exists()
        assert not (base / "state" / "default").exists()


def main() -> int:
    test_missing_invalid_and_legacy_only_hook_identity_do_not_mutate_ledgers()
    print("PASS test_missing_invalid_and_legacy_only_hook_identity_do_not_mutate_ledgers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
