from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, Iterable


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import test_dod011_rehydration_contract as dod011


REPO_ROOT = Path(__file__).resolve().parents[1]

SID = "MST-AGI-030-20260505T030405000Z-dod013aa"
OTHER_SID = "MST-AGI-030-20260505T030406000Z-dod013bb"
ROOT = "AGI-030"
REQ = "REQ-816"


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_mst(
    workspace: Path,
    policy_home: Path,
    *args: str,
    session_id: str | None = SID,
    context: dict | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return dod011._run_mst(
        workspace,
        policy_home,
        *args,
        session_id=session_id,
        context=context,
        extra_env=extra_env,
    )


def _seed_workspace(workspace: Path, policy_home: Path, *, session_id: str = SID) -> str:
    return dod011._seed_canonical_workspace(
        workspace,
        policy_home,
        session_id=session_id,
        next_skill="mst:approve",
        next_source=REQ,
    )


def _snapshot_path(workspace: Path, *, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"


def _history_path(workspace: Path, *, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "sessions" / session_id / "history.ndjson"


def _history_rows(workspace: Path, *, session_id: str = SID) -> list[dict]:
    return dod011._history_rows(workspace, session_id=session_id)


def _extract_json(stdout: str) -> dict | None:
    for index, line in enumerate(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            try:
                payload = json.loads("\n".join(stdout.splitlines()[index:]))
            except json.JSONDecodeError:
                return None
            return payload if isinstance(payload, dict) else None
    return None


def _assert_validation_failure(
    result: subprocess.CompletedProcess[str],
    *,
    target: str,
    field: str,
) -> dict:
    payload = _extract_json(result.stdout)
    assert isinstance(payload, dict), (
        "validation failure must be emitted as structured JSON on stdout\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert result.returncode != 0 or payload.get("status") not in {"ok", "success"}, payload
    assert payload.get("status") in {"error", "failed", "validation_failed"}, payload
    assert payload.get("target") == target, payload
    assert payload.get("field") == field, payload
    assert payload.get("created_new_session") is False, payload
    assert payload.get("failure_class") or payload.get("reason") or payload.get("code"), payload
    return payload


def _invalid_context(head: str, **core_overrides: object) -> dict:
    context = dod011._context(head=head, session_id=SID, root_mst_id=ROOT)
    core = dict(context["core_rehydration"])
    for key, value in core_overrides.items():
        if value is _DELETE:
            core.pop(key, None)
        else:
            core[key] = value
    context["core_rehydration"] = core
    return context


class _Delete:
    pass


_DELETE = _Delete()


def test_snapshot_required_fields_fail_closed() -> None:
    cases = [
        ("schema_version", _DELETE),
        ("mst_session_id", _DELETE),
        ("root_mst_id", _DELETE),
        ("workflow", _DELETE),
        ("workflow.current_step", {"current_skill": "mst:request", "current_step": "3", "status": "active"}),
        ("history.last_event_id", {"ledger_path": ".gran-maestro/sessions/history.ndjson"}),
    ]
    for field, replacement in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            _seed_workspace(workspace, policy_home)
            snapshot_path = _snapshot_path(workspace)
            snapshot = _read_json(snapshot_path)
            if "." in field:
                parent, child = field.split(".", 1)
                if replacement is _DELETE:
                    assert isinstance(snapshot[parent], dict)
                    snapshot[parent].pop(child, None)
                else:
                    snapshot[parent] = replacement
            elif replacement is _DELETE:
                snapshot.pop(field, None)
            else:
                snapshot[field] = replacement
            _write_json(snapshot_path, snapshot)

            result = _run_mst(workspace, policy_home, "state", "get")

            _assert_validation_failure(result, target="state_snapshot", field=field)


def test_snapshot_path_contract_fail_closed() -> None:
    cases = [
        ("mst_session_id", lambda snapshot: {**snapshot, "mst_session_id": OTHER_SID}),
        ("root_mst_id", lambda snapshot: {**snapshot, "root_mst_id": "REQ-816"}),
        ("schema_version", lambda snapshot: {**snapshot, "schema_version": 999}),
    ]
    for field, mutate in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            _seed_workspace(workspace, policy_home)
            snapshot_path = _snapshot_path(workspace)
            _write_json(snapshot_path, mutate(_read_json(snapshot_path)))
            before_sessions = dod011._session_dirs(workspace)

            result = _run_mst(workspace, policy_home, "state", "get")

            _assert_validation_failure(result, target="state_snapshot", field=field)
            assert dod011._session_dirs(workspace) == before_sessions


def test_history_event_contract_fail_closed() -> None:
    from scripts.mst_cmds import session as session_mod

    cases = [
        ("schema_version", {"event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
        ("event_id", {"schema_version": 1, "event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
        ("idempotency_key", {"schema_version": 1, "event_id": "evt-dod013", "event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
        ("mst_session_id", {"schema_version": 1, "event_id": "evt-dod013", "idempotency_key": "dod013-key", "root_mst_id": ROOT, "event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
        ("root_mst_id", {"schema_version": 1, "event_id": "evt-dod013", "idempotency_key": "dod013-key", "mst_session_id": SID, "root_mst_id": "REQ-816", "event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
        ("artifact_id", {"schema_version": 1, "event_id": "evt-dod013", "idempotency_key": "dod013-key", "mst_session_id": SID, "root_mst_id": ROOT, "event_type": "skill.step", "skill": "mst:request", "created_at": "2026-05-05T03:04:06.000Z"}),
        ("legacy_identity", {"schema_version": 1, "event_id": "evt-dod013", "idempotency_key": "dod013-key", "session_id": SID, "event_type": "skill.step", "skill": "mst:request", "artifact_id": REQ, "created_at": "2026-05-05T03:04:06.000Z"}),
    ]
    for field, event in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            _seed_workspace(workspace, policy_home)
            before_rows = _history_rows(workspace)

            try:
                session_mod.write_session_history_event(workspace / ".gran-maestro", SID, copy.deepcopy(event))
            except Exception as exc:
                message = str(exc)
                assert "validation" in message.lower(), message
                assert field in message, message
            else:
                raise AssertionError(f"history append accepted invalid {field} event")
            finally:
                assert _history_rows(workspace) == before_rows


def test_recover_bundle_contract_fail_closed() -> None:
    cases = [
        ("core_rehydration.schema_version", {"schema_version": _DELETE}),
        ("core_rehydration.auto", {"auto": "true"}),
        ("core_rehydration.continuation", {"auto": True, "continuation": _DELETE, "current_skill": "mst:request"}),
        (
            "core_rehydration.current_skill",
            {
                "auto": True,
                "continuation": {},
                "current_skill": _DELETE,
                "workflow": {"next_skill": "mst:approve", "next_source": REQ, "status": "active"},
            },
        ),
        ("core_rehydration.history_last_event_id", {"history": {"last_event_id": "f" * 64, "head_hash": "f" * 64}}),
    ]
    for field, overrides in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_workspace(workspace, policy_home)
            context = _invalid_context(head, **overrides)

            result = _run_mst(workspace, policy_home, "recover", ROOT, context=context)

            _assert_validation_failure(result, target="recover_bundle", field=field)


def test_dispatch_envelope_contract_fail_closed() -> None:
    cases = [
        (
            "schema_version",
            {"core_rehydration": {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT, "auto": True}},
        ),
        (
            "auto",
            {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT, "core_rehydration": {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT, "auto": False}},
        ),
        (
            "legacy_identity",
            {"schema_version": 1, "session_id": SID, "core_rehydration": {"schema_version": 1, "session_id": SID}},
        ),
    ]
    for field, context in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            _seed_workspace(workspace, policy_home)

            result = _run_mst(
                workspace,
                policy_home,
                "dispatch",
                "register",
                "--task-id",
                f"dod013-{field}",
                "--pid",
                "12345",
                "--provider",
                "codex",
                "--skill",
                "mst:request",
                "--model",
                "gpt-test",
                "--worktree-dir",
                str(workspace),
                context=context,
            )

            _assert_validation_failure(result, target="dispatch_envelope", field=field)


def test_failure_shape() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_workspace(workspace, policy_home)
        snapshot_path = _snapshot_path(workspace)
        snapshot = _read_json(snapshot_path)
        snapshot["mst_session_id"] = OTHER_SID
        _write_json(snapshot_path, snapshot)

        result = _run_mst(workspace, policy_home, "state", "get")

        payload = _assert_validation_failure(result, target="state_snapshot", field="mst_session_id")
        assert payload.get("created_new_session") is False
        assert payload.get("corrected") is not True
        assert payload.get("fallback_session_id") in (None, "")


TESTS: list[Callable[[], None]] = [
    test_snapshot_required_fields_fail_closed,
    test_snapshot_path_contract_fail_closed,
    test_history_event_contract_fail_closed,
    test_recover_bundle_contract_fail_closed,
    test_dispatch_envelope_contract_fail_closed,
    test_failure_shape,
]


def _selected_tests(pattern: str | None) -> Iterable[Callable[[], None]]:
    if not pattern:
        return TESTS
    terms = [term.strip() for term in re.split(r"\s+or\s+", pattern) if term.strip()]
    return [test for test in TESTS if any(term in test.__name__ for term in terms)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", dest="pattern", default=None)
    args = parser.parse_args()

    selected = list(_selected_tests(args.pattern))
    if not selected:
        print(f"No tests selected for -k {args.pattern!r}", file=sys.stderr)
        return 5

    failures = 0
    for test in selected:
        try:
            test()
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}", file=sys.stderr)
            traceback.print_exc()
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
