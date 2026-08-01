from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import native_delegation as native_delegation_mod
from scripts.mst_cmds.native_delegation import (
    _route_fingerprint,
    acknowledge_native_spawn,
    claim_native_spawn,
    finalize_orca_terminal,
    launch_external_via_orca,
    load_persisted_mst_context,
    mark_orca_cleanup_ready,
    native_state_path,
    plan_delegation_route,
    reconcile_orca_terminal,
    request_external_fallback,
    start_external_attempt,
    start_native_attempt,
)
from scripts.mst_cmds.orca_delegation import (
    OrcaClient,
    OrcaCommandError,
    OrcaCreateUncertain,
    OrcaPreflightError,
    resolve_orca_cli,
)


SESSION_ID = "MST-REQ-943-20260801T120000000Z-test9430"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _canonical_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MST_SESSION_ID", SESSION_ID)
    monkeypatch.delenv("MST_CONTEXT_JSON", raising=False)


class FakeOrcaClient:
    def __init__(self) -> None:
        self.command_argv = ("/mock/orca",)
        self.create_calls: list[dict[str, str]] = []
        self.list_calls: list[str] = []
        self.close_calls: list[str] = []
        self.preflight_error: Exception | None = None
        self.create_error: Exception | None = None
        self.terminals: list[dict[str, str]] = []

    def preflight(self, worktree_dir: Path | str) -> dict:
        if self.preflight_error:
            raise self.preflight_error
        worktree = str(Path(worktree_dir).resolve(strict=False))
        return {
            "ok": True,
            "runtime_scope": "local",
            "worktree_dir": worktree,
            "worktree_selector": f"path:{worktree}",
            "cli_argv": list(self.command_argv),
        }

    def create_terminal(self, *, selector: str, title: str, command: str) -> dict:
        self.create_calls.append({"selector": selector, "title": title, "command": command})
        if self.create_error:
            raise self.create_error
        return {"terminal": {"handle": "terminal-943", "title": title}}

    def list_terminals(self, *, selector: str) -> list[dict[str, str]]:
        self.list_calls.append(selector)
        return list(self.terminals)

    def close_terminal(self, *, handle: str) -> dict:
        self.close_calls.append(handle)
        return {"status": "closed", "terminal": {"handle": handle}}


def _route(*, provider: str = "codex", ready: bool = True) -> dict:
    route = plan_delegation_route(
        host="codex",
        provider=provider,
        scope="analysis",
        native_enabled=True,
        configured_scope="all",
        capability_status="available",
        external_adapter_available=True,
        orca_enabled=True,
        orca_preflight={
            "ok": ready,
            "runtime_scope": "local" if ready else None,
            "worktree_selector": "path:/tmp/worktree" if ready else None,
            "cli_argv": ["/mock/orca"] if ready else None,
            "reason_code": None if ready else "runtime_unreachable",
        },
    )
    route["route_fingerprint"] = _route_fingerprint(route)
    return route


def _started_state(tmp_path: Path, *, provider: str = "codex") -> tuple[Path, dict, Path, Path]:
    base = tmp_path / ".gran-maestro"
    base.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("secret prompt body", encoding="utf-8")
    output = tmp_path / "result.md"
    state = start_external_attempt(
        base_dir=base,
        task_id=f"REQ-943-{provider}",
        provider=provider,
        worktree_dir=tmp_path,
        idempotency_key=f"REQ-943-{provider}:start",
        route_reason="orca_launch_surface_ready",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="test-model",
        mst_session_id=SESSION_ID,
        route_decision=_route(provider=provider),
    )
    return base, state, prompt, output


