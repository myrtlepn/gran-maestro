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
STARTED_AT_COMPACT = "20260503T130813382Z"
RANDOM = "k7f3q9x2"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import session


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


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


def test_generator_parser_round_trip_preserves_hyphen_root() -> None:
    mst_session_id = session.generate_mst_session_id(
        "AGI-030",
        started_at=STARTED_AT,
        random_segment=RANDOM,
    )

    assert mst_session_id == f"MST-AGI-030-{STARTED_AT_COMPACT}-{RANDOM}"
    parsed = session.parse_mst_session_id(mst_session_id)
    assert parsed.root_mst_id == "AGI-030"
    assert parsed.started_at == STARTED_AT
    assert parsed.started_at_compact == STARTED_AT_COMPACT
    assert parsed.random == RANDOM


def test_parser_uses_right_split_for_allowed_hyphen_namespaces() -> None:
    for root_mst_id in ("PLN-632", "REQ-805", "INTENT-295"):
        mst_session_id = f"MST-{root_mst_id}-{STARTED_AT_COMPACT}-{RANDOM}"
        parsed = session.validate_mst_session_id(mst_session_id)
        assert parsed.root_mst_id == root_mst_id
        assert parsed.started_at == STARTED_AT
        assert parsed.random == RANDOM


def test_validator_rejects_malformed_matrix_without_normalizing() -> None:
    malformed = [
        "AGI-030-20260503T130813382Z-k7f3q9x2",
        "MST-BAD-030-20260503T130813382Z-k7f3q9x2",
        "MST-AGI-030-20260503T130813Z-k7f3q9x2",
        "MST-AGI-030-20260503T130813382+0000-k7f3q9x2",
        "MST-AGI-030-20260503T130813382Z-k7f3",
        "MST-AGI-030-20260503T130813382Z-k7F3q9x2",
        "MST-AGI-030-20260503T130813382Z-../evil",
        " MST-AGI-030-20260503T130813382Z-k7f3q9x2",
    ]

    for value in malformed:
        try:
            session.validate_mst_session_id(value)
        except session.MstSessionIdValidationError:
            pass
        else:
            raise AssertionError(f"malformed mst_session_id passed validation: {value!r}")


def test_validator_is_mutation_free() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        sentinel = workspace / ".gran-maestro" / "tmp" / "sentinel.txt"
        sentinel.write_text("unchanged\n", encoding="utf-8")
        before = _files(workspace)

        try:
            session.validate_mst_session_id("MST-AGI-030-20260503T130813382Z-../evil")
        except session.MstSessionIdValidationError:
            pass

        assert _files(workspace) == before
        assert sentinel.read_text(encoding="utf-8") == "unchanged\n"


def test_session_resolve_json_alias_matches_structured_mst_session_id() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        result = _run_mst(
            workspace,
            "session",
            "resolve",
            "--json",
            "--root-mst-id",
            "REQ-805",
            "--started-at",
            STARTED_AT_COMPACT,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mst_session_id"] == payload["session_id"]
        parsed = session.validate_mst_session_id(payload["mst_session_id"])
        assert parsed.root_mst_id == "REQ-805"
        assert parsed.started_at == STARTED_AT
        assert payload["source"] == "generated:root_mst_id"


def main() -> int:
    tests = [
        test_generator_parser_round_trip_preserves_hyphen_root,
        test_parser_uses_right_split_for_allowed_hyphen_namespaces,
        test_validator_rejects_malformed_matrix_without_normalizing,
        test_validator_is_mutation_free,
        test_session_resolve_json_alias_matches_structured_mst_session_id,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
