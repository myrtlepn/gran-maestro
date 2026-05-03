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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import session


STARTED_AT = datetime(2026, 5, 3, 13, 8, 13, 382000, tzinfo=timezone.utc)
MST_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _base_dir(workspace: Path) -> Path:
    base_dir = workspace / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


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


def _create_root_session(base_dir: Path) -> dict:
    return session.create_root_session_artifacts(
        base_dir,
        "AGI-030",
        root_payload={"id": "AGI-030", "status": "active"},
        started_at=STARTED_AT,
        random_segment="k7f3q9x2",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _files(base_dir: Path) -> dict[str, str]:
    if not base_dir.exists():
        return {}
    return {
        str(path.relative_to(base_dir)): path.read_text(encoding="utf-8")
        for path in base_dir.rglob("*")
        if path.is_file()
    }


def test_state_session_history_path_keys_and_payloads_use_full_structured_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        base_dir = _base_dir(workspace)
        created = _create_root_session(base_dir)

        state_result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "3",
            env={"MST_SESSION_ID": MST_SESSION_ID},
        )

        assert state_result.returncode == 0, state_result.stderr
        state_path = base_dir / "state" / MST_SESSION_ID / "snapshot.json"
        assert state_path.exists()
        assert _read_json(state_path)["mst_session_id"] == MST_SESSION_ID

        session_path = created["session_metadata_path"]
        assert session_path == base_dir / "sessions" / MST_SESSION_ID / "session.json"
        assert _read_json(session_path)["mst_session_id"] == MST_SESSION_ID

        history_path = session.write_session_history_event(
            base_dir,
            MST_SESSION_ID,
            {"event_type": "metadata-consistency-fixture"},
        )
        assert history_path == base_dir / "sessions" / MST_SESSION_ID / "history.ndjson"
        history_row = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
        assert history_row["mst_session_id"] == MST_SESSION_ID


def test_root_start_random_mismatch_blocks_mutation_without_changes() -> None:
    mismatch_cases = [
        ("root_mst_id", "REQ-805"),
        ("started_at", "2026-05-03T13:18:53.000Z"),
        ("random", "r4n8vd1c"),
    ]
    for key, value in mismatch_cases:
        with _workspace() as raw_workspace:
            workspace = Path(raw_workspace)
            base_dir = _base_dir(workspace)
            created = _create_root_session(base_dir)
            root_path = created["root_artifact_path"]
            root_payload = _read_json(root_path)
            root_payload[key] = value
            root_path.write_text(json.dumps(root_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = _files(base_dir)

            state_result = _run_mst(
                workspace,
                "state",
                "set",
                "--skill",
                "mst:request",
                "--step",
                "1",
                "--total",
                "3",
                env={"MST_SESSION_ID": MST_SESSION_ID},
            )

            assert state_result.returncode != 0
            assert "metadata mismatch" in f"{state_result.stdout}\n{state_result.stderr}"
            assert _files(base_dir) == before


def main() -> int:
    tests = [
        test_state_session_history_path_keys_and_payloads_use_full_structured_id,
        test_root_start_random_mismatch_blocks_mutation_without_changes,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
