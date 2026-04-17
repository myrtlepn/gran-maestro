import importlib.util
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _load_mst_module():
    spec = importlib.util.spec_from_file_location("mst_queue_module", MST_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _enqueue_in_process(workspace: str, skill: str, barrier: multiprocessing.Barrier):
    os.chdir(workspace)
    module = _load_mst_module()
    barrier.wait(timeout=10)
    module.queue_enqueue(
        {
            "skill": skill,
            "args": "--plan PLN-1 -a",
            "source_skill": "mst:plan",
            "source_id": "PLN-1",
            "resource_id": "PLN-1",
            "auto": True,
        }
    )


def test_enqueue_basic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    entry = mst.queue_enqueue({"skill": "mst:request", "args": "--plan PLN-1 -a"})

    queue_path = tmp_path / ".gran-maestro" / "pending.ndjson"
    assert queue_path.exists()

    lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    persisted = json.loads(lines[0])
    assert persisted == entry
    assert len(entry["id"]) == 32
    assert entry["skill"] == "mst:request"
    assert entry["args"] == "--plan PLN-1 -a"
    assert entry["status"] == "queued"
    assert isinstance(entry["created_at"], str) and entry["created_at"]


def test_pop_fifo_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    ids = []
    for i in range(3):
        ids.append(mst.queue_enqueue({"skill": f"mst:req:{i}", "args": f"--index {i}"})["id"])

    first = mst.queue_pop()
    second = mst.queue_pop()
    third = mst.queue_pop()
    fourth = mst.queue_pop()

    assert first and first["id"] == ids[0]
    assert second and second["id"] == ids[1]
    assert third and third["id"] == ids[2]
    assert fourth is None

    running_ids = [entry["id"] for entry in mst.queue_list("running")]
    assert running_ids == ids


def test_complete_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    entry = mst.queue_enqueue({"skill": "mst:request", "args": "--plan PLN-1 -a"})
    popped = mst.queue_pop()
    assert popped and popped["id"] == entry["id"]

    done = mst.queue_complete(entry["id"], result="ok")
    assert done is not None
    assert done["status"] == "done"
    assert done["result"] == "ok"

    done_ids = {item["id"] for item in mst.queue_list("done")}
    queued_ids = {item["id"] for item in mst.queue_list("queued")}
    assert entry["id"] in done_ids
    assert entry["id"] not in queued_ids

    again = mst.queue_complete(entry["id"], result="ignored")
    captured = capsys.readouterr()
    assert again is not None
    assert again["status"] == "done"
    assert again["result"] == "ok"
    assert f"already terminal: {entry['id']}" in captured.err


def test_fail_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    entry = mst.queue_enqueue({"skill": "mst:request", "args": "--plan PLN-1 -a"})
    popped = mst.queue_pop()
    assert popped and popped["id"] == entry["id"]

    failed = mst.queue_fail(entry["id"], error="boom")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"

    failed_ids = {item["id"] for item in mst.queue_list("failed")}
    assert entry["id"] in failed_ids


def test_count_by_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    done_entry = mst.queue_enqueue({"skill": "mst:done", "args": "--x"})
    failed_entry = mst.queue_enqueue({"skill": "mst:fail", "args": "--x"})
    running_entry = mst.queue_enqueue({"skill": "mst:running", "args": "--x"})
    mst.queue_enqueue({"skill": "mst:queued1", "args": "--x"})
    mst.queue_enqueue({"skill": "mst:queued2", "args": "--x"})

    first = mst.queue_pop()
    assert first and first["id"] == done_entry["id"]
    mst.queue_complete(done_entry["id"], result="ok")

    second = mst.queue_pop()
    assert second and second["id"] == failed_entry["id"]
    mst.queue_fail(failed_entry["id"], error="boom")

    third = mst.queue_pop()
    assert third and third["id"] == running_entry["id"]

    assert mst.queue_count() == 2
    assert mst.queue_count("running") == 1
    assert mst.queue_count("done") == 1
    assert mst.queue_count("failed") == 1


def test_pop_empty_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    assert mst.queue_pop() is None

    queue_path = tmp_path / ".gran-maestro" / "pending.ndjson"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("", encoding="utf-8")

    assert mst.queue_pop() is None
    assert mst.queue_count() == 0


def test_concurrent_enqueue(tmp_path):
    workspace = _make_workspace(tmp_path)

    barrier = multiprocessing.Barrier(2)
    p1 = multiprocessing.Process(
        target=_enqueue_in_process,
        args=(str(workspace), "mst:request", barrier),
    )
    p2 = multiprocessing.Process(
        target=_enqueue_in_process,
        args=(str(workspace), "mst:approve", barrier),
    )

    p1.start()
    p2.start()
    p1.join(timeout=15)
    p2.join(timeout=15)

    assert p1.exitcode == 0
    assert p2.exitcode == 0

    queue_path = workspace / ".gran-maestro" / "pending.ndjson"
    lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    entries = [json.loads(line) for line in lines]
    skills = {entry["skill"] for entry in entries}
    assert skills == {"mst:request", "mst:approve"}


def test_workflow_state_no_enqueue_by_default(tmp_path):
    workspace = _make_workspace(tmp_path)

    proc = _run_mst(
        workspace,
        "state",
        "set-workflow",
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--next-skill",
        "mst:request",
        "--next-source",
        "PLN-1",
        "--auto",
        "true",
    )

    assert proc.returncode == 0
    pending_path = workspace / ".gran-maestro" / "pending.ndjson"
    assert not pending_path.exists() or pending_path.read_text(encoding="utf-8").strip() == ""


def test_parse_and_list_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mst = _load_mst_module()

    first = mst.queue_enqueue({"skill": "mst:a", "args": "--a"})
    second = mst.queue_enqueue({"skill": "mst:b", "args": "--b"})

    popped_first = mst.queue_pop()
    assert popped_first and popped_first["id"] == first["id"]
    mst.queue_complete(first["id"], result="ok")

    popped_second = mst.queue_pop()
    assert popped_second and popped_second["id"] == second["id"]

    done_items = mst.queue_list("done")
    running_items = mst.queue_list("running")
    all_items = mst.queue_list("all")

    assert [item["id"] for item in done_items] == [first["id"]]
    assert [item["id"] for item in running_items] == [second["id"]]
    assert len(all_items) == 2


def test_enqueue_rejects_auto_without_dash_a(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    mst = _load_mst_module()
    state_base_dir = workspace / ".gran-maestro"
    monkeypatch.setattr(mst._common, "_skill_state_base_dir", lambda: state_base_dir)

    with pytest.raises(ValueError, match="queue_enqueue: auto=true entry"):
        mst.queue_enqueue(
            {
                "skill": "mst:request",
                "args": "REQ-001",
                "auto": True,
            }
        )

    pending_path = state_base_dir / "pending.ndjson"
    assert not pending_path.exists() or pending_path.read_text(encoding="utf-8").strip() == ""


def test_enqueue_accepts_dash_a(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    mst = _load_mst_module()
    state_base_dir = workspace / ".gran-maestro"
    monkeypatch.setattr(mst._common, "_skill_state_base_dir", lambda: state_base_dir)

    entry = mst.queue_enqueue(
        {
            "skill": "mst:request",
            "args": "-a REQ-001",
            "auto": True,
        }
    )

    pending_path = state_base_dir / "pending.ndjson"
    lines = pending_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    persisted = json.loads(lines[0])
    assert persisted["id"] == entry["id"]
    assert persisted["auto"] is True
    assert persisted["args"] == "-a REQ-001"


def test_enqueue_non_auto_allowed(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    mst = _load_mst_module()
    state_base_dir = workspace / ".gran-maestro"
    monkeypatch.setattr(mst._common, "_skill_state_base_dir", lambda: state_base_dir)

    entry = mst.queue_enqueue(
        {
            "skill": "mst:request",
            "args": "REQ-001",
            "auto": False,
        }
    )

    pending_path = state_base_dir / "pending.ndjson"
    lines = pending_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    persisted = json.loads(lines[0])
    assert persisted["id"] == entry["id"]
    assert persisted["auto"] is False
    assert persisted["args"] == "REQ-001"
