from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
LOOP_SCRIPT = REPO_ROOT / "scripts" / "mst-loop.sh"
SESSION_ID = "MST-REQ-777-20260523T000000000Z-codex7777"


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )


def test_codex_supervisor_queue_drain_records_host_context(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    env = {
        "MST_SESSION_ID": SESSION_ID,
        "CODEX_SESSION_ID": "codex-session-777",
        "CODEX_PERMISSION_MODE": "full-auto",
    }

    enqueued = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:request",
        "--args",
        "--plan PLN-777 -a",
        "--auto",
        "true",
        "--json",
        env=env,
    )
    assert enqueued.returncode == 0, enqueued.stderr

    drained = _run_mst(
        workspace,
        "queue",
        "drain-headless",
        "--host",
        "codex",
        "--json",
        env=env,
    )
    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    action = payload["action"]

    assert payload["status"] == "drained"
    assert action["status"] == "done"
    assert action["supervisor_host"] == "codex"
    assert action["supervisor_tick_source"] == "supervisor"
    assert action["host_context"]["host"] == "codex"
    assert action["host_context"]["mst_session_id"] == SESSION_ID
    assert action["host_context"]["host_session_id"] == "codex-session-777"
    assert action["host_context"]["adapter"]["uses_queue_supervisor"] is True
    assert action["host_context"]["adapter"]["uses_claude_hooks"] is False

    evidence = json.loads(Path(action["completion_evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "done"
    assert evidence["host_context"]["host"] == "codex"
    assert evidence["supervisor_tick"]["host"] == "codex"
    assert evidence["supervisor_tick"]["tick_source"] == "supervisor"
    assert evidence["supervisor_tick"]["skill"] == "mst:request"


def test_mst_loop_can_select_codex_supervisor_host(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(REPO_ROOT)

    proc = subprocess.run(
        [
            "bash",
            str(LOOP_SCRIPT),
            "--dry-run",
            "--max-iterations",
            "1",
            "--sleep",
            "0",
            "--host",
            "codex",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "queue empty" in proc.stdout

    enqueued = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:review",
        "--args",
        "REQ-777",
        "--json",
    )
    assert enqueued.returncode == 0, enqueued.stderr

    proc = subprocess.run(
        [
            "bash",
            str(LOOP_SCRIPT),
            "--dry-run",
            "--max-iterations",
            "1",
            "--sleep",
            "0",
            "--host",
            "codex",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "queue drain-headless --host codex --json" in proc.stdout


def test_codex_supervisor_execute_invokes_runner_with_host_context(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    runner_input = tmp_path / "runner-input.json"
    runner = tmp_path / "fake_runner.py"
    runner.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                f"payload_path = {str(runner_input)!r}",
                "payload = json.load(sys.stdin)",
                "with open(payload_path, 'w', encoding='utf-8') as handle:",
                "    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)",
                "print(json.dumps({'terminal_status': 'done', 'result': 'executed'}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = {
        "MST_SESSION_ID": SESSION_ID,
        "CODEX_SESSION_ID": "codex-session-777",
        "CODEX_PERMISSION_MODE": "full-auto",
    }

    enqueued = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:approve",
        "--args",
        "REQ-777 -a",
        "--auto",
        "true",
        "--json",
        env=env,
    )
    assert enqueued.returncode == 0, enqueued.stderr

    drained = _run_mst(
        workspace,
        "queue",
        "drain-headless",
        "--host",
        "codex",
        "--execute",
        "--runner",
        f"{sys.executable} {runner}",
        "--json",
        env=env,
    )
    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    action = payload["action"]

    assert action["status"] == "done"
    assert action["result"] == "executed"
    assert action["execution"]["mode"] == "runner"
    assert action["execution"]["status"] == "done"
    assert action["execution"]["exit_code"] == 0
    assert action["host_context"]["host"] == "codex"
    assert action["host_context"]["adapter"]["uses_queue_supervisor"] is True

    runner_payload = json.loads(runner_input.read_text(encoding="utf-8"))
    assert runner_payload["host_context"]["host"] == "codex"
    assert runner_payload["host_context"]["mst_session_id"] == SESSION_ID
    assert runner_payload["invocation"]["skill"] == "mst:approve"
    assert runner_payload["invocation"]["args"] == "REQ-777 -a"

    evidence = json.loads(Path(action["completion_evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "done"
    assert evidence["execution"]["parsed"]["result"] == "executed"


def test_mst_loop_can_enable_codex_supervisor_execute_runner(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(REPO_ROOT)

    enqueued = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:accept",
        "--args",
        "REQ-777",
        "--json",
    )
    assert enqueued.returncode == 0, enqueued.stderr

    proc = subprocess.run(
        [
            "bash",
            str(LOOP_SCRIPT),
            "--dry-run",
            "--max-iterations",
            "1",
            "--sleep",
            "0",
            "--host",
            "codex",
            "--execute",
            "--runner",
            "python3 fake_runner.py",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "--host codex --execute --runner python3\\ fake_runner.py --json" in proc.stdout


def test_codex_supervisor_executes_core_mst_workflow_queue(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    calls_path = tmp_path / "runner-calls.json"
    runner = tmp_path / "workflow_runner.py"
    runner.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                f"calls_path = Path({str(calls_path)!r})",
                "payload = json.load(sys.stdin)",
                "calls = json.loads(calls_path.read_text(encoding='utf-8')) if calls_path.exists() else []",
                "calls.append(payload)",
                "calls_path.write_text(json.dumps(calls, ensure_ascii=False, sort_keys=True), encoding='utf-8')",
                "skill = payload['invocation']['skill']",
                "print(json.dumps({'terminal_status': 'done', 'result': f'executed:{skill}'}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = {
        "MST_SESSION_ID": SESSION_ID,
        "CODEX_SESSION_ID": "codex-session-777",
        "CODEX_PERMISSION_MODE": "full-auto",
    }
    workflow = [
        ("mst:plan", "-a Codex supervisor workflow smoke", True),
        ("mst:request", "--plan PLN-777 -a Codex supervisor workflow smoke", True),
        ("mst:approve", "REQ-777 -a", True),
        ("mst:review", "REQ-777 --auto", False),
        ("mst:accept", "REQ-777", False),
        ("mst:recover", "REQ-777", False),
    ]

    for skill, skill_args, auto in workflow:
        enqueued = _run_mst(
            workspace,
            "queue",
            "enqueue",
            "--skill",
            skill,
            "--args",
            skill_args,
            "--auto",
            "true" if auto else "false",
            "--json",
            env=env,
        )
        assert enqueued.returncode == 0, enqueued.stderr

    drained_actions = []
    for _skill, _skill_args, _auto in workflow:
        drained = _run_mst(
            workspace,
            "queue",
            "drain-headless",
            "--host",
            "codex",
            "--execute",
            "--runner",
            f"{sys.executable} {runner}",
            "--json",
            env=env,
        )
        assert drained.returncode == 0, drained.stderr
        payload = json.loads(drained.stdout)
        assert payload["status"] == "drained"
        assert payload["action"]["status"] == "done"
        assert payload["action"]["supervisor_host"] == "codex"
        assert payload["action"]["supervisor_tick_source"] == "supervisor"
        drained_actions.append(payload["action"])

    assert [action["skill"] for action in drained_actions] == [item[0] for item in workflow]
    assert [action["result"] for action in drained_actions] == [
        f"executed:{skill}" for skill, _skill_args, _auto in workflow
    ]

    calls = json.loads(calls_path.read_text(encoding="utf-8"))
    assert [call["invocation"]["skill"] for call in calls] == [item[0] for item in workflow]
    assert all(call["host_context"]["host"] == "codex" for call in calls)
    assert all(call["host_context"]["adapter"]["uses_queue_supervisor"] is True for call in calls)
    assert all(call["host_context"]["adapter"]["uses_claude_hooks"] is False for call in calls)