def _overwrite_state(base: Path, state: dict) -> None:
    native_state_path(base, str(state["task_id"])).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_orca_disabled_preserves_existing_route_matrix() -> None:
    direct = plan_delegation_route(
        host="codex",
        provider="codex",
        scope="implementation",
        capability_status="available",
        external_adapter_available=True,
        orca_enabled=False,
    )

    assert direct["route"] == "native_candidate"
    assert direct["execution_transport"] == "native"
    assert direct["launch_surface"] == "direct"
    assert direct["requested_launch_surface"] == "direct"
    assert direct["launch_surface_status"] == "disabled"


@pytest.mark.parametrize("provider", ["codex", "claude", "agy"])
def test_orca_ready_routes_all_supported_providers_to_exact_worktree(provider: str) -> None:
    route = _route(provider=provider)

    assert route["route"] == "external"
    assert route["execution_transport"] == "external"
    assert route["launch_surface"] == "orca"
    assert route["requested_launch_surface"] == "orca"
    assert route["original_route_decision"]["route"] in {"native_candidate", "external"}
    assert _route_fingerprint(route) != route["original_route_fingerprint"]


def test_orca_preflight_failure_falls_back_before_create() -> None:
    route = _route(ready=False)

    assert route["route"] == "native_candidate"
    assert route["execution_transport"] == "native"
    assert route["launch_surface"] == "direct"
    assert route["requested_launch_surface"] == "orca"
    assert route["launch_surface_status"] == "preflight_failed"


