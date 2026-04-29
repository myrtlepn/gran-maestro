from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"


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
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(PRE_TOOL_HOOK)],
        cwd=cwd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def test_block_json_includes_machine_reason_and_human_summary_together(tmp_path: Path) -> None:
    req_id = "REQ-7456"
    write_request(tmp_path, req_id, detected_base="main")
    result = run_hook(
        tmp_path,
        {
            "tool_name": "Skill",
            "tool_input": {"skill_name": "mst:approve", "args": req_id},
        },
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert isinstance(payload.get("reason"), str)
    assert payload["reason"]
    assert "details" in payload
    assert "summary" in payload["details"]
    assert re.search(r"[가-힣]", payload["details"]["summary"])

