from __future__ import annotations

import hashlib
import json
import os
import pty
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_PY = REPO_ROOT / "scripts" / "mst.py"
ZERO_HASH = "0" * 64


def _project_key(project_root: Path) -> str:
    return hashlib.sha256(os.path.realpath(project_root).encode()).hexdigest()[:16]


def _clean_env(policy_home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_"))}
    env["MST_POLICY_HOME"] = str(policy_home)
    return env


def _run_tty(
    project_root: Path,
    policy_home: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    master_fd, slave_fd = pty.openpty()
    env = _clean_env(policy_home)
    if env_extra:
        env.update(env_extra)
    try:
        return subprocess.run(
            [sys.executable, str(MST_PY), *args],
            cwd=project_root,
            env=env,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def _run_plain(project_root: Path, policy_home: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = _clean_env(policy_home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(MST_PY), *args],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _history_paths(project_root: Path, policy_home: Path, sid: str) -> tuple[Path, Path, Path]:
    session_dir = project_root / ".gran-maestro" / "sessions" / sid
    return (
        session_dir / "history.ndjson",
        session_dir / "history.head",
        policy_home / "ledger-heads" / f"{sid}.head",
    )


def _append_event(project_root: Path, policy_home: Path, sid: str, event: dict) -> dict:
    history_file, local_head, mirror_head = _history_paths(project_root, policy_home, sid)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = local_head.read_text(encoding="utf-8").strip() if local_head.exists() else ZERO_HASH
    seq = sum(1 for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()) if history_file.exists() else 0
    event_hash = _sha256_text(prev_hash + "\n" + _canonical_event(event))
    row = {
        "event": event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "seq": seq + 1,
        "timestamp": event.get("timestamp", "2026-04-29T00:00:00Z"),
    }
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    return row


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    policy_home = tmp_path / "policy"
    (project_root / ".gran-maestro").mkdir(parents=True)
    policy_home.mkdir()
    return project_root, policy_home


def _seed_history(project_root: Path, policy_home: Path, sid: str, count: int) -> None:
    for index in range(1, count + 1):
        _append_event(
            project_root,
            policy_home,
            sid,
            {"type": "tool_call", "tool": "Test", "args_sha256": f"args-{index}", "timestamp": f"2026-04-29T00:00:0{index}Z"},
        )


def _read_rows(history_file: Path) -> list[dict]:
    return [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_truncate(tmp_path: Path) -> None:
    project_root, policy_home = _make_project(tmp_path)
    sid = "sid-truncate"
    _seed_history(project_root, policy_home, sid, 5)
    history_file, _, mirror_head = _history_paths(project_root, policy_home, sid)

    rows = _read_rows(history_file)
    rows[4]["event"]["tool"] = "Tampered"
    history_file.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n", encoding="utf-8")

    result = _run_tty(project_root, policy_home, "hook", "repair", "--session", sid, "--truncate-to", "4", "--yes")

    assert result.returncode == 0, result.stderr
    assert "seq=5" in result.stderr
    assert "recommended truncate seq: 4" in result.stderr
    repaired_rows = _read_rows(history_file)
    assert len(repaired_rows) == 4
    assert mirror_head.read_text(encoding="utf-8").strip() == repaired_rows[-1]["event_hash"]
    assert list(history_file.parent.glob("history.ndjson.bak.*"))


def test_manifest_recalc(tmp_path: Path) -> None:
    project_root, policy_home = _make_project(tmp_path)
    sid = "MST-AGI-036-20260513T120000000Z-manifest"
    _seed_history(project_root, policy_home, sid, 1)
    policy_dir = policy_home / "projects" / _project_key(project_root)
    rules_dir = policy_dir / "rules.d"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "core.json"
    rule_file.write_text('{"version":1,"rules":[]}\n', encoding="utf-8")
    manifest = policy_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"version": 1, "rules": [{"path": "rules.d/core.json", "sha256": "bad"}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run_tty(project_root, policy_home, "hook", "repair", "--manifest", "--yes")

    assert result.returncode == 0, result.stderr
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["rules"][0]["sha256"] == hashlib.sha256(rule_file.read_bytes()).hexdigest()
    history_file, _, _ = _history_paths(project_root, policy_home, sid)
    event = _read_rows(history_file)[-1]["event"]
    assert event["type"] == "repair_executed"
    assert event["repair_target"] == "manifest"


def test_tty_required(tmp_path: Path) -> None:
    project_root, policy_home = _make_project(tmp_path)

    result = _run_plain(
        project_root,
        policy_home,
        "hook",
        "repair",
        "--session",
        "sid",
        "--yes",
        env_extra={"CLAUDE_CODE_SESSION_ID": "llm"},
    )

    assert result.returncode != 0
    assert "TTY provenance required" in result.stderr


def test_claudecode_prefix_rejected(tmp_path: Path) -> None:
    project_root, policy_home = _make_project(tmp_path)

    result = _run_tty(
        project_root,
        policy_home,
        "hook",
        "repair",
        "--session",
        "sid",
        "--yes",
        env_extra={"CLAUDECODE_SESSION_ID": "llm"},
    )

    assert result.returncode != 0
    assert "TTY provenance required" in result.stderr


def test_noop_when_healthy(tmp_path: Path) -> None:
    project_root, policy_home = _make_project(tmp_path)
    sid = "sid-healthy"
    _seed_history(project_root, policy_home, sid, 3)
    history_file, _, mirror_head = _history_paths(project_root, policy_home, sid)
    before_text = history_file.read_text(encoding="utf-8")
    before_mtime = history_file.stat().st_mtime_ns
    before_mirror = mirror_head.read_text(encoding="utf-8")

    result = _run_tty(project_root, policy_home, "hook", "repair", "--session", sid, "--yes")

    assert result.returncode == 0, result.stderr
    assert "복구 불필요" in result.stdout
    assert history_file.read_text(encoding="utf-8") == before_text
    assert history_file.stat().st_mtime_ns == before_mtime
    assert mirror_head.read_text(encoding="utf-8") == before_mirror