def test_native_definitive_non_creation_fallback_uses_orca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / ".gran-maestro"
    base.mkdir()
    prompt = tmp_path / "native-prompt.md"
    prompt.write_text("native prompt", encoding="utf-8")
    direct_route = plan_delegation_route(
        host="codex",
        provider="codex",
        scope="analysis",
        capability_status="available",
        external_adapter_available=True,
    )
    direct_route["route_fingerprint"] = _route_fingerprint(direct_route)
    started = start_native_attempt(
        base_dir=base,
        task_id="REQ-943-native-fallback",
        idempotency_key="native-start",
        host="codex",
        provider="codex",
        worktree_dir=tmp_path,
        scope="analysis",
        read_only=True,
        route_decision=direct_route,
        prompt_file=prompt,
        mst_session_id=SESSION_ID,
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id=started["task_id"],
        expected_attempt_id=started["attempt_id"],
        claimant_id="test-parent",
        idempotency_key="native-claim",
    )
    acknowledged = acknowledge_native_spawn(
        base_dir=base,
        task_id=started["task_id"],
        expected_attempt_id=started["attempt_id"],
        spawn_status="definitive_not_created",
        claim_token=claim["claim_token"],
        idempotency_key="native-ack",
    )
    (base / "config.json").write_text(
        json.dumps({"delegation": {"orca": {"enabled": True}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        native_delegation_mod.shutil,
        "which",
        lambda command: f"/mock/{command}",
    )

    fallback = request_external_fallback(
        base_dir=base,
        task_id=started["task_id"],
        expected_attempt_id=acknowledged["attempt_id"],
        idempotency_key="native-fallback",
        orca_client=FakeOrcaClient(),
    )

    assert fallback["execution_transport"] == "external"
    assert fallback["launch_surface"] == "orca"
    assert fallback["orca_worktree_selector"] == f"path:{tmp_path.resolve()}"
    assert fallback["fallback_from"] == acknowledged["attempt_id"]


@pytest.mark.parametrize("provider", ["codex", "claude", "agy"])
def test_orca_command_contains_only_safe_identifiers(tmp_path: Path, provider: str) -> None:
    base, state, prompt, output = _started_state(tmp_path, provider=provider)
    client = FakeOrcaClient()

    launched = launch_external_via_orca(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        idempotency_key=f"{state['task_id']}:orca-launch",
        client=client,
        mst_script=Path("/plugin/scripts/mst.py"),
    )

    assert launched["execution_transport"] == "external"
    assert launched["launch_surface"] == "orca"
    assert launched["orca_terminal_handle"] == "terminal-943"
    assert len(client.create_calls) == 1
    call = client.create_calls[0]
    exact_worktree = str(tmp_path.resolve())
    assert call["selector"] == f"path:{exact_worktree}"
    assert call["title"] == f"MST/{state['task_id']}/{state['attempt_id']}"
    assert "dispatch run-external" in call["command"]
    assert str(state["task_id"]) in call["command"]
    assert str(state["attempt_id"]) in call["command"]
    assert SESSION_ID in call["command"]
    for forbidden in (
        "active",
        "current",
        "worktree create",
        prompt.read_text(encoding="utf-8"),
        str(prompt),
        str(output),
        str(state["prompt_snapshot_path"]),
        "claim-secret",
    ):
        assert forbidden not in call["command"]


def test_orca_create_unknown_never_falls_back_or_duplicates(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    client = FakeOrcaClient()
    client.create_error = OrcaCreateUncertain("create response lost")

    first = launch_external_via_orca(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        idempotency_key="orca-create-unknown",
        client=client,
        mst_script=Path("/plugin/scripts/mst.py"),
    )
    second = launch_external_via_orca(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        idempotency_key="orca-create-unknown-retry",
        client=client,
        mst_script=Path("/plugin/scripts/mst.py"),
    )

    assert len(client.create_calls) == 1
    assert first["phase"] == "reconciling"
    assert second["phase"] == "reconciling"
    assert second["fallback_allowed"] is False
    assert second["orca_reconciliation_required"] is True


def test_orca_launch_replay_trusts_the_persisted_created_handle(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "orca_create_invoked_at": "2026-08-01T00:00:00+00:00",
            "orca_terminal_handle": "terminal-existing",
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()

    replay = launch_external_via_orca(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        idempotency_key="orca-created-replay",
        client=client,
    )

    assert replay["orca_terminal_handle"] == "terminal-existing"
    assert client.create_calls == []
    assert client.list_calls == []


def test_orca_stale_handle_reacquires_one_deterministic_terminal(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    title = f"MST/{state['task_id']}/{state['attempt_id']}"
    state.update(
        {
            "orca_terminal_title": title,
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_create_invoked_at": "2026-08-01T00:00:00+00:00",
            "orca_launch_status": "create_unknown",
            "phase": "reconciling",
            "status": "orca_create_unknown",
            "provider_reconciliation_required": True,
            "orca_reconciliation_required": True,
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()
    client.terminals = [
        {"handle": "wrong-title", "title": "other"},
        {"handle": "replacement-943", "title": title},
    ]

    recovered = reconcile_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=client,
    )

    assert client.list_calls == [f"path:{tmp_path.resolve()}"]
    assert recovered["orca_terminal_handle"] == "replacement-943"
    assert recovered["phase"] == "planned"
    assert recovered["provider_reconciliation_required"] is False
    assert recovered["orca_reconciliation_required"] is False


def test_orca_reconcile_does_not_overwrite_a_concurrent_create_response(
    tmp_path: Path,
) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_create_invoked_at": "2026-08-01T00:00:00+00:00",
            "orca_launch_status": "create_invoked",
        }
    )
    _overwrite_state(base, state)

    class ConcurrentCreateClient(FakeOrcaClient):
        def list_terminals(self, *, selector: str) -> list[dict[str, str]]:
            self.list_calls.append(selector)
            concurrent = json.loads(
                native_state_path(base, state["task_id"]).read_text(encoding="utf-8")
            )
            concurrent.update(
                {
                    "orca_terminal_handle": "terminal-concurrent",
                    "orca_launch_status": "created",
                    "orca_reconciliation_required": False,
                }
            )
            _overwrite_state(base, concurrent)
            return []

    recovered = reconcile_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=ConcurrentCreateClient(),
    )

    assert recovered["orca_terminal_handle"] == "terminal-concurrent"
    assert recovered["orca_launch_status"] == "created"
    assert recovered["phase"] == "planned"


def test_orca_zero_or_multiple_reacquisition_matches_stay_reconciling(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    title = f"MST/{state['task_id']}/{state['attempt_id']}"
    state.update(
        {
            "orca_terminal_title": title,
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_create_invoked_at": "2026-08-01T00:00:00+00:00",
            "orca_launch_status": "create_unknown",
            "phase": "reconciling",
            "status": "orca_create_unknown",
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()
    client.terminals = [
        {"handle": "one", "title": title},
        {"handle": "two", "title": title},
    ]

    recovered = reconcile_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=client,
    )

    assert recovered["phase"] == "reconciling"
    assert recovered["orca_terminal_handle"] is None
    assert recovered["orca_reconciliation"]["match_count"] == 2


def test_orca_success_closes_tab_after_output_finalization(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "phase": "done",
            "status": "completed",
            "completion_signal": "process_exit",
            "orca_terminal_handle": "terminal-943",
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_launch_status": "created",
            "orca_cleanup_status": "ready_to_close",
            "orca_cleanup_ready_at": "2026-08-01T00:00:01+00:00",
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()

    finalized = finalize_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=client,
    )

    assert client.close_calls == ["terminal-943"]
    assert finalized["orca_cleanup_status"] == "closed"
    assert finalized["status"] == "completed"


def test_orca_success_cannot_self_close_before_controller_evidence(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "phase": "done",
            "status": "completed",
            "orca_terminal_handle": "terminal-943",
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()

    with pytest.raises(native_delegation_mod.LifecycleConflict, match="out-of-tab"):
        finalize_orca_terminal(
            base_dir=base,
            task_id=state["task_id"],
            expected_attempt_id=state["attempt_id"],
            client=client,
        )

    assert client.close_calls == []

    ready = mark_orca_cleanup_ready(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
    )
    assert ready["orca_cleanup_status"] == "ready_to_close"


def test_orca_worker_failure_wakes_outer_controller_and_preserves_terminal(
    tmp_path: Path,
) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "orca_terminal_handle": "terminal-943",
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)

    failed = native_delegation_mod.record_orca_worker_failure(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        reason_code="orca_context_restore_failed",
    )
    observed = native_delegation_mod.wait_for_orca_cleanup_ready(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        poll_interval=0.01,
    )
    client = FakeOrcaClient()
    preserved = finalize_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=client,
    )

    assert failed["phase"] == "reconciling"
    assert failed["orca_reconciliation_required"] is True
    assert observed["orca_cleanup_status"] == "ready_to_preserve"
    assert client.close_calls == []
    assert preserved["orca_cleanup_status"] == "preserved"


def test_orca_cleanup_wait_returns_for_provider_reconciliation(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "phase": "reconciling",
            "status": "reconciling",
            "provider_reconciliation_required": True,
            "orca_terminal_handle": "terminal-943",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)

    observed = native_delegation_mod.wait_for_orca_cleanup_ready(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        poll_interval=0.01,
    )

    assert observed["phase"] == "reconciling"
    assert observed["provider_reconciliation_required"] is True


def test_orca_cleanup_wait_bounds_worker_without_state_progress(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "orca_terminal_handle": "terminal-943",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)

    observed = native_delegation_mod.wait_for_orca_cleanup_ready(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        poll_interval=0.01,
        stale_timeout=0.01,
    )

    assert observed["phase"] == "reconciling"
    assert observed["failure_domain"] == "orca_worker_heartbeat_stale"
    assert observed["orca_cleanup_status"] == "ready_to_preserve"


@pytest.mark.parametrize(
    ("phase", "status"),
    [("failed", "failed"), ("terminated", "cancelled"), ("reconciling", "orca_create_unknown")],
)
def test_orca_failure_and_cancel_preserve_terminal(
    tmp_path: Path, phase: str, status: str
) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "phase": phase,
            "status": status,
            "orca_terminal_handle": "terminal-943",
            "orca_terminal_title": f"MST/{state['task_id']}/{state['attempt_id']}",
            "orca_worktree_selector": f"path:{tmp_path.resolve()}",
            "orca_launch_status": "created",
        }
    )
    _overwrite_state(base, state)
    client = FakeOrcaClient()

    finalized = finalize_orca_terminal(
        base_dir=base,
        task_id=state["task_id"],
        expected_attempt_id=state["attempt_id"],
        client=client,
    )

    assert client.close_calls == []
    assert finalized["orca_cleanup_status"] == "preserved"


def test_orca_executable_resolution_selects_once_without_fallthrough() -> None:
    observed: list[str] = []

    def which(command: str) -> str | None:
        observed.append(command)
        return "/resolved/special-orca" if command == "special-orca" else "/resolved/orca"

    selected = resolve_orca_cli(
        env={"ORCA_CLI_COMMAND": "special-orca --bridge local"},
        platform_name="darwin",
        which=which,
    )

    assert selected == ("/resolved/special-orca", "--bridge", "local")
    assert observed == ["special-orca"]

    with pytest.raises(OrcaCommandError):
        resolve_orca_cli(
            env={"ORCA_CLI_COMMAND": "missing-orca"},
            platform_name="darwin",
            which=lambda command: None,
        )


def test_orca_preflight_never_persists_wrapper_arguments(tmp_path: Path) -> None:
    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if "status" in argv:
            payload = {"ok": True, "result": {"app": {"running": True}}}
        else:
            payload = {"ok": True, "result": {"worktree": {"path": str(tmp_path)}}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    preflight = OrcaClient(
        command_argv=["/mock/orca", "--token", "secret-value"],
        runner=runner,
    ).preflight(tmp_path)

    assert preflight["cli_argv"] == ["/mock/orca"]
    assert "secret-value" not in json.dumps(preflight)


@pytest.mark.parametrize("failure_kind", ["timeout", "nonzero", "structured"])
def test_orca_errors_never_expose_wrapper_arguments(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    secret = "wrapper-secret-value"

    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(argv, 15)
        if failure_kind == "nonzero":
            return subprocess.CompletedProcess(
                argv,
                1,
                "",
                f"failed argv={argv!r}",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"ok": False, "error": f"bad --token {secret}"}),
            "",
        )

    client = OrcaClient(
        command_argv=["/mock/orca", "--token", secret],
        runner=runner,
    )

    with pytest.raises(OrcaPreflightError) as captured:
        client.preflight(tmp_path)

    message = str(captured.value)
    assert secret not in message
    assert "--token" not in message


def test_orca_child_restores_hash_bound_structured_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = {
        "schema_version": 1,
        "mst_session_id": SESSION_ID,
        "root_mst_id": "REQ-943",
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": SESSION_ID,
            "root_mst_id": "REQ-943",
            "auto": True,
            "continuation": {"depth": 3},
            "history_refs": ["history.ndjson#42"],
        },
    }
    monkeypatch.setenv("MST_CONTEXT_JSON", json.dumps(context))
    base, state, _prompt, _output = _started_state(tmp_path)

    stale_inherited = {
        **context,
        "core_rehydration": {
            **context["core_rehydration"],
            "auto": False,
            "continuation": {"depth": 99},
        },
    }
    restored = json.loads(
        load_persisted_mst_context(
            base_dir=base,
            task_id=state["task_id"],
            expected_attempt_id=state["attempt_id"],
            inherited_context=json.dumps(stale_inherited),
        )
    )

    assert restored["core_rehydration"]["auto"] is True
    assert restored["core_rehydration"]["continuation"] == {"depth": 3}
    assert restored["core_rehydration"]["history_refs"] == ["history.ndjson#42"]
    assert state["mst_context_snapshot_hash"].startswith("sha256:")


def test_orca_requested_fallback_never_uses_inherited_context_without_binding(
    tmp_path: Path,
) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "requested_launch_surface": "orca",
            "launch_surface": "direct",
            "mst_context_snapshot_path": None,
            "mst_context_snapshot_hash": None,
        }
    )
    _overwrite_state(base, state)

    with pytest.raises(native_delegation_mod.LifecycleConflict, match="context binding"):
        load_persisted_mst_context(
            base_dir=base,
            task_id=state["task_id"],
            expected_attempt_id=state["attempt_id"],
            inherited_context=json.dumps(
                {
                    "schema_version": 1,
                    "mst_session_id": SESSION_ID,
                    "root_mst_id": "REQ-943",
                }
            ),
        )


