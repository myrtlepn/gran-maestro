from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
AUDIT_JSON = REPO_ROOT / "hooks" / "canonical-hook-entrypoint-boundary.audit.json"
MATRIX_JSON = REPO_ROOT / "hooks" / "hook-event-contract-matrix.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import session
from scripts.mst_cmds.hook import append_history_event


STARTED_AT = datetime(2026, 5, 11, 11, 1, 21, tzinfo=timezone.utc)
FIXTURE_SESSION_ID = "MST-REQ-857-20260511T110121000Z-abcdef12"
MISMATCH_SESSION_ID = "MST-REQ-857-20260511T110121000Z-bcdef123"
ROOT_MST_ID = "REQ-857"
ZERO_HASH = "0" * 64


BOUNDARY_EXPECTATIONS = {
    ".claude-plugin/plugin.json + hooks/hooks.json + ${CLAUDE_PLUGIN_ROOT}/hooks/": "canonical_allowed",
    ".claude/hooks": "source_dev_legacy_noncanonical",
    "$CLAUDE_PROJECT_DIR/.claude/hooks": "project_noncanonical_rejected",
    "settings.local.json": "project_local_settings_noncanonical_rejected",
    "~/.claude/settings.json": "user_global_ignored_or_diagnostic_only",
}
BOUNDARY_CLASSIFICATION_ALIASES = {
    "source_dev_legacy_noncanonical": {"project_legacy_source_dev_helper"},
    "project_noncanonical_rejected": {"project_local_hook_registration"},
    "project_local_settings_noncanonical_rejected": {"project_local_settings_hook_registration"},
    "user_global_ignored_or_diagnostic_only": {"user_global_environment_hooks"},
}


def _clean_env(workspace: Path, policy_home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "MST_SESSION_ID",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "CLAUDE_PROJECT_DIR",
    ):
        env.pop(key, None)
    home = workspace / "home"
    claude_config = workspace / "claude-config"
    env.update(
        {
            "MST_FLOW_DISABLE_ATEXIT": "1",
            "MST_POLICY_HOME": str(policy_home),
            "MST_CLAUDE_HOME": str(home),
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(claude_config),
        }
    )
    if extra:
        env.update(extra)
    return env


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root}:{path.relative_to(root)}"] = path.read_text(encoding="utf-8", errors="replace")
    return result


