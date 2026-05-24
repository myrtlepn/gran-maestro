from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.session import cmd_session_merge_scope, ensure_session_worktree_contract
from scripts.mst_cmds.worktree import cmd_worktree_resolve_base, role_branch_name


ROOT = Path(__file__).resolve().parents[1]
OBJECTIVE_DETAIL_RELATIVE = (
    Path(".gran-maestro")
    / "agile"
    / "AGI-038"
    / "objective"
    / "details"
    / "merge-contract-and-state-machine.md"
)


def _resolve_repo_path(relative_path: Path) -> Path:
    for base in (ROOT, *ROOT.parents):
        candidate = base / relative_path
        if candidate.exists():
            return candidate
    return ROOT / relative_path


OBJECTIVE_DETAIL = _resolve_repo_path(OBJECTIVE_DETAIL_RELATIVE)
MST_SESSION_ID = "MST-AGI-038-20260515T010203004Z-abc12345"
REQ_ID = "REQ-870"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo_root: Path, *args: str) -> str:
    result = _run_git(repo_root, *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


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

    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "tester@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    _git(repo_root, "commit", "--allow-empty", "-m", "initial commit")
    _git(repo_root, "branch", "-M", "master")
    return repo_root


def _request_json_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "requests" / REQ_ID / "request.json"


def _seed_request(
    repo_root: Path,
    *,
    detected_base: str | None = None,
    original_base_branch: str | None = None,
    original_base_sha: str | None = None,
    parent_mst_session_id: str | None = None,
) -> Path:
    payload: dict[str, object] = {
        "id": REQ_ID,
        "request_id": REQ_ID,
        "title": "DOD-005 merge scope contract",
        "tasks": [{"id": "T01", "status": "pending"}],
    }
    if detected_base is not None:
        payload["detected_base"] = detected_base
    if original_base_branch is not None:
        payload["original_base_branch"] = original_base_branch
    if original_base_sha is not None:
        payload["original_base_sha"] = original_base_sha
    if parent_mst_session_id is not None:
        payload["parent_mst_session_id"] = parent_mst_session_id
    request_path = _request_json_path(repo_root)
    _write_json(request_path, payload)
    return request_path


def _seed_active_session(repo_root: Path) -> dict[str, object]:
    payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    assert payload["state"] == "active"
    return payload


def _set_repo_context(repo_root: Path, monkeypatch, *, cwd: Path | None = None) -> None:
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.chdir(cwd or repo_root)


def _checkout_feature_branch_with_commit(repo_root: Path, branch: str = "feature/original-base") -> str:
    _git(repo_root, "checkout", "-b", branch)
    (repo_root / "feature-base.txt").write_text(f"{branch}\n", encoding="utf-8")
    _git(repo_root, "add", "feature-base.txt")
    _git(repo_root, "commit", "-m", "feature base commit")
    return branch


def _create_child_branch(
    tmp_path: Path,
    repo_root: Path,
    *,
    session_branch: str,
) -> str:
    child_branch = role_branch_name(REQ_ID, "integration", session_branch)
    child_path = tmp_path / "req-870-integration"
    result = _run_git(repo_root, "worktree", "add", "-b", child_branch, str(child_path), session_branch)
    assert result.returncode == 0, result.stderr or result.stdout
    (child_path / "child-change.txt").write_text("child change for session merge\n", encoding="utf-8")
    _git(child_path, "add", "child-change.txt")
    _git(child_path, "commit", "-m", "child integration commit")
    return child_branch


def _merge_child_into_session(session_worktree: Path, child_branch: str) -> tuple[str, str]:
    before_sha = _git(session_worktree, "rev-parse", "HEAD")
    _git(session_worktree, "merge", "--no-ff", child_branch, "-m", "merge child into session")
    after_sha = _git(session_worktree, "rev-parse", "HEAD")
    return before_sha, after_sha


def _run_merge_scope(
    repo_root: Path,
    capsys,
    *,
    caller: str,
    requested_target: str = "auto",
    evidence: dict[str, object] | None = None,
    mst_session_id: str | None = None,
) -> tuple[int, dict[str, object]]:
    exit_code = cmd_session_merge_scope(
        argparse.Namespace(
            caller=caller,
            requested_target=requested_target,
            mst_session_id=mst_session_id,
            project_root=str(repo_root),
            evidence_json=json.dumps(evidence) if evidence is not None else None,
            json=True,
        )
    )
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


def test_child_accept_merges_to_session_only(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    original_base_branch = str(session_payload["base_branch"])
    original_base_sha = _git(repo_root, "rev-parse", original_base_branch)
    request_path = _seed_request(repo_root)

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code = cmd_worktree_resolve_base(argparse.Namespace(req=REQ_ID, json=True))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    resolve_payload = json.loads(captured.out)
    assert resolve_payload["base"] == session_payload["session_branch"]
    assert resolve_payload["parent_session_branch"] == session_payload["session_branch"]
    assert resolve_payload["original_base_branch"] == original_base_branch
    assert resolve_payload["original_base_sha"] == original_base_sha
    assert resolve_payload["merge_scope"]["child_to_session"] is True
    assert resolve_payload["merge_scope"]["session_to_original"] is False
    assert resolve_payload["merge_scope"]["target_branch"] == session_payload["session_branch"]

    child_branch = _create_child_branch(
        tmp_path,
        repo_root,
        session_branch=str(session_payload["session_branch"]),
    )
    session_before, session_after = _merge_child_into_session(
        Path(str(session_payload["session_worktree_path"])),
        child_branch,
    )

    assert session_after != session_before
    assert _git(repo_root, "rev-parse", original_base_branch) == original_base_sha

    request_data = _read_json(request_path)
    assert request_data["detected_base"] == session_payload["session_branch"]
    assert request_data["original_base_branch"] == original_base_branch
    assert request_data["original_base_sha"] == original_base_sha


def test_feature_branch_session_contract_preserves_original_base_and_child_request_context(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    feature_branch = _checkout_feature_branch_with_commit(repo_root)
    feature_sha = _git(repo_root, "rev-parse", "HEAD")
    master_sha = _git(repo_root, "rev-parse", "master")
    request_path = _seed_request(repo_root)
    session_payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)

    assert session_payload["state"] == "active"
    assert session_payload["base_branch"] == feature_branch
    assert session_payload["base_sha"] == feature_sha
    assert session_payload["base_sha"] != master_sha

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code = cmd_worktree_resolve_base(argparse.Namespace(req=REQ_ID, json=True))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["base"] == session_payload["session_branch"]
    assert payload["original_base_branch"] == feature_branch
    assert payload["original_base_sha"] == feature_sha
    request_data = _read_json(request_path)
    assert request_data["detected_base"] == session_payload["session_branch"]
    assert request_data["original_base_branch"] == feature_branch
    assert request_data["original_base_sha"] == feature_sha


@pytest.mark.parametrize(
    "temp_branch",
    [
        "gran-maestro/session/MST-AGI-038-20260515T010203004Z-abc12345",
        "gran-maestro/feature-x/REQ-870",
    ],
)
def test_session_worktree_contract_rejects_mst_temp_original_base(tmp_path: Path, temp_branch: str) -> None:
    repo_root = _init_repo(tmp_path)
    _git(repo_root, "checkout", "-b", temp_branch)

    payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)

    assert payload["state"] == "blocked"
    assert payload["outcome"] != "created"
    assert payload["outcome"] != "reused_existing"
    assert payload["outcome"] != "resume_preserved"
    assert not Path(str(payload["session_worktree_path"])).exists()


def test_session_worktree_contract_returns_structured_block_for_unborn_original_base(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo-unborn"
    repo_root.mkdir()
    (repo_root / ".gran-maestro" / "worktrees").mkdir(parents=True, exist_ok=True)

    assert _run_git(repo_root, "init").returncode == 0
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0

    try:
        payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    except Exception as exc:  # pragma: no cover - explicit regression guard
        pytest.fail(f"expected structured blocked payload for unborn original base, got exception: {exc}")

    assert payload["state"] == "blocked"
    assert payload["outcome"].startswith("blocked_")
    assert payload.get("base_branch") in (None, "")
    assert not Path(str(payload["session_worktree_path"])).exists()


def test_merge_scope_truth_table_runtime(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code, child_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="request_child_accept",
    )
    assert exit_code == 0
    assert child_payload["child_to_session"] is True
    assert child_payload["session_to_original"] is False
    assert child_payload["target_branch"] == session_payload["session_branch"]

    exit_code, final_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="session_level_accept",
        requested_target="session_to_original",
        evidence={
            "all_must_dod_eligible": True,
            "children_clean": True,
            "base_branch_lock_acquired": True,
            "destructive_command_policy_passed": True,
        },
    )
    assert exit_code == 0
    assert final_payload["child_to_session"] is False
    assert final_payload["session_to_original"] is True
    assert final_payload["target_branch"] == session_payload["base_branch"]

    exit_code, forbidden_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="assistant_turn_end",
    )
    assert exit_code != 0
    assert forbidden_payload["ok"] is False
    assert forbidden_payload["reason"] == "forbidden_caller"
    assert forbidden_payload["session_to_original"] is False


