import json
import multiprocessing
import os
import uuid
from pathlib import Path

import pytest


if os.name != "nt":
    try:
        FORK_CONTEXT = multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover
        FORK_CONTEXT = None
else:
    FORK_CONTEXT = None


def _pop_in_process(workspace_str: str):
    os.chdir(workspace_str)
    from scripts.mst_cmds import _common

    _common.BASE_DIR = Path(workspace_str) / ".gran-maestro"
    popped = _common.queue_pop()
    return None if popped is None else popped.get("entry_id")


@pytest.mark.skipif(
    FORK_CONTEXT is None,
    reason="fork-based process pop concurrency is unstable in this environment",
)
def test_concurrent_pop_no_duplicates(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    pending_path = base_dir / "pending.ndjson"

    entries = []
    for i in range(100):
        entries.append(
            {
                "id": uuid.uuid4().hex,
                "entry_id": uuid.uuid4().hex,
                "skill": "foo",
                "args": f"-a x-{i}",
                "source_skill": "",
                "source_id": "",
                "resource_id": "",
                "auto": True,
                "status": "queued",
                "created_at": "2026-04-29T00:00:00Z",
                "consumed_at": None,
                "completed_at": None,
                "error": None,
                "result": None,
            }
        )

    pending_path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )

    with FORK_CONTEXT.Pool(processes=20) as pool:
        results = pool.map(_pop_in_process, [str(tmp_path)] * 100)

    popped_entry_ids = [value for value in results if value is not None]
    assert len(popped_entry_ids) == 100
    assert len(set(popped_entry_ids)) == 100

    post_entries = [
        json.loads(line)
        for line in pending_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    running_entry_ids = [entry["entry_id"] for entry in post_entries if entry.get("status") == "running"]

    assert len(running_entry_ids) == 100
    assert set(running_entry_ids) == set(popped_entry_ids)
