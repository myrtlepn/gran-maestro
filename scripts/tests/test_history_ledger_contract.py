from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_BASH = REPO_ROOT / "hooks" / "lib" / "history.bash"
PRE_TOOL_FAST = REPO_ROOT / "hooks" / "lib" / "pre_tool_use_fast.py"
SESSION_ID = "MST-AGI-034-20260510T000000000Z-regress00"
ZERO_HASH = "0" * 64
ROOT_MST_ID = "AGI-034"

_FAST_SPEC = importlib.util.spec_from_file_location("req852_pre_tool_use_fast", PRE_TOOL_FAST)
assert _FAST_SPEC and _FAST_SPEC.loader
fast = importlib.util.module_from_spec(_FAST_SPEC)
_FAST_SPEC.loader.exec_module(fast)


def env_for(project_root: Path, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["MST_CLAUDE_HOME"] = str(home)
    env["MST_POLICY_HOME"] = str(project_root / ".gran-maestro" / "policy")
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    return env


@contextmanager
def policy_env(project_root: Path, home: Path):
    previous = {
        "HOME": os.environ.get("HOME"),
        "MST_CLAUDE_HOME": os.environ.get("MST_CLAUDE_HOME"),
        "MST_POLICY_HOME": os.environ.get("MST_POLICY_HOME"),
    }
    os.environ["HOME"] = str(home)
    os.environ["MST_CLAUDE_HOME"] = str(home)
    os.environ["MST_POLICY_HOME"] = str(project_root / ".gran-maestro" / "policy")
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_rows(history_file: Path) -> list[dict]:
    if not history_file.is_file():
        return []
    return [
        json.loads(line)
        for line in history_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def compute_event_hash(prev_hash: str, event: dict) -> str:
    canonical_event = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + "\n" + canonical_event).encode("utf-8")).hexdigest()


def history_artifacts(project_root: Path, home: Path) -> tuple[Path, Path, Path, Path]:
    return fast.history_paths(project_root, home, SESSION_ID)


