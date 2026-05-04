from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_START_HOOK = REPO_ROOT / "hooks" / "mst-session-init.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
USER_PROMPT_HOOK = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"
SID = "MST-AGI-030-20260504T170000000Z-dod007h1"
OTHER_SID = "MST-AGI-030-20260504T170000000Z-dod007h2"
LEGACY_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEGACY_PPID = "818181"
RESOURCE_IDS = {"AGI-030", "PLN-638", "REQ-811"}


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _legacy_payload(*, mst_session_id: str | None = None) -> dict:
    payload = {
        "hook_event_name": "SessionStart",
        "session_id": LEGACY_UUID,
        "sessionId": "legacy-sessionId-alias",
        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        "owner_ppid": int(LEGACY_PPID),
        "owner_session_id": "legacy-owner-session",
        "resource_id": "REQ-811",
        "plan_id": "PLN-638",
    }
    if mst_session_id is not None:
        payload["mst_session_id"] = mst_session_id
    return payload


def _env(workspace: Path, extra: dict[str, str] | None = None, *, payload: dict | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["HOME"] = str(workspace / "home")
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["MST_POLICY_HOME"] = str(workspace / "policy")
    env["CLAUDE_CONFIG_DIR"] = str(workspace / "home" / ".claude")
    env["CLAUDE_CODE_SESSION_ID"] = LEGACY_UUID
    env["MST_STATE_PPID"] = LEGACY_PPID
    env["MST_HOOK_STDIN_RAW"] = json.dumps(payload or _legacy_payload(), separators=(",", ":"))
    env.pop("MST_SESSION_ID", None)
    env.pop("MST_CONTEXT_JSON", None)
    if extra:
        env.update(extra)
    return env


def _run(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=env or _env(workspace),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


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
        env=env or _env(workspace),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _read_json_from_stdout(stdout: str) -> dict:
    for index, line in enumerate(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(stdout.splitlines()[index:]))
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _assert_no_resource_or_diagnostic_identity_artifacts(base: Path, policy_home: Path) -> None:
    forbidden = RESOURCE_IDS | {LEGACY_UUID, TRANSCRIPT_UUID, LEGACY_PPID, "legacy-sessionId-alias", "default"}
    for value in forbidden:
        assert not (base / "sessions" / value).exists()
        assert not (base / "state" / value).exists()
        assert not (base / "run" / f"{value}.json").exists()
        assert not (base / "active-flow" / f"{value}.json").exists()
        assert not (policy_home / "ledger-heads" / f"{value}.head").exists()


def test_dispatch_legacy_only_register_and_heartbeat_are_no_mutation_non_success() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        base = workspace / ".gran-maestro"
        policy_home = workspace / "policy"
        base.mkdir()
        policy_home.mkdir()
        before = _snapshot(base, policy_home)

        commands = [
            (
                "dispatch",
                "register",
                "--task-id",
                "dod007-task",
                "--pid",
                str(os.getpid()),
                "--provider",
                "codex",
                "--model",
                "test-model",
                "--worktree-dir",
                str(workspace),
                "--started-by-pid",
                LEGACY_PPID,
            ),
            ("dispatch", "heartbeat", "--task-id", "dod007-task", "--final", "--exit-code", "0"),
        ]
        for args in commands:
            result = _run(workspace, *args)
            assert result.returncode != 0, args
            assert _snapshot(base, policy_home) == before
            payload = _read_json_from_stdout(result.stdout)
            assert payload["status"] in {"error", "blocked", "non_success"}
            assert payload["code"] in {"missing_canonical_mst_session_id", "legacy_identity_not_canonical_source"}
            assert payload.get("created_new_session") is not True
            diagnostics = payload.get("legacy_diagnostics")
            assert diagnostics
            assert diagnostics.get("MST_STATE_PPID") == LEGACY_PPID
            assert diagnostics.get("hook_session_id") == LEGACY_UUID

        assert not (base / "run" / "dod007-task.json").exists()
        _assert_no_resource_or_diagnostic_identity_artifacts(base, policy_home)


def test_history_commands_reject_legacy_session_selectors_without_fallback_or_creation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        base = workspace / ".gran-maestro"
        policy_home = workspace / "policy"
        base.mkdir()
        policy_home.mkdir()
        sentinel = base / "sentinel.txt"
        sentinel.write_text("unchanged\n", encoding="utf-8")
        before = _snapshot(base, policy_home)

        for value in (LEGACY_UUID, TRANSCRIPT_UUID, "legacy-sessionId-alias", "818181"):
            for command in ("log", "verify", "head"):
                result = _run(workspace, "history", command, "--session", value, "--json")
                assert result.returncode != 0
                payload = _read_json_from_stdout(result.stdout)
                assert payload["status"] == "error"
                assert payload["code"] == "invalid_mst_session_id"
                assert payload.get("session_id") == value
                assert _snapshot(base, policy_home) == before

        _assert_no_resource_or_diagnostic_identity_artifacts(base, policy_home)


def test_hook_legacy_only_stdin_values_are_diagnostic_only_no_mutation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        base = workspace / ".gran-maestro"
        policy_home = workspace / "policy"
        base.mkdir()
        policy_home.mkdir()
        before = _snapshot(base, policy_home)

        payload = _legacy_payload(mst_session_id=SID)
        session_start = _run_hook(workspace, SESSION_START_HOOK, payload)
        stop = _run_hook(
            workspace,
            STOP_HOOK,
            {**payload, "hook_event_name": "Stop"},
            env=_env(workspace, {"MST_STOP_HOOK_CLEANUP_DISABLE": "1"}, payload=payload),
        )
        user_prompt = _run_hook(workspace, USER_PROMPT_HOOK, {**payload, "hook_event_name": "UserPromptSubmit"})

        combined = "\n".join(result.stdout + "\n" + result.stderr for result in (session_start, stop, user_prompt))
        assert session_start.returncode == 0, session_start.stderr
        assert stop.returncode == 0, stop.stderr
        assert user_prompt.returncode == 0, user_prompt.stderr
        assert _snapshot(base, policy_home) == before
        assert "ignored without inherited MST_SESSION_ID" in combined
        _assert_no_resource_or_diagnostic_identity_artifacts(base, policy_home)
        assert not (base / "sessions" / SID).exists()
        assert not (base / "state" / SID).exists()


def test_hook_env_stdin_mismatch_fails_closed_without_legacy_repair() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        base = workspace / ".gran-maestro"
        policy_home = workspace / "policy"
        base.mkdir()
        policy_home.mkdir()
        before = _snapshot(base, policy_home)
        payload = _legacy_payload(mst_session_id=OTHER_SID)

        result = _run_hook(
            workspace,
            SESSION_START_HOOK,
            payload,
            env=_env(workspace, {"MST_SESSION_ID": SID}, payload=payload),
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _snapshot(base, policy_home) == before
        assert "mismatch" in combined
        _assert_no_resource_or_diagnostic_identity_artifacts(base, policy_home)
        assert not (base / "sessions" / SID).exists()
        assert not (base / "sessions" / OTHER_SID).exists()


def main() -> int:
    for test in (
        test_dispatch_legacy_only_register_and_heartbeat_are_no_mutation_non_success,
        test_history_commands_reject_legacy_session_selectors_without_fallback_or_creation,
        test_hook_legacy_only_stdin_values_are_diagnostic_only_no_mutation,
        test_hook_env_stdin_mismatch_fails_closed_without_legacy_repair,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
