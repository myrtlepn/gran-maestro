"""REQ-710/T02: hook judge hard timeout regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from tests.fixtures.session_helper import init_project_root

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = PROJECT_ROOT / "hooks" / "mst-stop-hook.sh"


def _session_id() -> str:
    return str(uuid.uuid4())


def _flow_detail_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"


def _read_flow_detail_records(project_root: Path, session_id: str) -> list[dict]:
    path = _flow_detail_path(project_root, session_id)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _hook_payload(project_root: Path, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": "Stop",
        "cwd": str(project_root),
        "permission_mode": "allowlist",
        "last_assistant_message": "작업을 마무리합니다.",
    }


def _run_hook(
    project_root: Path,
    payload: dict,
    *,
    budget_ms: int,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], float]:
    env = {
        **os.environ,
        "MST_FLOW_DISABLE_ATEXIT": "1",
        **(extra_env or {}),
    }
    stdin_json = json.dumps(payload, ensure_ascii=False)
    timeout_s = (budget_ms / 1000.0) + 1.0
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=stdin_json,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        cwd=project_root,
        check=False,
        env=env,
    )
    elapsed = time.monotonic() - started
    return result, elapsed


def test_config_default_hook_judge_timeout_ms():
    result = subprocess.run(
        ["python3", "scripts/mst.py", "config", "get", "hook.judge_timeout_ms"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=True,
    )

    assert result.stdout.strip() == "500"


def test_slow_path_fail_open_and_event(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = _session_id()

    result, _elapsed = _run_hook(
        project_root,
        _hook_payload(project_root, session_id),
        budget_ms=500,
        extra_env={
            "MST_HOOK_JUDGE_TIMEOUT_MS": "500",
            "MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS": "2000",
        },
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["decision"] == "approve"

    event = _read_flow_detail_records(project_root, session_id)[-1]
    assert event["event_type"] == "judge_timeout"
    assert event["data"]["budget_ms"] == 500
    assert event["data"]["fail_open"] is True
    assert event["data"]["hook"] == "stop-hook"
    assert event["data"]["observed_ms_approx"] <= 2500


def test_fast_path_no_timeout_event(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = _session_id()

    before_records = _read_flow_detail_records(project_root, session_id)
    result, _elapsed = _run_hook(
        project_root,
        _hook_payload(project_root, session_id),
        budget_ms=500,
    )
    after_records = _read_flow_detail_records(project_root, session_id)

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["decision"] == "approve"

    new_records = after_records[len(before_records):]
    assert not any(record.get("event_type") == "judge_timeout" for record in new_records), (
        f"fast path must not emit judge_timeout: {new_records}"
    )


def test_config_override_shorter_budget(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = _session_id()

    result, _elapsed = _run_hook(
        project_root,
        _hook_payload(project_root, session_id),
        budget_ms=100,
        extra_env={
            "MST_HOOK_JUDGE_TIMEOUT_MS": "100",
            "MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS": "150",
        },
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["decision"] == "approve"

    event = _read_flow_detail_records(project_root, session_id)[-1]
    assert event["event_type"] == "judge_timeout"
    assert event["data"]["budget_ms"] == 100
    assert event["data"]["fail_open"] is True
    assert event["data"]["hook"] == "stop-hook"
    assert event["data"]["observed_ms_approx"] <= 500
