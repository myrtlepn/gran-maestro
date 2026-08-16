from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-DBG-946-20260816T060000000Z-inherited1"
OTHER_SID = "MST-DBG-946-20260816T060000001Z-inherited2"


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _run(
    workspace: Path,
    *args: str,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(env),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _files(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _bootstrap(workspace: Path, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(
        workspace,
        "session",
        "bootstrap",
        "--root-mst-id",
        "DBG-946",
        "--json",
        env=env,
    )


@pytest.mark.parametrize(
    ("authority", "expected_source"),
    [
        ({"MST_SESSION_ID": SID}, "env:MST_SESSION_ID"),
        (
            {
                "MST_CONTEXT_JSON": json.dumps(
                    {"schema_version": 1, "mst_session_id": SID, "root_mst_id": "DBG-946"}
                )
            },
            "context:MST_CONTEXT_JSON",
        ),
    ],
)
def test_exact_inherited_sid_is_persisted_and_reused(
    tmp_path: Path,
    authority: dict[str, str],
    expected_source: str,
) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    first = _bootstrap(tmp_path, env=authority)
    second = _bootstrap(tmp_path, env=authority)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["mst_session_id"] == SID
    assert first_payload["identity_source"] == expected_source
    assert first_payload["mutation_performed"] is True
    assert first_payload["root_artifact_created"] is True
    assert first_payload["session_metadata_created"] is True
    assert second_payload["mst_session_id"] == SID
    assert second_payload["identity_source"] == expected_source
    assert second_payload["mutation_performed"] is False
    assert second_payload["root_artifact_created"] is False
    assert second_payload["session_metadata_created"] is False
    files = set(_files(tmp_path))
    assert {
        "debug/DBG-946/session.json",
        f"sessions/{SID}/session.json",
    }.issubset(files)
    assert all(path == "debug/DBG-946/session.json" or SID in path for path in files)
    assert all(OTHER_SID not in path for path in files)


def test_child_preserves_valid_context_only_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.mst_cmds import session

    for key in ("MST_SESSION_ID", "MST_HOOK_STDIN_RAW"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "MST_CONTEXT_JSON",
        json.dumps(
            {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": "DBG-946",
                "preserved": "context-only",
            }
        ),
    )

    child_env = session.child_env_with_required_session_context()

    assert child_env["MST_SESSION_ID"] == SID
    child_context = json.loads(child_env["MST_CONTEXT_JSON"])
    assert child_context["mst_session_id"] == SID
    assert child_context["preserved"] == "context-only"


@pytest.mark.parametrize("source", ["hook", "stdin"])
def test_child_does_not_promote_hook_or_stdin_only_identity(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    from scripts.mst_cmds import session

    monkeypatch.delenv("MST_SESSION_ID", raising=False)
    monkeypatch.delenv("MST_CONTEXT_JSON", raising=False)
    monkeypatch.delenv("MST_HOOK_STDIN_RAW", raising=False)
    payload = json.dumps({"mst_session_id": SID})
    if source == "hook":
        monkeypatch.setenv("MST_HOOK_STDIN_RAW", payload)
    else:
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    with pytest.raises(ValueError, match="missing MST_SESSION_ID"):
        session.child_env_with_required_session_context()


@pytest.mark.parametrize(
    ("extra_env", "stdin"),
    [
        ({"MST_CONTEXT_JSON": "{"}, None),
        ({"MST_CONTEXT_JSON": "{}"}, None),
        ({"MST_CONTEXT_JSON": json.dumps({"preserved": "but-no-identity"})}, None),
        ({"MST_CONTEXT_JSON": json.dumps({"session_id": "legacy-only"})}, None),
        (
            {
                "MST_CONTEXT_JSON": json.dumps(
                    {
                        "schema_version": 1,
                        "mst_session_id": SID,
                        "root_mst_id": "DBG-946",
                        "core_rehydration": {
                            "schema_version": 1,
                            "mst_session_id": OTHER_SID,
                            "root_mst_id": "DBG-946",
                        },
                    }
                )
            },
            None,
        ),
        (
            {
                "MST_CONTEXT_JSON": json.dumps(
                    {"schema_version": 1, "mst_session_id": SID, "root_mst_id": "DBG-947"}
                )
            },
            None,
        ),
        ({"MST_HOOK_STDIN_RAW": json.dumps({"mst_session_id": SID})}, None),
        ({}, json.dumps({"mst_session_id": SID})),
    ],
)
@pytest.mark.parametrize("command", [("session", "resolve", "--json"), ("session", "bootstrap", "--root-mst-id", "DBG-946", "--json")])
def test_noncanonical_or_conflicting_identity_is_structured_no_mutation(
    tmp_path: Path,
    extra_env: dict[str, str],
    stdin: str | None,
    command: tuple[str, ...],
) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    before = _files(tmp_path)

    result = _run(tmp_path, *command, env=extra_env, stdin=stdin)

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] in {"error", "validation_failed", "non_success"}
    assert payload["mutation_performed"] is False
    assert payload["created_new_session"] is False
    assert _files(tmp_path) == before


def test_bootstrap_root_argument_mismatch_is_zero_mutation(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()

    result = _run(
        tmp_path,
        "session",
        "bootstrap",
        "--root-mst-id",
        "DBG-947",
        "--json",
        env={"MST_SESSION_ID": SID},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["mutation_performed"] is False
    assert _files(tmp_path) == {}


def test_concurrent_first_bootstrap_linearizes_to_one_session(tmp_path: Path) -> None:
    (tmp_path / ".gran-maestro").mkdir()
    command = [
        sys.executable,
        str(MST_SCRIPT),
        "session",
        "bootstrap",
        "--root-mst-id",
        "DBG-946",
        "--json",
    ]
    processes = [
        subprocess.Popen(
            command,
            cwd=tmp_path,
            env=_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [process.communicate(timeout=30) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    payloads = [json.loads(stdout) for stdout, _stderr in results]
    session_ids = {payload["mst_session_id"] for payload in payloads}
    assert len(session_ids) == 1
    winning_sid = session_ids.pop()
    assert sum(payload["mutation_performed"] is True for payload in payloads) == 1
    assert set(_files(tmp_path)) == {
        "debug/DBG-946/session.json",
        f"sessions/{winning_sid}/session.json",
    }


def test_failed_exact_bootstrap_rollback_keeps_preexisting_session_metadata(
    tmp_path: Path,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    session_path = session.session_metadata_path(base, SID)
    root_path = session.root_artifact_metadata_path(base, "DBG-946")
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        json.dumps(session._session_metadata_payload(base, root_path, session.validate_mst_session_id(SID))) + "\n",
        encoding="utf-8",
    )
    before = session_path.read_bytes()

    with pytest.raises(session.RootSessionCreateError, match="after_root_artifact_commit"):
        session.ensure_root_session_artifacts(
            base,
            "DBG-946",
            mst_session_id=SID,
            failure_stage="after_root_artifact_commit",
        )

    assert session_path.read_bytes() == before
    assert not root_path.exists()


def test_exact_api_rejects_conflicting_root_payload_before_commit(tmp_path: Path) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"

    with pytest.raises(ValueError, match="mismatch"):
        session.ensure_root_session_artifacts(
            base,
            "DBG-946",
            mst_session_id=SID,
            root_payload={"mst_session_id": OTHER_SID, "root_mst_id": "DBG-946"},
        )

    assert _files(tmp_path) == {}
