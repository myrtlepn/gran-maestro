from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".gran-maestro").mkdir(parents=True)
    return project


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home)}


def _project_key(project: Path) -> str:
    return hashlib.sha256(os.path.realpath(project).encode()).hexdigest()[:16]


def _policy_project(home: Path, project: Path) -> Path:
    return home / ".claude" / "gran-maestro-policy" / "projects" / _project_key(project)


def _run_mst(project: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(MST), *args],
        cwd=project,
        env=_env(home),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_hook(project: Path, home: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=project,
        env=_env(home),
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )


def _rewrite_manifest(policy_project: Path) -> None:
    rules = []
    for rule_file in sorted((policy_project / "rules.d").glob("*.json")):
        rel = rule_file.relative_to(policy_project)
        rules.append(
            {
                "path": rel.as_posix(),
                "sha256": hashlib.sha256(rule_file.read_bytes()).hexdigest(),
                "last_modified": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    (policy_project / "manifest.json").write_text(
        json.dumps({"version": 1, "rules": rules}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(policy_project / "manifest.json", 0o600)


def _overwrite_same_fingerprint(path: Path, new_bytes: bytes) -> None:
    original_stat = path.stat()
    assert len(new_bytes) == original_stat.st_size
    with path.open("r+b") as handle:
        handle.seek(0)
        handle.write(new_bytes)
        handle.truncate()
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert path.stat().st_size == original_stat.st_size
    assert path.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert path.stat().st_ino == original_stat.st_ino


def test_policy_init_creates_private_rule_store(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"

    result = _run_mst(project, home, "policy", "init")

    assert result.returncode == 0, result.stderr
    policy_project = _policy_project(home, project)
    rules_dir = policy_project / "rules.d"
    rule_file = rules_dir / "core-bypass.json"
    assert stat.S_IMODE(rules_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(rule_file.stat().st_mode) == 0o600


def test_manifest_mismatch_blocks_hook_startup(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    assert _run_mst(project, home, "policy", "init").returncode == 0
    policy_project = _policy_project(home, project)
    (policy_project / "rules.d" / "core-bypass.json").write_text("x", encoding="utf-8")

    result = _run_hook(project, home, {"tool_name": "Read", "tool_input": {"file_path": "README.md"}})

    assert result.returncode == 2
    assert "core-bypass.json" in result.stderr
    assert "expected=" in result.stderr
    assert "actual=" in result.stderr


def test_hardcoded_core_blocks_policy_directory_write(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "~/.claude/gran-maestro-policy/projects/demo/rules.d/x.json"
        },
    }

    result = _run_hook(project, home, payload)

    assert result.returncode == 2
    assert "정책 디렉토리" in result.stderr


def test_hardcoded_core_cannot_be_weakened_by_rule_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    assert _run_mst(project, home, "policy", "init").returncode == 0
    policy_project = _policy_project(home, project)
    weakening = {
        "version": 1,
        "rules": [
            {
                "id": "GM-WEAKEN-CORE",
                "severity": "warn",
                "trigger": {"tool": "Write"},
                "action": {"decision": "allow", "message": "weakened"},
            }
        ],
    }
    rule_file = policy_project / "rules.d" / "core-bypass.json"
    rule_file.write_text(json.dumps(weakening), encoding="utf-8")
    _rewrite_manifest(policy_project)

    result = _run_hook(
        project,
        home,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "~/.claude/gran-maestro-policy/projects/demo/rules.d/x.json"
            },
        },
    )

    assert result.returncode == 2
    assert "정책 디렉토리" in result.stderr


def test_unknown_predicate_fails_closed_at_load_time(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    assert _run_mst(project, home, "policy", "init").returncode == 0
    policy_project = _policy_project(home, project)
    custom = {
        "version": 1,
        "rules": [
            {
                "id": "GM-UNKNOWN",
                "severity": "block",
                "trigger": {"tool": "Bash"},
                "condition": {"all": [{"predicate": "unknown_xyz"}]},
                "action": {"decision": "block", "message": "unknown predicate must fail closed"},
            },
        ],
    }
    rule_file = policy_project / "rules.d" / "custom.json"
    rule_file.write_text(json.dumps(custom), encoding="utf-8")
    os.chmod(rule_file, 0o600)
    _rewrite_manifest(policy_project)

    result = _run_hook(
        project,
        home,
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
    )

    assert result.returncode == 2
    assert "unknown_predicate" in result.stderr
    assert "unknown_xyz" in result.stderr


def test_rule_cache_does_not_bypass_manifest_sha256_verification(tmp_path: Path) -> None:
    project = _project(tmp_path)
    home = tmp_path / "home"
    assert _run_mst(project, home, "policy", "init").returncode == 0
    policy_project = _policy_project(home, project)
    rule_file = policy_project / "rules.d" / "core-bypass.json"

    first = _run_hook(project, home, {"tool_name": "Read", "tool_input": {"file_path": "README.md"}})

    assert first.returncode == 0, first.stderr
    assert (policy_project / ".rule-engine-cache.json").is_file()

    original = rule_file.read_bytes()
    replacement = original.replace(b"core", b"CORE", 1)
    assert replacement != original
    _overwrite_same_fingerprint(rule_file, replacement)

    second = _run_hook(project, home, {"tool_name": "Read", "tool_input": {"file_path": "README.md"}})

    assert second.returncode == 2
    assert "manifest_sha256_mismatch" in second.stderr