def test_merge_scope_truth_table() -> None:
    detail = OBJECTIVE_DETAIL.read_text(encoding="utf-8")
    accept_skill = _read_repo_text("skills/accept/SKILL.md")

    for token in (
        "accept scope truth table",
        "request child accept",
        "session-level manual accept",
        "terminal_success transition",
        "Stop hook continuation",
    ):
        assert token in detail

    for token in (
        "child_to_session",
        "session_to_original",
        "forbidden_caller",
        "assistant_turn_end",
        "stop_hook_continuation",
        "subskill_return",
        "request_child_accept",
        "session_level_accept",
        "terminal_success",
    ):
        assert token in accept_skill


@pytest.mark.parametrize(
    "caller",
    [
        "stop_hook_continuation",
        "subskill_return",
        "review_pass_only",
    ],
)
def test_forbidden_callers_do_not_change_original_base(
    tmp_path: Path,
    monkeypatch,
    capsys,
    caller: str,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    original_base_branch = str(session_payload["base_branch"])
    original_base_sha = _git(repo_root, "rev-parse", original_base_branch)
    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    child_branch = _create_child_branch(
        tmp_path,
        repo_root,
        session_branch=str(session_payload["session_branch"]),
    )
    session_before, session_after = _merge_child_into_session(
        Path(str(session_payload["session_worktree_path"])),
        child_branch,
    )

    assert session_after != session_before, caller
    exit_code, payload = _run_merge_scope(repo_root, capsys, caller=caller)
    assert exit_code != 0, caller
    assert payload["ok"] is False, caller
    assert payload["merge_state"] == "forbidden_caller", caller
    assert payload["session_to_original"] is False, caller
    assert _git(repo_root, "rev-parse", original_base_branch) == original_base_sha, caller
    assert _git(repo_root, "log", "-1", "--pretty=%s", original_base_branch) == "initial commit", caller
    assert "final original merge" not in _git(repo_root, "log", "--pretty=%s", original_base_branch), caller


def test_final_merge_requires_base_drift_and_lock_evidence(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = _init_repo(tmp_path)
    session_payload = _seed_active_session(repo_root)
    session_worktree = Path(str(session_payload["session_worktree_path"]))

    _set_repo_context(repo_root, monkeypatch)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    exit_code, missing_lock = _run_merge_scope(
        repo_root,
        capsys,
        caller="session_level_accept",
        requested_target="session_to_original",
        evidence={
            "all_must_dod_eligible": True,
            "children_clean": True,
            "destructive_command_policy_passed": True,
        },
    )
    assert exit_code != 0
    assert missing_lock["merge_state"] == "blocked_final_merge"
    assert missing_lock["reason"] == "missing_base_branch_lock_acquired"
    assert missing_lock["session_to_original"] is False

    (repo_root / "drift.txt").write_text("base drift\n", encoding="utf-8")
    _git(repo_root, "add", "drift.txt")
    _git(repo_root, "commit", "-m", "base drift commit")

    exit_code, drift_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="terminal_success",
        requested_target="session_to_original",
        evidence={
            "all_must_dod_eligible": True,
            "children_clean": True,
            "base_branch_lock_acquired": True,
            "destructive_command_policy_passed": True,
        },
    )
    assert exit_code != 0
    assert drift_payload["merge_state"] == "blocked_final_merge"
    assert drift_payload["reason"] == "original_base_drift_detected"
    assert drift_payload["evidence"]["expected_original_base_sha"] == session_payload["base_sha"]

    (session_worktree / "dirty.txt").write_text("dirty session\n", encoding="utf-8")
    exit_code, dirty_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="session_level_accept",
        requested_target="session_to_original",
        evidence={
            "all_must_dod_eligible": True,
            "children_clean": True,
            "base_branch_lock_acquired": True,
            "destructive_command_policy_passed": True,
        },
    )
    assert exit_code != 0
    assert dirty_payload["merge_state"] == "blocked_final_merge"
    assert dirty_payload["reason"] == "dirty_session_branch"


