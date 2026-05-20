import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True)
    return tmp_path


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )


def _run_prompt_build(
    workspace: Path,
    input_path: Path,
    out_dir: Path,
    *,
    sid: str = "IDN-TEST",
) -> subprocess.CompletedProcess:
    return _run_mst(
        workspace,
        "prompt",
        "build",
        "--input",
        str(input_path),
        "--out-dir",
        str(out_dir),
        "--sid",
        sid,
    )


def _run_split_prompts(workspace: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return _run_mst(workspace, "session", "split-prompts", "--dir", str(out_dir))


def _seed_context(workspace: Path, sid: str = "IDN-TEST") -> None:
    (workspace / ".gran-maestro" / "tmp" / f"ctx-{sid}.md").write_text(
        "Shared reference context for integration regression.",
        encoding="utf-8",
    )


def _dispatch_payload(sid: str = "IDN-TEST") -> dict:
    return {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
            "topic": "Hybrid prompt builder integration",
            "constraints": ["Keep findings concrete", "Preserve split prompt compatibility"],
            "reference_context_file": f".gran-maestro/tmp/ctx-{sid}.md",
        },
        "tasks": [
            {
                "role": "architect(codex)",
                "angle": "system integration boundaries",
                "ask": "Identify coupling risks in the hybrid prompt path.",
            },
            {
                "role": "ux(gemini)",
                "angle": "operator workflow clarity",
                "ask": "Check whether the split prompts remain easy to inspect.",
            },
            {
                "role": "risk(claude)",
                "angle": "fallback and metrics risk",
                "ask": "List failure modes that would hide builder regressions.",
            },
        ],
    }


def _write_dispatch_input(workspace: Path, sid: str = "IDN-TEST") -> Path:
    _seed_context(workspace, sid=sid)
    input_path = workspace / f"dispatch-input-{sid}.json"
    _write_json(input_path, _dispatch_payload(sid=sid))
    return input_path


