from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.session import ensure_session_worktree_contract
from scripts.mst_cmds.worktree import (
    cmd_worktree_create,
    cmd_worktree_resolve_base,
    role_branch_name,
    role_worktree_path,
    task_branch_name,
)


ROOT = Path(__file__).resolve().parent.parent
MST_SESSION_ID = "MST-AGI-038-20260515T010203004Z-abc12345"
REQ_ID = "REQ-869"
TASK_ID = "T01"


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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_repo_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".gran-maestro" / "worktrees").mkdir(parents=True, exist_ok=True)

    _assert_git_ok(_run_git(repo_root, "init"))
    _assert_git_ok(_run_git(repo_root, "config", "user.email", "tester@example.com"))
    _assert_git_ok(_run_git(repo_root, "config", "user.name", "Test User"))
    _assert_git_ok(_run_git(repo_root, "commit", "--allow-empty", "-m", "initial commit"))
    _assert_git_ok(_run_git(repo_root, "branch", "-M", "master"))
    return repo_root


def _head_sha(repo_root: Path) -> str:
    return _assert_git_ok(_run_git(repo_root, "rev-parse", "HEAD"))


def _request_json_path(repo_root: Path, req_id: str = REQ_ID) -> Path:
    return repo_root / ".gran-maestro" / "requests" / req_id / "request.json"


def _seed_request(repo_root: Path, *, req_id: str = REQ_ID, detected_base: str | None = None) -> Path:
    payload: dict[str, object] = {
        "id": req_id,
        "request_id": req_id,
        "title": "DOD-004 regression fixture",
        "tasks": [{"id": TASK_ID, "status": "pending"}],
    }
    if detected_base is not None:
        payload["detected_base"] = detected_base
    request_path = _request_json_path(repo_root, req_id)
    _write_json(request_path, payload)
    return request_path


def _worktree_meta_path(repo_root: Path, worktree_path: Path) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / f"{worktree_path.name}.meta.json"


def _seed_active_session(repo_root: Path) -> dict[str, object]:
    payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    assert payload["state"] == "active"
    return payload


def _set_repo_context(repo_root: Path, monkeypatch, *, cwd: Path | None = None) -> None:
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.chdir(cwd or repo_root)


