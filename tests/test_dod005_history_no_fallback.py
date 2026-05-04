from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
VALID_MISSING = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
LEGACY_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _clean_env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["CLAUDE_CODE_SESSION_ID"] = LEGACY_UUID
    env["MST_STATE_PPID"] = "424242"
    return env


def _run(workspace: Path, policy_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_clean_env(policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _snapshot(*roots: Path) -> dict[str, str]:
    result = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_history_commands_fail_closed_for_invalid_and_legacy_inputs() -> None:
    invalid_values = [
        "../../x",
        "/tmp/mst-session",
        "MST-AGI-030-20260503T130813382Z-k7f3q9x2;touch-x",
        "MST-AGI-030-20260503T130813382Z-short",
        LEGACY_UUID,
    ]
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        base = workspace / ".gran-maestro"
        base.mkdir()
        sentinel = base / "sentinel.txt"
        sentinel.write_text("unchanged\n", encoding="utf-8")
        policy_home.mkdir()

        for value in invalid_values:
            before = _snapshot(base, policy_home)
            for command in ("log", "verify", "head"):
                result = _run(workspace, policy_home, "history", command, "--session", value, "--json")
                assert result.returncode != 0
                payload = json.loads(result.stdout)
                assert payload["status"] == "error"
                assert payload["code"] == "invalid_mst_session_id"
                assert _snapshot(base, policy_home) == before


def test_history_commands_do_not_fallback_or_create_missing_session() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        base = workspace / ".gran-maestro"
        base.mkdir()
        policy_home.mkdir()
        before = _snapshot(base, policy_home)

        for command in ("log", "verify", "head"):
            result = _run(workspace, policy_home, "history", command, "--session", VALID_MISSING, "--json")
            assert result.returncode != 0
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == "history_session_missing"
            assert _snapshot(base, policy_home) == before
            assert not (base / "sessions").exists()


def main() -> int:
    for test in (
        test_history_commands_fail_closed_for_invalid_and_legacy_inputs,
        test_history_commands_do_not_fallback_or_create_missing_session,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
