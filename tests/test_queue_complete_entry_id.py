import json

from scripts.mst_cmds import _common


def _queue_workspace(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    return base_dir


def _write_one_entry(path, entry):
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")


def _base_entry(action_id: str, entry_id: str):
    return {
        "id": action_id,
        "entry_id": entry_id,
        "skill": "foo",
        "args": "-a x",
        "source_skill": "",
        "source_id": "",
        "resource_id": "",
        "auto": True,
        "status": "running",
        "created_at": "2026-04-29T00:00:00Z",
        "consumed_at": "2026-04-29T00:01:00Z",
        "completed_at": None,
        "error": None,
        "result": None,
    }


def test_complete_by_action_id(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    pending_path = base_dir / "pending.ndjson"
    entry = _base_entry("legacy-action-id", "e" * 32)
    _write_one_entry(pending_path, entry)

    done = _common.queue_complete("legacy-action-id", result="ok")

    assert done is not None
    assert done["status"] == "done"
    assert done["result"] == "ok"


def test_complete_by_entry_id(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    pending_path = base_dir / "pending.ndjson"
    entry = _base_entry("legacy-action-id", "f" * 32)
    _write_one_entry(pending_path, entry)

    done = _common.queue_complete("f" * 32, result="ok")

    assert done is not None
    assert done["status"] == "done"
    assert done["result"] == "ok"


def test_fail_by_entry_id(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    pending_path = base_dir / "pending.ndjson"
    entry = _base_entry("legacy-action-id", "1" * 32)
    _write_one_entry(pending_path, entry)

    failed = _common.queue_fail("1" * 32, error="boom")

    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"


def test_complete_unknown_warns(tmp_path, monkeypatch, capsys):
    _queue_workspace(tmp_path, monkeypatch)

    output = _common.queue_complete("missing-id")
    captured = capsys.readouterr()

    assert output is None
    assert "[mst] warning: action not found: missing-id" in captured.err
