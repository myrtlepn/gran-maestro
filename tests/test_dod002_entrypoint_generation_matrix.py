from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STARTED_AT = "20260503T130813382Z"
STRUCTURED_PARENT = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
LEGACY_CLAUDE_SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_TRANSCRIPT_SESSION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")


ENTRYPOINT_GENERATION_MATRIX = [
    {
        "entrypoint": "top-level root artifact creation",
        "generation": "allowed",
        "evidence": "session resolve --root-mst-id AGI-030 --started-at 20260503T130813382Z",
    },
    {
        "entrypoint": "dispatch/workflow child",
        "generation": "forbidden",
        "evidence": "dispatch register requires inherited parent MST_SESSION_ID env",
    },
    {
        "entrypoint": "missing-context mutation path",
        "generation": "forbidden",
        "evidence": "state set-workflow requires inherited structured MST_SESSION_ID",
    },
]


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
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
        env=_env(env),
        check=False,
        timeout=30,
    )


def _read_non_success_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["created_new_session"] is False
    assert payload["canonical_mst_session_id"] is None
    return payload


def test_entrypoint_generation_matrix_has_required_allowed_and_forbidden_rows() -> None:
    allowed = [row for row in ENTRYPOINT_GENERATION_MATRIX if row["generation"] == "allowed"]
    child_forbidden = [
        row
        for row in ENTRYPOINT_GENERATION_MATRIX
        if row["generation"] == "forbidden" and "child" in row["entrypoint"]
    ]
    mutation_forbidden = [
        row
        for row in ENTRYPOINT_GENERATION_MATRIX
        if row["generation"] == "forbidden" and "mutation" in row["entrypoint"]
    ]

    assert allowed
    assert child_forbidden
    assert mutation_forbidden
    assert all(row["evidence"] for row in ENTRYPOINT_GENERATION_MATRIX)


def test_root_entrypoint_generation_allowed_with_explicit_root_context() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        result = _run_mst(
            workspace,
            "session",
            "resolve",
            "--json",
            "--root-mst-id",
            "AGI-030",
            "--started-at",
            STARTED_AT,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["source"] == "generated:root_mst_id"
        assert payload["mst_session_id"] == payload["session_id"]
        assert payload["mst_session_id"].startswith(f"MST-AGI-030-{STARTED_AT}-")
        assert UUID_V4_RE.search(payload["mst_session_id"]) is None


def test_child_entrypoint_generation_forbidden_without_parent_env() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "REQ-805-child",
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            env={"MST_CONTEXT_JSON": json.dumps({"mst_session_id": STRUCTURED_PARENT})},
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        payload = _read_non_success_payload(result)
        assert payload["code"] == "missing_canonical_mst_session_id"
        assert "REQ-805-child" not in combined
        assert not UUID_V4_RE.search(combined)
        assert _files(workspace) == before


def test_missing_context_mutation_generation_forbidden_without_legacy_fallback() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--next-skill",
            "mst:approve",
            env={
                "MST_HOOK_STDIN_RAW": json.dumps(
                    {
                        "session_id": LEGACY_CLAUDE_SESSION,
                        "transcript_path": f"/tmp/{LEGACY_TRANSCRIPT_SESSION}.jsonl",
                    }
                ),
                "MST_STATE_PPID": "818181",
            },
        )

        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0
        payload = _read_non_success_payload(result)
        assert payload["code"] == "legacy_identity_not_canonical_source"
        diagnostics = payload["legacy_diagnostics"]
        assert diagnostics["MST_STATE_PPID"] == "818181"
        assert diagnostics["hook_session_id"] == LEGACY_CLAUDE_SESSION
        assert diagnostics["hook_transcript_stem"] == LEGACY_TRANSCRIPT_SESSION
        assert "generated" not in combined
        assert _files(workspace) == before


def main() -> int:
    tests = [
        test_entrypoint_generation_matrix_has_required_allowed_and_forbidden_rows,
        test_root_entrypoint_generation_allowed_with_explicit_root_context,
        test_child_entrypoint_generation_forbidden_without_parent_env,
        test_missing_context_mutation_generation_forbidden_without_legacy_fallback,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
