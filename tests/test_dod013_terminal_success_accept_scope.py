from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.session import ensure_session_worktree_contract, resolve_session_merge_scope


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
