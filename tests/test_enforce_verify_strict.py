from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SAMPLE_TREE = REPO_ROOT / "hooks" / "enforce-tree.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "enforce_tree"


def _run_verify(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/mst.py", "enforce", "verify", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def _run_verify_json(*args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    proc = _run_verify(*args, "--strict", "--json")
    return proc, json.loads(proc.stdout)


def _load_sample() -> dict:
    return json.loads(SAMPLE_TREE.read_text(encoding="utf-8"))


def test_normal_pass_deterministic() -> None:
    outputs = {
        _run_verify("--tree", str(SAMPLE_TREE), "--strict", "--json").stdout
        for _ in range(10)
    }

    assert len(outputs) == 1


def test_schema_top_level_shape() -> None:
    tree = _load_sample()

    assert set(tree) == {"version", "schema_version", "skills", "global_rules"}
    assert tree["version"] == 1
    assert tree["schema_version"] == "enforce-tree-v1"
    assert isinstance(tree["skills"], dict)
    assert isinstance(tree["global_rules"], dict)


def test_step_required_fields() -> None:
    tree = _load_sample()
    step = tree["skills"]["mst:plan"]["steps"][0]

    for field in (
        "id",
        "name",
        "required",
        "path_whitelist",
        "allowed_sub_skills",
        "idempotent",
    ):
        assert field in step


def test_cycle_detection() -> None:
    proc, payload = _run_verify_json("--tree", str(FIXTURES / "cycle.json"))

    assert proc.returncode == 2
    assert payload["graph_dag"] is False
    assert any("cycle" in error for error in payload["errors"])


def test_unreachable_steps() -> None:
    proc, payload = _run_verify_json("--tree", str(FIXTURES / "unreachable.json"))

    assert proc.returncode == 2
    assert payload["graph_reachable"] is False
    assert any("unreachable" in error for error in payload["errors"])


def test_isolated_nodes() -> None:
    proc, payload = _run_verify_json("--tree", str(FIXTURES / "isolated.json"))

    assert proc.returncode == 2
    assert payload["graph_isolated_nodes"]


def test_idempotent_missing_or_bad() -> None:
    for fixture in ("missing_idempotent.json", "bad_idempotent.json"):
        proc, payload = _run_verify_json("--tree", str(FIXTURES / fixture))

        assert proc.returncode == 2
        assert payload["idempotent_missing_steps"]


def test_sample_passes() -> None:
    proc, payload = _run_verify_json("--tree", str(SAMPLE_TREE))

    assert proc.returncode == 0
    assert payload["errors"] == []
    assert payload["graph_dag"] is True
    assert payload["graph_reachable"] is True
    assert payload["graph_isolated_nodes"] == []
    assert payload["idempotent_missing_steps"] == []


def test_module_structure() -> None:
    from scripts.mst_cmds import enforce

    assert hasattr(enforce, "register")


def test_placeholder_passthrough() -> None:
    tree = _load_sample()
    whitelists = [
        path
        for step in tree["skills"]["mst:plan"]["steps"]
        for path in step["path_whitelist"]
    ]

    assert any("{PROJECT_ROOT}" in path for path in whitelists)

    proc, payload = _run_verify_json("--tree", str(SAMPLE_TREE))

    assert proc.returncode == 0
    assert payload["errors"] == []
    assert payload["graph_dag"] is True
    assert payload["graph_reachable"] is True
    assert payload["graph_isolated_nodes"] == []
