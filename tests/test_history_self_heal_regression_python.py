from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ZERO_HASH = "0" * 64


@pytest.fixture()
def fast_hook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MST_POLICY_HOME", raising=False)
    module_path = Path(__file__).resolve().parents[1] / "hooks/lib/pre_tool_use_fast.py"
    spec = importlib.util.spec_from_file_location("pre_tool_use_fast_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compute_event_hash(prev_hash: str, event: dict[str, str]) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode()).hexdigest()


def _write_ndjson(path: Path, events: list[dict[str, str]]) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    hashes: list[str] = []
    prev_hash = ZERO_HASH

    with path.open("w", encoding="utf-8") as handle:
        for seq, event in enumerate(events, 1):
            event_hash = _compute_event_hash(prev_hash, event)
            row = {
                "seq": seq,
                "prev_hash": prev_hash,
                "event_hash": event_hash,
                "event": event,
                **{
                    key: event[key]
                    for key in ("tool", "args_sha256", "timestamp")
                    if key in event
                },
            }
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            hashes.append(event_hash)
            prev_hash = event_hash

    return hashes


def _make_ledger_paths(tmp_path: Path, session_id: str) -> tuple[Path, Path, Path, Path]:
    project = tmp_path / "project"
    claude_home = tmp_path / "claude-home"
    session_dir = project / ".gran-maestro" / "sessions" / session_id
    heads_dir = claude_home / ".claude" / "gran-maestro-policy" / "ledger-heads"
    session_dir.mkdir(parents=True, exist_ok=True)
    heads_dir.mkdir(parents=True, exist_ok=True)
    return project, claude_home, session_dir / "history.head", heads_dir / f"{session_id}.head"


def _event(index: int) -> dict[str, str]:
    return {
        "type": "tool_call",
        "tool": f"tool-{index}",
        "args_sha256": f"args-{index}",
        "timestamp": f"2026-04-30T00:00:0{index}Z",
    }


def test_python_sigint_mid_append_self_heal(tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_hook) -> None:
    session_id = "python-sigint-mid-append"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(tmp_path, session_id)
    hashes = _write_ndjson(local_head.parent / "history.ndjson", [_event(1), _event(2)])
    local_head.write_text(hashes[0] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[0] + "\n", encoding="utf-8")

    result = fast_hook.verify_history(project, claude_home, session_id)
    stderr = capsys.readouterr().err

    assert result == (True, hashes[-1], 2)
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert stderr.splitlines() == [
        (
            f"[mst-history-self-heal] session={session_id} restored={hashes[-1][:12]} "
            f"targets=mirror,local prev_local={hashes[0][:12]} prev_mirror={hashes[0][:12]}"
        )
    ]


def test_python_sigkill_mid_append_self_heal(tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_hook) -> None:
    session_id = "python-sigkill-mid-append"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(tmp_path, session_id)
    hashes = _write_ndjson(local_head.parent / "history.ndjson", [_event(1), _event(2)])
    local_head.write_text(hashes[0] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[-1] + "\n", encoding="utf-8")

    result = fast_hook.verify_history(project, claude_home, session_id)
    stderr = capsys.readouterr().err

    assert result == (True, hashes[-1], 2)
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert stderr.splitlines() == [
        (
            f"[mst-history-self-heal] session={session_id} restored={hashes[-1][:12]} "
            f"targets=local prev_local={hashes[0][:12]} prev_mirror={hashes[-1][:12]}"
        )
    ]


def test_python_mirror_only_stale_self_heal(tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_hook) -> None:
    session_id = "python-mirror-only-stale"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(tmp_path, session_id)
    hashes = _write_ndjson(local_head.parent / "history.ndjson", [_event(1), _event(2), _event(3)])
    local_head.write_text(hashes[-1] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[1] + "\n", encoding="utf-8")

    result = fast_hook.verify_history(project, claude_home, session_id)
    stderr = capsys.readouterr().err

    assert result == (True, hashes[-1], 3)
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert stderr.splitlines() == [
        (
            f"[mst-history-self-heal] session={session_id} restored={hashes[-1][:12]} "
            f"targets=mirror prev_local={hashes[-1][:12]} prev_mirror={hashes[1][:12]}"
        )
    ]


def test_python_ndjson_empty_heads_nonzero_blocked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fast_hook,
) -> None:
    session_id = "python-empty-heads-nonzero"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(tmp_path, session_id)
    (local_head.parent / "history.ndjson").write_text("", encoding="utf-8")
    nonzero = "1" * 64
    local_head.write_text(nonzero + "\n", encoding="utf-8")
    mirror_head.write_text(ZERO_HASH + "\n", encoding="utf-8")

    result = fast_hook.verify_history(project, claude_home, session_id)
    stderr = capsys.readouterr().err

    assert result == (False, None, 0)
    assert local_head.read_text(encoding="utf-8").strip() == nonzero
    assert mirror_head.read_text(encoding="utf-8").strip() == ZERO_HASH
    assert stderr.splitlines() == [
        "history ledger mismatch: self-heal failed: ndjson empty but heads non-zero (rotation suspected)"
    ]
