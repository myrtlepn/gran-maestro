from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"

SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-9222-222222222222"
SID_C = "33333333-3333-4333-a333-333333333333"


@pytest.fixture(autouse=True)
def isolated_policy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy_home = tmp_path / ".claude" / "gran-maestro-policy"
    policy_home.mkdir(parents=True)
    monkeypatch.setenv("MST_POLICY_HOME", str(policy_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_hook(hook: Path, cwd: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    return subprocess.run(
        ["bash", str(hook)],
        cwd=cwd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def hook_payload(
    session_id: str = SID_A,
    tool_name: str = "Bash",
    tool_input: dict | None = None,
) -> dict:
    if tool_input is None:
        tool_input = {"command": "true"}
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def write_snapshot(root: Path, stdin_sid: str = SID_A, snapshot_sid: str = SID_B) -> Path:
    snapshot_path = root / ".gran-maestro" / "state" / stdin_sid / "snapshot.json"
    write_json(
        snapshot_path,
        {
            "sessionId": snapshot_sid,
            "currentSkill": "mst:dispatch",
            "currentStep": 1,
            "totalSteps": 1,
            "status": "completed",
        },
    )
    return snapshot_path


def write_request(root: Path, durable_sid: str | None = SID_C) -> Path:
    request: dict = {
        "id": "REQ-723",
        "status": "executing",
        "current_phase": 2,
        "tasks": [{"id": "T02"}],
    }
    if durable_sid is not None:
        request["owner_session_id"] = durable_sid
    request_path = root / ".gran-maestro" / "requests" / "REQ-723" / "request.json"
    write_json(request_path, request)
    return request_path


def read_flow_events(root: Path, session_id: str = SID_A) -> list[dict]:
    path = root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mismatch_events(root: Path, session_id: str = SID_A) -> list[dict]:
    return [
        event
        for event in read_flow_events(root, session_id)
        if event.get("event_type") == "session_id_mismatch"
    ]


def test_stop_hook_legacy_payload_is_diagnostic_only_without_canonical_parent(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_B)
    write_request(tmp_path, durable_sid=SID_C)

    result = run_hook(STOP_HOOK, tmp_path, hook_payload())

    assert result.returncode == 0
    assert "legacy session_id ignored without canonical MST_SESSION_ID/mst_session_id" in result.stderr
    assert "[session-id mismatch]" not in result.stderr


def test_stop_hook_legacy_payload_does_not_append_canonical_mismatch_event(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_B)
    write_request(tmp_path, durable_sid=SID_C)

    result = run_hook(STOP_HOOK, tmp_path, hook_payload())
    events = mismatch_events(tmp_path)

    assert result.returncode == 0
    assert events == []


def test_matching_legacy_artifacts_still_do_not_authorize_stop_hook(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_A)
    write_request(tmp_path, durable_sid=SID_A)

    result = run_hook(STOP_HOOK, tmp_path, hook_payload())

    assert result.returncode == 0
    assert "[session-id mismatch]" not in result.stderr
    assert mismatch_events(tmp_path) == []
    payload = json.loads(result.stdout)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "missing canonical MST_SESSION_ID; stop hook fail-open without mutation"


def test_missing_durable_owner_session_id_silent_skip(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_B)
    write_request(tmp_path, durable_sid=None)

    result = run_hook(STOP_HOOK, tmp_path, hook_payload())

    assert result.returncode == 0
    assert "[session-id mismatch]" not in result.stderr
    assert mismatch_events(tmp_path) == []


def test_pre_tool_use_legacy_payload_is_diagnostic_only_without_canonical_parent(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_B)
    write_request(tmp_path, durable_sid=SID_C)

    # RV-001 F-01: T07 phase gate가 mutating tool에 spec.accepted/override 요구. session_id mismatch warning 의도 검증을 위해 read-only tool 사용. (PLN-560 PAC-19)
    payload = hook_payload(tool_name="Read", tool_input={"file_path": "README.md"})
    result = run_hook(PRE_TOOL_HOOK, tmp_path, payload)
    events = mismatch_events(tmp_path)

    assert result.returncode == 0
    # REQ-946 explicit-only contract: hook payload session_id is legacy
    # diagnostic input, not authority that may select or mutate a session.
    assert "legacy session_id ignored without canonical MST_SESSION_ID/mst_session_id" in result.stderr
    assert "[session-id mismatch]" not in result.stderr
    assert events == []


def test_pre_tool_use_legacy_diagnostic_repeats_without_creating_dedup_state(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snapshot_sid=SID_B)
    write_request(tmp_path, durable_sid=SID_C)

    # RV-001 F-01: T07 phase gate가 mutating tool에 spec.accepted/override 요구. session_id mismatch warning 의도 검증을 위해 read-only tool 사용. (PLN-560 PAC-19)
    payload = hook_payload(tool_name="Read", tool_input={"file_path": "README.md"})
    first = run_hook(PRE_TOOL_HOOK, tmp_path, payload)
    second = run_hook(PRE_TOOL_HOOK, tmp_path, payload)

    assert first.returncode == 0
    assert second.returncode == 0
    # A no-authority ordinary hook cannot persist a dedup marker: both calls
    # stay diagnostic-only and leave canonical flow history untouched.
    diagnostic = "legacy session_id ignored without canonical MST_SESSION_ID/mst_session_id"
    assert first.stderr.count(diagnostic) == 1
    assert second.stderr.count(diagnostic) == 1
    assert mismatch_events(tmp_path) == []
