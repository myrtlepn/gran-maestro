from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import session


STARTED_AT = datetime(2026, 5, 3, 13, 8, 13, 382000, tzinfo=timezone.utc)
STARTED_AT_ISO = "2026-05-03T13:08:13.382Z"
MST_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _base_dir(workspace: Path) -> Path:
    base_dir = workspace / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _files(base_dir: Path) -> set[str]:
    if not base_dir.exists():
        return set()
    return {str(path.relative_to(base_dir)) for path in base_dir.rglob("*") if path.is_file()}


def _assert_no_orphans(base_dir: Path) -> None:
    assert not (base_dir / "agile" / "AGI-030" / "session.json").exists()
    assert not (base_dir / "sessions" / MST_SESSION_ID / "session.json").exists()
    assert _files(base_dir) == set()


def test_root_creation_success_records_equal_root_and_session_metadata() -> None:
    with _workspace() as raw_workspace:
        base_dir = _base_dir(Path(raw_workspace))

        result = session.create_root_session_artifacts(
            base_dir,
            "AGI-030",
            root_payload={"id": "AGI-030", "status": "active"},
            started_at=STARTED_AT,
            random_segment="k7f3q9x2",
        )

        assert result["mst_session_id"] == MST_SESSION_ID
        root_payload = session.load_json_object(result["root_artifact_path"])
        session_payload = session.load_json_object(result["session_metadata_path"])
        expected = {
            "mst_session_id": MST_SESSION_ID,
            "root_mst_id": "AGI-030",
            "started_at": STARTED_AT_ISO,
            "random": "k7f3q9x2",
        }
        for payload in (root_payload, session_payload):
            assert payload is not None
            for key, value in expected.items():
                assert payload[key] == value
        assert root_payload["mst_session_id"] == session_payload["mst_session_id"]
        assert session_payload["root_artifact_path"] == "agile/AGI-030/session.json"


def test_root_artifact_commit_failure_rolls_back_root_and_session_metadata() -> None:
    with _workspace() as raw_workspace:
        base_dir = _base_dir(Path(raw_workspace))

        try:
            session.create_root_session_artifacts(
                base_dir,
                "AGI-030",
                root_payload={"id": "AGI-030"},
                started_at=STARTED_AT,
                random_segment="k7f3q9x2",
                failure_stage="after_root_artifact_commit",
            )
        except session.RootSessionCreateError as exc:
            assert "after_root_artifact_commit" in str(exc)
        else:
            raise AssertionError("injected root artifact failure did not fail")

        _assert_no_orphans(base_dir)


def test_session_metadata_commit_failure_rolls_back_session_and_root_metadata() -> None:
    with _workspace() as raw_workspace:
        base_dir = _base_dir(Path(raw_workspace))

        try:
            session.create_root_session_artifacts(
                base_dir,
                "AGI-030",
                root_payload={"id": "AGI-030"},
                started_at=STARTED_AT,
                random_segment="k7f3q9x2",
                commit_order="session-first",
                failure_stage="after_session_metadata_commit",
            )
        except session.RootSessionCreateError as exc:
            assert "after_session_metadata_commit" in str(exc)
        else:
            raise AssertionError("injected session metadata failure did not fail")

        _assert_no_orphans(base_dir)


def main() -> int:
    tests = [
        test_root_creation_success_records_equal_root_and_session_metadata,
        test_root_artifact_commit_failure_rolls_back_root_and_session_metadata,
        test_session_metadata_commit_failure_rolls_back_session_and_root_metadata,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
