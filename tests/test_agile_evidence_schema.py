import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "agile-plan" / "evidence"


def _load_mst_module():
    spec = importlib.util.spec_from_file_location("mst_module", MST_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MST_MODULE = _load_mst_module()


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _fixture(name: str) -> Path:
    path = FIXTURE_ROOT / name
    assert path.is_file(), f"missing fixture: {name}"
    return path


def test_evidence_and_source_mapping_coexist():
    content = _fixture("coexist.md").read_text(encoding="utf-8")

    parsed = MST_MODULE.parse_agile_detail_metadata(content)

    assert parsed["source_mapping"]["valid"] is True
    assert parsed["source_mapping"]["original"] == "docs/spec.md"
    assert parsed["source_mapping"]["sections"] == ["Evidence", "Parser"]
    assert parsed["evidence"]["plan"]["artifact_paths"] == ["src/foo.py", "tests/test_foo.py"]
    assert parsed["evidence"]["plan"]["entrypoint_path"] == "src/foo.py:main"

    rewritten = MST_MODULE.upsert_agile_detail_evidence(content, parsed["evidence"])
    reparsed = MST_MODULE.parse_agile_detail_metadata(rewritten)

    assert rewritten.splitlines()[0] == content.splitlines()[0]
    assert reparsed["source_mapping"] == parsed["source_mapping"]
    assert reparsed["evidence"] == parsed["evidence"]


def test_validator_basic(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = _fixture("validator-basic.md")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-evidence",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["path"] == str(details_path)
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == []
    assert payload["evidence"]["plan"]["artifact_paths"] == ["src/bar.py"]
    assert payload["evidence"]["plan"]["entrypoint_path"] == "src/bar.py:run"
    assert payload["evidence"]["runtime"]["integration_smoke_id"] == "TBD"
    assert payload["evidence"]["runtime"]["verify_cmd"] == "TBD"
    assert payload["evidence"]["runtime"]["expected_signal"] == "TBD"


def test_validator_missing_entrypoint(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = _fixture("missing-entrypoint.md")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-evidence",
        str(details_path),
    )

    assert proc.returncode == 1
    assert "entrypoint_path missing" in proc.stderr
    assert "entrypoint: none" in proc.stderr


def test_entrypoint_none_exception(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = _fixture("none-exception.md")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-evidence",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["valid"] is True
    assert payload["warnings"] == []
    assert payload["errors"] == []
    assert payload["evidence"]["plan"]["entrypoint"] == "none"
    assert payload["evidence"]["plan"]["reason"] == "internal library"


def test_legacy_graceful_read(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = _fixture("legacy-no-evidence.md")

    parsed = MST_MODULE.parse_agile_detail_metadata(details_path.read_text(encoding="utf-8"))
    assert parsed["source_mapping"]["valid"] is True
    assert parsed["evidence"] == {}

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-evidence",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert "evidence fields not defined (legacy format)" in proc.stderr
    assert payload["source_mapping"]["valid"] is True


@pytest.mark.parametrize(
    "fixture_name",
    [
        "dummy-verify-true.md",
        "dummy-verify-exit0.md",
        "dummy-verify-echo.md",
    ],
)
def test_goodhart_linter_rejects_dummy(tmp_path, fixture_name):
    workspace = _make_workspace(tmp_path)
    details_path = _fixture(fixture_name)

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-evidence",
        str(details_path),
    )

    assert proc.returncode == 1
    assert "Goodhart linter: verify_cmd rejected (dummy command)" in proc.stderr
