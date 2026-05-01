"""DOD-001 reproduction signals for bounded ``mst.py agile result`` calls.

The ledger-mismatch case intentionally uses a local sentinel/env marker instead
of invoking real hook scripts. That keeps this module isolated to the result
CLI process while documenting the boundary: hook ledger mismatch is simulated as
external context, not reproduced by mutating production history ledger files.
"""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

try:
    import fcntl
except ImportError:  # pragma: no cover - platform dependent.
    fcntl = None


REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MST_PY = REPO_ROOT / "scripts" / "mst.py"
MST_PY = (
    Path(os.environ["MST_PLUGIN_ROOT"]) / "scripts" / "mst.py"
    if os.environ.get("MST_PLUGIN_ROOT")
    else _DEFAULT_MST_PY
)
CAUSE_CATEGORIES = {"normal", "lock-contention", "ledger-mismatch", "aux-failure"}
AUX_WARNING_STAGES = {"drift-report", "recall-manifest", "links-update"}
LOCK_CONTENTION_CATEGORIES = {"result-lock-contention", "lock-contention"}
LOCK_CONTENTION_NEXT_ACTIONS = {"wait-for-owner", "retry"}
SINGLE_CALL_TIMEOUT_SEC = 30
CONCURRENT_TIMEOUT_SEC = 60


def _sprint_dir(project_root: Path, agi_id: str, sprint: int) -> Path:
    return project_root / ".gran-maestro" / "agile" / agi_id / "sprints" / f"S{sprint:02d}"


def _events_path(project_root: Path, agi_id: str) -> Path:
    return project_root / ".gran-maestro" / "agile" / agi_id / "events.ndjson"


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
    sprint_dir = _sprint_dir(project_root, agi_id, sprint)
    result_json = sprint_dir / "result.json"
    events_path = _events_path(project_root, agi_id)
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
    if (
        "lock timeout" in text
        or "lock-contention" in text
        or ("lock" in text and "timeout" in text)
        or ("lock" in text and "contention" in text)
    ):
        return "lock-contention"
    if "[warn]" in text or "drift-report" in text or "recall" in text:
        return "aux-failure"
    if "error:" in text:
        return "error"
    return ""


def _extract_diagnostic(outcome: dict[str, object]) -> dict[str, object]:
    """Best-effort parser for JSON or key=value diagnostic output."""

    for stream_name in ("stdout", "stderr"):
        raw = str(outcome.get(stream_name) or "").strip()
        if not raw:
            continue
        for candidate in (raw, *raw.splitlines()):
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload

    text = "\n".join(str(outcome.get(name) or "") for name in ("stdout", "stderr"))
    fields: dict[str, object] = {}
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", text):
        fields[match.group(1)] = match.group(2).rstrip(",")
    lowered = text.lower()
    if "result-lock-contention" in lowered:
        fields.setdefault("category", "result-lock-contention")
    elif "lock-contention" in lowered or "lock timeout" in lowered:
        fields.setdefault("category", "lock-contention")
    if "wait-for-owner" in lowered:
        fields.setdefault("next_action", "wait-for-owner")
    elif "retry" in lowered:
        fields.setdefault("next_action", "retry")
    return fields


def _classify_outcome(outcome: dict[str, object]) -> str:
    if outcome.get("timeout"):
        return "lock-contention"

    pattern = outcome.get("stderr_pattern")
    if pattern in CAUSE_CATEGORIES:
        return str(pattern)
    if outcome.get("returncode") != 0 and _stderr_pattern(str(outcome.get("stderr", ""))) == "aux-failure":
        return "aux-failure"
    if outcome.get("returncode") != 0 and _stderr_pattern(str(outcome.get("stderr", ""))) == "lock-contention":
        return "lock-contention"
    if outcome.get("returncode") == 0:
        return "normal"
    return "normal"


