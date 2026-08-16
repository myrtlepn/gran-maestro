from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SKILLS = ("debug", "ideation", "discussion", "explore", "plan", "plan-doc", "request")
CANONICAL_FIELDS = (
    "mst_session_id",
    "root_mst_id",
    "started_at",
    "started_at_compact",
    "random",
)
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _skill(root: Path, name: str) -> str:
    return (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_root_template_writes_merge_bootstrap_metadata() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for name in ROOT_SKILLS:
            text = _skill(root, name)
            assert "Canonical Root Metadata Merge (MANDATORY)" in text, (root, name)
            assert "replace/overwrite하지 않고 object merge" in text, (root, name)
            assert "identity를 재발급하지 않는다" in text, (root, name)
            for field in CANONICAL_FIELDS:
                assert f"`{field}`" in text, (root, name, field)


def test_source_and_projection_share_identical_bootstrap_contract() -> None:
    source = (REPO_ROOT / "skills" / "_shared" / "session-bootstrap.md").read_text(
        encoding="utf-8"
    )
    projected = (
        REPO_ROOT / "plugins" / "mst" / "skills" / "_shared" / "session-bootstrap.md"
    ).read_text(encoding="utf-8")
    assert projected == source


def test_root_workflow_merge_does_not_reissue_bootstrap_identity() -> None:
    with tempfile.TemporaryDirectory() as raw_workspace:
        workspace = Path(raw_workspace)
        (workspace / ".gran-maestro").mkdir()
        env = os.environ.copy()
        env["MST_FLOW_DISABLE_ATEXIT"] = "1"
        for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
            env.pop(key, None)

        first = subprocess.run(
            [
                sys.executable,
                str(MST_SCRIPT),
                "session",
                "bootstrap",
                "--root-mst-id",
                "REQ-946",
                "--json",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert first.returncode == 0, first.stderr
        identity = json.loads(first.stdout)
        root_path = workspace / ".gran-maestro" / "requests" / "REQ-946" / "request.json"
        root_payload = json.loads(root_path.read_text(encoding="utf-8"))
        canonical = {field: root_payload[field] for field in CANONICAL_FIELDS}

        # This is the merge operation mandated for every root skill template.
        root_payload.update({"title": "O'Reilly $(touch should-not-run)", "status": "phase1_analysis"})
        root_path.write_text(
            json.dumps(root_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        resumed_env = dict(env)
        resumed_env["MST_SESSION_ID"] = identity["mst_session_id"]
        second = subprocess.run(
            [
                sys.executable,
                str(MST_SCRIPT),
                "session",
                "bootstrap",
                "--root-mst-id",
                "REQ-946",
                "--json",
            ],
            cwd=workspace,
            env=resumed_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert second.returncode == 0, second.stderr
        assert json.loads(second.stdout)["mst_session_id"] == identity["mst_session_id"]
        merged = json.loads(root_path.read_text(encoding="utf-8"))
        assert {field: merged[field] for field in CANONICAL_FIELDS} == canonical
