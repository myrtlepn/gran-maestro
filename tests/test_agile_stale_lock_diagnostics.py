from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ZERO_HASH = "0" * 64
STALE_SECONDS = 3600

DIAGNOSTIC_ENTRYPOINTS = (
    ("scripts.mst_cmds.agile", "diagnose_agile_stale_lock"),
    ("scripts.mst_cmds.agile", "_diagnose_agile_stale_lock"),
    ("scripts.mst_cmds.agile", "diagnose_stale_lock"),
    ("scripts.mst_cmds.agile", "_diagnose_stale_lock"),
    ("scripts.mst_cmds.agile", "diagnose_history_lock"),
    ("scripts.mst_cmds.agile", "_diagnose_history_lock"),
    ("scripts.mst_cmds.hook", "diagnose_stale_lock"),
    ("scripts.mst_cmds.hook", "_diagnose_stale_lock"),
    ("scripts.mst_cmds.hook", "diagnose_history_lock"),
    ("scripts.mst_cmds.hook", "_diagnose_history_lock"),
    ("pre_tool_use_fast_under_test", "diagnose_stale_lock"),
    ("pre_tool_use_fast_under_test", "_diagnose_stale_lock"),
    ("pre_tool_use_fast_under_test", "diagnose_history_lock"),
    ("pre_tool_use_fast_under_test", "_diagnose_history_lock"),
)


def _load_fast_hook_module():
    module_path = REPO_ROOT / "hooks/lib/pre_tool_use_fast.py"
    spec = importlib.util.spec_from_file_location("pre_tool_use_fast_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostic_entrypoint():
    modules = {
        "pre_tool_use_fast_under_test": _load_fast_hook_module(),
    }
    for module_name, function_name in DIAGNOSTIC_ENTRYPOINTS:
        module = modules.get(module_name)
        if module is None:
            module = importlib.import_module(module_name)
            modules[module_name] = module
        candidate = getattr(module, function_name, None)
        if callable(candidate):
            return candidate
    expected = ", ".join(f"{module}.{name}" for module, name in DIAGNOSTIC_ENTRYPOINTS)
    pytest.fail(f"missing DOD-004 stale lock diagnostic entrypoint; expected one of: {expected}")


def _make_history_scope(tmp_path: Path, session_id: str = "dod004-session") -> dict[str, Path | str]:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    mirror_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
    session_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "history.ndjson").write_text("", encoding="utf-8")
    (session_dir / "history.head").write_text(ZERO_HASH + "\n", encoding="utf-8")
    (mirror_dir / f"{session_id}.head").write_text(ZERO_HASH + "\n", encoding="utf-8")
    return {
        "project_root": project_root,
        "home": home,
        "session_id": session_id,
        "session_dir": session_dir,
        "lock_path": session_dir / "history.lock",
        "mirror_head": mirror_dir / f"{session_id}.head",
        "local_head": session_dir / "history.head",
    }