def shell_append_tool_call(
    project_root: Path,
    home: Path,
    *,
    tool_name: str,
    tool_input: dict,
) -> subprocess.CompletedProcess[str]:
    env = env_for(project_root, home)
    env["HISTORY_BASH_PATH"] = str(HISTORY_BASH)
    env["PROJECT_ROOT_UNDER_TEST"] = str(project_root)
    env["TEST_MST_SESSION_ID"] = SESSION_ID
    env["MST_HOOK_TOOL_NAME"] = tool_name
    env["MST_HOOK_TOOL_INPUT_CANONICAL"] = json.dumps(
        tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    env["STDIN_RAW_PAYLOAD"] = json.dumps(
        {"tool_name": tool_name, "tool_input": tool_input, "mst_session_id": SESSION_ID},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return subprocess.run(
        [
            "bash",
            "-lc",
            'source "$HISTORY_BASH_PATH"; '
            'mst_history_append_tool_call "$PROJECT_ROOT_UNDER_TEST" "$TEST_MST_SESSION_ID" "$STDIN_RAW_PAYLOAD"',
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
    )


def run_pre_tool_fast(
    project_root: Path,
    home: Path,
    payload: dict,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = env_for(project_root, home)
    env["MST_SESSION_ID"] = SESSION_ID
    if extra_env:
        env.update(extra_env)
    fast_payload = {**payload, "mst_session_id": SESSION_ID}
    return subprocess.run(
        [sys.executable, str(PRE_TOOL_FAST), str(project_root)],
        cwd=project_root,
        input=json.dumps(fast_payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        env=env,
    )


def mutate_partial_row(history_file: Path, _local_head: Path, _mirror_head: Path, _verify_state: Path) -> None:
    history_file.write_text(history_file.read_text(encoding="utf-8") + '{"seq":2,"event":', encoding="utf-8")


def mutate_corrupt_hash(
    history_file: Path,
    _local_head: Path,
    _mirror_head: Path,
    _verify_state: Path,
) -> None:
    rows = load_rows(history_file)
    rows[0]["event_hash"] = "f" * 64
    history_file.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def mutate_invalid_cursor(
    history_file: Path,
    local_head: Path,
    _mirror_head: Path,
    verify_state: Path,
) -> None:
    current_head = local_head.read_text(encoding="utf-8").strip()
    fingerprint = fast.file_fingerprint(history_file)
    verify_state.write_text(f"{current_head[::-1]}\t{fingerprint}\t1\n", encoding="utf-8")


def mutate_stale_lock(
    _history_file: Path,
    _local_head: Path,
    _mirror_head: Path,
    verify_state: Path,
) -> None:
    (verify_state.parent / "history.lock").mkdir(parents=True, exist_ok=True)


@pytest.mark.parametrize("append_mode", ["shell", "python"])
def test_duplicate_idempotency_is_not_appended_twice(append_mode: str, tmp_path: Path) -> None:
    project_root = tmp_path
    home = tmp_path / "home"
    tool_input = {"command": "printf duplicate-idempotency"}

    with policy_env(project_root, home):
        if append_mode == "shell":
            first = shell_append_tool_call(project_root, home, tool_name="Bash", tool_input=tool_input)
            second = shell_append_tool_call(project_root, home, tool_name="Bash", tool_input=tool_input)
            assert first.returncode == 0, first.stderr
            assert second.returncode == 0, second.stderr
        else:
            history_file, local_head, mirror_head, verify_state = history_artifacts(project_root, home)
            history_file.parent.mkdir(parents=True, exist_ok=True)
            mirror_head.parent.mkdir(parents=True, exist_ok=True)
            status = fast.append_tool_call_after_verified(project_root, home, SESSION_ID, "Bash", tool_input)
            assert status == 0, "fixture=duplicate_idempotency mode=python first append failed"
            first_head = local_head.read_text(encoding="utf-8").strip()
            first_verify = fast.read_verify_state(verify_state)
            status = fast.append_tool_call_after_verified(project_root, home, SESSION_ID, "Bash", tool_input)
            assert status == 0, "fixture=duplicate_idempotency mode=python second append failed"
            assert local_head.read_text(encoding="utf-8").strip() == first_head
            assert fast.read_verify_state(verify_state) == first_verify

        history_file, local_head, mirror_head, verify_state = history_artifacts(project_root, home)
        rows = load_rows(history_file)
        assert len(rows) == 1, (
            f"fixture=duplicate_idempotency mode={append_mode} expected a single logical event, "
            f"got {len(rows)} rows"
        )
        last_hash = rows[-1]["event_hash"]
        assert local_head.read_text(encoding="utf-8").strip() == last_hash
        assert mirror_head.read_text(encoding="utf-8").strip() == last_hash
        assert fast.read_verify_state(verify_state) == (
            last_hash,
            fast.file_fingerprint(history_file),
            1,
        )


def test_normal_append_hash_chain_matches_heads_and_verify_state(tmp_path: Path) -> None:
    project_root = tmp_path
    home = tmp_path / "home"

    with policy_env(project_root, home):
        shell_result = shell_append_tool_call(
            project_root,
            home,
            tool_name="Bash",
            tool_input={"command": "printf shell-ledger"},
        )
        assert shell_result.returncode == 0, shell_result.stderr

        ok, first_head, first_seq = fast.verify_history(project_root, home, SESSION_ID)
        assert ok, "fixture=normal_append_hash_chain expected shell row to verify via Python fast path"
        assert first_seq == 1
        assert first_head and len(first_head) == 64

        status = fast.append_tool_call_after_verified(
            project_root,
            home,
            SESSION_ID,
            "Bash",
            {"command": "printf python-ledger"},
        )
        assert status == 0, "fixture=normal_append_hash_chain expected Python append after verified to succeed"

        history_file, local_head, mirror_head, verify_state = history_artifacts(project_root, home)
        rows = load_rows(history_file)
        assert [row["seq"] for row in rows] == [1, 2]

        prev_hash = ZERO_HASH
        for index, row in enumerate(rows, start=1):
            event = row["event"]
            assert row["prev_hash"] == prev_hash, f"fixture=normal_append_hash_chain row={index} prev_hash drift"
            assert row["event_hash"] == compute_event_hash(prev_hash, event), (
                f"fixture=normal_append_hash_chain row={index} event_hash recomputation mismatch"
            )
            assert row["mst_session_id"] == SESSION_ID
            assert row["root_mst_id"] == ROOT_MST_ID
            assert row["schema_version"] == 1
            assert row["event_type"] == "tool_call"
            assert isinstance(row["idempotency_key"], str) and row["idempotency_key"].strip()
            assert event["mst_session_id"] == SESSION_ID
            assert event["root_mst_id"] == ROOT_MST_ID
            assert event["schema_version"] == 1
            assert event["event_type"] == "tool_call"
            assert event["idempotency_key"] == row["idempotency_key"]
            prev_hash = row["event_hash"]

        last_hash = rows[-1]["event_hash"]
        assert local_head.read_text(encoding="utf-8").strip() == last_hash
        assert mirror_head.read_text(encoding="utf-8").strip() == last_hash
        assert fast.read_verify_state(verify_state) == (
            last_hash,
            fast.file_fingerprint(history_file),
            2,
        )


@pytest.mark.parametrize(
    ("fixture_id", "mutator", "expected_fragment", "extra_env"),
    [
        ("partial_row", mutate_partial_row, "history ledger mismatch:", {}),
        ("corrupt_row", mutate_corrupt_hash, "history ledger mismatch:", {}),
        (
            "invalid_locked_state",
            mutate_invalid_cursor,
            "history.verify cursor does not match current head",
            {},
        ),
        ("stale_lock", mutate_stale_lock, "history ledger mismatch: lock timeout", {"MST_HISTORY_LOCK_TRIES": "1"}),
    ],
)
def test_corrupt_partial_and_stale_lock_failure_evidence_block_without_hiding_damage(
    fixture_id: str,
    mutator: Callable[[Path, Path, Path, Path], None],
    expected_fragment: str,
    extra_env: dict[str, str],
    tmp_path: Path,
) -> None:
    project_root = tmp_path
    home = tmp_path / "home"
    with policy_env(project_root, home):
        shell_result = shell_append_tool_call(
            project_root,
            home,
            tool_name="Write",
            tool_input={"file_path": "safe.txt", "content": "seed"},
        )
        assert shell_result.returncode == 0, shell_result.stderr

        history_file, local_head, mirror_head, verify_state = history_artifacts(project_root, home)
        mutator(history_file, local_head, mirror_head, verify_state)
        before_history = history_file.read_text(encoding="utf-8") if history_file.exists() else ""
        before_local_head = local_head.read_text(encoding="utf-8") if local_head.exists() else ""
        before_mirror_head = mirror_head.read_text(encoding="utf-8") if mirror_head.exists() else ""
        before_verify = verify_state.read_text(encoding="utf-8") if verify_state.exists() else ""

        result = run_pre_tool_fast(
            project_root,
            home,
            {"tool_name": "Write", "tool_input": {"file_path": "safe.txt", "content": fixture_id}},
            extra_env=extra_env,
        )

        assert result.returncode == 2, (
            f"fixture={fixture_id} expected fail-closed nonzero status for damaged ledger, "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert result.stdout == "", f"fixture={fixture_id} expected no stdout schema pollution on history failure"
        assert expected_fragment in result.stderr, (
            f"fixture={fixture_id} expected structured stderr evidence containing {expected_fragment!r}, "
            f"got {result.stderr!r}"
        )
        assert history_file.read_text(encoding="utf-8") == before_history, (
            f"fixture={fixture_id} must not append a new event that hides ledger damage"
        )
        assert local_head.read_text(encoding="utf-8") == before_local_head
        assert mirror_head.read_text(encoding="utf-8") == before_mirror_head
        assert verify_state.read_text(encoding="utf-8") == before_verify


def test_pre_tool_history_pipeline_happy_path_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "notes.txt", "content": "ok"},
        "mst_session_id": SESSION_ID,
    }

    monkeypatch.setenv("MST_SESSION_ID", SESSION_ID)
    monkeypatch.setattr(fast, "acquire_lock", lambda _lock_dir: True)
    monkeypatch.setattr(fast, "warn_session_id_mismatch_once_if_any", lambda *args, **kwargs: None)
    monkeypatch.setattr(fast, "expire_pending_confirm", lambda *args, **kwargs: None)
    monkeypatch.setattr(fast, "hardcoded_core_check", lambda *args, **kwargs: 0)
    monkeypatch.setattr(fast, "consume_pending_override", lambda *args, **kwargs: None)
    monkeypatch.setattr(fast, "check_allowlist", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        fast,
        "canonical_mst_session_id_from_payload",
        lambda parsed_payload: (calls.append("canonical_identity") or SESSION_ID),
    )
    monkeypatch.setattr(
        fast,
        "inspect_hot_path_history_cursor",
        lambda *args, **kwargs: (calls.append("history_verify") or True, ZERO_HASH, 0, ""),
    )
    monkeypatch.setattr(
        fast,
        "evaluate_policy",
        lambda *args, **kwargs: (calls.append("policy_evaluation") or 0, []),
    )
    monkeypatch.setattr(
        fast,
        "evaluate_phase_gate",
        lambda *args, **kwargs: (calls.append("phase_gate") or 0, []),
    )
    monkeypatch.setattr(
        fast,
        "append_tool_call_after_verified",
        lambda *args, **kwargs: calls.append("decision_append") or 0,
    )
    monkeypatch.setattr(sys, "argv", ["pre_tool_use_fast.py", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))

    status = fast.main()

    assert status == 0
    assert calls.index("canonical_identity") < calls.index("history_verify")
    assert calls.index("history_verify") < calls.index("policy_evaluation")
    assert calls.index("policy_evaluation") < calls.index("decision_append")


def test_pre_tool_history_pipeline_blocks_corruption_before_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "mst confirm cf_fixture"},
        "mst_session_id": SESSION_ID,
    }

    monkeypatch.setenv("MST_SESSION_ID", SESSION_ID)
    monkeypatch.setattr(fast, "acquire_lock", lambda _lock_dir: True)
    monkeypatch.setattr(
        fast,
        "inspect_hot_path_history_cursor",
        lambda *args, **kwargs: (False, None, 0, "fixture_corrupt_cursor"),
    )
    monkeypatch.setattr(
        fast,
        "evaluate_policy",
        lambda *args, **kwargs: pytest.fail("fixture=pre_tool_history_pipeline policy evaluation must not run"),
    )
    monkeypatch.setattr(sys, "argv", ["pre_tool_use_fast.py", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))

    status = fast.main()
    captured = capsys.readouterr()

    assert status == 2
    assert "fixture_corrupt_cursor" in captured.err
    assert "[policy-block]" not in captured.err
