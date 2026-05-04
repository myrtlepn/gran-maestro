from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_PY = REPO_ROOT / "scripts" / "mst.py"
ZERO_HASH = "0" * 64
SID_ONE = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
SID_FILTER = "MST-REQ-808-20260504T000000000Z-h0okl0g1"
SID_A = "MST-PLN-635-20260504T000000001Z-h0okl0ga"
SID_B = "MST-PLN-635-20260504T000000002Z-h0okl0gb"
SID_C = "MST-PLN-635-20260504T000000003Z-h0okl0gc"
SID_JSON = "MST-AGI-030-20260504T000000004Z-h0okl0gj"
SID_LIMIT = "MST-AGI-030-20260504T000000005Z-h0okl0gl"


def _clean_env(project_root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_"))}
    env["MST_POLICY_HOME"] = str(project_root / ".policy")
    return env


def _run(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_PY), *args],
        cwd=project_root,
        env=_clean_env(project_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _make_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".gran-maestro").mkdir(parents=True)
    return project_root


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _root_from_sid(sid: str) -> str:
    return sid[len("MST-") :].rsplit("-", 2)[0]


def _write_history(project_root: Path, sid: str, events: list[dict]) -> None:
    session_dir = project_root / ".gran-maestro" / "sessions" / sid
    session_dir.mkdir(parents=True)
    root = _root_from_sid(sid)
    (session_dir / "session.json").write_text(
        json.dumps({"schema_version": 1, "mst_session_id": sid, "root_mst_id": root}) + "\n",
        encoding="utf-8",
    )
    rows = []
    prev_hash = ZERO_HASH
    for index, event in enumerate(events, 1):
        canonical = dict(event)
        canonical.update(
            {
                "schema_version": 1,
                "mst_session_id": sid,
                "root_mst_id": root,
                "event_type": canonical["type"],
                "created_at": canonical["timestamp"],
                "idempotency_key": f"{sid}:{canonical['type']}:{index}",
            }
        )
        event_hash = _sha256_text(prev_hash + "\n" + _canonical_event(canonical))
        rows.append(
            {
                "event": canonical,
                "event_hash": event_hash,
                "mst_session_id": sid,
                "prev_hash": prev_hash,
                "seq": index,
                "timestamp": canonical["timestamp"],
            }
        )
        prev_hash = event_hash
    session_dir.joinpath("history.ndjson").write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    (session_dir / "history.head").write_text(prev_hash + "\n", encoding="utf-8")
    mirror = project_root / ".policy" / "ledger-heads" / f"{sid}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(prev_hash + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(
        f"{prev_hash}\t{_fingerprint(session_dir / 'history.ndjson')}\t{len(rows)}\n",
        encoding="utf-8",
    )


def _event(event_type: str, timestamp: str, *, rule_id: str | None = None, tool: str | None = None, reason: str | None = None) -> dict:
    event = {"type": event_type, "timestamp": timestamp}
    if rule_id is not None:
        event["rule_id"] = rule_id
    if tool is not None:
        event["tool"] = tool
    if reason is not None:
        event["reason"] = reason
    return event


def _table_rows(stdout: str) -> list[str]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines[0] == "시간 | 세션 | 이벤트 | 룰/도구 | 비고"
    return lines[1:]


def test_single_session_prints_five_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(
        project_root,
        SID_ONE,
        [_event("tool_call", f"2026-04-29T00:00:0{index}Z", tool=f"Tool{index}") for index in range(1, 6)],
    )

    result = _run(project_root, "hook", "log", "--session", SID_ONE, "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 5
    assert all(f" | {SID_ONE} | tool_call | Tool" in row for row in rows)


def test_type_filter_prints_only_matching_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    events = []
    for index in range(1, 11):
        event_type = "core_block" if index % 2 == 0 else "tool_call"
        events.append(_event(event_type, f"2026-04-29T00:00:{index:02d}Z", rule_id=f"rule-{index}"))
    _write_history(project_root, SID_FILTER, events)

    result = _run(project_root, "hook", "log", "--session", SID_FILTER, "--type", "core_block", "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 5
    assert all(" | core_block | " in row for row in rows)
    assert not any(" | tool_call | " in row for row in rows)


def test_all_sessions_are_sorted_by_timestamp(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(project_root, SID_B, [_event("tool_call", "2026-04-29T00:00:03Z", tool="B")])
    _write_history(project_root, SID_A, [_event("tool_call", "2026-04-29T00:00:01Z", tool="A")])
    _write_history(project_root, SID_C, [_event("tool_call", "2026-04-29T00:00:02Z", tool="C")])

    result = _run(project_root, "hook", "log", "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert [row.split(" | ")[1] for row in rows] == [SID_A, SID_C, SID_B]
    assert [row.split(" | ")[0] for row in rows] == ["2026-04-29T00:00:01Z", "2026-04-29T00:00:02Z", "2026-04-29T00:00:03Z"]


def test_json_outputs_ndjson(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(
        project_root,
        SID_JSON,
        [
            _event("core_block", "2026-04-29T00:00:01Z", rule_id="core-1", reason="blocked"),
            _event("policy_block", "2026-04-29T00:00:02Z", rule_id="policy-1", reason="denied"),
        ],
    )

    result = _run(project_root, "hook", "log", "--session", SID_JSON, "--json")

    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    assert [row["event"]["type"] for row in rows] == ["core_block", "policy_block"]
    assert all(row["session_id"] == SID_JSON for row in rows)


def test_limit_returns_latest_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    start = datetime(2026, 4, 29, tzinfo=timezone.utc)
    _write_history(
        project_root,
        SID_LIMIT,
        [
            _event("tool_call", (start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"), tool=f"Tool{index}")
            for index in range(100)
        ],
    )

    result = _run(project_root, "hook", "log", "--session", SID_LIMIT, "--limit", "10")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 10
    assert rows[0].startswith("2026-04-29T01:30:00Z | ")
    assert rows[-1].startswith("2026-04-29T01:39:00Z | ")


def main() -> int:
    tests = [
        test_single_session_prints_five_events,
        test_type_filter_prints_only_matching_events,
        test_all_sessions_are_sorted_by_timestamp,
        test_json_outputs_ndjson,
        test_limit_returns_latest_events,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as raw:
            test(Path(raw))
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
