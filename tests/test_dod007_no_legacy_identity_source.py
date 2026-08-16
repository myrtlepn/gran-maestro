from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.mst_cmds.session import parse_mst_session_id


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-AGI-030-20260504T170000000Z-dod007a1"
OTHER_SID = "MST-REQ-822-20260506T010203456Z-dod007b2"
LEGACY_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CANONICAL_SESSION_RE = re.compile(
    r"^MST-(AGI|PLN|REQ|DBG|EXP|DSC|IDN|DES|INTENT|CAP|FC|REF)-\d+-\d{8}T\d{9}Z-[a-z0-9]{8,}$"
)


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


def _read_json_from_output(*streams: str) -> dict:
    combined = "\n".join(stream for stream in streams if stream)
    for index, line in enumerate(combined.splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(combined.splitlines()[index:]))
    raise AssertionError(f"output did not contain JSON object:\n{combined}")


def _assert_pac5_non_success_payload(payload: dict, *, code: str | None = None) -> None:
    assert payload["status"] == "error"
    if code is not None:
        assert payload["code"] == code
    assert isinstance(payload.get("message"), str) and payload["message"].strip()
    assert payload.get("canonical_mst_session_id") is None
    assert isinstance(payload.get("legacy_diagnostics"), dict)
    assert payload.get("mutation_performed") is False
    assert payload.get("created_new_session") is not True


@pytest.mark.parametrize(
    "value",
    [
        SID,
        "MST-REQ-822-20260506T010203456Z-dod007b2",
        "MST-INTENT-297-20260506T235959999Z-abc123xyz",
        "MST-FC-12-20260101T000000000Z-a1b2c3d4",
    ],
)
def test_canonical_mst_session_id_grammar_accepts_full_anchored_valid_samples(value: str) -> None:
    assert CANONICAL_SESSION_RE.fullmatch(value)
    parsed = parse_mst_session_id(value)
    assert parsed.mst_session_id == value
    assert parsed.started_at_compact.endswith("Z")
    assert len(parsed.random) >= 8


@pytest.mark.parametrize(
    "value",
    [
        LEGACY_UUID,
        "1234567890",
        "MST-REQ-822-20260506T010203456Z-short",
        "MST-REQ-822-20260506T010203456+0900-abcdef12",
        "MST-REQ-822-20260506T010203456Z-../../escape",
    ],
)
def test_invalid_canonical_mst_session_id_samples_emit_pac5_json_without_mutation(value: str) -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        policy_home = workspace / "policy"
        policy_home.mkdir()
        before = _snapshot(workspace / ".gran-maestro", policy_home)
        env = _clean_env(workspace, {"MST_SESSION_ID": value, "MST_CONTEXT_JSON": ""})

        result = _run(workspace, "session", "resolve", "--json", env=env)

        assert result.returncode != 0
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        payload = _read_json_from_output(result.stdout, result.stderr)
        _assert_pac5_non_success_payload(payload)


def test_env_and_structured_canonical_mismatch_is_pac5_json_no_mutation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        policy_home = workspace / "policy"
        policy_home.mkdir()
        before = _snapshot(workspace / ".gran-maestro", policy_home)
        context = {**_legacy_payload(), "mst_session_id": OTHER_SID}
        env = _clean_env(workspace, {"MST_SESSION_ID": SID, "MST_CONTEXT_JSON": json.dumps(context)})

        result = _run(workspace, "session", "resolve", "--json", env=env)

        assert result.returncode != 0
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        payload = _read_json_from_output(result.stdout, result.stderr)
        _assert_pac5_non_success_payload(payload, code="mst_session_id_mismatch")
        assert SID not in str(payload.get("canonical_mst_session_id", ""))
        assert OTHER_SID not in str(payload.get("canonical_mst_session_id", ""))


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
        _assert_pac5_non_success_payload(payload)
        assert payload["code"] in {"missing_canonical_mst_session_id", "legacy_identity_not_canonical_source"}
        assert payload.get("legacy_diagnostics")
        assert LEGACY_UUID not in str(payload.get("canonical_mst_session_id", ""))
        assert TRANSCRIPT_UUID not in str(payload.get("canonical_mst_session_id", ""))
        assert not (workspace / ".gran-maestro" / "sessions").exists()
        assert not (policy_home / "ledger-heads").exists()


def test_canonical_env_with_legacy_only_context_fails_closed_without_mutation() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        policy_home = workspace / "policy"
        policy_home.mkdir()
        before = _snapshot(workspace / ".gran-maestro", policy_home)
        env = _clean_env(workspace, {"MST_SESSION_ID": SID})

        result = _run(workspace, "session", "resolve", "--json", env=env)

        # REQ-946 strict transport rejects an accompanying legacy-only
        # MST_CONTEXT_JSON even when the environment carries a canonical SID.
        assert result.returncode != 0
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before
        payload = _read_json_from_stdout(result.stdout)
        _assert_pac5_non_success_payload(payload, code="legacy_identity_not_canonical_source")
        assert payload.get("legacy_diagnostics", {}).get("hook_session_id") == LEGACY_UUID
        assert payload.get("legacy_diagnostics", {}).get("hook_transcript_stem") == TRANSCRIPT_UUID
        assert payload.get("canonical_mst_session_id") is None
        assert not (workspace / ".gran-maestro" / "sessions" / LEGACY_UUID).exists()
        assert not (workspace / ".gran-maestro" / "sessions" / TRANSCRIPT_UUID).exists()


def main() -> int:
    for test in (
        test_legacy_only_session_resolve_is_no_mutation_structured_non_success,
        test_canonical_env_with_legacy_only_context_fails_closed_without_mutation,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
