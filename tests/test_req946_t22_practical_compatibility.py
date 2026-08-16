from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        env.pop(key, None)
    return env


def _bootstrap(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "session",
            "bootstrap",
            "--root-type",
            "dbg",
            "--json",
        ],
        cwd=workspace,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_fresh_root_bootstrap_reserves_and_persists_the_same_id(tmp_path: Path) -> None:
    result = _bootstrap(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["root_mst_id"] == "DBG-001"
    assert payload["counter_reserved_id"] == "DBG-001"
    assert payload["identity_source"] == "generated:reserved_root_type"
    assert json.loads(
        (tmp_path / ".gran-maestro" / "debug" / "counter.json").read_text(encoding="utf-8")
    ) == {"last_id": 1}
    assert (tmp_path / payload["root_artifact_path"]).is_file()
    assert (tmp_path / payload["session_metadata_path"]).is_file()


def test_existing_request_bootstrap_reuses_exact_id_without_counter_allocation(
    tmp_path: Path,
) -> None:
    request_dir = tmp_path / ".gran-maestro" / "requests" / "REQ-946"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "request.json"
    request_path.write_text(
        json.dumps({"id": "REQ-946", "status": "spec_ready"}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "session",
            "bootstrap",
            "--root-mst-id",
            "REQ-946",
            "--json",
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["root_mst_id"] == "REQ-946"
    assert payload["identity_source"] == "generated:root_mst_id"
    assert not (tmp_path / ".gran-maestro" / "requests" / "counter.json").exists()
    persisted = json.loads(request_path.read_text(encoding="utf-8"))
    assert persisted["id"] == "REQ-946"
    assert persisted["mst_session_id"] == payload["mst_session_id"]


def test_shared_bootstrap_selects_existing_id_or_new_type_explicitly() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        bootstrap = (root / "skills" / "_shared" / "session-bootstrap.md").read_text(
            encoding="utf-8"
        )
        assert 'elif [ -n "${ROOT_ID:-}" ] && [ -z "${ROOT_TYPE:-}" ]; then' in bootstrap
        assert '--root-mst-id "$ROOT_ID" --json' in bootstrap
        assert 'elif [ -z "${ROOT_ID:-}" ] && [ -n "${ROOT_TYPE:-}" ]; then' in bootstrap
        assert '--root-type "$ROOT_TYPE" --json' in bootstrap
        assert "exactly one of ROOT_ID or ROOT_TYPE is required" in bootstrap

        approve = (root / "skills" / "approve" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "existing-only entry" in approve
        assert approve.index('--root-mst-id "$ROOT_ID" --json') < approve.index(
            '--root-type "$ROOT_TYPE" --json'
        )


def test_failed_fresh_root_bootstrap_can_retry_the_same_id(tmp_path: Path) -> None:
    from scripts.mst_cmds import session

    base = tmp_path / ".gran-maestro"
    with pytest.raises(session.RootSessionCreateError, match="after_root_artifact_commit"):
        session.reserve_root_session_artifacts(
            base,
            "dbg",
            failure_stage="after_root_artifact_commit",
        )

    counter_path = base / "debug" / "counter.json"
    assert not counter_path.exists()

    outcome = session.reserve_root_session_artifacts(base, "dbg")
    assert outcome["root_mst_id"] == "DBG-001"
    assert json.loads(counter_path.read_text(encoding="utf-8")) == {"last_id": 1}


def test_modest_parallel_fresh_bootstrap_allocates_distinct_roots(tmp_path: Path) -> None:
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(MST_SCRIPT),
                "session",
                "bootstrap",
                "--root-type",
                "dbg",
                "--json",
            ],
            cwd=tmp_path,
            env=_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [process.communicate(timeout=30) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    payloads = [json.loads(stdout) for stdout, _stderr in results]
    assert {payload["root_mst_id"] for payload in payloads} == {
        "DBG-001",
        "DBG-002",
        "DBG-003",
        "DBG-004",
    }
    assert json.loads(
        (tmp_path / ".gran-maestro" / "debug" / "counter.json").read_text(encoding="utf-8")
    ) == {"last_id": 4}


def test_agile_init_reuses_the_root_reserved_by_bootstrap(tmp_path: Path) -> None:
    bootstrap = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "session",
            "bootstrap",
            "--root-type",
            "agi",
            "--json",
        ],
        cwd=tmp_path,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    identity = json.loads(bootstrap.stdout)

    env = _env()
    env["MST_SESSION_ID"] = identity["mst_session_id"]
    initialized = subprocess.run(
        [sys.executable, str(MST_SCRIPT), "agile", "init", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert initialized.returncode == 0, initialized.stderr
    payload = json.loads(initialized.stdout)
    assert payload["agi_id"] == identity["root_mst_id"] == "AGI-001"
    assert payload["mst_session_id"] == identity["mst_session_id"]
    assert json.loads(
        (tmp_path / ".gran-maestro" / "agile" / "counter.json").read_text(encoding="utf-8")
    ) == {"last_id": 1}
