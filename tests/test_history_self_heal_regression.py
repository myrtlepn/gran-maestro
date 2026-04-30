from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path


HOOKS_BASH = Path(__file__).parent.parent / "hooks/lib/history.bash"
ZERO_HASH = "0" * 64


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


def _call_verify(
    project_root: Path, session_id: str, claude_home: Path
) -> subprocess.CompletedProcess[str]:
    cmd = (
        f"set -e; source {shlex.quote(str(HOOKS_BASH))}; "
        f"mst_history_verify_chain_unlocked "
        f"{shlex.quote(str(project_root))} {shlex.quote(session_id)}"
    )
    env = os.environ.copy()
    env["MST_CLAUDE_HOME"] = str(claude_home)
    return subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


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


def test_sigint_mid_append_self_heal(tmp_path: Path) -> None:
    session_id = "sigint-mid-append"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(
        tmp_path, session_id
    )
    hashes = _write_ndjson(
        local_head.parent / "history.ndjson",
        [_event(1), _event(2)],
    )
    local_head.write_text(hashes[0] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[0] + "\n", encoding="utf-8")

    result = _call_verify(project, session_id, claude_home)

    assert result.returncode == 0, result.stderr
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert "[mst-history-self-heal]" in result.stderr
    assert f"restored={hashes[-1][:12]}" in result.stderr
    assert "targets=mirror,local" in result.stderr


def test_sigkill_mid_append_self_heal(tmp_path: Path) -> None:
    session_id = "sigkill-mid-append"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(
        tmp_path, session_id
    )
    hashes = _write_ndjson(
        local_head.parent / "history.ndjson",
        [_event(1), _event(2)],
    )
    local_head.write_text(hashes[0] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[-1] + "\n", encoding="utf-8")

    result = _call_verify(project, session_id, claude_home)

    assert result.returncode == 0, result.stderr
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert "[mst-history-self-heal]" in result.stderr
    assert f"restored={hashes[-1][:12]}" in result.stderr
    assert "targets=local" in result.stderr


def test_mirror_only_stale_self_heal(tmp_path: Path) -> None:
    session_id = "mirror-only-stale"
    project, claude_home, local_head, mirror_head = _make_ledger_paths(
        tmp_path, session_id
    )
    hashes = _write_ndjson(
        local_head.parent / "history.ndjson",
        [_event(1), _event(2), _event(3)],
    )
    local_head.write_text(hashes[-1] + "\n", encoding="utf-8")
    mirror_head.write_text(hashes[1] + "\n", encoding="utf-8")

    result = _call_verify(project, session_id, claude_home)

    assert result.returncode == 0, result.stderr
    assert local_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert mirror_head.read_text(encoding="utf-8").strip() == hashes[-1]
    assert "[mst-history-self-heal]" in result.stderr
    assert f"restored={hashes[-1][:12]}" in result.stderr
    assert "targets=mirror" in result.stderr