@pytest.mark.parametrize(
    ("case_name", "env_updates", "seed_blocked_session"),
    [
        ("missing", {}, False),
        ("invalid", {"MST_SESSION_ID": "invalid-session-id"}, False),
        ("legacy-only", {"MST_CONTEXT_JSON": json.dumps({"session_id": "legacy-only"})}, False),
        ("blocked", {"MST_SESSION_ID": MST_SESSION_ID}, True),
    ],
)
def test_legacy_or_blocked_session_cannot_authorize_merge(
    tmp_path: Path,
    monkeypatch,
    capsys,
    case_name: str,
    env_updates: dict[str, str],
    seed_blocked_session: bool,
) -> None:
    repo_root = _init_repo(tmp_path)
    original_base_sha = _git(repo_root, "rev-parse", "master")
    request_path = _seed_request(
        repo_root,
        detected_base="keep-me",
        original_base_branch="master",
        original_base_sha=original_base_sha,
        parent_mst_session_id="keep-parent",
    )

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

    merge_exit_code, merge_payload = _run_merge_scope(
        repo_root,
        capsys,
        caller="session_level_accept",
        requested_target="session_to_original",
    )
    assert merge_exit_code != 0, case_name
    assert merge_payload["ok"] is False, case_name
    assert merge_payload["session_to_original"] is False, case_name

    request_data = _read_json(request_path)
    assert request_data["detected_base"] == "keep-me"
    assert request_data["original_base_branch"] == "master"
    assert request_data["original_base_sha"] == original_base_sha
    assert request_data["parent_mst_session_id"] == "keep-parent"


