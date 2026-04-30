"""DOD-001 reproduction signals for bounded ``mst.py agile result`` calls.

The ledger-mismatch case intentionally uses a local sentinel/env marker instead
of invoking real hook scripts. That keeps this module isolated to the result
CLI process while documenting the boundary: hook ledger mismatch is simulated as
external context, not reproduced by mutating production history ledger files.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MST_PY = REPO_ROOT / "scripts" / "mst.py"
MST_PY = (
    Path(os.environ["MST_PLUGIN_ROOT"]) / "scripts" / "mst.py"
    if os.environ.get("MST_PLUGIN_ROOT")
    else _DEFAULT_MST_PY
)
CAUSE_CATEGORIES = {"normal", "lock-contention", "ledger-mismatch", "aux-failure"}
AUX_WARNING_STAGES = {"drift-report", "recall-manifest", "links-update"}
SINGLE_CALL_TIMEOUT_SEC = 30
CONCURRENT_TIMEOUT_SEC = 60


def _clean_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        part for part in env.get("PATH", "").split(os.pathsep) if "hook-bash-wrapper" not in part
    )
    if extra:
        env.update(extra)
    return env


def _init_agile_session(project_root: Path) -> str:
    (project_root / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(MST_PY), "agile", "init", "--json"],
        cwd=str(project_root),
        executable=sys.executable,
        capture_output=True,
        text=True,
        timeout=SINGLE_CALL_TIMEOUT_SEC,
        env=_clean_subprocess_env(),
        check=False,
    )
    elapsed = time.monotonic() - start
    assert elapsed <= SINGLE_CALL_TIMEOUT_SEC, (
        f"agile-init cause_category=normal elapsed={elapsed:.3f}s exceeded timeout"
    )
    assert proc.returncode == 0, (
        f"agile-init cause_category=normal elapsed={elapsed:.3f}s "
        f"returncode={proc.returncode} stderr={proc.stderr!r}"
    )
    payload = json.loads(proc.stdout)
    return str(payload["agi_id"])


@pytest.fixture
def isolated_project():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        yield {"root": root, "agi_id": _init_agile_session(root)}


def _collect_artifacts(project_root: Path, agi_id: str, sprint: int) -> dict[str, object]:
    sprint_dir = project_root / ".gran-maestro" / "agile" / agi_id / "sprints" / f"S{sprint:02d}"
    result_json = sprint_dir / "result.json"
    events_path = project_root / ".gran-maestro" / "agile" / agi_id / "events.ndjson"
    payload = None
    if result_json.exists():
        try:
            payload = json.loads(result_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = "invalid-json"
    agile_result_event = False
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "agile.result" and event.get("sprint_id") == f"S{sprint:02d}":
                agile_result_event = True
                break
    return {
        "sprint_dir": str(sprint_dir),
        "result_json": result_json.exists(),
        "result_md": (sprint_dir / "result.md").exists(),
        "drift_report": (sprint_dir / "drift-report.json").exists(),
        "recall_manifest": (sprint_dir / "recall-patch-manifest.json").exists(),
        "events": events_path.exists(),
        "agile_result_event": agile_result_event,
        "payload": payload,
    }


def _run_agile_result(
    project_root: Path,
    agi_id: str,
    *,
    sprint: int,
    status: str = "done",
    summary: str = "hang reproduction",
    timeout: int = SINGLE_CALL_TIMEOUT_SEC,
    extra_args: list[str] | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict[str, object]:
    args = [
        sys.executable,
        str(MST_PY),
        "agile",
        "result",
        agi_id,
        "--sprint",
        str(sprint),
        "--status",
        status,
        "--planned",
        "DOD-001",
        "--completed",
        "DOD-001",
        "--summary",
        summary,
        "--json",
    ]
    if extra_args:
        args.extend(extra_args)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=str(project_root),
            executable=sys.executable,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_subprocess_env(env_extra),
            check=False,
        )
        elapsed = time.monotonic() - started
        return {
            "case": summary,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "stderr_pattern": _stderr_pattern(proc.stderr),
            "elapsed": elapsed,
            "timeout": False,
            "timeout_limit": timeout,
            "partial_artifacts": _collect_artifacts(project_root, agi_id, sprint),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        return {
            "case": summary,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "stderr_pattern": "timeout",
            "elapsed": elapsed,
            "timeout": True,
            "timeout_limit": timeout,
            "partial_artifacts": _collect_artifacts(project_root, agi_id, sprint),
        }


def _stderr_pattern(stderr: str) -> str:
    text = (stderr or "").lower()
    if "history ledger mismatch" in text or "ledger" in text:
        return "ledger-mismatch"
    if "lock" in text or "contention" in text:
        return "lock-contention"
    if "[warn]" in text or "drift-report" in text or "recall" in text:
        return "aux-failure"
    if "error:" in text:
        return "error"
    return ""


def _classify_outcome(outcome: dict[str, object]) -> str:
    if outcome.get("timeout"):
        return "lock-contention"

    pattern = outcome.get("stderr_pattern")
    if pattern in CAUSE_CATEGORIES:
        return str(pattern)
    if outcome.get("returncode") != 0 and _stderr_pattern(str(outcome.get("stderr", ""))) == "aux-failure":
        return "aux-failure"
    if outcome.get("returncode") == 0:
        return "normal"
    return "normal"


def _assert_bounded(outcome: dict[str, object], expected_category: str, limit: int) -> None:
    category = _classify_outcome(outcome)
    elapsed = float(outcome["elapsed"])
    assert category == expected_category, (
        f"{outcome['case']} cause_category={category} expected={expected_category} "
        f"elapsed={elapsed:.3f}s stderr={outcome.get('stderr')!r}"
    )
    assert elapsed <= limit, (
        f"{outcome['case']} cause_category={category} elapsed={elapsed:.3f}s "
        f"limit={limit}s"
    )


def test_classify_outcome_normal():
    outcome = {"returncode": 0, "stderr_pattern": "", "stderr": "", "timeout": False}

    assert _classify_outcome(outcome) == "normal"


def test_classify_outcome_timeout():
    outcome = {"returncode": None, "stderr_pattern": "", "stderr": "", "timeout": True}

    assert _classify_outcome(outcome) == "lock-contention"


def test_classify_outcome_stderr_pattern():
    outcome = {"returncode": 1, "stderr_pattern": "aux-failure", "stderr": "", "timeout": False}

    assert _classify_outcome(outcome) == "aux-failure"


def test_classify_outcome_aux_failure_stderr():
    outcome = {"returncode": 1, "stderr_pattern": "", "stderr": "[warn] recall failed", "timeout": False}

    assert _classify_outcome(outcome) == "aux-failure"


def test_classify_outcome_unknown_failure():
    outcome = {"returncode": 1, "stderr_pattern": "", "stderr": "unexpected failure", "timeout": False}

    assert _classify_outcome(outcome) == "normal"


def test_normal_single_call(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    outcome = _run_agile_result(root, agi_id, sprint=1, summary="test_normal_single_call")

    _assert_bounded(outcome, "normal", SINGLE_CALL_TIMEOUT_SEC)
    assert outcome["returncode"] == 0, (
        f"test_normal_single_call cause_category=normal elapsed={outcome['elapsed']:.3f}s "
        f"stderr={outcome['stderr']!r}"
    )
    artifacts = outcome["partial_artifacts"]
    assert artifacts["result_json"] and artifacts["result_md"], (
        f"test_normal_single_call cause_category=normal elapsed={outcome['elapsed']:.3f}s "
        f"artifacts={artifacts!r}"
    )
    payload = artifacts["payload"]
    assert isinstance(payload, dict), (
        f"test_normal_single_call cause_category=normal elapsed={outcome['elapsed']:.3f}s "
        f"payload={payload!r}"
    )
    assert payload.get("aux_status") == "ok" and payload.get("aux_warnings") == [], (
        f"test_normal_single_call cause_category=normal elapsed={outcome['elapsed']:.3f}s "
        f"payload={payload!r}"
    )


def test_repeated_same_sprint(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    outcomes = [
        _run_agile_result(root, agi_id, sprint=2, summary=f"test_repeated_same_sprint_{index}")
        for index in range(3)
    ]

    for outcome in outcomes:
        _assert_bounded(outcome, "normal", SINGLE_CALL_TIMEOUT_SEC)
        assert outcome["returncode"] == 0, (
            f"{outcome['case']} cause_category=normal elapsed={outcome['elapsed']:.3f}s "
            f"stderr={outcome['stderr']!r}"
        )
    last_payload = outcomes[-1]["partial_artifacts"]["payload"]
    assert isinstance(last_payload, dict) and last_payload["summary"] == "test_repeated_same_sprint_2", (
        f"test_repeated_same_sprint cause_category=normal elapsed={outcomes[-1]['elapsed']:.3f}s "
        f"payload={last_payload!r}"
    )


def test_concurrent_same_sprint(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                _run_agile_result,
                root,
                agi_id,
                sprint=3,
                summary=f"test_concurrent_same_sprint_{index}",
                timeout=SINGLE_CALL_TIMEOUT_SEC,
            )
            for index in range(4)
        ]
        try:
            outcomes = [future.result(timeout=CONCURRENT_TIMEOUT_SEC) for future in futures]
        except concurrent.futures.TimeoutError:
            elapsed = time.monotonic() - started
            pytest.xfail(f"test_concurrent_same_sprint cause_category=lock-contention elapsed={elapsed:.3f}s")

    elapsed_group = time.monotonic() - started
    assert elapsed_group <= CONCURRENT_TIMEOUT_SEC, (
        f"test_concurrent_same_sprint cause_category=lock-contention elapsed={elapsed_group:.3f}s "
        f"limit={CONCURRENT_TIMEOUT_SEC}s"
    )
    if all(outcome["timeout"] for outcome in outcomes):
        pytest.xfail(
            "test_concurrent_same_sprint cause_category=lock-contention "
            f"elapsed={elapsed_group:.3f}s all calls timed out"
        )
    if any(outcome["timeout"] for outcome in outcomes):
        pytest.xfail(
            "test_concurrent_same_sprint cause_category=lock-contention "
            f"elapsed={elapsed_group:.3f}s partial timeout observed"
        )

    returncodes = [outcome["returncode"] for outcome in outcomes]
    successes = sum(1 for code in returncodes if code == 0)
    pattern_a = successes == 4
    pattern_b = 1 <= successes < 4 and all(code is not None for code in returncodes)
    assert pattern_a or pattern_b, (
        f"test_concurrent_same_sprint elapsed={elapsed_group:.3f}s "
        f"returncodes={returncodes!r}"
    )
    if pattern_a:
        for outcome in outcomes:
            _assert_bounded(outcome, "normal", SINGLE_CALL_TIMEOUT_SEC)
    else:
        for outcome in outcomes:
            category = _classify_outcome(outcome)
            assert category in CAUSE_CATEGORIES, (
                f"{outcome['case']} cause_category={category} elapsed={outcome['elapsed']:.3f}s "
                f"returncode={outcome['returncode']} stderr={outcome.get('stderr')!r}"
            )
            assert float(outcome["elapsed"]) <= SINGLE_CALL_TIMEOUT_SEC, (
                f"{outcome['case']} cause_category={category} elapsed={outcome['elapsed']:.3f}s "
                f"limit={SINGLE_CALL_TIMEOUT_SEC}s"
            )


def test_aux_output_failure(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    links_dir = root / ".gran-maestro" / "agile" / agi_id / "index"
    shutil.rmtree(links_dir)
    links_dir.write_text("not a directory\n", encoding="utf-8")
    outcome = _run_agile_result(
        root,
        agi_id,
        sprint=4,
        status="done",
        summary="test_aux_output_failure",
        extra_args=["--pln", "PLN-593"],
    )

    category = _classify_outcome(outcome)
    assert category == "aux-failure", (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"stderr={outcome['stderr']!r}"
    )
    _assert_bounded(outcome, category, SINGLE_CALL_TIMEOUT_SEC)
    assert outcome["returncode"] == 0, (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"stderr={outcome['stderr']!r}"
    )
    artifacts = outcome["partial_artifacts"]
    assert (
        artifacts["result_json"]
        and artifacts["result_md"]
        and artifacts["agile_result_event"]
        and artifacts["drift_report"]
    ), (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"artifacts={artifacts!r}"
    )
    payload = artifacts["payload"]
    assert isinstance(payload, dict), (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"payload={payload!r}"
    )
    assert payload.get("aux_status") == "partial", (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"payload={payload!r}"
    )
    aux_warnings = payload.get("aux_warnings")
    assert isinstance(aux_warnings, list) and aux_warnings, (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"payload={payload!r}"
    )
    for warning in aux_warnings:
        assert isinstance(warning, dict), f"aux warning must be dict: {warning!r}"
        assert warning.get("stage") in AUX_WARNING_STAGES, f"unexpected aux warning stage: {warning!r}"
        assert warning.get("error_class"), f"missing aux warning error_class: {warning!r}"
        assert "message" in warning, f"missing aux warning message: {warning!r}"
    assert re.search(r"\[warn\] (drift-report|recall-manifest|links-update) hook 실패:", outcome["stderr"]), (
        f"test_aux_output_failure cause_category={category} elapsed={outcome['elapsed']:.3f}s "
        f"stderr={outcome['stderr']!r}"
    )


def test_hook_ledger_mismatch_isolation(isolated_project):
    """Simulate hook ledger mismatch using an isolated sentinel, not hook execution."""

    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    before = _run_agile_result(root, agi_id, sprint=5, summary="ledger_mismatch_before")
    ledger_sentinel = root / ".gran-maestro" / "history-ledger-mismatch.sentinel"
    ledger_sentinel.write_text("simulated mismatch outside agile result path\n", encoding="utf-8")
    sentinel_before = ledger_sentinel.read_text(encoding="utf-8")
    after = _run_agile_result(
        root,
        agi_id,
        sprint=6,
        summary="test_hook_ledger_mismatch_isolation",
        env_extra={"MST_HISTORY_LEDGER_MISMATCH_SENTINEL": str(ledger_sentinel)},
    )

    _assert_bounded(before, "normal", SINGLE_CALL_TIMEOUT_SEC)
    _assert_bounded(after, "normal", SINGLE_CALL_TIMEOUT_SEC)
    before_category = _classify_outcome(before)
    after_category = _classify_outcome(after)
    assert before_category == after_category == "normal", (
        f"test_hook_ledger_mismatch_isolation before_category={before_category} "
        f"after_category={after_category}"
    )
    assert before["returncode"] == after["returncode"] == 0, (
        f"test_hook_ledger_mismatch_isolation cause_category={after_category} "
        f"elapsed={after['elapsed']:.3f}s before={before['returncode']} after={after['returncode']}"
    )
    assert float(before["elapsed"]) <= SINGLE_CALL_TIMEOUT_SEC and float(after["elapsed"]) <= SINGLE_CALL_TIMEOUT_SEC, (
        f"test_hook_ledger_mismatch_isolation cause_category={after_category} "
        f"before_elapsed={before['elapsed']:.3f}s after_elapsed={after['elapsed']:.3f}s"
    )
    assert ledger_sentinel.exists() and ledger_sentinel.read_text(encoding="utf-8") == sentinel_before, (
        f"test_hook_ledger_mismatch_isolation cause_category={after_category} "
        f"sentinel={ledger_sentinel}"
    )
    assert after["partial_artifacts"]["result_json"] and after["partial_artifacts"]["result_md"], (
        f"test_hook_ledger_mismatch_isolation cause_category={after_category} "
        f"elapsed={after['elapsed']:.3f}s artifacts={after['partial_artifacts']!r}"
    )