def _run_history(workspace: Path, policy_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "history", *args],
        cwd=workspace,
        env=_clean_env(workspace, policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _run_required_session_context(
    workspace: Path,
    policy_home: Path,
    *,
    env_session_id: str | None = None,
    payload: dict | None = None,
    legacy_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = """
import json
from scripts.mst_cmds import session
try:
    child_env = session.child_env_with_required_session_context()
except Exception as exc:
    print(json.dumps({"status":"error","error_type":type(exc).__name__,"message":str(exc)}, sort_keys=True))
    raise SystemExit(2)
print(json.dumps({
    "status":"ok",
    "mst_session_id": child_env.get("MST_SESSION_ID"),
    "context": json.loads(child_env.get("MST_CONTEXT_JSON", "{}")),
}, sort_keys=True))
"""
    extra = dict(legacy_env or {})
    extra["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if part
    )
    if env_session_id is not None:
        extra["MST_SESSION_ID"] = env_session_id
    if payload is not None:
        extra["MST_CONTEXT_JSON"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=workspace,
        env=_clean_env(workspace, policy_home, extra),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _json_lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_structured_id_contract() -> str:
    generated = session.generate_mst_session_id(
        ROOT_MST_ID,
        started_at=STARTED_AT,
        random_segment="abcdef12",
    )
    assert generated == FIXTURE_SESSION_ID, "ID stage: generator must preserve structured REQ fixture format"
    parsed = session.parse_mst_session_id(generated)
    assert parsed.root_mst_id == ROOT_MST_ID, "ID stage: parser must preserve hyphenated root resource"
    assert session.validate_mst_session_id(generated).mst_session_id == generated, "ID stage: valid ID rejected"

    malformed = [
        "MST-REQ857-20260511T110121000Z-abcdef12",
        "MST-REQ-857-abcdef12",
        "MST-REQ-857-20260511T110121000Z-ABCDEF12",
        "MST-REQ-857-20260511T110121000Z-",
        "MST--REQ-857-20260511T110121000Z-abcdef12",
    ]
    for value in malformed:
        try:
            session.validate_mst_session_id(value)
        except session.MstSessionIdValidationError:
            continue
        raise AssertionError(f"ID stage: malformed mst_session_id passed validation: {value!r}")
    return generated


def _identity_payload(mst_session_id: str, **extra: object) -> dict:
    payload = {
        "schema_version": 1,
        "mst_session_id": mst_session_id,
        "root_mst_id": ROOT_MST_ID,
    }
    payload.update(extra)
    return payload


def _assert_session_identity_contract(workspace: Path, policy_home: Path, mst_session_id: str) -> None:
    state_roots = (workspace / ".gran-maestro", policy_home, workspace / "claude-config")
    before = _snapshot(*state_roots)

    match = _run_required_session_context(
        workspace,
        policy_home,
        env_session_id=mst_session_id,
        payload=_identity_payload(mst_session_id),
    )
    assert match.returncode == 0, "session stage: env/payload match should approve canonical ID: " + match.stdout + match.stderr
    match_payload = json.loads(match.stdout)
    assert match_payload["mst_session_id"] == mst_session_id, "session stage: canonical ID was not preserved"
    assert match_payload["context"]["mst_session_id"] == mst_session_id, "session stage: child context lacks canonical mst_session_id"

    mismatch = _run_required_session_context(
        workspace,
        policy_home,
        env_session_id=mst_session_id,
        payload=_identity_payload(MISMATCH_SESSION_ID),
    )
    assert mismatch.returncode != 0, "session stage: env/payload mismatch should be diagnostic non-success"
    mismatch_payload = json.loads(mismatch.stdout)
    assert mismatch_payload["status"] == "error"
    assert "mismatch" in mismatch_payload["message"]

    env_only = _run_required_session_context(workspace, policy_home, env_session_id=mst_session_id)
    assert env_only.returncode == 0, "session stage: env-only canonical ID should approve: " + env_only.stdout + env_only.stderr
    assert json.loads(env_only.stdout)["mst_session_id"] == mst_session_id

    stdin_only = _run_required_session_context(workspace, policy_home, payload=_identity_payload(mst_session_id))
    assert stdin_only.returncode != 0, "session stage: stdin-only canonical ID without inherited env should be non-success"
    stdin_payload = json.loads(stdin_only.stdout)
    assert stdin_payload["status"] == "error"
    assert "missing MST_SESSION_ID" in stdin_payload["message"]

    legacy_only = _run_required_session_context(
        workspace,
        policy_home,
        payload={"session_id": "legacy-hook-session"},
        legacy_env={"MST_STATE_PPID": "12345", "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot"},
    )
    assert legacy_only.returncode != 0, "session stage: legacy-only input must not become canonical"
    assert "missing MST_SESSION_ID" in json.loads(legacy_only.stdout)["message"]

    assert _snapshot(*state_roots) == before, "session stage: resolver mutated MST/policy/config filesystem state"


def _assert_history_contract(workspace: Path, policy_home: Path, mst_session_id: str) -> None:
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    history_file = append_history_event(
        workspace,
        policy_home,
        mst_session_id,
        {
            "event_type": "dod004.integration_start",
            "created_at": "2026-05-11T11:01:21.000Z",
            "idempotency_key": f"{mst_session_id}:dod004.integration_start:fixture",
            "flow_correlation_id": "REQ-858-T01",
        },
    )
    append_history_event(
        workspace,
        policy_home,
        mst_session_id,
        {
            "event_type": "dod004.integration_end",
            "created_at": "2026-05-11T11:01:22.000Z",
            "idempotency_key": f"{mst_session_id}:dod004.integration_end:fixture",
            "flow_correlation_id": "REQ-858-T01",
        },
    )

    verify = _run_history(workspace, policy_home, "verify", "--session", mst_session_id, "--json")
    head = _run_history(workspace, policy_home, "head", "--session", mst_session_id, "--json")
    log = _run_history(workspace, policy_home, "log", "--session", mst_session_id, "--json")
    assert verify.returncode == 0, "history stage: verify failed: " + verify.stdout + verify.stderr
    assert head.returncode == 0, "history stage: head failed: " + head.stdout + head.stderr
    assert log.returncode == 0, "history stage: log failed: " + log.stdout + log.stderr

    rows = _json_lines(log.stdout)
    assert len(rows) == 2, "history stage: expected two production-appended rows"
    assert [row["seq"] for row in rows] == [1, 2], "history stage: seq chain mismatch"
    assert rows[0]["prev_hash"] == ZERO_HASH, "history stage: first row must start from zero hash"
    assert rows[1]["prev_hash"] == rows[0]["event_hash"], "history stage: previous/head linkage mismatch"
    for row in rows:
        assert row["mst_session_id"] == mst_session_id, "history stage: row missing canonical mst_session_id"
        assert row["root_mst_id"] == ROOT_MST_ID, "history stage: row missing root resource"

    verify_payload = json.loads(verify.stdout)
    head_payload = json.loads(head.stdout)
    assert verify_payload["tail"]["event_hash"] == rows[-1]["event_hash"], "history stage: verifier tail is not log tail"
    assert verify_payload["verify"]["event_hash"] == rows[-1]["event_hash"], "history stage: verify state head is stale"
    assert head_payload["head"] == {"event_hash": rows[-1]["event_hash"], "seq": 2}, "history stage: head payload mismatch"
    assert history_file == Path(verify_payload["history_path"]), "history stage: verifier points at unexpected ledger"

    tampered = json.loads(history_file.read_text(encoding="utf-8").splitlines()[-1])
    tampered["mst_session_id"] = MISMATCH_SESSION_ID
    lines = history_file.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    history_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    negative = _run_history(workspace, policy_home, "verify", "--session", mst_session_id, "--json")
    assert negative.returncode != 0, "history stage: tampered wrong-session row should fail production verifier"
    negative_payload = json.loads(negative.stdout)
    assert negative_payload["status"] == "error"
    assert negative_payload["code"] in {
        "history_session_mismatch",
        "history_row_session_mismatch",
        "history_event_hash_mismatch",
    }, negative_payload


def _assert_boundary_contract() -> None:
    plugin_payload = _read_json(PLUGIN_JSON)
    hooks_payload = _read_json(HOOKS_JSON)
    audit_payload = _read_json(AUDIT_JSON)
    matrix_payload = _read_json(MATRIX_JSON)

    assert plugin_payload["hooks"] == "./hooks/hooks.json", "boundary stage: plugin manifest hook registration drifted"
    runtime_commands = {
        hook["command"]
        for registrations in hooks_payload["hooks"].values()
        for registration in registrations
        for hook in registration.get("hooks", [])
    }
    assert runtime_commands, "boundary stage: hooks/hooks.json has no canonical runtime commands"
    assert all(command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/") for command in runtime_commands), "boundary stage: canonical command root drifted"
    assert all(".claude/hooks" not in command for command in runtime_commands), "boundary stage: .claude/hooks was promoted to canonical runtime"

    observed = {
        ".claude-plugin/plugin.json + hooks/hooks.json + ${CLAUDE_PLUGIN_ROOT}/hooks/": "canonical_allowed"
    }
    audit_boundaries = {
        item["path"]: item
        for item in audit_payload["canonical_runtime_boundary"]["non_canonical_runtimes"]
    }
    matrix_boundaries = {row["path"]: row for row in matrix_payload["negative_boundary_rows"]}

    for path, expected in BOUNDARY_EXPECTATIONS.items():
        if expected == "canonical_allowed":
            assert observed[path] == expected, "boundary stage: canonical plugin registration not allowed"
            continue
        row = matrix_boundaries[path]
        assert row["canonical_mst_core_runtime"] is False, f"boundary stage: {path} became canonical"
        assert row["allowed_only_as"] == "negative_boundary", f"boundary stage: {path} allowed outside negative boundary"
        assert row["classification"] in BOUNDARY_CLASSIFICATION_ALIASES[expected], f"boundary stage: {path} classification drifted"
        observed[path] = expected

    assert audit_boundaries[".claude/hooks"]["classification"] in BOUNDARY_CLASSIFICATION_ALIASES["source_dev_legacy_noncanonical"]
    assert audit_boundaries["~/.claude/settings.json"]["classification"] in BOUNDARY_CLASSIFICATION_ALIASES["user_global_ignored_or_diagnostic_only"]
    assert observed == BOUNDARY_EXPECTATIONS, "boundary stage: row-level expectation table incomplete"


def test_dod004_id_session_history_boundary_integration(tmp_path: Path) -> None:
    workspace = tmp_path / "project-root"
    policy_home = tmp_path / "policy-home"
    workspace.mkdir()
    policy_home.mkdir()

    assert workspace != REPO_ROOT, "isolation stage: test project root must not be repository root"
    env = _clean_env(workspace, policy_home)
    assert Path(env["HOME"]).is_relative_to(tmp_path), "isolation stage: HOME must be under tmp_path"
    assert Path(env["CLAUDE_CONFIG_DIR"]).is_relative_to(tmp_path), "isolation stage: CLAUDE_CONFIG_DIR must be under tmp_path"
    assert Path(env["MST_POLICY_HOME"]).is_relative_to(tmp_path), "isolation stage: policy home must be under tmp_path"

    mst_session_id = _assert_structured_id_contract()
    _assert_session_identity_contract(workspace, policy_home, mst_session_id)
    _assert_history_contract(workspace, policy_home, mst_session_id)
    _assert_boundary_contract()
