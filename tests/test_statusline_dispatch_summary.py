import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"


def _run_statusline(workspace: Path, payload: str = "{}") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_dispatch_state(path: Path, task_id: str, heartbeat: datetime) -> None:
    payload = {
        "task_id": task_id,
        "phase": "running",
        "provider": "codex",
        "model": "gpt-test",
        "last_heartbeat": heartbeat.isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_state(workspace: Path, payload: dict) -> Path:
    state_dir = workspace / ".gran-maestro" / "tmp"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"mst-state-{os.getpid()}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return state_path


def _write_transcript(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _last_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines[-1]


def test_statusline_includes_dispatch_summary_prefix(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    _write_dispatch_state(run_dir / "test-01.json", "test-01", now - timedelta(seconds=30))
    _write_dispatch_state(run_dir / "test-02.json", "test-02", now - timedelta(seconds=90))

    result = _run_statusline(workspace)
    assert result.returncode == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    last_line = lines[-1]

    match = re.search(r"MST 2 run · oldest (\d+)s", last_line)
    assert match, last_line
    oldest = int(match.group(1))
    assert oldest >= 80


def test_statusline_omits_dispatch_summary_when_no_run_files(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.search(r"MST \d+ run · oldest \d+s", last_line) is None


def test_state_priority_uses_prefixed_context_id_over_transcript(tmp_path):
    workspace = tmp_path / "workspace"
    transcript_path = workspace / "session.transcript"
    _write_state(
        workspace,
        {
            "current_skill": "mst:plan",
            "active_req": "REQ-651-01",
            "next_action": {"source_id": "", "source": ""},
            "updated_at": "2026-04-18T00:00:00Z",
        },
    )
    _write_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-04-18T00:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Skill",
                            "input": {"skill": "mst:request", "args": "--req REQ-999"},
                        }
                    ]
                },
            }
        ],
    )

    payload = json.dumps({"transcript_path": str(transcript_path)})
    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert "(REQ-651-01)" in last_line
    assert "request(" not in last_line


def test_state_uses_next_action_source_id_with_prefixed_plan_id(tmp_path):
    workspace = tmp_path / "workspace"
    _write_state(
        workspace,
        {
            "current_skill": "mst:plan",
            "active_req": "",
            "next_action": {"source_id": "PLN-493-ALT", "source": ""},
            "updated_at": "2026-04-18T00:00:00Z",
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert "(PLN-493-ALT)" in last_line


def test_transcript_pending_skill_extracts_prefixed_context_id_only(tmp_path):
    workspace = tmp_path / "workspace"
    transcript_path = workspace / "pending.transcript"
    _write_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-04-18T00:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_2",
                            "name": "proxy_Skill",
                            "input": {
                                "skill": "mst:plan",
                                "args": "--plan PLN-493-ALT --note temporary free text",
                            },
                        }
                    ]
                },
            }
        ],
    )

    payload = json.dumps({"transcript_path": str(transcript_path)})
    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert "plan(" in last_line
    assert "(PLN-493-ALT)" in last_line
    assert "temporary free text" not in last_line


def test_transcript_free_text_args_are_not_exposed_without_context_id(tmp_path):
    workspace = tmp_path / "workspace"
    transcript_path = workspace / "free-text.transcript"
    _write_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-04-18T00:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_3",
                            "name": "Skill",
                            "input": {
                                "skill": "mst:plan",
                                "args": "--note this should never be printed on hud",
                            },
                        }
                    ]
                },
            }
        ],
    )

    payload = json.dumps({"transcript_path": str(transcript_path)})
    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert "plan(" in last_line
    assert "this should never be printed on hud" not in last_line
    assert "(REQ-" not in last_line
    assert "(PLN-" not in last_line


def test_statusline_falls_back_to_idle_on_broken_transcript(tmp_path):
    workspace = tmp_path / "workspace"
    transcript_path = workspace / "broken.transcript"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("this is not jsonl\n", encoding="utf-8")

    payload = json.dumps({"transcript_path": str(transcript_path)})
    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert last_line == "MST idle"