def test_legacy_direct_attempt_can_use_matching_inherited_context(tmp_path: Path) -> None:
    base, state, _prompt, _output = _started_state(tmp_path)
    state.update(
        {
            "requested_launch_surface": "direct",
            "launch_surface": "direct",
            "mst_context_snapshot_path": None,
            "mst_context_snapshot_hash": None,
        }
    )
    _overwrite_state(base, state)
    inherited = json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SESSION_ID,
            "root_mst_id": "REQ-943",
            "legacy": True,
        }
    )

    restored = json.loads(
        load_persisted_mst_context(
            base_dir=base,
            task_id=state["task_id"],
            expected_attempt_id=state["attempt_id"],
            inherited_context=inherited,
        )
    )

    assert restored["legacy"] is True


def test_legacy_route_fingerprint_remains_valid_when_orca_fields_are_absent() -> None:
    decision = {
        "host": "codex",
        "provider": "codex",
        "transport_policy": "external-only",
        "scope": "analysis",
        "configured_scope": "review-and-exploration-only",
        "native_enabled": False,
        "capability_status": "unknown",
        "route": "external",
        "execution_transport": "external",
        "reason_code": "policy_disabled",
        "route_cause": "policy_disabled",
        "handshake_required": False,
    }
    fingerprint = native_delegation_mod._legacy_route_fingerprint(decision)
    decision["route_fingerprint"] = fingerprint
    state = {
        "route_decision": decision,
        "route_fingerprint": fingerprint,
        "execution_transport": "external",
    }

    assert native_delegation_mod._validate_persisted_route(state) is decision
    current_direct = {
        **decision,
        "requested_launch_surface": "direct",
        "launch_surface": "direct",
        "launch_surface_status": "disabled",
    }
    assert native_delegation_mod._route_policy_signature(
        decision
    ) == native_delegation_mod._route_policy_signature(current_direct)
    assert native_delegation_mod._route_policy_signature(
        decision
    ) != native_delegation_mod._route_policy_signature(
        {
            **current_direct,
            "requested_launch_surface": "orca",
            "launch_surface": "orca",
        }
    )

    decision["scope"] = "implementation"
    with pytest.raises(native_delegation_mod.LifecycleConflict, match="fingerprint"):
        native_delegation_mod._validate_persisted_route(state)


