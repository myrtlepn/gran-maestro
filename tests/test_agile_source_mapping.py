import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


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


def test_parse_source_mapping_valid():
    text = (
        "<!-- source-mapping: original=docs/sample.md sections=[Intro, Background, Decisions] -->\n"
        "# Domain\n"
    )
    payload = MST_MODULE.parse_source_mapping(text)

    assert payload["valid"] is True
    assert payload["original"] == "docs/sample.md"
    assert payload["sections"] == ["Intro", "Background", "Decisions"]
    assert payload["errors"] == []


def test_parse_source_mapping_missing():
    payload = MST_MODULE.parse_source_mapping("# Domain\n")

    assert payload["valid"] is False
    assert payload["original"] is None
    assert payload["sections"] == []
    assert payload["errors"]


def test_parse_source_mapping_malformed():
    text = (
        "<!-- source-mapping: original=docs/sample.md sections=[\"Intro, Decisions] -->\n"
        "# Domain\n"
    )
    payload = MST_MODULE.parse_source_mapping(text)

    assert payload["valid"] is False
    assert payload["original"] is None
    assert payload["sections"] == []
    assert payload["errors"]


def test_validate_mapping_cli_valid_json(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = tmp_path / "details-valid.md"
    details_path.write_text(
        "<!-- source-mapping: original=docs/sample.md sections=[\"Intro\", Decisions, \"QA\"] -->\n"
        "# Domain\n",
        encoding="utf-8",
    )

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-mapping",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["path"] == str(details_path)
    assert payload["valid"] is True
    assert payload["original"] == "docs/sample.md"
    assert payload["sections"] == ["Intro", "Decisions", "QA"]
    assert payload["errors"] == []


def test_validate_mapping_cli_missing_metadata_graceful(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = tmp_path / "details-missing.md"
    details_path.write_text("# Domain\n", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-mapping",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["path"] == str(details_path)
    assert payload["valid"] is False
    assert payload["errors"]
    assert "Traceback" not in proc.stderr


def test_validate_mapping_cli_file_not_found(tmp_path):
    workspace = _make_workspace(tmp_path)
    details_path = tmp_path / "nope.md"

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "validate-mapping",
        str(details_path),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["path"] == str(details_path)
    assert payload["valid"] is False
    assert payload["original"] is None
    assert payload["sections"] == []
    assert payload["errors"] == [f"file not found: {details_path}"]
    assert "Traceback" not in proc.stderr
