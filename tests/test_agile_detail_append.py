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


def test_agile_detail_append_chunk1_create(tmp_path):
    workspace = _make_workspace(tmp_path)
    target_dir = tmp_path / "details"
    content_file = tmp_path / "chunk1.md"
    content = (
        "<!-- source-mapping: original=src.md sections=[\"Intro\"] -->\n"
        "# Demo\n\n"
        "## Intro\n"
        "첫 번째 청크."
    )
    content_file.write_text(content, encoding="utf-8")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "1",
        "--content-file",
        str(content_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    target_path = target_dir / "demo.md"
    assert proc.returncode == 0
    assert payload == {
        "target_path": str(target_path),
        "chunk_id": 1,
        "action": "created",
        "valid": True,
        "errors": [],
    }
    assert target_path.read_text(encoding="utf-8") == f"{content}\n<!-- chunk:1 -->\n"


def test_agile_detail_append_chunk2_append(tmp_path):
    workspace = _make_workspace(tmp_path)
    target_dir = tmp_path / "details"
    chunk1_file = tmp_path / "chunk1.md"
    chunk2_file = tmp_path / "chunk2.md"
    chunk1 = "# Demo\n\n## Intro\n첫 번째 청크."
    chunk2 = "## Scope\n두 번째 청크."
    chunk1_file.write_text(chunk1, encoding="utf-8")
    chunk2_file.write_text(chunk2, encoding="utf-8")

    create_proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "1",
        "--content-file",
        str(chunk1_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    assert create_proc.returncode == 0

    append_proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "2",
        "--content-file",
        str(chunk2_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    payload = json.loads(append_proc.stdout)

    target_path = target_dir / "demo.md"
    assert append_proc.returncode == 0
    assert payload["target_path"] == str(target_path)
    assert payload["chunk_id"] == 2
    assert payload["action"] == "appended"
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert target_path.read_text(encoding="utf-8") == (
        f"{chunk1}\n<!-- chunk:1 -->\n\n{chunk2}\n<!-- chunk:2 -->\n"
    )


def test_agile_detail_append_chunk2_idempotent_replace(tmp_path):
    workspace = _make_workspace(tmp_path)
    target_dir = tmp_path / "details"
    chunk1_file = tmp_path / "chunk1.md"
    chunk2_file = tmp_path / "chunk2.md"
    chunk2_v2_file = tmp_path / "chunk2_v2.md"
    chunk1 = "# Demo\n\n## Intro\n첫 번째 청크."
    chunk2 = "## Scope\n두 번째 청크."
    chunk2_v2 = "## Scope\n두 번째 청크(수정)."
    chunk1_file.write_text(chunk1, encoding="utf-8")
    chunk2_file.write_text(chunk2, encoding="utf-8")
    chunk2_v2_file.write_text(chunk2_v2, encoding="utf-8")

    _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "1",
        "--content-file",
        str(chunk1_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "2",
        "--content-file",
        str(chunk2_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )

    replace_proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "2",
        "--content-file",
        str(chunk2_v2_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    payload = json.loads(replace_proc.stdout)

    target_path = target_dir / "demo.md"
    assert replace_proc.returncode == 0
    assert payload["action"] == "replaced"
    assert target_path.read_text(encoding="utf-8") == (
        f"{chunk1}\n<!-- chunk:1 -->\n\n{chunk2_v2}\n<!-- chunk:2 -->\n"
    )


def test_agile_detail_append_target_dir_default_current_directory(tmp_path):
    workspace = _make_workspace(tmp_path)
    content_file = tmp_path / "chunk1.md"
    content = "# Demo\n\n## Intro\n기본 디렉토리 케이스"
    content_file.write_text(content, encoding="utf-8")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo-default",
        "--chunk-id",
        "1",
        "--content-file",
        str(content_file),
        "--json",
    )
    payload = json.loads(proc.stdout)

    target_path = workspace / "demo-default.md"
    assert proc.returncode == 0
    assert payload == {
        "target_path": str(target_path),
        "chunk_id": 1,
        "action": "created",
        "valid": True,
        "errors": [],
    }
    assert target_path.read_text(encoding="utf-8") == f"{content}\n<!-- chunk:1 -->\n"


def test_agile_detail_append_content_file_missing_graceful(tmp_path):
    workspace = _make_workspace(tmp_path)
    target_dir = tmp_path / "details"
    content_file = tmp_path / "missing.md"

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "1",
        "--content-file",
        str(content_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["target_path"] == str(target_dir / "demo.md")
    assert payload["chunk_id"] == 1
    assert payload["valid"] is False
    assert payload["errors"] == [f"content-file not found: {content_file}"]
    assert "Traceback" not in proc.stderr


def test_agile_detail_append_chunk2_requires_existing_target(tmp_path):
    workspace = _make_workspace(tmp_path)
    target_dir = tmp_path / "details"
    content_file = tmp_path / "chunk2.md"
    content_file.write_text("## Scope\n두 번째 청크.", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "agile",
        "detail",
        "append",
        "--domain",
        "demo",
        "--chunk-id",
        "2",
        "--content-file",
        str(content_file),
        "--target-dir",
        str(target_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["target_path"] == str(target_dir / "demo.md")
    assert payload["chunk_id"] == 2
    assert payload["valid"] is False
    assert payload["errors"] == ["target not found, run chunk-id=1 first"]
    assert "Traceback" not in proc.stderr


def test_apply_chunk_append_helper_direct_import(tmp_path):
    target_path = tmp_path / "demo.md"
    chunk1 = "# Demo\n\n## Intro\n첫 번째 청크."
    chunk2 = "## Scope\n두 번째 청크."
    chunk2_v2 = "## Scope\n두 번째 청크(수정)."

    result1 = MST_MODULE.apply_chunk_append(target_path, 1, chunk1)
    result2 = MST_MODULE.apply_chunk_append(target_path, 2, chunk2)
    result3 = MST_MODULE.apply_chunk_append(target_path, 2, chunk2_v2)

    assert result1["action"] == "created"
    assert result1["valid"] is True
    assert result2["action"] == "appended"
    assert result2["valid"] is True
    assert result3["action"] == "replaced"
    assert result3["valid"] is True
    assert target_path.read_text(encoding="utf-8") == (
        f"{chunk1}\n<!-- chunk:1 -->\n\n{chunk2_v2}\n<!-- chunk:2 -->\n"
    )
