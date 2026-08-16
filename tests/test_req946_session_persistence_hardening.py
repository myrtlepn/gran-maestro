from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
ROOT_ID = "DBG-946"
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
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(env),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _tree(path: Path) -> list[tuple[str, str, bytes | None]]:
    if not path.exists() and not path.is_symlink():
        return []
    entries: list[tuple[str, str, bytes | None]] = []
    for entry in sorted(path.rglob("*")):
        relative = str(entry.relative_to(path))
        if entry.is_symlink():
            entries.append((relative, "symlink", os.readlink(entry).encode()))
        elif entry.is_dir():
            entries.append((relative, "dir", None))
        else:
            entries.append((relative, "file", entry.read_bytes()))
    return entries


STRICT_CONTEXT_FAILURES = [
    '{"schema_version":1,"mst_session_id":"%s","mst_session_id":"%s","root_mst_id":"DBG-946"}'
    % (SID, OTHER_SID),
    '{"schema_version":1,"mst_session_id":"%s","root_mst_id":"DBG-946","value":NaN}' % SID,
    '{"schema_version":1,"mst_session_id":"%s","root_mst_id":"DBG-946","value":Infinity}' % SID,
    json.dumps({"schema_version": True, "mst_session_id": SID, "root_mst_id": ROOT_ID}),
    json.dumps({"schema_version": 1.0, "mst_session_id": SID, "root_mst_id": ROOT_ID}),
    json.dumps({"schema_version": 1, "mst_session_id": "", "root_mst_id": ROOT_ID}),
    json.dumps({"schema_version": 1, "mst_session_id": SID, "root_mst_id": 0}),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": 0,
            "root_mst_id": ROOT_ID,
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT_ID,
            },
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT_ID,
            "core_rehydration": [],
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": "",
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT_ID,
            },
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT_ID,
            "core_rehydration": {
                "schema_version": False,
                "mst_session_id": SID,
                "root_mst_id": ROOT_ID,
            },
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT_ID,
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": 0,
                "root_mst_id": ROOT_ID,
            },
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT_ID,
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT_ID,
                "next_execution": {"env": {"MST_SESSION_ID": OTHER_SID}},
            },
        }
    ),
    json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT_ID,
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT_ID,
                "execution_handoff": {
                    "mst_session_id": SID,
                    "root_mst_id": "DBG-947",
                },
            },
        }
    ),
]


