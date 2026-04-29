from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import confirm


SID = "73000000-0000-4000-8000-000000000101"


def _setup_workspace(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    project_root = tmp_path / "workspace"
    home = tmp_path / "home"
    (project_root / ".gran-maestro" / "sessions").mkdir(parents=True)
    home.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(_common, "BASE_DIR", project_root / ".gran-maestro")
    for key in list(confirm.os.environ):
        if key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_")):
            monkeypatch.delenv(key, raising=False)
    return project_root, home


def _write_pending(project_root: Path, sid: str, payload: dict) -> Path:
    path = project_root / ".gran-maestro" / "sessions" / sid / "pending-confirm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _pending_payload(
    *,
    pending_id: str = "cf_X",
    tool: str = "Bash",
    args_sha256: str = "a" * 64,
    consumed: object = False,
    expires_at: str = "2999-01-01T00:00:00Z",
) -> dict:
    return {
        "id": pending_id,
        "tool": tool,
        "args_canonical": {"command": "echo guarded"},
        "args_sha256": args_sha256,
        "created_at": "2026-04-29T00:00:00Z",
        "expires_at": expires_at,
        "consumed": consumed,
    }


def _events(project_root: Path, sid: str) -> list[dict]:
    path = project_root / ".gran-maestro" / "sessions" / sid / "history.ndjson"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line)["event"])
    return rows


def _append_event(project_root: Path, home: Path, sid: str, event: dict) -> None:
    assert confirm.hooklib.append_event_after_verified(project_root, home, sid, event) == 0


def _grant_count(project_root: Path, sid: str, pending_id: str) -> int:
    return sum(
        1
        for event in _events(project_root, sid)
        if event["type"] == "override_granted" and event["pending_id"] == pending_id
    )


