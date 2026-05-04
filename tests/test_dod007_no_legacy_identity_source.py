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
SID = "MST-AGI-030-20260504T170000000Z-dod007a1"
LEGACY_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


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


def _legacy_payload() -> dict:
    return {
        "session_id": LEGACY_UUID,
        "sessionId": "legacy-sessionId-alias",
        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        "owner_ppid": 818181,
        "owner_session_id": "legacy-owner-session",
    }


def _clean_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["HOME"] = str(workspace / "home")
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["MST_POLICY_HOME"] = str(workspace / "policy")
    env["CLAUDE_CONFIG_DIR"] = str(workspace / "home" / ".claude")
    env["MST_STATE_PPID"] = "818181"
    env["MST_SNAPSHOT_SESSION_ID"] = "legacy-snapshot-alias"
    env["CLAUDE_CODE_SESSION_ID"] = LEGACY_UUID
    env["MST_CONTEXT_JSON"] = json.dumps(_legacy_payload(), separators=(",", ":"))
    env["MST_HOOK_STDIN_RAW"] = json.dumps(_legacy_payload(), separators=(",", ":"))
    for key in ("MST_SESSION_ID",):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _run(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=env or _clean_env(workspace),
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


def test_legacy_only_session_resolve_is_no_mutation_structured_non_success() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        sentinel = workspace / ".gran-maestro" / "sentinel.txt"
        sentinel.write_text("unchanged\n", encoding="utf-8")
        policy_home = workspace / "policy"
        policy_home.mkdir()
        before = _snapshot(workspace / ".gran-maestro", policy_home)

        result = _run(workspace, "session", "resolve", "--json")

        assert result.returncode != 0
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        payload = _read_json_from_stdout(result.stdout)
        assert payload["status"] in {"error", "blocked", "non_success"}
        assert payload["code"] in {"missing_canonical_mst_session_id", "legacy_identity_not_canonical_source"}
        assert payload.get("created_new_session") is not True
        assert payload.get("canonical_mst_session_id") in (None, "")
        assert payload.get("legacy_diagnostics")
        assert LEGACY_UUID not in str(payload.get("canonical_mst_session_id", ""))
        assert TRANSCRIPT_UUID not in str(payload.get("canonical_mst_session_id", ""))
        assert not (workspace / ".gran-maestro" / "sessions").exists()
        assert not (policy_home / "ledger-heads").exists()


def test_canonical_env_wins_over_conflicting_legacy_session_values() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        policy_home = workspace / "policy"
        policy_home.mkdir()
        before = _snapshot(workspace / ".gran-maestro", policy_home)
        env = _clean_env(workspace, {"MST_SESSION_ID": SID})

        result = _run(workspace, "session", "resolve", "--json", env=env)

        assert result.returncode == 0, result.stderr
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        payload = _read_json_from_stdout(result.stdout)
        assert payload["mst_session_id"] == SID
        assert payload.get("session_id") in (SID, None)
        assert payload["source"] == "env:MST_SESSION_ID"
        assert payload.get("legacy_diagnostics", {}).get("hook_session_id") == LEGACY_UUID
        assert payload.get("legacy_diagnostics", {}).get("hook_transcript_stem") == TRANSCRIPT_UUID
        assert LEGACY_UUID not in {payload.get("mst_session_id"), payload.get("session_id")}
        assert not (workspace / ".gran-maestro" / "sessions" / LEGACY_UUID).exists()
        assert not (workspace / ".gran-maestro" / "sessions" / TRANSCRIPT_UUID).exists()


def main() -> int:
    for test in (
        test_legacy_only_session_resolve_is_no_mutation_structured_non_success,
        test_canonical_env_wins_over_conflicting_legacy_session_values,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