def _write_history_lock(lock_path: Path, owner: dict[str, Any] | None = None, *, age_seconds: int = 0) -> None:
    lock_path.mkdir(parents=True, exist_ok=True)
    if owner is not None:
        (lock_path / "owner.json").write_text(
            json.dumps(owner, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(lock_path, (old, old))
        owner_path = lock_path / "owner.json"
        if owner_path.exists():
            os.utime(owner_path, (old, old))


def _make_result_scope(tmp_path: Path) -> dict[str, Path | str | int]:
    project_root = tmp_path / "project"
    agi_id = "AGI-780"
    sprint = 1
    sprint_id = "S01"
    sprint_dir = project_root / ".gran-maestro" / "agile" / agi_id / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    return {
        "project_root": project_root,
        "agi_id": agi_id,
        "sprint": sprint,
        "sprint_id": sprint_id,
        "sprint_dir": sprint_dir,
        "lock_path": sprint_dir / ".result.lock",
    }


def _call_diagnosis(**context: Any) -> dict[str, Any]:
    entrypoint = _load_diagnostic_entrypoint()
    signature = inspect.signature(entrypoint)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        result = entrypoint(**context)
    else:
        kwargs = {
            name: context[name]
            for name, parameter in signature.parameters.items()
            if name in context
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        missing = [
            name
            for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            and name not in kwargs
        ]
        if missing:
            pytest.fail(
                f"diagnostic entrypoint {entrypoint.__module__}.{entrypoint.__name__} "
                f"requires unsupported parameters: {missing}"
            )
        result = entrypoint(**kwargs)

    if hasattr(result, "__dict__") and not isinstance(result, dict):
        result = vars(result)
    assert isinstance(result, dict), f"diagnostic result must be a dict, got {type(result)}: {result!r}"
    return result


def _diagnose_history_lock(
    *,
    project_root: Path,
    home: Path,
    session_id: str,
    lock_path: Path,
) -> dict[str, Any]:
    return _call_diagnosis(
        project_root=project_root,
        base_dir=project_root / ".gran-maestro",
        home=home,
        policy_home=home / ".claude" / "gran-maestro-policy",
        session_id=session_id,
        lock_path=lock_path,
        lock_kind="history",
        kind="history",
        stale_after_sec=STALE_SECONDS,
    )


def _diagnose_result_lock(
    *,
    project_root: Path,
    agi_id: str,
    sprint: int,
    sprint_id: str,
    lock_path: Path,
) -> dict[str, Any]:
    return _call_diagnosis(
        project_root=project_root,
        base_dir=project_root / ".gran-maestro",
        agi_id=agi_id,
        sprint=sprint,
        sprint_id=sprint_id,
        lock_path=lock_path,
        lock_kind="result",
        kind="result",
        stale_after_sec=STALE_SECONDS,
    )


def _diagnose_history_scope(scope: dict[str, Path | str]) -> dict[str, Any]:
    return _diagnose_history_lock(
        project_root=scope["project_root"],  # type: ignore[arg-type]
        home=scope["home"],  # type: ignore[arg-type]
        session_id=scope["session_id"],  # type: ignore[arg-type]
        lock_path=scope["lock_path"],  # type: ignore[arg-type]
    )


def _diagnose_result_scope(scope: dict[str, Path | str | int]) -> dict[str, Any]:
    return _diagnose_result_lock(
        project_root=scope["project_root"],  # type: ignore[arg-type]
        agi_id=scope["agi_id"],  # type: ignore[arg-type]
        sprint=scope["sprint"],  # type: ignore[arg-type]
        sprint_id=scope["sprint_id"],  # type: ignore[arg-type]
        lock_path=scope["lock_path"],  # type: ignore[arg-type]
    )


def _assert_preserved(path: Path) -> None:
    assert os.path.lexists(path), f"diagnosis must not delete {path}"


def _assert_diagnostic(
    payload: dict[str, Any],
    *,
    category: str,
    next_action: str,
    required_fields: tuple[str, ...],
) -> None:
    assert payload.get("category") == category, payload
    assert payload.get("next_action") == next_action, payload
    for field in required_fields:
        assert payload.get(field) not in (None, ""), f"missing {field}: {payload!r}"
    assert payload.get("aux_status") != "partial", (
        "stale lock diagnostic failures must not be wrapped as successful aux_status=partial "
        f"payloads: {payload!r}"
    )


def test_history_lock_live_owner_is_preserved(tmp_path: Path) -> None:
    scope = _make_history_scope(tmp_path)
    lock_path = scope["lock_path"]
    assert isinstance(lock_path, Path)
    owner_pid = os.getpid()
    _write_history_lock(
        lock_path,
        {
            "owner_pid": owner_pid,
            "owner_started_at": time.time(),
            "session_id": scope["session_id"],
        },
    )

    payload = _diagnose_history_scope(scope)

    _assert_diagnostic(
        payload,
        category="owner-live",
        next_action="wait-for-owner",
        required_fields=("lock_path", "owner_pid", "owner_status"),
    )
    assert int(payload["owner_pid"]) == owner_pid
    _assert_preserved(lock_path)


def test_history_lock_owner_unknown_is_preserved(tmp_path: Path) -> None:
    scope = _make_history_scope(tmp_path)
    lock_path = scope["lock_path"]
    assert isinstance(lock_path, Path)
    _write_history_lock(lock_path, {"session_id": scope["session_id"]}, age_seconds=STALE_SECONDS + 30)

    payload = _diagnose_history_scope(scope)

    _assert_diagnostic(
        payload,
        category="owner-unknown",
        next_action="inspect-lock-owner",
        required_fields=("lock_path", "owner_status", "reason"),
    )
    _assert_preserved(lock_path)


def test_history_lock_process_lookup_failure_is_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _make_history_scope(tmp_path)
    lock_path = scope["lock_path"]
    assert isinstance(lock_path, Path)
    _write_history_lock(
        lock_path,
        {
            "owner_pid": os.getpid(),
            "owner_started_at": time.time(),
            "session_id": scope["session_id"],
        },
    )

    def raise_permission_error(pid: int, signal: int) -> None:
        raise PermissionError("process lookup denied")

    monkeypatch.setattr(os, "kill", raise_permission_error)
    payload = _diagnose_history_scope(scope)

    _assert_diagnostic(
        payload,
        category="diagnosis-inconclusive",
        next_action="inspect-lock-owner",
        required_fields=("lock_path", "reason"),
    )
    _assert_preserved(lock_path)


def test_history_lock_stale_candidate_requires_manual_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _make_history_scope(tmp_path)
    lock_path = scope["lock_path"]
    assert isinstance(lock_path, Path)
    _write_history_lock(
        lock_path,
        {
            "owner_pid": 987654321,
            "owner_started_at": time.time() - STALE_SECONDS - 30,
            "session_id": scope["session_id"],
        },
        age_seconds=STALE_SECONDS + 30,
    )

    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError("owner process is gone")

    monkeypatch.setattr(os, "kill", raise_process_lookup)
    payload = _diagnose_history_scope(scope)

    _assert_diagnostic(
        payload,
        category="history-lock-stale-candidate",
        next_action="manual-recovery-approval",
        required_fields=("lock_path", "lock_age"),
    )
    assert float(payload["lock_age"]) >= STALE_SECONDS
    _assert_preserved(lock_path)


def test_ledger_mismatch_blocks_stale_lock_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _make_history_scope(tmp_path)
    lock_path = scope["lock_path"]
    local_head = scope["local_head"]
    assert isinstance(lock_path, Path) and isinstance(local_head, Path)
    local_head.write_text("1" * 64 + "\n", encoding="utf-8")
    _write_history_lock(
        lock_path,
        {
            "owner_pid": 987654321,
            "owner_started_at": time.time() - STALE_SECONDS - 30,
            "session_id": scope["session_id"],
        },
        age_seconds=STALE_SECONDS + 30,
    )

    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError("owner process is gone")

    monkeypatch.setattr(os, "kill", raise_process_lookup)
    payload = _diagnose_history_scope(scope)

    _assert_diagnostic(
        payload,
        category="ledger-mismatch",
        next_action="run-ledger-verification",
        required_fields=("lock_path", "ledger_status"),
    )
    _assert_preserved(lock_path)
    assert payload.get("category") != "history-lock-stale-candidate", payload


def test_lock_scope_mismatch_is_preserved(tmp_path: Path) -> None:
    scope = _make_history_scope(tmp_path)
    outside_lock = tmp_path / "outside-scope" / "history.lock"
    _write_history_lock(outside_lock, {"owner_pid": os.getpid(), "owner_started_at": time.time()})

    payload = _diagnose_history_lock(
        project_root=scope["project_root"],  # type: ignore[arg-type]
        home=scope["home"],  # type: ignore[arg-type]
        session_id=scope["session_id"],  # type: ignore[arg-type]
        lock_path=outside_lock,
    )

    _assert_diagnostic(
        payload,
        category="scope-mismatch",
        next_action="inspect-lock-owner",
        required_fields=("lock_path", "scope_status"),
    )
    _assert_preserved(outside_lock)


def test_partial_result_artifact_blocks_auto_recovery(tmp_path: Path) -> None:
    scope = _make_result_scope(tmp_path)
    lock_path = scope["lock_path"]
    sprint_dir = scope["sprint_dir"]
    assert isinstance(lock_path, Path) and isinstance(sprint_dir, Path)
    lock_path.write_text("orphan result lock\n", encoding="utf-8")
    artifact_path = sprint_dir / "result.json.tmp"
    artifact_path.write_text('{"status": "done"', encoding="utf-8")

    payload = _diagnose_result_scope(scope)

    _assert_diagnostic(
        payload,
        category="partial-output-detected",
        next_action="inspect-partial-output",
        required_fields=("lock_path", "artifact_path"),
    )
    _assert_preserved(lock_path)
    _assert_preserved(artifact_path)
