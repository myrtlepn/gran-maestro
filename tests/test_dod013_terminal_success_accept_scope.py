from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.session import (
    ensure_session_worktree_contract,
    perform_session_original_ff_only_merge,
    resolve_session_merge_scope,
)


MST_SESSION_ID = "MST-AGI-038-20260515T074500000Z-dod013a1"
FINAL_EVIDENCE = {
    "all_must_dod_eligible": True,
    "children_clean": True,
    "base_branch_lock_acquired": True,
    "destructive_command_policy_passed": True,
}


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


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "tester@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    _git(repo_root, "commit", "--allow-empty", "-m", "initial commit")
    _git(repo_root, "branch", "-M", "master")
    return repo_root


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _session_json_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "sessions" / MST_SESSION_ID / "session.json"


def _checkout_feature_branch_with_commit(repo_root: Path, branch: str = "feature/original-base") -> str:
    _git(repo_root, "checkout", "-b", branch)
    (repo_root / "feature-base.txt").write_text(f"{branch}\n", encoding="utf-8")
    _git(repo_root, "add", "feature-base.txt")
    _git(repo_root, "commit", "-m", "feature base commit")
    return branch


@pytest.fixture()
def repo_with_session(tmp_path: Path, monkeypatch) -> tuple[Path, dict[str, object]]:
    repo_root = _init_repo(tmp_path)
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    session_payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    assert session_payload["state"] == "active"
    return repo_root, session_payload


