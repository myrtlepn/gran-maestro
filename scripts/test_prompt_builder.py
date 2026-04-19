import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import mst


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro" / "tmp").mkdir(parents=True)
    return workspace


def _valid_payload() -> dict:
    return {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
            "topic": "Dispatch prompt builder",
            "constraints": ["Keep the answer grounded", "Return concrete risks"],
            "reference_context_file": ".gran-maestro/tmp/ctx-DSC-001.md",
        },
        "tasks": [
            {
                "role": "architect",
                "angle": "system boundaries",
                "ask": "Identify integration risks.",
            },
            {
                "role": "devils_advocate",
                "angle": "failure modes",
                "ask_file": ".gran-maestro/tmp/task-ask.md",
            },
        ],
    }


def _seed_context_files(workspace: Path) -> None:
    (workspace / ".gran-maestro" / "tmp" / "ctx-DSC-001.md").write_text(
        "REFERENCE CONTEXT BODY",
        encoding="utf-8",
    )
    (workspace / ".gran-maestro" / "tmp" / "task-ask.md").write_text(
        "LONGER ASK FROM FILE",
        encoding="utf-8",
    )


def _run_prompt(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST), "prompt", *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )


def test_prompt_build_valid_inputs(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    _write_json(input_path, _valid_payload())

    result = _run_prompt(workspace, "build", "--input", str(input_path), "--out-dir", str(out_dir))

    assert result.returncode == 0, result.stderr
    combined = (out_dir / "combined-prompts.txt").read_text(encoding="utf-8")
    assert "===SPLIT: architect-prompt.md===" in combined
    assert "===SPLIT: devils_advocate-prompt.md===" in combined
    assert "Dispatch prompt builder" in combined
    assert "Keep the answer grounded" in combined
    assert "REFERENCE CONTEXT BODY" in combined
    assert "Identify integration risks." in combined
    assert "LONGER ASK FROM FILE" in combined


def test_prompt_build_rejects_long_inline_ask(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    payload = _valid_payload()
    payload["tasks"] = [{"role": "architect", "ask": "x" * 220}]
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "build", "--input", str(input_path), "--out-dir", str(out_dir))

    assert result.returncode == 2
    errors = json.loads(result.stdout)["errors"]
    assert errors[0]["path"] == "tasks[0].ask"
    assert "exceeds 200 chars" in errors[0]["reason"]
    assert not (out_dir / "combined-prompts.txt").exists()


def test_prompt_validate_rejects_inline_reference_context(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    payload = _valid_payload()
    payload["common"]["reference_context"] = "long markdown body"
    input_path = tmp_path / "dispatch.json"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "validate", "--input", str(input_path))

    assert result.returncode == 2
    errors = json.loads(result.stdout)["errors"]
    assert any(
        error["path"] == "common.reference_context"
        and "inline long body is forbidden" in error["reason"]
        for error in errors
    )


def test_prompt_validate_preserves_json_decode_location(tmp_path):
    workspace = _workspace(tmp_path)
    input_path = tmp_path / "broken.json"
    input_path.write_text('{"format": "mst.dispatch",\n"schema_version": 1,\n}', encoding="utf-8")

    result = _run_prompt(workspace, "validate", "--input", str(input_path))

    assert result.returncode == 2
    errors = json.loads(result.stdout)["errors"]
    assert any(error["path"].startswith("<root:line") for error in errors)
    assert any(error["reason"].startswith("JSON decode error") for error in errors)


def test_prompt_build_rejects_code_fence_in_ask(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    payload = _valid_payload()
    payload["tasks"] = [{"role": "architect", "ask": "```python\nfoo\n```"}]
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "build", "--input", str(input_path), "--out-dir", str(out_dir))

    assert result.returncode == 2
    errors = json.loads(result.stdout)["errors"]
    assert any("code fence" in error["reason"] for error in errors)
    assert not (out_dir / "combined-prompts.txt").exists()


def test_prompt_build_ask_file_wins(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    payload = _valid_payload()
    payload["tasks"] = [
        {
            "role": "architect",
            "ask": "short",
            "ask_file": ".gran-maestro/tmp/task-ask.md",
        }
    ]
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "build", "--input", str(input_path), "--out-dir", str(out_dir))

    assert result.returncode == 0, result.stderr
    combined = (out_dir / "combined-prompts.txt").read_text(encoding="utf-8")
    assert "LONGER ASK FROM FILE" in combined
    assert "short" not in combined
    assert "warning" in result.stderr.lower()
    assert "ask_file" in result.stderr


@pytest.mark.parametrize(
    ("mutator", "expected_path"),
    [
        (lambda payload: payload.pop("format"), "format"),
        (lambda payload: payload.pop("schema_version"), "schema_version"),
        (lambda payload: payload["common"].update({"topic": ""}), "common.topic"),
        (lambda payload: payload.update({"tasks": []}), "tasks"),
        (lambda payload: payload["tasks"][0].pop("role"), "tasks[0].role"),
    ],
)
def test_prompt_validate_missing_fields(tmp_path, mutator, expected_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    payload = _valid_payload()
    mutator(payload)
    input_path = tmp_path / f"{expected_path.replace('.', '_')}.json"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "validate", "--input", str(input_path))

    assert result.returncode == 2
    errors = json.loads(result.stdout)["errors"]
    assert errors
    assert any(error["path"] == expected_path for error in errors)
    assert all("path" in error and "reason" in error for error in errors)


def test_prompt_build_missing_reference_file(tmp_path):
    workspace = _workspace(tmp_path)
    payload = _valid_payload()
    payload["common"]["reference_context_file"] = ".gran-maestro/tmp/nonexistent_xxx.md"
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    _write_json(input_path, payload)

    result = _run_prompt(workspace, "build", "--input", str(input_path), "--out-dir", str(out_dir))

    assert result.returncode == 3
    assert ".gran-maestro/tmp/nonexistent_xxx.md" in result.stderr
    assert not (out_dir / "combined-prompts.txt").exists()


def test_prompt_build_dry_run_metrics(tmp_path):
    workspace = _workspace(tmp_path)
    _seed_context_files(workspace)
    input_path = tmp_path / "dispatch.json"
    out_dir = tmp_path / "prompts"
    metrics_file = tmp_path / "metrics.ndjson"
    _write_json(input_path, _valid_payload())

    result = _run_prompt(
        workspace,
        "build",
        "--input",
        str(input_path),
        "--out-dir",
        str(out_dir),
        "--dry-run",
        "--metrics-file",
        str(metrics_file),
    )

    assert result.returncode == 0, result.stderr
    prompts = json.loads(result.stdout)
    assert isinstance(prompts, list)
    assert all("role" in item and "prompt" in item for item in prompts)
    assert not (out_dir / "combined-prompts.txt").exists()
    metric = json.loads(metrics_file.read_text(encoding="utf-8").splitlines()[-1])
    assert metric["parse_status"] == "ok"
    assert isinstance(metric["token_count_estimate"], int)
    assert metric["token_count_estimate"] > 0
    assert metric["fallback_reason"] is None


def test_prompt_write_context(tmp_path):
    workspace = _workspace(tmp_path)
    raw = tmp_path / "raw.md"
    raw.write_text("hello ctx", encoding="utf-8")

    result = _run_prompt(workspace, "write-context", "--sid", "DSC-999", "--content-file", str(raw))

    assert result.returncode == 0, result.stderr
    out_path = Path(result.stdout.strip())
    assert out_path.is_absolute()
    assert out_path == workspace / ".gran-maestro" / "tmp" / "ctx-DSC-999.md"
    assert out_path.read_text(encoding="utf-8") == "hello ctx"


def test_imports_mst_facade():
    assert mst.find_base_dir is not None
