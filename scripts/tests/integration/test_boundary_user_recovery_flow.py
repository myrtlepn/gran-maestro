from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def init_git_project(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Boundary Test",
            "-c",
            "user.email=boundary@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    hook_dir = root / ".claude" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "mst-placeholder.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")


def write_request(root: Path, req_id: str, *, detected_base: str) -> None:
    write_json(
        root / ".gran-maestro" / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "status": "phase2_execution",
            "current_phase": 2,
            "detected_base": detected_base,
            "tasks": [{"id": "T01"}],
        },
    )


def install_mst_launcher(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "mst.py"
    launcher.write_text(
        f"#!/usr/bin/env bash\nexec python3 \"{REPO_ROOT / 'scripts' / 'mst.py'}\" \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def install_failing_git(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    failing_git = bin_dir / "git"
    failing_git.write_text(
        "#!/usr/bin/env bash\necho \"simulated git failure\" >&2\nexit 127\n",
        encoding="utf-8",
    )
    failing_git.chmod(0o755)


def run_hook(cwd: Path, payload: dict, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(PRE_TOOL_HOOK)],
        cwd=cwd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def test_user_can_recover_by_running_blocked_recovery_command_once(tmp_path: Path) -> None:
    req_id = "REQ-7459"
    init_git_project(tmp_path)
    write_request(tmp_path, req_id, detected_base="main")
    ok_bin = tmp_path / "bin-ok"
    fail_git_bin = tmp_path / "bin-fail-git"
    install_mst_launcher(ok_bin)
    install_failing_git(fail_git_bin)

    broken_env = {"PATH": f"{fail_git_bin}:{ok_bin}:{os.environ.get('PATH', '')}"}
    first = run_hook(
        tmp_path,
        {
            "tool_name": "Skill",
            "tool_input": {"skill_name": "mst:approve", "args": req_id},
        },
        env=broken_env,
    )
    first_payload = json.loads(first.stdout)

    assert first.returncode == 0
    assert first_payload["decision"] == "block"
    assert first_payload["reason"] == "base_not_verified"
    recovery_command = first_payload["details"]["recovery_command"]
    assert recovery_command.startswith("mst.py worktree create ")

    normal_env = {"PATH": f"{ok_bin}:{os.environ.get('PATH', '')}"}
    recovery = subprocess.run(
        ["bash", "-lc", recovery_command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=normal_env,
    )
    assert recovery.returncode == 0, recovery.stderr

    second = run_hook(
        tmp_path,
        {
            "tool_name": "Skill",
            "tool_input": {"skill_name": "mst:approve", "args": req_id},
        },
        env=normal_env,
    )

    assert second.returncode == 0
    assert second.stdout.strip() == ""
