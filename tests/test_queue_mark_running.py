import json

from scripts.mst_cmds import _common


def _queue_workspace(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    return base_dir


def test_mark_running_success(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    entry_id = "a" * 32
    pending_path = base_dir / "pending.ndjson"
    pending_path.write_text(
        json.dumps(
            {
                "id": "legacy-id",
                "entry_id": entry_id,
                "skill": "foo",
                "args": "-a x",
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
        + "\n",
        encoding="utf-8",
    )

    updated = _common.queue_mark_running(entry_id)

    assert updated is not None
    assert updated["status"] == "running"
    assert updated["consumed_at"] is not None


def test_mark_running_idempotent(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    entry_id = "b" * 32
    pending_path = base_dir / "pending.ndjson"
    pending_path.write_text(
        json.dumps(
            {
                "id": "legacy-id",
                "entry_id": entry_id,
                "skill": "foo",
                "args": "-a x",
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
        + "\n",
        encoding="utf-8",
    )

    first = _common.queue_mark_running(entry_id)
    second = _common.queue_mark_running(entry_id)

    assert first is not None
    assert first["status"] == "running"
    assert second is None


def test_mark_running_unknown_returns_none(tmp_path, monkeypatch):
    _queue_workspace(tmp_path, monkeypatch)

    assert _common.queue_mark_running("c" * 32) is None
