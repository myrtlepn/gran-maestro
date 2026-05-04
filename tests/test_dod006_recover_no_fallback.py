from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
ROOT = "AGI-030"
LEGACY_PPID = "818181"
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _legacy_only_env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        env.pop(key, None)
    env["MST_STATE_PPID"] = LEGACY_PPID
    env["MST_SNAPSHOT_SESSION_ID"] = "legacy-snapshot-alias"
    env["MST_HOOK_STDIN_RAW"] = json.dumps(
        {
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "legacy-owner-session",
            "sessionId": "legacy-sessionId-alias",
        },
        separators=(",", ":"),
    )
    return env


def _run_recover(workspace: Path, policy_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "recover", ROOT],
        cwd=workspace,
        env=_legacy_only_env(policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _read_json_from_stdout(stdout: str) -> dict:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(lines[index:]))
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _seed_legacy_only_fixture(workspace: Path) -> None:
    base = workspace / ".gran-maestro"
    _write_json(
        base / "agile" / ROOT / "session.json",
        {
            "id": ROOT,
            "status": "executing",
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "legacy-owner-session",
            "session_id": CLAUDE_SESSION_ID,
            "sessionId": "legacy-sessionId-alias",
        },
    )
    _write_json(
        base / "state" / LEGACY_PPID / "snapshot.json",
        {
            "sessionId": LEGACY_PPID,
            "owner_ppid": int(LEGACY_PPID),
            "owner_session_id": "legacy-owner-session",
            "currentSkill": "mst:request",
            "status": "active",
        },
    )
    _write_json(
        base / "state" / "legacy-snapshot-alias" / "snapshot.json",
        {"sessionId": "legacy-snapshot-alias", "currentSkill": "mst:recover", "status": "active"},
    )


def test_legacy_only_recover_input_is_no_mutation_structured_non_success() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_legacy_only_fixture(workspace)
        before = _hashes(workspace)

        result = _run_recover(workspace, policy_home)

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        assert _hashes(workspace) == before
        payload = _read_json_from_stdout(result.stdout)
        assert payload["status"] in {"error", "blocked", "non_success"}
        assert payload["code"] in {"missing_canonical_mst_session_id", "legacy_identity_not_canonical_source"}
        assert payload.get("created_new_session") is not True
        assert payload.get("canonical_mst_session_id") in (None, "")
        assert payload.get("legacy_diagnostics")
        assert not UUID_V4_RE.search(str(payload.get("canonical_mst_session_id", "")))
        assert CLAUDE_SESSION_ID not in str(payload.get("canonical_mst_session_id", ""))
        assert TRANSCRIPT_SESSION_ID not in str(payload.get("canonical_mst_session_id", ""))
        assert "MST-AGI-030" not in combined
        assert not (workspace / ".gran-maestro" / "sessions").exists()
        assert not (policy_home / "ledger-heads").exists()


def main() -> int:
    test_legacy_only_recover_input_is_no_mutation_structured_non_success()
    print("PASS test_legacy_only_recover_input_is_no_mutation_structured_non_success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