def test_grant_success(tmp_path, monkeypatch, capsys) -> None:
    project_root, _home = _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(confirm.os, "isatty", lambda fd: fd == 0)
    _write_pending(
        project_root,
        SID,
        {
            "id": "cf_X",
            "tool": "Bash",
            "args_canonical": {"command": "echo guarded"},
            "args_sha256": "a" * 64,
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )

    status = confirm.cmd_confirm(argparse.Namespace(pending_id="cf_X", list=False))

    captured = capsys.readouterr()
    assert status == 0
    assert "override granted" in captured.out
    assert captured.err == ""
    events = _events(project_root, SID)
    assert events[-1]["type"] == "override_granted"
    assert events[-1]["pending_id"] == "cf_X"
    assert events[-1]["tool"] == "Bash"
    assert events[-1]["args_sha256"] == "a" * 64


def test_idempotent_grant(tmp_path, monkeypatch, capsys) -> None:
    project_root, _home = _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(confirm.os, "isatty", lambda fd: fd == 0)
    _write_pending(
        project_root,
        SID,
        {
            "id": "cf_X",
            "tool": "Bash",
            "args_canonical": {"command": "echo guarded"},
            "args_sha256": "a" * 64,
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )

    first_status = confirm.cmd_confirm(argparse.Namespace(pending_id="cf_X", list=False))
    first_capture = capsys.readouterr()
    second_status = confirm.cmd_confirm(argparse.Namespace(pending_id="cf_X", list=False))
    second_capture = capsys.readouterr()

    assert first_status == 0
    assert "override granted" in first_capture.out
    assert second_status == 0
    assert "already granted (cf_X)" in second_capture.out
    events = _events(project_root, SID)
    assert sum(1 for event in events if event["type"] == "override_granted" and event["pending_id"] == "cf_X") == 1


def test_concurrent_grant_is_idempotent(tmp_path, monkeypatch, capsys) -> None:
    project_root, _home = _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(confirm.os, "isatty", lambda fd: fd == 0)
    _write_pending(
        project_root,
        SID,
        {
            "id": "cf_X",
            "tool": "Bash",
            "args_canonical": {"command": "echo guarded"},
            "args_sha256": "a" * 64,
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )

    def run_confirm() -> int:
        return confirm.cmd_confirm(argparse.Namespace(pending_id="cf_X", list=False))

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _index: run_confirm(), range(2)))

    capsys.readouterr()
    assert statuses == [0, 0]
    events = _events(project_root, SID)
    assert sum(1 for event in events if event["type"] == "override_granted" and event["pending_id"] == "cf_X") == 1


def test_tty_required(tmp_path, monkeypatch, capsys) -> None:
    project_root, _home = _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(confirm.os, "isatty", lambda fd: fd == 0)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "llm-session")
    _write_pending(
        project_root,
        SID,
        {
            "id": "cf_X",
            "tool": "Bash",
            "args_canonical": {"command": "echo guarded"},
            "args_sha256": "b" * 64,
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )

    status = confirm.cmd_confirm(argparse.Namespace(pending_id="cf_X", list=False))

    captured = capsys.readouterr()
    assert status != 0
    assert "TTY provenance required" in captured.err


def test_list(tmp_path, monkeypatch, capsys) -> None:
    project_root, _home = _setup_workspace(tmp_path, monkeypatch)
    _write_pending(
        project_root,
        SID,
        {
            "id": "cf_one",
            "tool": "Bash",
            "args_canonical": {"command": "echo one"},
            "args_sha256": "1234567890abcdef",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )
    _write_pending(
        project_root,
        "73000000-0000-4000-8000-000000000102",
        {
            "id": "cf_two",
            "tool": "Write",
            "args_canonical": {"file_path": "x"},
            "args_sha256": "abcdef1234567890",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": "2999-01-01T00:00:00Z",
            "consumed": False,
        },
    )

    status = confirm.cmd_confirm(argparse.Namespace(pending_id=None, list=True))

    captured = capsys.readouterr()
    assert status == 0
    assert "id tool args_sha256 expires_at" in captured.out
    assert "cf_one Bash 1234567890ab 2999-01-01T00:00:00Z" in captured.out
    assert "cf_two Write abcdef123456 2999-01-01T00:00:00Z" in captured.out


def test_append_override_granted_rejects_consumed_pending(tmp_path, monkeypatch) -> None:
    project_root, home = _setup_workspace(tmp_path, monkeypatch)
    stale_payload = _pending_payload(consumed=False)
    _write_pending(project_root, SID, _pending_payload(consumed=True))
    _append_event(
        project_root,
        home,
        SID,
        {
            "args_sha256": stale_payload["args_sha256"],
            "pending_id": stale_payload["id"],
            "timestamp": "2026-04-29T00:00:01Z",
            "tool": stale_payload["tool"],
            "type": "override_granted",
        },
    )
    _append_event(
        project_root,
        home,
        SID,
        {
            "args_sha256": stale_payload["args_sha256"],
            "pending_id": stale_payload["id"],
            "timestamp": "2026-04-29T00:00:02Z",
            "tool": stale_payload["tool"],
            "type": "override_consumed",
        },
    )

    status, append_state = confirm._append_override_granted(project_root, home, SID, stale_payload)

    assert status == 1
    assert append_state == confirm.APPEND_ALREADY_CONSUMED
    assert _grant_count(project_root, SID, stale_payload["id"]) == 1


def test_append_override_granted_rejects_expired_pending(tmp_path, monkeypatch) -> None:
    project_root, home = _setup_workspace(tmp_path, monkeypatch)
    stale_payload = _pending_payload(expires_at="2020-01-01T00:00:00Z")
    _write_pending(project_root, SID, stale_payload)

    status, append_state = confirm._append_override_granted(project_root, home, SID, stale_payload)

    assert status == 1
    assert append_state == confirm.APPEND_EXPIRED
    assert _grant_count(project_root, SID, stale_payload["id"]) == 0


def test_append_override_granted_rejects_mismatched_payload(tmp_path, monkeypatch) -> None:
    project_root, home = _setup_workspace(tmp_path, monkeypatch)
    stale_payload = _pending_payload(tool="Edit", args_sha256="b" * 64)
    _write_pending(project_root, SID, _pending_payload(tool="Bash", args_sha256="a" * 64))

    status, append_state = confirm._append_override_granted(project_root, home, SID, stale_payload)

    assert status == 1
    assert append_state == confirm.APPEND_MISMATCH
    assert _grant_count(project_root, SID, stale_payload["id"]) == 0


def test_append_override_granted_normal_path_grants_once(tmp_path, monkeypatch) -> None:
    project_root, home = _setup_workspace(tmp_path, monkeypatch)
    payload = _pending_payload()
    _write_pending(project_root, SID, payload)

    first_status, first_state = confirm._append_override_granted(project_root, home, SID, payload)
    second_status, second_state = confirm._append_override_granted(project_root, home, SID, payload)

    assert (first_status, first_state) == (0, confirm.APPEND_GRANTED)
    assert (second_status, second_state) == (0, confirm.APPEND_ALREADY_GRANTED)
    assert _grant_count(project_root, SID, payload["id"]) == 1