def _metrics_file(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "metrics" / "prompt-builder.ndjson"


def _read_metrics(workspace: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in _metrics_file(workspace).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assert_split_outputs(out_dir: Path) -> None:
    expectations = {
        "architect(codex)-prompt.md": (
            "Hybrid prompt builder integration",
            "system integration boundaries",
            "Identify coupling risks in the hybrid prompt path.",
        ),
        "ux(gemini)-prompt.md": (
            "Hybrid prompt builder integration",
            "operator workflow clarity",
            "Check whether the split prompts remain easy to inspect.",
        ),
        "risk(claude)-prompt.md": (
            "Hybrid prompt builder integration",
            "fallback and metrics risk",
            "List failure modes that would hide builder regressions.",
        ),
    }
    for filename, expected_fragments in expectations.items():
        prompt_path = out_dir / filename
        assert prompt_path.exists(), f"missing split prompt: {prompt_path}"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in prompt_text


def test_integration_hybrid_to_split_end_to_end(tmp_path):
    workspace = _workspace(tmp_path)
    input_path = _write_dispatch_input(workspace)
    out_dir = workspace / "prompts"

    build = _run_prompt_build(workspace, input_path, out_dir)
    assert build.returncode == 0, build.stderr
    assert (out_dir / "combined-prompts.txt").exists()

    split = _run_split_prompts(workspace, out_dir)
    assert split.returncode == 0, split.stderr
    _assert_split_outputs(out_dir)

    metrics = _read_metrics(workspace)
    assert len(metrics) == 1
    assert metrics[-1]["parse_status"] == "ok"
    assert metrics[-1]["sid"] == "IDN-TEST"
    assert metrics[-1]["fallback_reason"] is None


def test_integration_combined_prompt_carries_context_path_and_work_contract(tmp_path):
    workspace = _workspace(tmp_path)
    input_path = _write_dispatch_input(workspace)
    out_dir = workspace / "prompts"

    build = _run_prompt_build(workspace, input_path, out_dir)
    assert build.returncode == 0, build.stderr

    combined_prompt = (out_dir / "combined-prompts.txt").read_text(encoding="utf-8")

    assert "## Reference Context Path" in combined_prompt
    assert ".gran-maestro/tmp/ctx-IDN-TEST.md" in combined_prompt
    assert "## Work Contract" in combined_prompt
    assert "read_requirements: inspect `common.reference_context_file` before answering." in combined_prompt
    assert "output_contract: return findings with explicit evidence and cite the inspected context path." in combined_prompt
    assert "verification_contract: include verification/evidence notes or a structured `missing_context` reason." in combined_prompt
    assert "failure_contract: if the context file cannot be read, respond with `missing_context`." in combined_prompt


def test_integration_metrics_accumulation_and_summary(tmp_path):
    workspace = _workspace(tmp_path)

    for index in range(5):
        sid = f"IDN-TEST-{index}"
        input_path = _write_dispatch_input(workspace, sid=sid)
        out_dir = workspace / f"prompts-{index}"

        build = _run_prompt_build(workspace, input_path, out_dir, sid=sid)
        assert build.returncode == 0, build.stderr
        split = _run_split_prompts(workspace, out_dir)
        assert split.returncode == 0, split.stderr

    metrics_path = _metrics_file(workspace)
    assert len(_read_metrics(workspace)) == 5

    summary = _run_mst(
        workspace,
        "metrics",
        "summary",
        "--scope",
        "prompt-builder",
        "--input",
        str(metrics_path),
    )

    assert summary.returncode == 0, summary.stderr
    payload = json.loads(summary.stdout)
    assert payload["sample_count"] == 5
    assert payload["parse_success_rate"] == 1.0
    assert payload["fallback_count"] == 0
    assert payload["avg_token_count_estimate"] > 0


def test_integration_legacy_path_regression(tmp_path):
    workspace = _workspace(tmp_path)
    out_dir = workspace / "prompts"
    out_dir.mkdir(parents=True)
    (out_dir / "combined-prompts.txt").write_text(
        "\n".join(
            [
                "===SPLIT: architect(codex)-prompt.md===",
                "# Architect legacy prompt",
                "Legacy topic and architect ask",
                "",
                "===SPLIT: ux(gemini)-prompt.md===",
                "# UX legacy prompt",
                "Legacy topic and UX ask",
                "",
                "===SPLIT: risk(claude)-prompt.md===",
                "# Risk legacy prompt",
                "Legacy topic and risk ask",
                "",
            ]
        ),
        encoding="utf-8",
    )

    split = _run_split_prompts(workspace, out_dir)

    assert split.returncode == 0, split.stderr
    assert (out_dir / "architect(codex)-prompt.md").read_text(encoding="utf-8") == (
        "# Architect legacy prompt\nLegacy topic and architect ask"
    )
    assert (out_dir / "ux(gemini)-prompt.md").read_text(encoding="utf-8") == (
        "# UX legacy prompt\nLegacy topic and UX ask"
    )
    assert (out_dir / "risk(claude)-prompt.md").read_text(encoding="utf-8") == (
        "# Risk legacy prompt\nLegacy topic and risk ask"
    )
    assert not _metrics_file(workspace).exists()


def test_integration_split_compat(tmp_path):
    workspace = _workspace(tmp_path)
    input_path = _write_dispatch_input(workspace)
    out_dir = workspace / "prompts"

    build = _run_prompt_build(workspace, input_path, out_dir)
    assert build.returncode == 0, build.stderr
    combined_path = out_dir / "combined-prompts.txt"
    combined_before_split = combined_path.read_text(encoding="utf-8")
    assert "===SPLIT: architect(codex)-prompt.md===" in combined_before_split
    assert "===SPLIT: ux(gemini)-prompt.md===" in combined_before_split
    assert "===SPLIT: risk(claude)-prompt.md===" in combined_before_split

    split = _run_split_prompts(workspace, out_dir)

    assert split.returncode == 0, split.stderr
    assert combined_path.read_text(encoding="utf-8") == combined_before_split
    _assert_split_outputs(out_dir)
