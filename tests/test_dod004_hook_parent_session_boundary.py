from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_START_HOOK = REPO_ROOT / "hooks" / "mst-session-init.sh"
PRE_TOOL_USE_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
USER_PROMPT_HOOK = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"
PARENT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-807-20260503T131853000Z-r4n8vd1c"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEGACY_PPID = "818181"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    for name in ("scripts", "templates"):
        target = path / name
        if not target.exists():
            target.symlink_to(REPO_ROOT / name, target_is_directory=True)


def _clean_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["HOME"] = str(workspace / "home")
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["CLAUDE_CONFIG_DIR"] = str(workspace / "home" / ".claude")
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {
                        "input_tokens": 100_000,
                        "cache_read_input_tokens": 20_000,
                        "cache_creation_input_tokens": 10_000,
                    },
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _parent_payload(event_name: str) -> dict:
    payload = {
        "hook_event_name": event_name,
        "mst_session_id": PARENT_SESSION_ID,
        "session_id": CLAUDE_SESSION_ID,
        "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
        "owner_ppid": int(LEGACY_PPID),
        "owner_session_id": "owner-diagnostic-only",
    }
    if event_name == "PreToolUse":
        payload.update({"tool_name": "Skill", "tool_input": {"skill_name": "mst:request", "args": "REQ-807"}})
    return payload


def _identity_paths(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    prefixes = ("state/", "sessions/", "run/", "active-flow/")
    paths = set()
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(base))
        if rel.startswith(prefixes) or rel.startswith("tmp/mst-state-"):
            paths.add(rel)
    return paths


def test_session_start_pretool_stop_and_user_prompt_keep_parent_structured_session() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        parent_env = {"MST_SESSION_ID": PARENT_SESSION_ID, "MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"}

        session_start = _run_hook(workspace, SESSION_START_HOOK, _parent_payload("SessionStart"), env=parent_env)
        pre_tool = _run_hook(workspace, PRE_TOOL_USE_HOOK, _parent_payload("PreToolUse"), env=parent_env)
        _write_json(
            workspace / ".gran-maestro" / "state" / PARENT_SESSION_ID / "snapshot.json",
            {
                "schema_version": 1,
                "mst_session_id": PARENT_SESSION_ID,
                "root_mst_id": "AGI-030",
                "sessionId": PARENT_SESSION_ID,
                "currentSkill": "mst:request",
                "currentStep": 1,
                "totalSteps": 1,
            },
        )
        stop = _run_hook(
            workspace,
            STOP_HOOK,
            _parent_payload("Stop"),
            env={**parent_env, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        )
        _write_json(
            workspace / ".gran-maestro" / "tmp" / f"mst-state-{PARENT_SESSION_ID}.json",
            {
                "schema_version": 1,
                "mst_session_id": PARENT_SESSION_ID,
                "root_mst_id": "AGI-030",
                "workflow_active": True,
                "next_action": {"auto_mode": True},
            },
        )
        transcript = workspace / "transcript.jsonl"
        _write_transcript(transcript)
        user_prompt_payload = _parent_payload("UserPromptSubmit")
        user_prompt_payload["transcript_path"] = str(transcript)
        user_prompt = _run_hook(workspace, USER_PROMPT_HOOK, user_prompt_payload, env=parent_env)

        assert session_start.returncode == 0, session_start.stderr
        assert pre_tool.returncode == 0, pre_tool.stderr
        assert stop.returncode == 0, stop.stderr
        assert user_prompt.returncode == 0, user_prompt.stderr
        identity_paths = _identity_paths(workspace)
        assert any(path.startswith(f"sessions/{PARENT_SESSION_ID}/") for path in identity_paths)
        assert f"state/{PARENT_SESSION_ID}/snapshot.json" in identity_paths
        assert f"tmp/mst-state-{PARENT_SESSION_ID}.json" in identity_paths
        assert not any(CLAUDE_SESSION_ID in path or TRANSCRIPT_SESSION_ID in path for path in identity_paths)
        assert not any(LEGACY_PPID in path or "/default/" in f"/{path}/" for path in identity_paths)


def test_claude_session_transcript_ppid_and_owner_metadata_are_diagnostic_only() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _identity_paths(workspace)
        legacy_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Skill",
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "owner-diagnostic-only",
            "tool_input": {"skill_name": "mst:request", "args": "REQ-807"},
        }

        result = _run_hook(
            workspace,
            PRE_TOOL_USE_HOOK,
            legacy_payload,
            env={"MST_STATE_PPID": LEGACY_PPID, "MST_PRE_TOOL_USE_TEST_BOOTSTRAP": "1"},
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode == 0, result.stderr
        assert _identity_paths(workspace) == before
        assert not UUID_V4_RE.search(combined)
        assert not (workspace / ".gran-maestro" / "sessions" / CLAUDE_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "sessions" / TRANSCRIPT_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "state" / LEGACY_PPID).exists()
        assert not (workspace / ".gran-maestro" / "tmp" / f"mst-state-{LEGACY_PPID}.json").exists()


def test_missing_parent_hooks_produce_no_uuid_default_or_ppid_identity_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _identity_paths(workspace)
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "owner-diagnostic-only",
        }

        session_start = _run_hook(workspace, SESSION_START_HOOK, payload, env={"MST_STATE_PPID": LEGACY_PPID})
        stop = _run_hook(
            workspace,
            STOP_HOOK,
            {**payload, "hook_event_name": "Stop"},
            env={"MST_STATE_PPID": LEGACY_PPID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        )

        assert session_start.returncode == 0, session_start.stderr
        assert stop.returncode == 0, stop.stderr
        assert _identity_paths(workspace) == before
        assert not (workspace / ".gran-maestro" / "sessions" / CLAUDE_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "sessions" / TRANSCRIPT_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "state" / "default").exists()
        assert not (workspace / ".gran-maestro" / "state" / LEGACY_PPID).exists()
        assert not (workspace / ".gran-maestro" / "tmp" / f"mst-state-{LEGACY_PPID}.json").exists()


def test_hook_env_stdin_mismatch_fails_closed_without_identity_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before_hashes = _hashes(workspace)
        mismatch_payload = {
            "hook_event_name": "SessionStart",
            "mst_session_id": STALE_SESSION_ID,
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "owner-diagnostic-only",
        }

        result = _run_hook(workspace, SESSION_START_HOOK, mismatch_payload, env={"MST_SESSION_ID": PARENT_SESSION_ID})

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _hashes(workspace) == before_hashes
        assert "mismatch" in combined
        assert PARENT_SESSION_ID not in "\n".join(_identity_paths(workspace))
        assert STALE_SESSION_ID not in "\n".join(_identity_paths(workspace))


def main() -> int:
    tests = [
        test_session_start_pretool_stop_and_user_prompt_keep_parent_structured_session,
        test_claude_session_transcript_ppid_and_owner_metadata_are_diagnostic_only,
        test_missing_parent_hooks_produce_no_uuid_default_or_ppid_identity_mutation,
        test_hook_env_stdin_mismatch_fails_closed_without_identity_mutation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
