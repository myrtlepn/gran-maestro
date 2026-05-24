from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
MST_SESSION_ID = "MST-AGI-036-20260513T120000000Z-wrapper1"


def _run_wrapper(tmp_path: Path, *, env: dict[str, str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").write_text("gitdir: .\n", encoding="utf-8")
    merged_env = os.environ.copy()
    merged_env["MST_SESSION_ID"] = MST_SESSION_ID
    merged_env.update(env)
    return subprocess.run(
        ["bash", str(STOP_HOOK)],
        input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": False, "mst_session_id": MST_SESSION_ID}),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
        check=False,
    )


def _strict_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0])
    assert set(payload) == {"decision", "reason"}
    assert payload["decision"] in {"approve", "block"}
    assert isinstance(payload["reason"], str) and payload["reason"].strip()
    return payload


def test_invalid_judge_output_empty_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": "", "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0"},
    )

    assert result.returncode == 0
    payload = _strict_stdout(result)
    assert payload == {"decision": "approve", "reason": "hook judge startup failure fail-open"}


def test_invalid_judge_output_non_json_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": "diagnostic only\n", "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0"},
    )

    payload = _strict_stdout(result)
    assert payload["reason"] == "hook judge startup failure fail-open"
    assert "diagnostic only" not in result.stdout


def test_invalid_judge_output_multiline_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={
            "MST_STOP_HOOK_TEST_JUDGE_STDOUT": '{"decision":"approve","reason":"ok"}\n{"decision":"block","reason":"late"}\n',
            "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0",
        },
    )

    payload = _strict_stdout(result)
    assert payload["reason"] == "hook judge startup failure fail-open"


def test_invalid_judge_output_traceback_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": "Traceback (most recent call last):\nboom\n", "MST_STOP_HOOK_TEST_JUDGE_EXIT": "1"},
    )

    payload = _strict_stdout(result)
    assert payload["reason"] == "hook judge startup failure fail-open"
    assert "Traceback" not in result.stdout


def test_invalid_judge_output_invalid_decision_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": '{"decision":"pause","reason":"bad"}\n', "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0"},
    )

    payload = _strict_stdout(result)
    assert payload["reason"] == "hook judge startup failure fail-open"


def test_invalid_judge_output_extra_key_falls_back(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": '{"decision":"approve","reason":"ok","debug":true}\n', "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0"},
    )

    payload = _strict_stdout(result)
    assert payload["reason"] == "hook judge startup failure fail-open"


def test_timeout_race_suppresses_late_stdout_and_duplicate_emit(tmp_path: Path) -> None:
    result = _run_wrapper(
        tmp_path,
        env={
            "MST_HOOK_JUDGE_TIMEOUT_MS": "5",
            "MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS": "80",
            "MST_STOP_HOOK_TEST_JUDGE_STDOUT": '{"decision":"block","reason":"late child output"}\n',
            "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0",
        },
        timeout=5.0,
    )

    assert result.returncode == 0
    payload = _strict_stdout(result)
    assert payload == {"decision": "approve", "reason": "hook judge timeout (>5ms) fail-open"}
    assert "late child output" not in result.stdout


def test_unexpected_execution_path_emits_strict_fail_open_json(tmp_path: Path) -> None:
    broken_dir = tmp_path / "${CLAUDE_PLUGIN_ROOT}" / "hooks"
    broken_dir.mkdir(parents=True)
    broken_hook = broken_dir / "mst-stop-hook.sh"
    broken_hook.write_text(STOP_HOOK.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(broken_hook)],
        input="",
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=5.0,
        check=False,
    )

    assert result.returncode == 0
    payload = _strict_stdout(result)
    assert payload["decision"] == "approve"
    assert payload["reason"] in {
        "unexpected hook execution path; stop hook fail-open without mutation",
        "missing hook bootstrap files; stop hook fail-open without mutation",
    }


def test_missing_bootstrap_emits_strict_fail_open_json(tmp_path: Path) -> None:
    broken_dir = tmp_path / "hooks"
    broken_dir.mkdir(parents=True)
    broken_hook = broken_dir / "mst-stop-hook.sh"
    broken_hook.write_text(STOP_HOOK.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(broken_hook)],
        input="",
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=5.0,
        check=False,
    )

    assert result.returncode == 0
    payload = _strict_stdout(result)
    assert payload == {
        "decision": "approve",
        "reason": "missing hook bootstrap files; stop hook fail-open without mutation",
    }
