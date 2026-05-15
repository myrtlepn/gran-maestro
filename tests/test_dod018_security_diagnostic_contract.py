from __future__ import annotations

from scripts.mst_cmds import session


MST_SESSION_ID = "MST-AGI-038-20260515T090045000Z-dod018sec"
SESSION_BRANCH = "gran-maestro/session/MST-AGI-038-20260515T090045000Z-dod018sec"
SESSION_ROOT = "/tmp/gran-maestro-session-dod018sec"
BASE_BRANCH = "master"
BASE_SHA = "3333333333333333333333333333333333333333"


def _require_session_api(name: str):
    value = getattr(session, name, None)
    assert callable(value), f"session.{name} contract helper is missing"
    return value


def _resolve(**overrides: object) -> dict[str, object]:
    resolver = _require_session_api("resolve_security_diagnostic_contract_state")
    payload: dict[str, object] = {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
    }
    payload.update(overrides)
    return resolver(payload)


def test_required_security_contract_policy_api_exists() -> None:
    _require_session_api("resolve_security_diagnostic_contract_state")


def test_unsafe_session_values_are_blocked_without_canonical_fallback() -> None:
    unsafe_values = [
        "../MST-AGI-038-20260515T090045000Z-dod018sec",
        "MST-AGI-038-20260515T090045000Z-dod018sec;rm -rf /",
        "MST-AGI-038-20260515T090045000Z-dod018sec/child",
        "MST-AGI-038-20260515T090045000Z-déjàvu18",
        "MST-AGI-038-20260515T090045000Z-" + "a" * 180,
        "MST-AGI-038-20260515T090045000Z-%2e%2e",
        "<script>alert(1)</script>",
    ]

    for value in unsafe_values:
        payload = _resolve(mst_session_id=value)

        assert payload["ok"] is False, value
        assert payload["classification"] == "security_boundary_blocked", value
        assert payload["canonical_identity_source"] == "blocked", value
        assert payload["destructive_action_allowed"] is False, value
        assert any(
            diagnostic["code"] == "invalid_session_id" and diagnostic["boundary"] == "session_id"
            for diagnostic in payload["diagnostics"]
        ), value
        assert payload["boundary_payload"] == {}, value


def test_legacy_identity_fields_are_diagnostic_only_not_canonical_sources() -> None:
    payload = _resolve(
        mst_session_id="",
        owner_session_id=MST_SESSION_ID,
        session_id=MST_SESSION_ID,
        sessionId=MST_SESSION_ID,
        owner_pid=4242,
    )

    assert payload["ok"] is False
    assert payload["classification"] == "security_boundary_blocked"
    assert payload["canonical_identity_source"] == "blocked"
    assert payload["legacy_diagnostics"] == {
        "owner_session_id": MST_SESSION_ID,
        "owner_pid": 4242,
        "session_id": MST_SESSION_ID,
        "sessionId": MST_SESSION_ID,
    }
    assert payload["boundary_payload"] == {}
    assert payload["destructive_action_allowed"] is False


def test_boundary_contract_blocks_branch_path_shell_api_and_ui_crossing() -> None:
    payload = _resolve(
        session_branch="gran-maestro/session/../../master",
        session_worktree_path="/tmp/gran-maestro-session-dod018sec/../escape",
        shell_args=["git", "branch", "-D", "main;rm -rf /"],
        api_params={"mst_session_id": "../escape", "label": "<img src=x onerror=alert(1)>"},
        ui_payload={"label": "<script>alert(1)</script>", "href": "javascript:alert(1)"},
    )

    assert payload["ok"] is False
    assert payload["classification"] == "security_boundary_blocked"
    assert payload["destructive_action_allowed"] is False
    blocked = {(diagnostic["boundary"], diagnostic["code"]) for diagnostic in payload["diagnostics"]}
    assert ("branch", "unsafe_branch") in blocked
    assert ("path", "unsafe_path") in blocked
    assert ("shell", "unsafe_shell_arg") in blocked
    assert ("api", "unsafe_api_param") in blocked
    assert ("ui", "unsafe_ui_value") in blocked
    assert payload["boundary_payload"] == {}


def test_destructive_git_commands_are_blocked_without_dry_run_evidence() -> None:
    commands = [
        {"command": ["git", "branch", "-D", SESSION_BRANCH], "target": SESSION_BRANCH},
        {"command": ["git", "worktree", "remove", "--force", SESSION_ROOT], "target": SESSION_ROOT},
        {"command": ["git", "reset", "--hard"], "target": BASE_BRANCH},
        {"command": ["git", "clean", "-fdx"], "target": SESSION_ROOT},
    ]

    for command in commands:
        payload = _resolve(destructive_commands=[command])

        assert payload["ok"] is False
        assert payload["classification"] == "blocked_destructive"
        assert payload["destructive_action_allowed"] is False
        assert payload["destructive_diagnostics"] == [
            {
                "code": "blocked_destructive",
                "command": command["command"],
                "target": command["target"],
                "reason": "dry_run_evidence_required",
                "safer_action": "run_dry_run_and_revalidate_contract",
                "dry_run_required": True,
            }
        ]


def test_safe_canonical_input_produces_deterministic_boundary_payload_without_authority() -> None:
    payload = _resolve(
        shell_args=["git", "status", "--porcelain"],
        api_params={"mst_session_id": MST_SESSION_ID, "view": "graph"},
        ui_payload={"label": MST_SESSION_ID, "href": "/api/flow?mst_session_id=" + MST_SESSION_ID},
    )

    assert payload["ok"] is True
    assert payload["classification"] == "security_contract_clear"
    assert payload["canonical_identity_source"] == "mst_session_id"
    assert payload["diagnostics"] == []
    assert payload["destructive_diagnostics"] == []
    assert payload["destructive_action_allowed"] is False
    assert payload["boundary_payload"] == {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "shell_args": ["git", "status", "--porcelain"],
        "api_params": {"mst_session_id": MST_SESSION_ID, "view": "graph"},
        "ui_payload": {
            "label": MST_SESSION_ID,
            "href": "/api/flow?mst_session_id=" + MST_SESSION_ID,
        },
    }