def test_resolve_base_prefers_session_branch_and_persists_request_detected_base(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    request_path = _seed_request(repo_root)

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code = cmd_worktree_resolve_base(argparse.Namespace(req=REQ_ID, json=True))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert payload["base"] == session_payload["session_branch"]
    assert payload["base_slug"] == str(session_payload["session_branch"]).replace("/", "-")
    assert _read_json(request_path)["detected_base"] == session_payload["session_branch"]


def test_integration_child_metadata_records_parent_session_fields(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    session_branch = str(session_payload["session_branch"])
    integration_branch = role_branch_name(REQ_ID, "integration", session_branch)
    integration_path = tmp_path / "req-869-integration"

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(integration_path),
            branch=integration_branch,
            base=session_branch,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(integration_path)

    meta = _read_json(_worktree_meta_path(repo_root, integration_path))
    assert meta["parent_mst_session_id"] == MST_SESSION_ID
    assert meta["parent_session_branch"] == session_branch
    assert meta["base_branch"] == session_branch
    assert meta["base_sha"] == _head_sha(repo_root)


def test_task_child_base_uses_session_derived_integration_branch(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    session_branch = str(session_payload["session_branch"])
    integration_branch = role_branch_name(REQ_ID, "integration", session_branch)
    integration_path = tmp_path / "req-869-integration-seeded"

    add_integration = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        integration_branch,
        str(integration_path),
        session_branch,
    )
    assert add_integration.returncode == 0, add_integration.stderr

    _write_text(integration_path / "integration.txt", "session-derived integration commit\n")
    _assert_git_ok(_run_git(integration_path, "add", "integration.txt"))
    _assert_git_ok(_run_git(integration_path, "commit", "-m", "integration commit"))
    integration_sha = _head_sha(integration_path)
    assert integration_sha != _head_sha(repo_root)

    task_branch = task_branch_name(REQ_ID, TASK_ID, session_branch)
    task_path = tmp_path / "req-869-task-t01"

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(task_path),
            branch=task_branch,
            base=integration_branch,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert _head_sha(task_path) == integration_sha

    meta = _read_json(_worktree_meta_path(repo_root, task_path))
    assert meta["parent_mst_session_id"] == MST_SESSION_ID
    assert meta["parent_session_branch"] == session_branch
    assert meta["base_branch"] == integration_branch
    assert meta["base_sha"] == integration_sha


@pytest.mark.parametrize(
    ("case_name", "env_updates", "seed_blocked_session"),
    [
        ("missing", {}, False),
        ("invalid", {"MST_SESSION_ID": "invalid-session-id"}, False),
        ("legacy-only", {"MST_CONTEXT_JSON": json.dumps({"session_id": "legacy-only"})}, False),
        ("blocked", {"MST_SESSION_ID": MST_SESSION_ID}, True),
    ],
)
def test_blocked_or_legacy_no_fallback_returns_structured_non_success(
    tmp_path: Path,
    monkeypatch,
    capsys,
    case_name: str,
    env_updates: dict[str, str],
    seed_blocked_session: bool,
) -> None:
    repo_root = _init_repo(tmp_path)
    request_path = _seed_request(repo_root, detected_base="keep-me")

    if seed_blocked_session:
        blocked_payload = _seed_active_session(repo_root)
        blocked_payload["state"] = "blocked"
        blocked_payload["outcome"] = "blocked_missing_worktree"
        blocked_payload["reason"] = "session_worktree_missing"
        blocked_payload["action"] = "repair_or_remove_stale_session_metadata"
        _write_json(
            repo_root / ".gran-maestro" / "sessions" / MST_SESSION_ID / "session.json",
            blocked_payload,
        )

    _set_repo_context(repo_root, monkeypatch)
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env_updates.items():
        monkeypatch.setenv(key, value)

    exit_code = cmd_worktree_resolve_base(argparse.Namespace(req=REQ_ID, json=True))
    captured = capsys.readouterr()

    assert exit_code != 0, case_name

    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert isinstance(payload.get("reason"), str) and payload["reason"]
    assert isinstance(payload.get("action"), str) and payload["action"]
    assert payload.get("base") in (None, "")
    assert _read_json(request_path)["detected_base"] == "keep-me"


def test_approve_preflight_contract_documents_session_parent_resolve_base() -> None:
    approve_skill = _read_repo_text("skills/approve/SKILL.md")

    assert "worktree resolve-base --req {REQ-ID} --json" in approve_skill
    assert "MST_SESSION_ID" in approve_skill
    assert "session_branch" in approve_skill
    assert "parent_mst_session_id" in approve_skill
    assert "original_base_branch" in approve_skill
    assert "current `git HEAD` branch" not in approve_skill


def test_approve_child_worktree_commands_use_session_derived_bases() -> None:
    approve_skill = _read_repo_text("skills/approve/SKILL.md")

    assert "SESSION_BASE_BRANCH" in approve_skill
    assert "REQ_BRANCH" in approve_skill
    assert "--base \"$SESSION_BASE_BRANCH\"" in approve_skill
    assert "--base \"$REQ_BRANCH\"" in approve_skill
    assert "request.json.detected_base" in approve_skill
    assert "original base" in approve_skill


def test_effective_root_boundary_documents_session_worktree_handoff() -> None:
    request_skill = _read_repo_text("skills/request/SKILL.md")
    approve_skill = _read_repo_text("skills/approve/SKILL.md")

    combined = f"{request_skill}\n{approve_skill}"
    assert "session worktree" in combined
    assert "effective project root" in combined
    assert "original checkout" in combined
    assert "structured" in combined
    assert "MST_SESSION_ID" in combined


def test_accept_scope_keeps_child_merge_scoped_to_session_not_original_base() -> None:
    approve_skill = _read_repo_text("skills/approve/SKILL.md")
    accept_skill = _read_repo_text("skills/accept/SKILL.md")
    worktree_block = accept_skill[accept_skill.index("3. **Worktree") : accept_skill.index("[커밋 양식 감지]")]

    assert "DOD-005/DOD-013" in approve_skill
    assert "final original" in approve_skill
    assert "request.json.detected_base" in accept_skill
    assert "merge --squash" in accept_skill
    assert "session branch" in worktree_block
    assert "child/request accept가 original base branch로 직접 merge하지 않는다" in worktree_block
    assert "final session→original merge는 여기서 수행하지" in worktree_block


def test_nested_guard_allows_session_owned_child_and_blocks_general_nested_target(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    session_branch = str(session_payload["session_branch"])
    session_path = Path(str(session_payload["session_worktree_path"]))

    existing_worktree = tmp_path / "linked-worktree-A"
    add_existing = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        "feature/existing-worktree",
        str(existing_worktree),
        "master",
    )
    assert add_existing.returncode == 0, add_existing.stderr

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    nested_target = existing_worktree / "nested-blocked"
    blocked_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(nested_target),
            branch="feature/nested-blocked",
            base="master",
        )
    )
    blocked = capsys.readouterr()

    assert blocked_code != 0
    assert "nested worktree path detected" in blocked.err

    session_child_target = role_worktree_path(session_path, REQ_ID, "integration")
    session_child_target.parent.mkdir(parents=True, exist_ok=True)
    session_child_branch = role_branch_name(REQ_ID, "integration", session_branch)

    allowed_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(session_child_target),
            branch=session_child_branch,
            base=session_branch,
        )
    )
    allowed = capsys.readouterr()

    assert allowed_code == 0, allowed.err
    assert allowed.err == ""
    assert allowed.out.strip() == str(session_child_target)
