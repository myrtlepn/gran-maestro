from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _load_mst_module():
    spec = importlib.util.spec_from_file_location("mst_resolver_module", MST_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_workflow_state(workspace: Path, payload: dict, ppid: str = "12345") -> Path:
    path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{ppid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_workflow_state_path(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "next_action": {
                "skill": "mst:request",
                "source": "PLN-572",
                "auto": True,
                "expected_skill": "mst:request",
                "source_skill": "mst:plan",
                "source_id": "PLN-572",
                "auto_mode": True,
            },
        },
    )

    proc = _run_mst(workspace, "resolve-next-action", "--json", env={"MST_STATE_PPID": "12345"})

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "command": "/mst:request --plan PLN-572 -a",
        "source": "workflow_state",
    }


def test_queue_priority_first(tmp_path):
    workspace = _make_workspace(tmp_path)
    enq = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:approve",
        "--args",
        "-a REQ-743",
        "--auto",
        "true",
        "--json",
    )
    assert enq.returncode == 0, enq.stderr
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "next_action": {"expected_skill": "mst:request", "source_id": "PLN-572", "auto_mode": True},
        },
    )

    proc = _run_mst(workspace, "resolve-next-action", "--json", env={"MST_STATE_PPID": "12345"})
    peek = _run_mst(workspace, "queue", "peek", "--json")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"command": "/mst:approve -a REQ-743", "source": "queue"}
    assert json.loads(peek.stdout)["status"] == "queued"


def test_wakeup_hint_stop_recover(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(
        workspace,
        "resolve-next-action",
        "--wakeup-hint",
        "stop-recover",
        "--json",
        env={"RETURN_TO_SKILL": "plan", "RETURN_TO_STEP": "3"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "command": "/mst:plan (continue from step 3)",
        "source": "wakeup-hint:stop-recover",
    }


def test_wakeup_hint_stop_recover_from_snapshot(tmp_path):
    workspace = _make_workspace(tmp_path)
    snapshot_path = workspace / ".gran-maestro" / "state" / "cid-001" / "snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps({"returnTo": {"skill": "request", "step": 2}}, ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run_mst(
        workspace,
        "resolve-next-action",
        "--conversation-id",
        "cid-001",
        "--wakeup-hint",
        "stop-recover",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "command": "/mst:request (continue from step 2)",
        "source": "wakeup-hint:stop-recover",
    }


def test_noop_exit(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(workspace, "resolve-next-action", "--json")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"command": None, "source": "no-op"}


def test_conversation_id_fallback(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("MST_TRANSCRIPT_PATH", raising=False)
    mst = _load_mst_module()
    from scripts.mst_cmds import resolver

    assert resolver.resolve_conversation_id(None) is None
    result = resolver.resolve_result(
        type("Args", (), {"conversation_id": None, "wakeup_hint": None, "enqueue": False, "dry_run": False})()
    )

    assert result == {"command": None, "source": "no-op"}


def test_workflow_state_enqueue_option(tmp_path):
    workspace = _make_workspace(tmp_path)
    _write_workflow_state(
        workspace,
        {
            "workflow_active": True,
            "next_action": {
                "expected_skill": "mst:request",
                "source_skill": "mst:plan",
                "source_id": "PLN-572",
                "auto_mode": True,
            },
        },
    )

    proc = _run_mst(
        workspace,
        "resolve-next-action",
        "--enqueue",
        "--json",
        env={"MST_STATE_PPID": "12345"},
    )
    peek = _run_mst(workspace, "queue", "peek", "--json")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "command": "/mst:request --plan PLN-572 -a",
        "source": "workflow_state",
    }
    entry = json.loads(peek.stdout)
    assert entry["skill"] == "mst:request"
    assert entry["args"] == "--plan PLN-572 -a"
    assert entry["auto"] is True


def test_latency_p95(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    mst = _load_mst_module()
    from scripts.mst_cmds import resolver

    for index in range(1000):
        mst.queue_enqueue({"skill": "mst:request", "args": f"--plan PLN-{index}"})

    args = type("Args", (), {"conversation_id": None, "wakeup_hint": None, "enqueue": False, "dry_run": False})()
    samples = []
    for _ in range(100):
        start = time.perf_counter()
        result = resolver.resolve_result(args)
        samples.append((time.perf_counter() - start) * 1000)
        assert result["source"] == "queue"

    p95 = sorted(samples)[94]
    assert p95 < 100


def test_e2e_latency_p95(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    mst = _load_mst_module()
    from scripts.mst_cmds import resolver

    for index in range(1000):
        mst.queue_enqueue({"skill": "mst:request", "args": f"--plan PLN-{index}"})

    args = type("Args", (), {"conversation_id": None, "wakeup_hint": None, "enqueue": False, "dry_run": False})()
    samples = []
    for _ in range(100):
        start = time.perf_counter()
        result = resolver.resolve_result(args)
        popped = mst.queue_pop()
        assert popped is not None
        completed = mst.queue_complete(popped["id"], result="ok")
        samples.append((time.perf_counter() - start) * 1000)

        assert result["source"] == "queue"
        assert result["command"] == f"/{popped['skill']} {popped['args']}"
        assert completed is not None
        assert completed["status"] == "done"

    p95 = sorted(samples)[94]
    assert p95 < 100, f"resolver + queue pop/complete p95 latency was {p95:.2f}ms"