@pytest.mark.parametrize("raw_context", STRICT_CONTEXT_FAILURES)
@pytest.mark.parametrize(
    "command",
    [
        ("session", "resolve", "--json"),
        ("session", "bootstrap", "--root-mst-id", ROOT_ID, "--json"),
    ],
)
def test_strict_structured_context_rejects_ambiguous_json_before_mutation(
    tmp_path: Path,
    raw_context: str,
    command: tuple[str, ...],
) -> None:
    before = _tree(tmp_path)

    result = _run(tmp_path, *command, env={"MST_CONTEXT_JSON": raw_context})

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["mutation_performed"] is False
    assert payload["created_new_session"] is False
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "context_payload",
    [
        {},
        {"preserved": "but-no-canonical-identity"},
        {"session_id": "legacy-only"},
        {"sessionId": "legacy-only"},
        {"owner_session_id": "legacy-only"},
        {"core_rehydration": {"session_id": "legacy-only"}},
    ],
)
@pytest.mark.parametrize(
    "command",
    [
        ("session", "resolve", "--json"),
        ("session", "bootstrap", "--root-mst-id", ROOT_ID, "--json"),
    ],
)
def test_env_plus_noncanonical_context_fails_closed(
    tmp_path: Path,
    context_payload: dict[str, object],
    command: tuple[str, ...],
) -> None:
    before = _tree(tmp_path)
    context = json.dumps(context_payload)

    result = _run(
        tmp_path,
        *command,
        env={"MST_SESSION_ID": SID, "MST_CONTEXT_JSON": context},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["mutation_performed"] is False
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("raw_context", STRICT_CONTEXT_FAILURES)
def test_child_context_transport_uses_the_same_strict_parser(
    monkeypatch: pytest.MonkeyPatch,
    raw_context: str,
) -> None:
    from scripts.mst_cmds import session

    monkeypatch.setenv("MST_SESSION_ID", SID)
    monkeypatch.setenv("MST_CONTEXT_JSON", raw_context)

    with pytest.raises(ValueError):
        session.child_env_with_required_session_context()


@pytest.mark.parametrize("linked_relative", ["debug", "sessions", "debug/DBG-946"])
def test_existing_symlink_components_cannot_redirect_session_persistence(
    tmp_path: Path,
    linked_relative: str,
) -> None:
    base = tmp_path / ".gran-maestro"
    victim = tmp_path / "victim"
    victim.mkdir()
    linked_path = base / linked_relative
    linked_path.parent.mkdir(parents=True, exist_ok=True)
    linked_path.symlink_to(victim, target_is_directory=True)
    before_workspace = _tree(base)
    before_victim = _tree(victim)

    result = _run(
        tmp_path,
        "session",
        "bootstrap",
        "--root-mst-id",
        ROOT_ID,
        "--json",
        env={"MST_SESSION_ID": SID},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["mutation_performed"] is False
    assert _tree(base) == before_workspace
    assert _tree(victim) == before_victim


def test_symlinked_canonical_base_is_rejected_without_external_write(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (tmp_path / ".gran-maestro").symlink_to(victim, target_is_directory=True)
    before = _tree(victim)

    result = _run(
        tmp_path,
        "session",
        "bootstrap",
        "--root-mst-id",
        ROOT_ID,
        "--json",
        env={"MST_SESSION_ID": SID},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["mutation_performed"] is False
    assert _tree(victim) == before


@pytest.mark.parametrize(
    "linked_relative",
    [
        "debug/DBG-946/session.json",
        f"sessions/{SID}/session.json",
    ],
)
def test_existing_symlink_metadata_file_is_rejected_without_external_write(
    tmp_path: Path,
    linked_relative: str,
) -> None:
    base = tmp_path / ".gran-maestro"
    victim = tmp_path / "victim.json"
    victim.write_text("preserve\n", encoding="utf-8")
    linked_path = base / linked_relative
    linked_path.parent.mkdir(parents=True, exist_ok=True)
    linked_path.symlink_to(victim)
    before_workspace = _tree(base)
    before_victim = victim.read_bytes()

    result = _run(
        tmp_path,
        "session",
        "bootstrap",
        "--root-mst-id",
        ROOT_ID,
        "--json",
        env={"MST_SESSION_ID": SID},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["mutation_performed"] is False
    assert _tree(base) == before_workspace
    assert victim.read_bytes() == before_victim


def test_symlink_swap_during_commit_rolls_back_its_own_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    base.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    moved = victim / "moved-root"
    root_parent = base / "debug" / ROOT_ID
    real_replace = os.replace
    swapped = False

    def _swap_then_replace(src, dst, *args, **kwargs):
        nonlocal swapped
        if not swapped and dst == "session.json" and root_parent.is_dir():
            swapped = True
            shutil.move(str(root_parent), str(moved))
            root_parent.symlink_to(victim, target_is_directory=True)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", _swap_then_replace)

    with pytest.raises(session.RootSessionCreateError):
        session.ensure_root_session_artifacts(base, ROOT_ID, mst_session_id=SID)

    assert swapped is True
    assert not (victim / "session.json").exists()
    assert not (moved / "session.json").exists()


def test_second_commit_swap_rolls_back_first_commit_through_retained_dir_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    base.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    moved = victim / "moved-root"
    root_parent = base / "debug" / ROOT_ID
    real_replace = os.replace
    replace_count = 0

    def _swap_root_during_second_replace(src, dst, *args, **kwargs):
        nonlocal replace_count
        if dst == "session.json":
            replace_count += 1
            if replace_count == 2:
                shutil.move(str(root_parent), str(moved))
                root_parent.symlink_to(victim, target_is_directory=True)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", _swap_root_during_second_replace)

    with pytest.raises(session.RootSessionCreateError):
        session.ensure_root_session_artifacts(base, ROOT_ID, mst_session_id=SID)

    assert replace_count >= 2
    assert not (moved / "session.json").exists()
    assert not (base / "sessions" / SID / "session.json").exists()


@pytest.mark.parametrize(
    "root_id,session_id",
    [
        ("DBG-" + "9" * 300, None),
        ("DBG-" + "9" * 220, None),
        (ROOT_ID, "MST-DBG-946-20260816T060000000Z-" + "a" * 300),
    ],
)
def test_overlong_identity_components_fail_before_lock_or_workspace_creation(
    tmp_path: Path,
    root_id: str,
    session_id: str | None,
) -> None:
    env = {"MST_SESSION_ID": session_id} if session_id else None
    before = _tree(tmp_path)

    result = _run(
        tmp_path,
        "session",
        "bootstrap",
        "--root-mst-id",
        root_id,
        "--json",
        env=env,
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["mutation_performed"] is False
    assert payload["created_new_session"] is False
    assert _tree(tmp_path) == before


def test_overlong_direct_random_rejects_before_lock_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"

    def _unexpected_lock(_path: Path):
        raise AssertionError("lock creation must not run for an overlong generated SID")

    monkeypatch.setattr(session, "_open_session_bootstrap_lock", _unexpected_lock)

    with pytest.raises(session.MstSessionIdValidationError, match="UTF-8 bytes"):
        session.ensure_root_session_artifacts(base, ROOT_ID, random_segment="a" * 300)

    assert not base.exists()


def _valid_artifacts(base: Path) -> tuple[Path, Path]:
    from scripts.mst_cmds import session

    result = session.ensure_root_session_artifacts(base, ROOT_ID, mst_session_id=SID)
    return result["root_artifact_path"], result["session_metadata_path"]


@pytest.mark.parametrize(
    "target,field,bad_value",
    [
        ("root", "id", "DBG-947"),
        ("root", "id", ""),
        ("root", "id", 946),
        ("root", "mst_session_id", ""),
        ("root", "mst_session_id", 946),
        ("root", "root_mst_id", ""),
        ("root", "root_mst_id", 946),
        ("root", "started_at", ""),
        ("root", "started_at", 946),
        ("root", "started_at_compact", "20260816T060000001Z"),
        ("root", "started_at_compact", False),
        ("root", "random", ""),
        ("root", "random", 946),
        ("root", "schema_version", True),
        ("root", "schema_version", 1.0),
        ("root", "root_artifact_path", "elsewhere/session.json"),
        ("root", "root_artifact_path", 946),
        ("session", "mst_session_id", ""),
        ("session", "mst_session_id", OTHER_SID),
        ("session", "mst_session_id", 946),
        ("session", "id", "DBG-947"),
        ("session", "id", 946),
        ("session", "root_mst_id", 946),
        ("session", "started_at", "2026-08-16T06:00:00.001Z"),
        ("session", "started_at_compact", ""),
        ("session", "random", False),
        ("session", "schema_version", True),
        ("session", "schema_version", 1.0),
        ("session", "root_artifact_path", ""),
        ("session", "root_artifact_path", 946),
    ],
)
def test_corrupt_present_metadata_fields_fail_without_repair(
    tmp_path: Path,
    target: str,
    field: str,
    bad_value: object,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    root_path, session_path = _valid_artifacts(base)
    corrupt_path = root_path if target == "root" else session_path
    payload = json.loads(corrupt_path.read_text(encoding="utf-8"))
    payload[field] = bad_value
    corrupt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before = _tree(base)

    with pytest.raises((session.MstSessionIdValidationError, session.RootSessionCreateError, ValueError)):
        session.ensure_root_session_artifacts(base, ROOT_ID, mst_session_id=SID)

    assert _tree(base) == before


@pytest.mark.parametrize(
    "target,raw_payload",
    [
        (
            "root",
            '{"id":"DBG-946","mst_session_id":"%s","mst_session_id":"%s"}' % (SID, OTHER_SID),
        ),
        (
            "session",
            '{"schema_version":1,"mst_session_id":"%s","root_mst_id":"DBG-946","value":NaN}' % SID,
        ),
    ],
)
def test_persisted_metadata_uses_strict_json_parser(
    tmp_path: Path,
    target: str,
    raw_payload: str,
) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    root_path, session_path = _valid_artifacts(base)
    corrupt_path = root_path if target == "root" else session_path
    corrupt_path.write_text(raw_payload + "\n", encoding="utf-8")
    before = _tree(base)

    with pytest.raises(session.RootSessionCreateError):
        session.ensure_root_session_artifacts(base, ROOT_ID, mst_session_id=SID)

    assert _tree(base) == before