@pytest.mark.parametrize(
    ("env", "platform_name", "expected"),
    [
        ({"ORCA_DEV_REPO_ROOT": "/dev/orca"}, "darwin", "orca-dev"),
        ({}, "linux", "orca-ide"),
        ({"ORCA_WORKTREE_ID": "repo::/worktree"}, "linux", "orca"),
        ({}, "darwin", "orca"),
    ],
)
def test_orca_executable_resolution_follows_installed_guide_order(
    env: dict[str, str], platform_name: str, expected: str
) -> None:
    observed: list[str] = []

    selected = resolve_orca_cli(
        env=env,
        platform_name=platform_name,
        which=lambda command: observed.append(command) or f"/resolved/{command}",
    )

    assert selected == (f"/resolved/{expected}",)
    assert observed == [expected]


def test_orca_client_preflight_uses_json_and_exact_path_selector(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[1:] == ["status", "--json"]:
            payload = {
                "id": "local-status",
                "ok": True,
                "result": {
                    "app": {"running": True, "pid": 943},
                    "runtime": {
                        "state": "ready",
                        "reachable": True,
                        "runtimeId": "runtime-local",
                    },
                    "graph": {"state": "ready"},
                },
            }
        else:
            payload = {"worktree": {"path": str(tmp_path.resolve())}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    result = OrcaClient(command_argv=["/mock/orca"], runner=runner).preflight(tmp_path)

    selector = f"path:{tmp_path.resolve()}"
    assert result["worktree_selector"] == selector
    assert calls == [
        ["/mock/orca", "status", "--json"],
        [
            "/mock/orca",
            "worktree",
            "show",
            "--worktree",
            selector,
            "--json",
        ],
    ]


def test_orca_client_rejects_remote_runtime_without_worktree_lookup(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = {
            "id": "remote-status",
            "ok": True,
            "result": {
                "app": {"running": False, "pid": None},
                "runtime": {
                    "state": "ready",
                    "reachable": True,
                    "runtimeId": "runtime-remote",
                },
                "graph": {"state": "ready"},
            },
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    with pytest.raises(OrcaCommandError, match="remote or federated"):
        OrcaClient(command_argv=["/mock/orca"], runner=runner).preflight(tmp_path)

    assert calls == [["/mock/orca", "status", "--json"]]


def test_orca_client_closes_the_whole_tab() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = {"close": {"handle": "terminal-943"}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    OrcaClient(command_argv=["/mock/orca"], runner=runner).close_terminal(
        handle="terminal-943"
    )

    assert calls == [
        [
            "/mock/orca",
            "terminal",
            "close",
            "--terminal",
            "terminal-943",
            "--tab",
            "--json",
        ]
    ]


def test_orca_client_parses_terminal_rpc_envelopes() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[1:3] == ["terminal", "create"]:
            result = {
                "terminal": {
                    "handle": "terminal-created",
                    "title": "MST/REQ-943/T01",
                }
            }
        else:
            result = {
                "terminals": [
                    {
                        "handle": "terminal-created",
                        "title": "MST/REQ-943/T01",
                    }
                ],
                "totalCount": 1,
                "truncated": False,
            }
        payload = {"id": "rpc-id", "ok": True, "result": result}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    client = OrcaClient(command_argv=["/mock/orca"], runner=runner)
    created = client.create_terminal(
        selector="path:/tmp/worktree",
        title="MST/REQ-943/T01",
        command="python3 mst.py dispatch run-external",
    )
    terminals = client.list_terminals(selector="path:/tmp/worktree")

    assert created["terminal_handle"] == "terminal-created"
    assert terminals == [
        {"handle": "terminal-created", "title": "MST/REQ-943/T01"}
    ]
    assert len(calls) == 2


def test_dashboard_and_projection_include_orca_enabled_setting() -> None:
    source_defaults = json.loads(
        (REPO_ROOT / "templates" / "defaults" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    projected_defaults = json.loads(
        (
            REPO_ROOT
            / "plugins"
            / "mst"
            / "templates"
            / "defaults"
            / "config.json"
        ).read_text(encoding="utf-8")
    )
    source_descriptions = (
        REPO_ROOT / "frontend" / "src" / "config" / "settingDescriptions.ts"
    ).read_text(encoding="utf-8")
    built_dashboard = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "dist" / "static").glob("*.js")
    )
    projected_dashboard = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "plugins" / "mst" / "dist" / "static").glob("*.js")
    )

    assert source_defaults["delegation"]["orca"] == {"enabled": False}
    assert projected_defaults["delegation"]["orca"] == {"enabled": False}
    assert "delegation.orca.enabled" in source_descriptions
    assert "delegation.orca.enabled" in built_dashboard
    assert "delegation.orca.enabled" in projected_dashboard
    assert (
        REPO_ROOT / "plugins" / "mst" / "scripts" / "mst_cmds" / "orca_delegation.py"
    ).is_file()
