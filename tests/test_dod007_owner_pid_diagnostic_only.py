from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds.agile import _diagnose_history_lock


SID = "MST-AGI-030-20260504T170000000Z-dod007p1"
OWNER_PID = 987654321
ZERO_HASH = "0" * 64
STALE_SECONDS = 3600


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _write_history_scope(workspace: Path, *, owner: dict[str, Any]) -> tuple[Path, Path, Path]:
    project_root = workspace / "project"
    home = workspace / "home"
    session_dir = project_root / ".gran-maestro" / "sessions" / SID
    mirror_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
    session_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "history.ndjson").write_text("", encoding="utf-8")
    (session_dir / "history.head").write_text(ZERO_HASH + "\n", encoding="utf-8")
    (session_dir / "history.lock").mkdir()
    (session_dir / "history.lock" / "owner.json").write_text(json.dumps(owner, sort_keys=True) + "\n", encoding="utf-8")
    (mirror_dir / f"{SID}.head").write_text(ZERO_HASH + "\n", encoding="utf-8")
    old = time.time() - STALE_SECONDS - 30
    os.utime(session_dir / "history.lock", (old, old))
    os.utime(session_dir / "history.lock" / "owner.json", (old, old))
    return project_root, home, session_dir / "history.lock"


def test_owner_pid_is_lock_liveness_diagnostic_not_session_identity_source() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        project_root, home, lock_path = _write_history_scope(
            workspace,
            owner={
                "owner_pid": OWNER_PID,
                "owner_started_at": time.time() - STALE_SECONDS - 30,
                "session_id": "legacy-owner-session-id",
                "owner_session_id": "legacy-owner-session-id",
            },
        )
        before = _snapshot(project_root, home)

        payload = _diagnose_history_lock(
            project_root=project_root,
            home=home,
            session_id=SID,
            lock_path=lock_path,
            stale_after_sec=STALE_SECONDS,
        )

        assert _snapshot(project_root, home) == before
        assert payload["category"] in {"history-lock-stale-candidate", "owner-live", "diagnosis-inconclusive", "owner-unknown"}
        assert payload["next_action"] in {"manual-recovery-approval", "wait-for-owner", "inspect-lock-owner"}
        assert str(lock_path) == payload.get("lock_path")
        assert not (project_root / ".gran-maestro" / "sessions" / str(OWNER_PID)).exists()
        assert not (project_root / ".gran-maestro" / "sessions" / "legacy-owner-session-id").exists()
        assert not (home / ".claude" / "gran-maestro-policy" / "ledger-heads" / f"{OWNER_PID}.head").exists()
        assert not (home / ".claude" / "gran-maestro-policy" / "ledger-heads" / "legacy-owner-session-id.head").exists()
        assert lock_path.exists()


def main() -> int:
    test_owner_pid_is_lock_liveness_diagnostic_not_session_identity_source()
    print("PASS test_owner_pid_is_lock_liveness_diagnostic_not_session_identity_source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
