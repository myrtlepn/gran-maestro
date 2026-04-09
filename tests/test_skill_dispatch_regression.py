import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_stub_cli(bin_dir: Path, name: str) -> None:
    path = bin_dir / name
    path.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _dispatch_and_execute(
    workspace: Path,
    env: dict,
    provider: str,
    prompt_file: Path,
    output_file: Path,
    task_id: str,
) -> None:
    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        provider,
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(output_file),
        "--model",
        "smoke-model",
        env=env,
    )
    assert built.returncode == 0, built.stderr

    command = built.stdout.strip()
    executed = subprocess.run(
        ["bash", "-c", command],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert executed.returncode == 0, executed.stderr

    assert output_file.exists()
    assert "EXIT_CODE:0" in output_file.read_text(encoding="utf-8")

    state_file = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state.get("phase") == "done"
    assert isinstance(state.get("terminated_at"), str) and state["terminated_at"]


def test_skill_dispatch_smoke_for_ideation_discussion_debug(tmp_path):
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_stub_cli(bin_dir, "codex")
    _write_stub_cli(bin_dir, "gemini")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    cases = [
        ("ideation", "IDN-001", "codex"),
        ("discussion", "DSC-001", "gemini"),
        ("debug", "DBG-001", "codex"),
    ]

    for skill_name, session_id, provider in cases:
        session_dir = base / skill_name / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps({"id": session_id, "status": "collecting"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        prompt_file = session_dir / "prompt.md"
        prompt_file.write_text(f"{skill_name} smoke prompt", encoding="utf-8")

        output_file = session_dir / "result.md"
        task_id = f"{skill_name}-{session_id.lower()}"

        _dispatch_and_execute(
            workspace=workspace,
            env=env,
            provider=provider,
            prompt_file=prompt_file,
            output_file=output_file,
            task_id=task_id,
        )


def test_skill_dispatch_extended_smoke_for_ideation_discussion_debug(tmp_path):
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_stub_cli(bin_dir, "codex")
    _write_stub_cli(bin_dir, "gemini")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    ideation_dir = base / "ideation" / "IDN-001"
    ideation_dir.mkdir(parents=True, exist_ok=True)
    (ideation_dir / "session.json").write_text(
        json.dumps({"id": "IDN-001", "status": "collecting"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ideation_cases = [
        ("codex", "architect-codex"),
        ("codex", "ux-codex"),
        ("gemini", "risk-gemini"),
    ]
    for provider, key in ideation_cases:
        prompt_file = ideation_dir / f"{key}-prompt.md"
        prompt_file.write_text(f"ideation prompt: {key}", encoding="utf-8")
        _dispatch_and_execute(
            workspace=workspace,
            env=env,
            provider=provider,
            prompt_file=prompt_file,
            output_file=ideation_dir / f"opinion-{key}.md",
            task_id=f"ideation-idn-001-{key}",
        )

    synthesis_prompt = ideation_dir / "synthesis-prompt.md"
    synthesis_prompt.write_text("summarize ideation opinions", encoding="utf-8")
    _dispatch_and_execute(
        workspace=workspace,
        env=env,
        provider="codex",
        prompt_file=synthesis_prompt,
        output_file=ideation_dir / "synthesis.md",
        task_id="ideation-idn-001-synthesis",
    )
    assert (ideation_dir / "synthesis.md").exists()

    discussion_round = base / "discussion" / "DSC-001" / "rounds" / "01"
    discussion_round.mkdir(parents=True, exist_ok=True)
    participant_prompt = discussion_round / "architect-prompt.md"
    participant_prompt.write_text("discussion round 1 participant", encoding="utf-8")
    _dispatch_and_execute(
        workspace=workspace,
        env=env,
        provider="codex",
        prompt_file=participant_prompt,
        output_file=discussion_round / "architect.md",
        task_id="discussion-dsc-001-round1-architect",
    )

    critic_prompt = discussion_round / "critic-prompt.md"
    critic_prompt.write_text("discussion round 1 critic", encoding="utf-8")
    _dispatch_and_execute(
        workspace=workspace,
        env=env,
        provider="gemini",
        prompt_file=critic_prompt,
        output_file=discussion_round / "critique-claude.md",
        task_id="discussion-dsc-001-round1-critic",
    )
    assert (discussion_round / "critique-claude.md").exists()

    debug_dir = base / "debug" / "DBG-001"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "session.json").write_text(
        json.dumps({"id": "DBG-001", "status": "investigating"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    debug_prompt = debug_dir / "investigator-codex-prompt.md"
    debug_prompt.write_text("debug investigation prompt", encoding="utf-8")
    _dispatch_and_execute(
        workspace=workspace,
        env=env,
        provider="codex",
        prompt_file=debug_prompt,
        output_file=debug_dir / "finding-codex.md",
        task_id="debug-dbg-001-codex",
    )
    assert (debug_dir / "session.json").exists()
