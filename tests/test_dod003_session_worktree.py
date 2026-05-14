from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "mst-session-init.sh"
MST_SESSION_ID = "MST-AGI-038-20260515T010203004Z-abc12345"
LEGACY_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SESSION_WORKTREE_OUTCOME_KEY = "session_worktree_outcome"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_git_ok(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    _assert_git_ok(_run_git(repo_root, "init"))
    _assert_git_ok(_run_git(repo_root, "config", "user.email", "tester@example.com"))
    _assert_git_ok(_run_git(repo_root, "config", "user.name", "Test User"))
    _assert_git_ok(_run_git(repo_root, "commit", "--allow-empty", "-m", "initial commit"))
    _assert_git_ok(_run_git(repo_root, "branch", "-M", "master"))
    return repo_root


def _hook_env(repo_root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    home = repo_root.parent / "home"
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_DISABLE_AUTO_MIGRATE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(home)
    env["MST_CLAUDE_HOME"] = str(home)
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
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


def _hook_payload(
    *,
    mst_session_id: str | None = MST_SESSION_ID,
    session_id: str = LEGACY_SESSION_ID,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        "owner_ppid": 424242,
        "owner_session_id": "diagnostic-only-owner",
    }
    if mst_session_id is not None:
        payload["mst_session_id"] = mst_session_id
    return payload


def _run_session_start(
    repo_root: Path,
    *,
    payload: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        cwd=repo_root,
        input=json.dumps(payload or _hook_payload(), ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        env=_hook_env(repo_root, env),
        check=False,
        timeout=30,
    )


def _head_branch(repo_root: Path) -> str:
    return _assert_git_ok(_run_git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD"))


def _head_sha(repo_root: Path) -> str:
    return _assert_git_ok(_run_git(repo_root, "rev-parse", "HEAD"))


def _session_branch(session_id: str = MST_SESSION_ID) -> str:
    return f"gran-maestro/session/{session_id}"


def _session_worktree_path(repo_root: Path, session_id: str = MST_SESSION_ID) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / "sessions" / session_id


def _session_json_path(repo_root: Path, session_id: str = MST_SESSION_ID) -> Path:
    return repo_root / ".gran-maestro" / "sessions" / session_id / "session.json"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _worktree_list(repo_root: Path) -> list[dict[str, str]]:
    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    assert result.returncode == 0, result.stderr
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = raw_line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def _create_manual_session_worktree(repo_root: Path, *, session_id: str = MST_SESSION_ID, base_branch: str = "master") -> Path:
    session_path = _session_worktree_path(repo_root, session_id)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        _session_branch(session_id),
        str(session_path),
        base_branch,
    )
    assert result.returncode == 0, result.stderr
    return session_path


def test_clean_session_metadata_creates_session_json_for_session_worktree(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    before_branch = _head_branch(repo_root)
    before_sha = _head_sha(repo_root)

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    session_json = _session_json_path(repo_root)
    assert session_json.exists(), result.stderr

    payload = _read_json(session_json)
    assert payload["mst_session_id"] == MST_SESSION_ID
    assert payload["session_worktree_path"] == str(_session_worktree_path(repo_root))
    assert payload["session_branch"] == _session_branch()
    assert payload["base_branch"] == before_branch
    assert payload["base_sha"] == before_sha
    assert isinstance(payload["created_at"], str) and str(payload["created_at"]).endswith("Z")
    assert payload["state"] == "active"
    assert payload[SESSION_WORKTREE_OUTCOME_KEY] == "created"


def test_base_immutability_records_original_branch_and_head_without_moving_parent_checkout(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    before_branch = _head_branch(repo_root)
    before_sha = _head_sha(repo_root)

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    payload = _read_json(_session_json_path(repo_root))
    assert payload["base_branch"] == before_branch
    assert payload["base_sha"] == before_sha
    assert _head_branch(repo_root) == before_branch
    assert _head_sha(repo_root) == before_sha


def test_worktree_list_and_safe_branch_trace_canonical_session_id(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    payload = _read_json(_session_json_path(repo_root))
    session_branch = str(payload["session_branch"])
    session_worktree_path = str(payload["session_worktree_path"])

    assert session_branch == _session_branch()
    assert session_branch.endswith(MST_SESSION_ID)
    assert re.fullmatch(r"[A-Za-z0-9._/-]+", session_branch)
    assert ".." not in session_branch
    assert session_worktree_path == str(_session_worktree_path(repo_root))
    assert Path(session_worktree_path).name == MST_SESSION_ID

    entries = _worktree_list(repo_root)
    matching = [entry for entry in entries if entry.get("worktree") == session_worktree_path]
    assert matching
    assert matching[0].get("branch") == f"refs/heads/{session_branch}"


def test_detached_head_is_classified_without_creating_or_retargeting_session_worktree(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    before_sha = _head_sha(repo_root)
    before_worktrees = _worktree_list(repo_root)
    _assert_git_ok(_run_git(repo_root, "checkout", "--detach"))

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    session_json = _session_json_path(repo_root)
    assert session_json.exists(), result.stderr

    payload = _read_json(session_json)
    assert payload["mst_session_id"] == MST_SESSION_ID
    assert payload["state"] == "blocked"
    assert payload[SESSION_WORKTREE_OUTCOME_KEY] == "blocked_detached_head"
    assert payload.get("base_branch") in (None, "")
    assert payload["base_sha"] == before_sha
    assert _head_sha(repo_root) == before_sha
    assert _worktree_list(repo_root) == before_worktrees
    assert not _session_worktree_path(repo_root).exists()


def test_existing_session_worktree_is_reused_with_structured_outcome(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    before_branch = _head_branch(repo_root)
    before_sha = _head_sha(repo_root)
    session_path = _create_manual_session_worktree(repo_root, base_branch=before_branch)

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    payload = _read_json(_session_json_path(repo_root))
    assert payload["session_worktree_path"] == str(session_path)
    assert payload["session_branch"] == _session_branch()
    assert payload["base_branch"] == before_branch
    assert payload["base_sha"] == before_sha
    assert payload["state"] == "active"
    assert payload[SESSION_WORKTREE_OUTCOME_KEY] == "reused_existing"
    assert _head_branch(repo_root) == before_branch
    assert _head_sha(repo_root) == before_sha


def test_resume_keeps_existing_branch_path_and_base_sha_without_silent_overwrite(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    initial_branch = _head_branch(repo_root)
    initial_sha = _head_sha(repo_root)
    session_path = _create_manual_session_worktree(repo_root, base_branch=initial_branch)
    session_json = _session_json_path(repo_root)
    _write_json(
        session_json,
        {
            "mst_session_id": MST_SESSION_ID,
            "session_worktree_path": str(session_path),
            "session_branch": _session_branch(),
            "base_branch": initial_branch,
            "base_sha": initial_sha,
            "created_at": "2026-05-15T00:00:00Z",
            "state": "active",
        },
    )

    (repo_root / "resume.txt").write_text("resume boundary\n", encoding="utf-8")
    _assert_git_ok(_run_git(repo_root, "add", "resume.txt"))
    _assert_git_ok(_run_git(repo_root, "commit", "-m", "resume boundary"))
    resumed_head_sha = _head_sha(repo_root)
    assert resumed_head_sha != initial_sha

    result = _run_session_start(repo_root, env={"MST_SESSION_ID": MST_SESSION_ID})

    assert result.returncode == 0, result.stderr
    payload = _read_json(session_json)
    assert payload["session_worktree_path"] == str(session_path)
    assert payload["session_branch"] == _session_branch()
    assert payload["base_branch"] == initial_branch
    assert payload["base_sha"] == initial_sha
    assert payload["created_at"] == "2026-05-15T00:00:00Z"
    assert payload["state"] == "active"
    assert payload[SESSION_WORKTREE_OUTCOME_KEY] == "resume_preserved"
    assert _head_branch(repo_root) == initial_branch
    assert _head_sha(repo_root) == resumed_head_sha


def test_legacy_identity_no_mutation_does_not_create_session_worktree_or_session_metadata(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    before_branch = _head_branch(repo_root)
    before_sha = _head_sha(repo_root)
    before_worktrees = _worktree_list(repo_root)

    result = _run_session_start(
        repo_root,
        payload=_hook_payload(mst_session_id=None),
        env={"MST_STATE_PPID": "424242"},
    )

    assert result.returncode == 0, result.stderr
    assert _head_branch(repo_root) == before_branch
    assert _head_sha(repo_root) == before_sha
    assert _worktree_list(repo_root) == before_worktrees
    assert not (repo_root / ".gran-maestro" / "sessions").exists()
    assert not (repo_root / ".gran-maestro" / "worktrees" / "sessions").exists()
