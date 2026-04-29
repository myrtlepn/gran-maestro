import json
import re

from scripts.mst_cmds import _common


HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")


def _queue_workspace(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    return base_dir


def test_build_entry_has_entry_id(tmp_path, monkeypatch):
    _queue_workspace(tmp_path, monkeypatch)

    entry = _common._queue_build_entry({"skill": "foo", "args": "-a x", "auto": True})

    assert "entry_id" in entry
    assert isinstance(entry["entry_id"], str)
    assert HEX_32_RE.fullmatch(entry["entry_id"])


def test_legacy_entry_gets_uuid(tmp_path, monkeypatch):
    _queue_workspace(tmp_path, monkeypatch)

    parsed = _common._queue_parse_entries(
        [
            json.dumps(
                {
                    "id": "legacy-id",
                    "skill": "foo",
                    "args": "-a x",
                    "auto": True,
                    "status": "queued",
                }
            )
        ]
    )

    assert len(parsed) == 1
    assert HEX_32_RE.fullmatch(parsed[0]["entry_id"])


def test_entry_id_persisted_after_compact(tmp_path, monkeypatch):
    base_dir = _queue_workspace(tmp_path, monkeypatch)
    pending_path = base_dir / "pending.ndjson"
    pending_path.write_text(
        json.dumps(
            {
                "id": "legacy-id",
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

    def _mutator(entries):
        entries[0]["result"] = "mutated"
        return entries, entries[0]

    _common._queue_compact(_mutator)

    persisted = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(persisted) == 1
    assert HEX_32_RE.fullmatch(persisted[0]["entry_id"])
    assert persisted[0]["result"] == "mutated"
