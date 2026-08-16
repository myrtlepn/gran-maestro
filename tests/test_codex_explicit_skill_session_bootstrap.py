from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
UUID_V4_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
MST_SESSION_RE = re.compile(r"^MST-DBG-999-\d{8}T\d{9}Z-[a-z0-9]{8,}$")

def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()

def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro").mkdir(parents=True, exist_ok=True)

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

def test_explicit_root_bootstrap_in_clean_env() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        # 1. clean env에서 session bootstrap 실행
        result = _run_mst(
            workspace,
            "session",
            "bootstrap",
            "--root-mst-id",
            "DBG-999",
            "--json",
        )

        # 2. 실행 성공 여부 검증 (구현 완료 시 통과해야 하는 조건)
        assert result.returncode == 0, f"bootstrap failed: {result.stderr}\nstdout: {result.stdout}"

        payload = json.loads(result.stdout)
        mst_session_id = payload.get("mst_session_id")

        # 3. durable MST-DBG-999-{timestamp}-{random} 형식 검증
        assert mst_session_id is not None
        assert MST_SESSION_RE.match(mst_session_id)
        assert UUID_V4_RE.search(mst_session_id) is None

        # 4. root 및 session metadata에 일치하게 기록되는지 검증
        root_metadata_path = workspace / ".gran-maestro" / "debug" / "DBG-999" / "session.json"
        session_metadata_path = workspace / ".gran-maestro" / "sessions" / mst_session_id / "session.json"

        assert root_metadata_path.exists(), "root metadata file not created"
        assert session_metadata_path.exists(), "session metadata file not created"

        root_data = json.loads(root_metadata_path.read_text(encoding="utf-8"))
        session_data = json.loads(session_metadata_path.read_text(encoding="utf-8"))

        assert root_data.get("mst_session_id") == mst_session_id
        assert session_data.get("mst_session_id") == mst_session_id
        assert root_data.get("id") == "DBG-999"

        # 5. 기존에 이미 canonical env가 존재하는 상황에서의 멱등성(idempotency)/상속성 검증
        result_re = _run_mst(
            workspace,
            "session",
            "bootstrap",
            "--root-mst-id",
            "DBG-999",
            "--json",
            env={"MST_SESSION_ID": mst_session_id}
        )
        assert result_re.returncode == 0, f"bootstrap with existing session failed: {result_re.stderr}"
        payload_re = json.loads(result_re.stdout)
        assert payload_re.get("mst_session_id") == mst_session_id


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, capture_output=True, check=True)
    readme = path / "README.md"
    readme.write_text("initial", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, capture_output=True, check=True)


def test_bootstrap_followed_by_ensure_worktree_regression() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_git_repo(workspace)
        _init_workspace(workspace)

        # 1. session bootstrap 실행
        boot_res = _run_mst(
            workspace,
            "session",
            "bootstrap",
            "--root-mst-id",
            "DBG-999",
            "--json",
        )
        assert boot_res.returncode == 0, f"bootstrap failed: {boot_res.stderr}"
        boot_payload = json.loads(boot_res.stdout)
        mst_session_id = boot_payload["mst_session_id"]

        # 2. session ensure-worktree 실행
        wt_res = _run_mst(
            workspace,
            "session",
            "ensure-worktree",
            "--json",
            env={"MST_SESSION_ID": mst_session_id}
        )
        assert wt_res.returncode == 0, f"ensure-worktree failed: {wt_res.stderr}\nstdout: {wt_res.stdout}"
        wt_payload = json.loads(wt_res.stdout)

        # 3. 결과 상태 검증
        assert wt_payload.get("state") == "active"
        assert wt_payload.get("outcome") == "created"

        wt_path = Path(wt_payload["session_worktree_path"])
        assert wt_path.exists()
        assert (wt_path / ".git").exists() or (wt_path / ".git").is_file()


def test_parent_session_resolve_reports_root_without_reissuance() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        parent_session_id = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"

        result = _run_mst(
            workspace,
            "session",
            "resolve",
            "--json",
            env={"MST_SESSION_ID": parent_session_id},
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mst_session_id"] == parent_session_id
        assert payload["root_mst_id"] == "AGI-030"
        assert payload["source"] == "env:MST_SESSION_ID"
        assert not (workspace / ".gran-maestro" / "sessions").exists()
