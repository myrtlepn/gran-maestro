from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STARTED_AT = datetime(2026, 5, 3, 13, 8, 13, 382000, tzinfo=timezone.utc)
ENV_SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STRUCTURED_SID = "MST-REQ-807-20260503T131853000Z-r4n8vd1c"
SESSION_METADATA_SID = "MST-PLN-638-20260503T132500000Z-h7p2n4c8"
SNAPSHOT_SID = "MST-REQ-811-20260503T133000000Z-v8m1q2z4"
LEGACY_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import _skill_state
from scripts.mst_cmds import execution_flow
from scripts.mst_cmds import session


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _base_dir(workspace: Path) -> Path:
    base_dir = workspace / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _files(base_dir: Path) -> dict[str, str]:
    if not base_dir.exists():
        return {}
    return {
        str(path.relative_to(base_dir)): path.read_text(encoding="utf-8")
        for path in base_dir.rglob("*")
        if path.is_file()
    }


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=_clean_env(env),
        check=False,
        timeout=30,
    )


def test_diagnostic_json_exposes_required_fields_and_stable_precedence() -> None:
    diagnostic = execution_flow.resolve_canonical_mst_session_identity(
        {"mst_session_id": STRUCTURED_SID},
        {"MST_SESSION_ID": ENV_SID},
        session_metadata={"mst_session_id": SESSION_METADATA_SID},
        snapshot_payload={"mst_session_id": SNAPSHOT_SID},
        snapshot_path=f"/tmp/project/.gran-maestro/state/{SNAPSHOT_SID}/snapshot.json",
        invocation_class="diagnostic_invocation",
    )

    for field in ("valid", "reason", "action", "source_precedence", "observed_sources", "invocation_class"):
        assert field in diagnostic
    assert diagnostic["valid"] is False
    assert diagnostic["reason"] == "canonical_identity_conflict"
    assert diagnostic["action"] == "repair_canonical_identity_conflict"
    assert diagnostic["invocation_class"] == "diagnostic_invocation"
    assert diagnostic["source_precedence"] == [
        "env:MST_SESSION_ID",
        "structured:mst_session_id",
        "session_metadata:mst_session_id",
        "snapshot_path:mst_session_id",
        "snapshot_body:mst_session_id",
    ]
    assert diagnostic["selected_source"] == "env:MST_SESSION_ID"
    assert diagnostic["canonical_mst_session_id"] == ENV_SID
    observed = diagnostic["observed_sources"]
    assert observed["env:MST_SESSION_ID"]["value"] == ENV_SID
    assert observed["structured:mst_session_id"]["value"] == STRUCTURED_SID
    assert observed["session_metadata:mst_session_id"]["value"] == SESSION_METADATA_SID
    assert observed["snapshot_path:mst_session_id"]["value"] == SNAPSHOT_SID
    assert observed["snapshot_body:mst_session_id"]["value"] == SNAPSHOT_SID


def test_lower_priority_sources_resolve_stably_when_higher_priority_sources_are_absent() -> None:
    diagnostic = execution_flow.resolve_canonical_mst_session_identity(
        {},
        {},
        session_metadata={"mst_session_id": SESSION_METADATA_SID},
        snapshot_payload={"mst_session_id": SNAPSHOT_SID},
        snapshot_path=f"/tmp/project/.gran-maestro/state/{SNAPSHOT_SID}/snapshot.json",
        invocation_class="diagnostic_invocation",
    )

    assert diagnostic["valid"] is False
    assert diagnostic["reason"] == "canonical_identity_conflict"
    assert diagnostic["selected_source"] == "session_metadata:mst_session_id"
    assert diagnostic["canonical_mst_session_id"] == SESSION_METADATA_SID


def test_missing_invalid_and_legacy_only_inputs_remain_no_mutation_diagnostics() -> None:
    invalid = execution_flow.resolve_canonical_mst_session_identity(
        {"mst_session_id": "legacy-session"},
        {},
        invocation_class="diagnostic_invocation",
    )
    assert invalid["valid"] is False
    assert invalid["reason"] == "invalid_canonical_identity"
    assert invalid["action"] == "emit_diagnostic_no_mutation"
    assert invalid["canonical_mst_session_id"] is None

    legacy_only = execution_flow.resolve_canonical_mst_session_identity(
        {
            "session_id": LEGACY_UUID,
            "sessionId": "legacy-alias",
            "owner_ppid": 424242,
            "owner_pid": 434343,
            "owner_session_id": "owner-alias",
            "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
        },
        {"MST_STATE_PPID": "424242", "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias"},
        invocation_class="diagnostic_invocation",
    )
    assert legacy_only["valid"] is False
    assert legacy_only["reason"] == "legacy_identity_not_canonical_source"
    assert legacy_only["action"] == "emit_diagnostic_no_mutation"
    assert legacy_only["legacy_diagnostics"] == {
        "MST_STATE_PPID": "424242",
        "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
        "session_id": LEGACY_UUID,
        "sessionId": "legacy-alias",
        "owner_ppid": 424242,
        "owner_pid": 434343,
        "owner_session_id": "owner-alias",
        "hook_transcript_stem": TRANSCRIPT_UUID,
    }

    missing = execution_flow.resolve_canonical_mst_session_identity({}, {}, invocation_class="diagnostic_invocation")
    assert missing["valid"] is False
    assert missing["reason"] == "missing_canonical_identity"
    assert missing["action"] == "emit_diagnostic_no_mutation"


def test_external_invocation_legacy_only_payload_stays_read_only() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        base_dir = _base_dir(workspace)
        before = _files(base_dir)

        result = _run_mst(
            workspace,
            "session",
            "resolve",
            "--json",
            env={
                "MST_STATE_PPID": "424242",
                "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
                "MST_HOOK_STDIN_RAW": json.dumps(
                    {
                        "session_id": LEGACY_UUID,
                        "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
                    }
                ),
            },
        )

        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["valid"] is False
        assert payload["reason"] == "legacy_identity_not_canonical_source"
        assert payload["action"] == "emit_diagnostic_no_mutation"
        assert payload["invocation_class"] == "external_invocation"
        assert _files(base_dir) == before


def test_normal_entry_generation_and_skill_snapshot_converge_on_canonical_id() -> None:
    generated = execution_flow.resolve_canonical_mst_session_identity(
        {},
        {},
        invocation_class="normal_entry",
        allow_generate=True,
        root_mst_id="AGI-030",
        started_at=STARTED_AT,
    )
    assert generated["valid"] is True
    assert generated["reason"] == "generated_canonical_identity"
    assert generated["action"] == "generate_canonical_mst_session_id"
    session_id = generated["canonical_mst_session_id"]
    assert isinstance(session_id, str) and session_id.startswith("MST-AGI-030-")

    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        base_dir = _base_dir(workspace)
        created = session.create_root_session_artifacts(
            base_dir,
            "AGI-030",
            root_payload={"id": "AGI-030", "status": "active"},
            started_at=STARTED_AT,
            random_segment="k7f3q9x2",
        )
        snapshot = _skill_state.recover_agile_snapshot_from_durable_state(
            base_dir,
            "AGI-030",
            session_id=created["mst_session_id"],
        )

        assert isinstance(snapshot, dict)
        assert snapshot["mst_session_id"] == created["mst_session_id"]
        assert snapshot["sessionId"] == created["mst_session_id"]
        snapshot_path = base_dir / "state" / created["mst_session_id"] / "snapshot.json"
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert payload["mst_session_id"] == created["mst_session_id"]
        assert payload["root_mst_id"] == "AGI-030"

