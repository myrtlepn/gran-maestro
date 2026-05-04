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
ROOT = "AGI-030"
SID = "MST-AGI-030-20260504T170000000Z-dod007s1"
OTHER_SID = "MST-AGI-030-20260504T170000000Z-dod007s2"
LEGACY_PPID = "818181"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        "session_id": CLAUDE_SESSION_ID,
        "sessionId": "legacy-sessionId-alias",
        "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
        "owner_ppid": int(LEGACY_PPID),
        "owner_session_id": "legacy-owner-session",
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
    env["MST_STATE_PPID"] = LEGACY_PPID
    env["MST_SNAPSHOT_SESSION_ID"] = "legacy-snapshot-alias"
    env["MST_CONTEXT_JSON"] = json.dumps(payload or _legacy_payload(), separators=(",", ":"))
    env["MST_HOOK_STDIN_RAW"] = json.dumps(payload or _legacy_payload(), separators=(",", ":"))
    env.pop("MST_SESSION_ID", None)
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


def _read_json_from_stdout(stdout: str) -> dict:
    for index, line in enumerate(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(stdout.splitlines()[index:]))
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _seed_legacy_only_state(workspace: Path) -> None:
    base = workspace / ".gran-maestro"
    _write_json(
        base / "agile" / ROOT / "session.json",
        {
            "id": ROOT,
            "status": "active",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "legacy-owner-session",
            "session_id": CLAUDE_SESSION_ID,
            "sessionId": "legacy-sessionId-alias",
        },
    )
    _write_json(
        base / "state" / LEGACY_PPID / "snapshot.json",
        {
            "sessionId": LEGACY_PPID,
            "currentSkill": "mst:request",
            "currentStep": 1,
            "totalSteps": 3,
            "status": "active",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "legacy-owner-session",
        },
    )
    _write_json(
        base / "state" / "legacy-snapshot-alias" / "snapshot.json",
        {
            "sessionId": "legacy-snapshot-alias",
            "currentSkill": "mst:recover",
            "status": "active",
        },
    )


def test_legacy_only_state_mutation_commands_are_structured_no_mutation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        policy_home.mkdir()
        _seed_legacy_only_state(workspace)
        before = _snapshot(workspace / ".gran-maestro", policy_home)

        commands = [
            ("state", "set", "--skill", "mst:request", "--step", "1", "--total", "3"),
            ("state", "get"),
            ("state", "clear"),
            ("state", "recover", ROOT),
        ]
        for args in commands:
            result = _run(workspace, *args)
            assert result.returncode != 0, args
            assert _snapshot(workspace / ".gran-maestro", policy_home) == before
            payload = _read_json_from_stdout(result.stdout)
            assert payload["status"] in {"error", "blocked", "non_success"}
            assert payload["code"] in {"missing_canonical_mst_session_id", "legacy_identity_not_canonical_source"}
            assert payload.get("created_new_session") is not True
            assert payload.get("legacy_diagnostics")

        assert not (workspace / ".gran-maestro" / "state" / CLAUDE_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "state" / TRANSCRIPT_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "state" / "legacy-snapshot-alias" / "history.ndjson").exists()
        assert not (policy_home / "ledger-heads").exists()


def test_canonical_env_context_conflict_fails_without_repairing_to_legacy_aliases() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        policy_home.mkdir()
        _write_json(workspace / ".gran-maestro" / "sentinel.json", {"status": "unchanged"})
        before = _snapshot(workspace / ".gran-maestro", policy_home)
        env = _env(workspace, {"MST_SESSION_ID": SID}, payload=_legacy_payload(mst_session_id=OTHER_SID))

        result = _run(workspace, "state", "set", "--skill", "mst:request", "--step", "1", "--total", "3", env=env)

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        assert "mismatch" in combined
        assert not (workspace / ".gran-maestro" / "state" / SID).exists()
        assert not (workspace / ".gran-maestro" / "state" / OTHER_SID).exists()
        assert not (workspace / ".gran-maestro" / "state" / CLAUDE_SESSION_ID).exists()


def main() -> int:
    for test in (
        test_legacy_only_state_mutation_commands_are_structured_no_mutation,
        test_canonical_env_context_conflict_fails_without_repairing_to_legacy_aliases,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
