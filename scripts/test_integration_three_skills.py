import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
SKILLS_DIR = REPO_ROOT / "skills"

STEP_COUNT_MINIMUMS = {
    "discussion": 11,
    "debug": 7,
    "explore": 7,
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro" / "tmp").mkdir(parents=True)
    return workspace


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
    sid: str,
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


def _metrics_file(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "metrics" / "prompt-builder.ndjson"


def _read_metrics(workspace: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in _metrics_file(workspace).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _role_filename(role: str) -> str:
    safe = role.strip().replace("/", "-").replace("\\", "-")
    safe = "_".join(safe.split())
    return f"{safe}-prompt.md"


def _dispatch_payload(skill: str, sid: str, tasks: list[dict]) -> dict:
    return {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
            "topic": f"{skill} prompt builder regression",
            "constraints": [
                "Keep the dispatch prompt grounded",
                "Preserve split prompt compatibility",
            ],
            "reference_context_file": f".gran-maestro/tmp/ctx-{sid}.md",
        },
        "tasks": tasks,
    }


def _write_dispatch_input(
    workspace: Path,
    *,
    skill: str,
    sid: str,
    tasks: list[dict],
) -> Path:
    (workspace / ".gran-maestro" / "tmp" / f"ctx-{sid}.md").write_text(
        f"Shared context for {skill} integration regression.",
        encoding="utf-8",
    )
    input_path = workspace / f"{skill}-dispatch-input.json"
    _write_json(input_path, _dispatch_payload(skill, sid, tasks))
    return input_path


def _assert_prompt_outputs(out_dir: Path, *, skill: str, tasks: list[dict]) -> None:
    combined = (out_dir / "combined-prompts.txt").read_text(encoding="utf-8")
    assert f"{skill} prompt builder regression" in combined

    for task in tasks:
        filename = _role_filename(task["role"])
        assert f"===SPLIT: {filename}===" in combined

        prompt_path = out_dir / filename
        assert prompt_path.exists(), f"missing split prompt: {prompt_path}"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        assert task["role"] in prompt_text
        assert task["angle"] in prompt_text
        assert task["ask"] in prompt_text
        assert f"Shared context for {skill} integration regression." in prompt_text


def _assert_metrics(workspace: Path, *, sid: str) -> None:
    metrics = _read_metrics(workspace)
    assert len(metrics) == 1
    assert metrics[-1]["parse_status"] == "ok"
    assert metrics[-1]["sid"] == sid
    assert metrics[-1]["fallback_reason"] is None
    assert isinstance(metrics[-1]["token_count_estimate"], int)
    assert metrics[-1]["token_count_estimate"] > 0


def _assert_skill_dispatch(
    tmp_path: Path,
    *,
    skill: str,
    sid: str,
    tasks: list[dict],
) -> None:
    workspace = _workspace(tmp_path)
    input_path = _write_dispatch_input(workspace, skill=skill, sid=sid, tasks=tasks)
    out_dir = workspace / "prompts"

    build = _run_prompt_build(workspace, input_path, out_dir, sid=sid)
    assert build.returncode == 0, build.stderr
    assert (out_dir / "combined-prompts.txt").exists()

    split = _run_split_prompts(workspace, out_dir)
    assert split.returncode == 0, split.stderr

    _assert_prompt_outputs(out_dir, skill=skill, tasks=tasks)
    _assert_metrics(workspace, sid=sid)


@pytest.mark.parametrize("skill", ["discussion", "debug", "explore"])
def test_three_skills_feature_flag_structure(skill: str) -> None:
    skill_text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")

    assert skill_text.count("prompt_builder.enabled") >= 2
    assert re.search(r'"format"\s*:\s*"mst\.dispatch"', skill_text) is not None
    assert "fallback" in skill_text.lower()
    assert "repair" in skill_text.lower()
    assert len(re.findall(r"^### Step", skill_text, flags=re.MULTILINE)) >= STEP_COUNT_MINIMUMS[skill]


def test_integration_discussion_style_dispatch(tmp_path: Path) -> None:
    tasks = [
        {
            "role": "participant_codex",
            "angle": "implementation feasibility",
            "ask": "Assess whether the proposed dispatch flow remains practical.",
        },
        {
            "role": "participant_gemini",
            "angle": "operator clarity",
            "ask": "Identify workflow wording that could confuse an operator.",
        },
        {
            "role": "critic_claude",
            "angle": "regression risk",
            "ask": "Challenge assumptions that might hide prompt builder regressions.",
        },
    ]

    _assert_skill_dispatch(tmp_path, skill="discussion", sid="DSC-T02", tasks=tasks)


def test_integration_debug_style_dispatch(tmp_path: Path) -> None:
    tasks = [
        {
            "role": "investigator_codex",
            "angle": "root cause path",
            "ask": "Trace the most likely source of a prompt assembly failure.",
        },
        {
            "role": "investigator_gemini",
            "angle": "observability evidence",
            "ask": "List the evidence needed to diagnose split prompt issues.",
        },
        {
            "role": "investigator_claude",
            "angle": "fallback behavior",
            "ask": "Check whether repair and fallback behavior remains explicit.",
        },
    ]

    _assert_skill_dispatch(tmp_path, skill="debug", sid="DBG-T02", tasks=tasks)


def test_integration_explore_style_dispatch(tmp_path: Path) -> None:
    tasks = [
        {
            "role": "explorer_codex",
            "angle": "codebase mapping",
            "ask": "Map the files involved in prompt build and split behavior.",
        },
        {
            "role": "explorer_gemini",
            "angle": "pattern comparison",
            "ask": "Compare related integration tests for missing assertions.",
        },
    ]

    _assert_skill_dispatch(tmp_path, skill="explore", sid="EXP-T02", tasks=tasks)