def _read_ndjson_strict(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - asserted in callers.
            raise AssertionError(f"{path}: invalid JSON at line {line_no}: {exc}") from exc
        assert isinstance(payload, dict), f"{path}: expected object at line {line_no}, got {type(payload)}"
        rows.append(payload)
    return rows


def _hold_result_lock(lock_path_text: str, ready_path_text: str, hold_sec: float) -> None:
    if fcntl is None:
        return

    lock_path = Path(lock_path_text)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        Path(ready_path_text).write_text("ready", encoding="utf-8")
        time.sleep(hold_sec)
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


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
    aux = {"returncode": 1, "stderr_pattern": "aux-failure", "stderr": "", "timeout": False}
    lock_timeout = {"returncode": 1, "stderr_pattern": "", "stderr": "Error: lock timeout (5s)", "timeout": False}
    lock_contention = {
        "returncode": 1,
        "stderr_pattern": "",
        "stderr": "agile result lock-contention on sprint",
        "timeout": False,
    }

    assert _classify_outcome(aux) == "aux-failure"
    assert _classify_outcome(lock_timeout) == "lock-contention"
    assert _classify_outcome(lock_contention) == "lock-contention"


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
            pytest.fail(
                "test_concurrent_same_sprint must complete without future timeout; "
                f"elapsed={elapsed:.3f}s"
            )

    elapsed_group = time.monotonic() - started
    assert elapsed_group <= CONCURRENT_TIMEOUT_SEC, (
        f"test_concurrent_same_sprint cause_category=lock-contention elapsed={elapsed_group:.3f}s "
        f"limit={CONCURRENT_TIMEOUT_SEC}s"
    )
    assert not any(outcome["timeout"] for outcome in outcomes), (
        "test_concurrent_same_sprint must not rely on subprocess timeout; "
        f"outcomes={outcomes!r}"
    )

    returncodes = [outcome["returncode"] for outcome in outcomes]
    successes = sum(1 for code in returncodes if code == 0)
    failures = [outcome for outcome in outcomes if outcome["returncode"] != 0]
    pattern_a = successes == 4 and not failures
    pattern_b = 1 <= successes < 4 and failures and all(code is not None for code in returncodes)
    assert pattern_a or pattern_b, (
        f"test_concurrent_same_sprint elapsed={elapsed_group:.3f}s "
        f"returncodes={returncodes!r}"
    )
    for outcome in outcomes:
        assert float(outcome["elapsed"]) <= SINGLE_CALL_TIMEOUT_SEC, (
            f"{outcome['case']} elapsed={outcome['elapsed']:.3f}s exceeded {SINGLE_CALL_TIMEOUT_SEC}s"
        )
    for failure in failures:
        assert failure["returncode"] not in (0, None), f"unexpected failure returncode={failure['returncode']!r}"
        category = _classify_outcome(failure)
        assert category == "lock-contention", (
            f"{failure['case']} cause_category={category} returncode={failure['returncode']} "
            f"stderr={failure['stderr']!r}"
        )
        stderr_lower = str(failure.get("stderr") or "").lower()
        assert "lock timeout" in stderr_lower or "lock-contention" in stderr_lower, (
            f"{failure['case']} expected lock timeout/contention stderr but got {failure['stderr']!r}"
        )

    successful_summaries = {str(outcome["case"]) for outcome in outcomes if outcome["returncode"] == 0}
    assert successful_summaries, f"expected at least one successful call, outcomes={outcomes!r}"

    sprint_dir = _sprint_dir(root, agi_id, 3)
    result_json_path = sprint_dir / "result.json"
    result_md_path = sprint_dir / "result.md"
    events_path = _events_path(root, agi_id)
    assert result_json_path.exists(), f"missing {result_json_path}"
    assert result_md_path.exists(), f"missing {result_md_path}"
    assert events_path.exists(), f"missing {events_path}"

    result_payload = json.loads(result_json_path.read_text(encoding="utf-8"))
    assert isinstance(result_payload, dict), f"invalid result payload type: {type(result_payload)}"
    final_summary = result_payload.get("summary")
    assert final_summary in successful_summaries, (
        f"result.json summary was corrupted: summary={final_summary!r} "
        f"successful_summaries={sorted(successful_summaries)!r}"
    )

    result_md = result_md_path.read_text(encoding="utf-8")
    assert result_md.strip(), f"{result_md_path} is empty"
    assert any(f"- summary: {summary}" in result_md for summary in successful_summaries), (
        f"result.md summary does not match successful run: summaries={sorted(successful_summaries)!r}"
    )

    events = _read_ndjson_strict(events_path)
    sprint_events = [e for e in events if e.get("event") == "agile.result" and e.get("sprint_id") == "S03"]
    assert sprint_events, f"no agile.result event for sprint S03 in {events_path}"
    final_event = sprint_events[-1]
    assert final_event.get("status") == "done", f"unexpected final sprint event: {final_event!r}"


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_result_lock_held_returns_lock_timeout(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    sprint = 7
    lock_path = _sprint_dir(root, agi_id, sprint) / ".result.lock"
    ready_path = root / "result-lock-held.ready"

    process = multiprocessing.Process(
        target=_hold_result_lock,
        args=(str(lock_path), str(ready_path), 6.0),
    )
    process.start()
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists(), f"lock-holder did not signal readiness: {ready_path}"

        outcome = _run_agile_result(
            root,
            agi_id,
            sprint=sprint,
            summary="test_result_lock_held_returns_lock_timeout",
            timeout=SINGLE_CALL_TIMEOUT_SEC,
        )
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert process.exitcode in (0, -15), f"unexpected lock-holder exit code: {process.exitcode}"
    assert not outcome["timeout"], f"expected CLI failure, got subprocess timeout: {outcome!r}"
    assert outcome["returncode"] not in (None, 0), f"expected non-zero return code: {outcome!r}"
    assert float(outcome["elapsed"]) < SINGLE_CALL_TIMEOUT_SEC, (
        f"command exceeded timeout budget: elapsed={outcome['elapsed']:.3f}s "
        f"limit={SINGLE_CALL_TIMEOUT_SEC}s"
    )

    category = _classify_outcome(outcome)
    assert category == "lock-contention", (
        f"test_result_lock_held_returns_lock_timeout cause_category={category} "
        f"stderr={outcome['stderr']!r}"
    )
    stderr = str(outcome.get("stderr") or "")
    stderr_lower = stderr.lower()
    assert "lock timeout" in stderr_lower or "lock-contention" in stderr_lower, stderr
    diagnostic = _extract_diagnostic(outcome)
    assert diagnostic.get("category") in LOCK_CONTENTION_CATEGORIES, (
        f"missing DOD-004 lock contention category: diagnostic={diagnostic!r} stderr={stderr!r}"
    )
    assert str(diagnostic.get("agi_id") or "").lower() == agi_id.lower(), diagnostic
    assert str(diagnostic.get("sprint_id") or "").lower() == f"s{sprint:02d}".lower(), diagnostic
    diagnostic_lock_path = Path(str(diagnostic.get("lock_path") or "")).resolve(strict=False)
    assert diagnostic_lock_path == lock_path.resolve(strict=False), diagnostic
    assert diagnostic.get("next_action") in LOCK_CONTENTION_NEXT_ACTIONS, diagnostic
    assert lock_path.exists(), f"lock file must be preserved on contention: {lock_path}"

    artifacts = outcome["partial_artifacts"]
    payload = artifacts.get("payload") if isinstance(artifacts, dict) else None
    assert not (isinstance(payload, dict) and payload.get("aux_status") == "partial"), (
        "lock diagnostic failures must not be wrapped as successful aux_status=partial "
        f"payloads: {payload!r}"
    )


def test_orphan_result_lock_file_does_not_block_success(isolated_project):
    root = isolated_project["root"]
    agi_id = isolated_project["agi_id"]
    sprint = 8
    lock_path = _sprint_dir(root, agi_id, sprint) / ".result.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("orphan lock file without an fcntl owner\n", encoding="utf-8")

    outcome = _run_agile_result(
        root,
        agi_id,
        sprint=sprint,
        summary="test_orphan_result_lock_file_does_not_block_success",
        timeout=SINGLE_CALL_TIMEOUT_SEC,
    )

    _assert_bounded(outcome, "normal", SINGLE_CALL_TIMEOUT_SEC)
    assert outcome["returncode"] == 0, (
        f"orphan result lock should not block success: stderr={outcome['stderr']!r}"
    )
    assert lock_path.exists(), f"orphan result lock file should not be deleted: {lock_path}"
    artifacts = outcome["partial_artifacts"]
    assert artifacts["result_json"] and artifacts["result_md"] and artifacts["events"], artifacts
    payload = artifacts["payload"]
    assert isinstance(payload, dict), payload
    assert payload.get("summary") == "test_orphan_result_lock_file_does_not_block_success"
    assert payload.get("aux_status") == "ok", payload
    result_json_path = _sprint_dir(root, agi_id, sprint) / "result.json"
    events_path = _events_path(root, agi_id)
    json.loads(result_json_path.read_text(encoding="utf-8"))
    events = _read_ndjson_strict(events_path)
    assert any(event.get("event") == "agile.result" and event.get("sprint_id") == "S08" for event in events)


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