def _resolve(
    repo_root: Path,
    *,
    caller: str,
    requested_target: str | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    return resolve_session_merge_scope(
        repo_root,
        caller=caller,
        requested_target=requested_target,
        mst_session_id=MST_SESSION_ID,
        evidence=evidence,
    )


@pytest.mark.parametrize(
    "caller",
    [
        "assistant_turn_end",
        "stop_hook_continuation",
        "tool_exit",
        "subskill_return",
        "review_pass_only",
        "cancel",
        "recover_dry_run",
    ],
)
def test_forbidden_truth_table_callers_never_authorize_merge(repo_with_session: tuple[Path, dict[str, object]], caller: str) -> None:
    repo_root, session_payload = repo_with_session

    payload = _resolve(repo_root, caller=caller, requested_target="session_to_original", evidence=FINAL_EVIDENCE)

    assert payload["ok"] is False
    assert payload["merge_state"] == "forbidden_caller"
    assert payload["reason"] == "forbidden_caller"
    assert payload["forbidden_caller"] is True
    assert payload["child_to_session"] is False
    assert payload["session_to_original"] is False
    assert payload["target_branch"] is None
    assert payload["session_branch"] == session_payload["session_branch"]
    assert payload["original_base_branch"] == session_payload["base_branch"]
    assert payload["original_base_sha"] == session_payload["base_sha"]
    assert payload["action"] == "resume_parent_session_workflow"


@pytest.mark.parametrize("caller", ["request_child_accept", "auto_accept_result_child", "auto_accept_result_for_child"])
def test_child_scope_callers_authorize_only_child_to_session(repo_with_session: tuple[Path, dict[str, object]], caller: str) -> None:
    repo_root, session_payload = repo_with_session

    payload = _resolve(repo_root, caller=caller)

    assert payload["ok"] is True
    assert payload["merge_state"] == "authorized_child_merge"
    assert payload["child_to_session"] is True
    assert payload["session_to_original"] is False
    assert payload["target_branch"] == session_payload["session_branch"]
    assert payload["original_base_branch"] == session_payload["base_branch"]
    assert payload["original_base_sha"] == session_payload["base_sha"]
    assert payload["evidence"] == {"merge_target": "parent_session_branch"}


@pytest.mark.parametrize("caller", ["session_level_accept", "terminal_success"])
def test_final_success_callers_authorize_session_to_original_with_all_evidence(repo_with_session: tuple[Path, dict[str, object]], caller: str) -> None:
    repo_root, session_payload = repo_with_session

    payload = _resolve(
        repo_root,
        caller=caller,
        requested_target="session_to_original",
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is True
    assert payload["merge_state"] == "authorized_final_merge"
    assert payload["child_to_session"] is False
    assert payload["session_to_original"] is True
    assert payload["target_branch"] == session_payload["base_branch"]
    assert payload["session_branch"] == session_payload["session_branch"]
    assert payload["required_evidence"] == [
        "all_must_dod_eligible",
        "children_clean",
        "base_branch_lock_acquired",
        "destructive_command_policy_passed",
    ]
    assert payload["evidence"]["current_original_base_sha"] == session_payload["base_sha"]


def test_feature_branch_final_merge_targets_recorded_original_branch(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    feature_branch = _checkout_feature_branch_with_commit(repo_root)
    feature_sha = _git(repo_root, "rev-parse", "HEAD")
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    session_payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)

    payload = resolve_session_merge_scope(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        mst_session_id=MST_SESSION_ID,
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is True
    assert payload["target_branch"] == feature_branch
    assert payload["original_base_branch"] == feature_branch
    assert payload["original_base_sha"] == feature_sha
    assert session_payload["base_branch"] == feature_branch


def test_public_ff_only_helper_reflects_session_branch_after_revalidation(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    feature_branch = _checkout_feature_branch_with_commit(repo_root)
    feature_sha = _git(repo_root, "rev-parse", "HEAD")
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    session_payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    session_worktree = Path(str(session_payload["session_worktree_path"]))

    (session_worktree / "child-result.txt").write_text("child accepted in session\n", encoding="utf-8")
    _git(session_worktree, "add", "child-result.txt")
    _git(session_worktree, "commit", "-m", "child accepted in session")
    session_sha = _git(session_worktree, "rev-parse", "HEAD")

    assert session_payload["base_branch"] == feature_branch
    assert session_payload["base_sha"] == feature_sha
    assert _git(repo_root, "branch", "--show-current") == feature_branch
    assert _git(repo_root, "rev-parse", "HEAD") == feature_sha
    assert not (repo_root / "child-result.txt").exists()

    authorization = resolve_session_merge_scope(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        mst_session_id=MST_SESSION_ID,
        evidence=FINAL_EVIDENCE,
    )
    assert authorization["ok"] is True
    assert authorization["merge_state"] == "authorized_final_merge"
    assert authorization["evidence"]["session_branch_sha"] == session_sha

    payload = perform_session_original_ff_only_merge(
        repo_root,
        caller="terminal_success",
        mst_session_id=MST_SESSION_ID,
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is True
    assert payload["merge_state"] == "final_reflected_ff_only"
    assert payload["session_to_original"] is True
    assert payload["evidence"]["ff_only"] is True
    assert payload["evidence"]["merged_original_base_sha"] == session_sha
    assert _git(repo_root, "branch", "--show-current") == feature_branch
    assert _git(repo_root, "rev-parse", "HEAD") == session_sha
    assert (repo_root / "child-result.txt").read_text(encoding="utf-8") == "child accepted in session\n"


@pytest.mark.parametrize(
    ("missing_key", "reason"),
    [
        ("all_must_dod_eligible", "missing_all_must_dod_eligible"),
        ("children_clean", "missing_children_clean"),
        ("base_branch_lock_acquired", "missing_base_branch_lock_acquired"),
        ("destructive_command_policy_passed", "missing_destructive_command_policy_passed"),
    ],
)
def test_final_block_reasons_for_missing_required_evidence(
    repo_with_session: tuple[Path, dict[str, object]],
    missing_key: str,
    reason: str,
) -> None:
    repo_root, session_payload = repo_with_session
    evidence = dict(FINAL_EVIDENCE)
    evidence[missing_key] = False

    payload = _resolve(repo_root, caller="terminal_success", requested_target="session_to_original", evidence=evidence)

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["reason"] == reason
    assert payload["action"] == "collect_required_final_merge_evidence"
    assert payload["child_to_session"] is False
    assert payload["session_to_original"] is False
    assert payload["target_branch"] is None
    assert payload["session_branch"] == session_payload["session_branch"]
    assert payload["evidence"]["missing_evidence"] == missing_key


def test_final_block_reason_for_explicit_conflict_signal(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, _session_payload = repo_with_session

    payload = _resolve(
        repo_root,
        caller="session_level_accept",
        requested_target="session_to_original",
        evidence={**FINAL_EVIDENCE, "conflict_detected": True},
    )

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["reason"] == "final_merge_conflict"
    assert payload["action"] == "resolve_conflict_before_final_merge"
    assert payload["session_to_original"] is False


def test_final_block_reason_for_dirty_original_checkout(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, _session_payload = repo_with_session
    (repo_root / "dirty-original.txt").write_text("dirty original checkout\n", encoding="utf-8")

    payload = _resolve(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["session_to_original"] is False
    assert "dirty" in str(payload.get("reason", ""))


def test_final_block_reason_for_original_base_drift(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, session_payload = repo_with_session
    (repo_root / "drift.txt").write_text("base drift\n", encoding="utf-8")
    _git(repo_root, "add", "drift.txt")
    _git(repo_root, "commit", "-m", "base drift")

    payload = _resolve(repo_root, caller="terminal_success", requested_target="session_to_original", evidence=FINAL_EVIDENCE)

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["reason"] == "original_base_drift_detected"
    assert payload["session_to_original"] is False
    assert payload["evidence"]["expected_original_base_sha"] == session_payload["base_sha"]
    assert payload["evidence"]["current_original_base_sha"] != session_payload["base_sha"]


def test_final_block_reason_for_dirty_session_branch(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, session_payload = repo_with_session
    session_worktree = Path(str(session_payload["session_worktree_path"]))
    (session_worktree / "dirty.txt").write_text("dirty session\n", encoding="utf-8")

    payload = _resolve(repo_root, caller="session_level_accept", requested_target="session_to_original", evidence=FINAL_EVIDENCE)

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["reason"] == "dirty_session_branch"
    assert payload["action"] == "clean_session_branch_before_final_merge"
    assert payload["session_to_original"] is False
    assert "dirty.txt" in json.dumps(payload["evidence"], sort_keys=True)


def test_final_block_reason_for_non_fast_forward_original_reflection(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)

    (repo_root / "base-second.txt").write_text("base second commit\n", encoding="utf-8")
    _git(repo_root, "add", "base-second.txt")
    _git(repo_root, "commit", "-m", "base second commit")
    session_payload = ensure_session_worktree_contract(repo_root, MST_SESSION_ID)
    session_worktree = Path(str(session_payload["session_worktree_path"]))

    _git(session_worktree, "reset", "--hard", "HEAD~1")
    (session_worktree / "session-sibling.txt").write_text("session sibling\n", encoding="utf-8")
    _git(session_worktree, "add", "session-sibling.txt")
    _git(session_worktree, "commit", "-m", "session sibling commit")

    payload = resolve_session_merge_scope(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        mst_session_id=MST_SESSION_ID,
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is False
    assert payload["merge_state"] == "blocked_final_merge"
    assert payload["session_to_original"] is False
    assert "ff" in str(payload.get("reason", "")).lower() or "fast" in str(payload.get("reason", "")).lower()


def test_final_block_reason_for_wrong_original_checkout_identity(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, _session_payload = repo_with_session
    session_json = _session_json_path(repo_root)
    session_data = _read_json(session_json)
    session_data["parent_project_root"] = str(repo_root.parent / "other-original-checkout")
    _write_json(session_json, session_data)

    payload = _resolve(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is False
    assert payload["session_to_original"] is False
    assert "original" in str(payload.get("reason", "")).lower() or "identity" in str(payload.get("reason", "")).lower()


def test_final_block_reason_for_stale_session_branch_checkout(repo_with_session: tuple[Path, dict[str, object]]) -> None:
    repo_root, session_payload = repo_with_session
    session_worktree = Path(str(session_payload["session_worktree_path"]))
    _git(session_worktree, "checkout", "-b", "gran-maestro/stale-session-branch")

    payload = _resolve(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is False
    assert payload["session_to_original"] is False
    assert "session_branch" in str(payload.get("reason", "")).lower() or "stale" in str(payload.get("reason", "")).lower()


def test_legacy_identity_diagnostics_do_not_authorize_final_merge(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.delenv("MST_SESSION_ID", raising=False)
    monkeypatch.setenv("MST_CONTEXT_JSON", json.dumps({"session_id": MST_SESSION_ID, "owner_session_id": MST_SESSION_ID}))

    payload = resolve_session_merge_scope(
        repo_root,
        caller="terminal_success",
        requested_target="session_to_original",
        evidence=FINAL_EVIDENCE,
    )

    assert payload["ok"] is False
    assert payload["merge_state"] == "non_success_diagnostic"
    assert payload["reason"] == "legacy_identity_not_canonical_source"
    assert payload["child_to_session"] is False
    assert payload["session_to_original"] is False
    assert payload["legacy_diagnostics"] == {"hook_session_id": MST_SESSION_ID}