def test_accept_skill_documents_scope_split() -> None:
    detail = OBJECTIVE_DETAIL.read_text(encoding="utf-8")
    accept_skill = _read_repo_text("skills/accept/SKILL.md")

    assert "accept scope는 child와 session으로 분리한다" in detail
    assert "terminal success는 상태머신 전이로만 인정한다" in detail

    for token in (
        "child_to_session",
        "session_to_original",
        "original_base_branch",
        "original_base_sha",
        "Stop hook continuation",
        "subskill return",
        "DOD-013",
        "DOD-014",
    ):
        assert token in accept_skill


def test_accept_skill_separates_detected_base_from_original_base() -> None:
    accept_skill = _read_repo_text("skills/accept/SKILL.md")
    approve_skill = _read_repo_text("skills/approve/SKILL.md")
    request_skill = _read_repo_text("skills/request/SKILL.md")

    for token in (
        "request.json.detected_base",
        "original_base_branch",
        "original_base_sha",
        "final original merge evidence",
        "child/request accept가 original base branch로 직접 merge하지 않는다",
    ):
        assert token in accept_skill

    assert "`detected_base` 필드는 `session_branch`와 같은 값으로 저장되어야 한다" in approve_skill
    assert "original base branch는 `original_base_branch`/`original_base_sha` reference로만 보존" in approve_skill
    assert "`request` 단계는 merge authority를 부여하지 않는다" in request_skill


def test_accept_skill_lists_forbidden_original_merge_callers() -> None:
    accept_skill = _read_repo_text("skills/accept/SKILL.md")

    for token in (
        "assistant_turn_end",
        "stop_hook_continuation",
        "tool_exit",
        "subskill_return",
        "review_pass_only",
        "Stop hook continuation",
        "subskill return",
        "continuation 안내",
        "diagnostic 반환",
        "parent workflow control return",
        "session→original merge를 실행하지 않는다",
    ):
        assert token in accept_skill


def test_accept_skill_keeps_dod013_dod014_boundary() -> None:
    accept_skill = _read_repo_text("skills/accept/SKILL.md")

    assert "DOD-005는 DOD-013 full truth table과 DOD-014 multi-child ordering/idempotency를 범위 밖으로 유지한다." in accept_skill
    assert "이 단계에서는 final original merge authorization을 확장하지 않는다." in accept_skill
