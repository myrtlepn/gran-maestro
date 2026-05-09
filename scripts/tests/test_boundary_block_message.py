from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
TEST_MST_SESSION_ID = "MST-AGI-030-20260509T000000000Z-test0000"


def write_request(root: Path, req_id: str, *, detected_base: str) -> None:
    request_path = root / ".gran-maestro" / "requests" / req_id / "request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(
        json.dumps(
            {
                "id": req_id,
                "status": "phase2_execution",
                "current_phase": 2,
                "detected_base": detected_base,
                "tasks": [{"id": "T01"}],
            }
        ),
        encoding="utf-8",
    )


def run_hook(cwd: Path, payload: dict, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.setdefault("MST_SESSION_ID", TEST_MST_SESSION_ID)
    merged_env.setdefault("MST_POLICY_HOME", str(cwd / ".gran-maestro" / "policy"))
    if env:
        merged_env.update(env)
    hook_payload = {**payload, "mst_session_id": merged_env["MST_SESSION_ID"]}
    return subprocess.run(
        ["bash", str(PRE_TOOL_HOOK)],
        cwd=cwd,
        input=json.dumps(hook_payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def test_block_message_contains_reason_and_all_detail_fields(tmp_path: Path) -> None:
    req_id = "REQ-7452"
    write_request(tmp_path, req_id, detected_base="main")
    result = run_hook(
        tmp_path,
        {
            "tool_name": "Skill",
            "tool_input": {"skill_name": "mst:approve", "args": req_id},
        },
    )
    payload = json.loads(result.stdout)
    details = payload["details"]

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == "base_not_verified"
    assert details["summary"]
    assert details["recovery_command"]
    assert details["retry_criterion"] == "복구 명령 1회 실행 후 동일 도구 재호출"
    assert details["log_location"] == ".gran-maestro/logs/boundary-guard.log"
    assert "--path" in details["recovery_command"]
    assert "--branch" in details["recovery_command"]
    assert "--base \"main\"" in details["recovery_command"]
