from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest


ZERO_HASH = "0" * 64
STALE_SECONDS = 3600
LEDGER_SPECIFIC_NEXT_ACTIONS = {
    "run-ledger-verification",
    "verify-ledger",
    "run-history-ledger-verification",
}
NON_LEDGER_NEXT_ACTIONS = {
    "wait-for-owner",
    "retry",
    "inspect-partial-output",
}

DIAGNOSTIC_ENTRYPOINTS = (
    ("scripts.mst_cmds.agile", "diagnose_history_lock"),
    ("scripts.mst_cmds.agile", "_diagnose_history_lock"),
    ("scripts.mst_cmds.agile", "diagnose_agile_stale_lock"),
    ("scripts.mst_cmds.agile", "diagnose_stale_lock"),
)


def _load_diagnostic_entrypoint():
    for module_name, function_name in DIAGNOSTIC_ENTRYPOINTS:
        module = importlib.import_module(module_name)
        candidate = getattr(module, function_name, None)
        if callable(candidate):
            return candidate
    expected = ", ".join(f"{module}.{name}" for module, name in DIAGNOSTIC_ENTRYPOINTS)
    pytest.fail(f"missing ledger mismatch diagnostic entrypoint; expected one of: {expected}")


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
    assert isinstance(result, dict), f"diagnostic result must be a dict, got {type(result)}"
    return result


def _hash_history_event(previous_hash: str, event: dict[str, Any]) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((previous_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _write_controlled_mirror_head_mismatch(
    tmp_path: Path,
    *,
    session_id: str = "dod005-ledger-mismatch",
) -> dict[str, Path | str]:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    mirror_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
    session_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)

    event = {
        "event": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
    }
    event_hash = _hash_history_event(ZERO_HASH, event)
    row = {
        "seq": 1,
        "prev_hash": ZERO_HASH,
        "event": event,
        "event_hash": event_hash,
    }

    history_ndjson = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    verify_state = session_dir / "history.verify"
    mirror_head = mirror_dir / f"{session_id}.head"
    lock_path = session_dir / "history.lock"

    history_ndjson.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    verify_state.write_text(
        json.dumps({"cached_head": event_hash, "cached_seq": 1}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    mirror_head.write_text("f" * 64 + "\n", encoding="utf-8")

    lock_path.mkdir(parents=True, exist_ok=True)
    (lock_path / "owner.json").write_text(
        json.dumps(
            {
                "owner_pid": 987654321,
                "owner_started_at": time.time() - STALE_SECONDS - 30,
                "session_id": session_id,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    old = time.time() - STALE_SECONDS - 30
    os.utime(lock_path, (old, old))
    os.utime(lock_path / "owner.json", (old, old))

    return {
        "project_root": project_root,
        "home": home,
        "session_id": session_id,
        "session_dir": session_dir,
        "lock_path": lock_path,
        "history_ndjson": history_ndjson,
        "local_head": local_head,
        "verify_state": verify_state,
        "mirror_head": mirror_head,
    }


def _diagnose_mismatch_scope(
    scope: dict[str, Path | str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError("owner process is gone")

    monkeypatch.setattr(os, "kill", raise_process_lookup)
    return _call_diagnosis(
        project_root=scope["project_root"],
        base_dir=Path(scope["project_root"]) / ".gran-maestro",
        home=scope["home"],
        policy_home=Path(scope["home"]) / ".claude" / "gran-maestro-policy",
        session_id=scope["session_id"],
        lock_path=scope["lock_path"],
        lock_kind="history",
        kind="history",
        stale_after_sec=STALE_SECONDS,
    )


def _diagnose_mismatch_scope_with_policy_home_only(
    scope: dict[str, Path | str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError("owner process is gone")

    monkeypatch.setattr(os, "kill", raise_process_lookup)
    return _call_diagnosis(
        project_root=scope["project_root"],
        base_dir=Path(scope["project_root"]) / ".gran-maestro",
        home=Path(scope["home"]) / "unrelated-home",
        policy_home=Path(scope["home"]) / ".claude" / "gran-maestro-policy",
        session_id=scope["session_id"],
        lock_path=scope["lock_path"],
        lock_kind="history",
        kind="history",
        stale_after_sec=STALE_SECONDS,
    )


def _snapshot_sentinels(scope: dict[str, Path | str]) -> dict[str, bytes]:
    labels = ("history_ndjson", "local_head", "verify_state", "mirror_head")
    return {label: Path(scope[label]).read_bytes() for label in labels}


def test_ledger_mismatch_diagnostic_returns_bounded_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)

    started = time.monotonic()
    payload = _diagnose_mismatch_scope(scope, monkeypatch)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"ledger mismatch diagnosis must be bounded: {elapsed:.3f}s"
    assert payload.get("category") == "ledger-mismatch", payload
    assert payload.get("category") not in {
        "result-lock-contention",
        "lock-contention",
        "history-lock-stale-candidate",
        "owner-live",
    }
    ledger_status = payload.get("ledger_status")
    assert isinstance(ledger_status, dict), payload
    assert ledger_status.get("ok") is False, payload
    assert ledger_status.get("reason") in {"home mirror head", "mirror head"}, payload


def test_ledger_mismatch_next_action_is_ledger_specific(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)

    payload = _diagnose_mismatch_scope(scope, monkeypatch)

    assert payload.get("category") == "ledger-mismatch", payload
    assert payload.get("next_action") in LEDGER_SPECIFIC_NEXT_ACTIONS, payload
    assert payload.get("next_action") not in NON_LEDGER_NEXT_ACTIONS, payload


def test_ledger_mismatch_diagnostic_uses_policy_home_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)

    payload = _diagnose_mismatch_scope_with_policy_home_only(scope, monkeypatch)

    assert payload.get("category") == "ledger-mismatch", payload
    ledger_status = payload.get("ledger_status")
    assert isinstance(ledger_status, dict), payload
    assert ledger_status.get("reason") in {"home mirror head", "mirror head"}, payload


def test_ledger_mismatch_is_not_successful_aux_status_partial_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)

    payload = _diagnose_mismatch_scope(scope, monkeypatch)

    assert payload.get("category") == "ledger-mismatch", payload
    assert payload.get("aux_status") != "partial", payload
    assert not (
        payload.get("status") in {"done", "completed", "accepted"}
        and payload.get("aux_status") == "partial"
    ), payload


def test_ledger_mismatch_diagnostic_does_not_create_success_result_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)
    sprint_dir = (
        Path(scope["project_root"])
        / ".gran-maestro"
        / "agile"
        / "AGI-783"
        / "sprints"
        / "S01"
    )
    sprint_dir.mkdir(parents=True, exist_ok=True)
    result_json = sprint_dir / "result.json"
    result_md = sprint_dir / "result.md"

    payload = _diagnose_mismatch_scope(scope, monkeypatch)

    assert payload.get("category") == "ledger-mismatch", payload
    assert not result_json.exists(), f"ledger diagnostic must not create {result_json}"
    assert not result_md.exists(), f"ledger diagnostic must not create {result_md}"


def test_ledger_mismatch_sentinel_preserved_after_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _write_controlled_mirror_head_mismatch(tmp_path)
    before = _snapshot_sentinels(scope)

    payload = _diagnose_mismatch_scope(scope, monkeypatch)
    after = _snapshot_sentinels(scope)

    assert payload.get("category") == "ledger-mismatch", payload
    assert after == before
