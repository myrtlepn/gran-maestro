from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _find_main_repo_root(repo_root: Path) -> Path:
    for candidate in (repo_root, *repo_root.parents):
        if (candidate / ".gran-maestro" / "requests" / "REQ-923" / "request.json").is_file():
            return candidate
    return repo_root


MAIN_REPO_ROOT = _find_main_repo_root(REPO_ROOT)
REQUEST_JSON = MAIN_REPO_ROOT / ".gran-maestro" / "requests" / "REQ-923" / "request.json"
DISPATCH_SOURCE = REPO_ROOT / "scripts" / "mst_cmds" / "dispatch_shards" / "part_001.py"
RUN_SOURCE = REPO_ROOT / "scripts" / "mst_cmds" / "run.py"
SID = "MST-AGI-040-20260520T090000000Z-dod010a1"
ROOT = "AGI-040"


def _run_mst(workspace: Path, *args: str, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _context(extra: Optional[dict] = None) -> dict:
    payload = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "next_execution": {
                "env": {"MST_SESSION_ID": SID},
                "context": {"mst_session_id": SID, "root_mst_id": ROOT},
            },
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _env(*, context: Optional[dict] = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_HOST"] = "headless"
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps(
        _context() if context is None else context,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return env


def _source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _inventory() -> dict[str, dict]:
    request_payload = json.loads(REQUEST_JSON.read_text(encoding="utf-8"))
    return {
        "prompt_file": {
            "routes": {"command_assembly", "filesystem", "log_path"},
            "evidence": [
                (DISPATCH_SOURCE, "prompt_file = Path(args.prompt_file).resolve()"),
                (DISPATCH_SOURCE, "$(cat {q(str(prompt_file))})"),
            ],
        },
        "files_pattern": {
            "routes": {"command_assembly"},
            "evidence": [
                (REPO_ROOT / "skills" / "gemini" / "SKILL.md", "--files src/**/*.ts"),
            ],
        },
        "trace_label": {
            "routes": {"trace_path", "trace_metadata"},
            "evidence": [
                (RUN_SOURCE, "def _parse_trace_label(trace: str)"),
                (RUN_SOURCE, "trace_path = traces_dir / f\"{provider}-{label}-{ts}.md\""),
            ],
        },
        "task_label": {
            "routes": {"dispatch_state", "attempt_snapshot"},
            "evidence": [
                (REPO_ROOT / "scripts" / "mst_cmds" / "dispatch_shards" / "part_002.py", '"label": _lifecycle_label('),
                (DISPATCH_SOURCE, '"label",'),
            ],
        },
        "context_path": {
            "routes": {"filesystem", "context_files_read"},
            "evidence": [
                (DISPATCH_SOURCE, "def _context_file_candidates("),
                (DISPATCH_SOURCE, "def _collect_context_files_read("),
            ],
        },
        "branch": {
            "routes": {"filesystem"},
            "values": {
                "parent_session_branch": request_payload.get("parent_session_branch"),
                "original_base_branch": request_payload.get("original_base_branch"),
            },
        },
        "worktree": {
            "routes": {"filesystem", "log_path", "dispatch_state"},
            "evidence": [
                (DISPATCH_SOURCE, '--worktree-dir {q(str(worktree_dir))}'),
                (RUN_SOURCE, '"worktree_dir": str((worktree_dir or Path.cwd()).resolve(strict=False)),'),
            ],
        },
        "session": {
            "routes": {"dispatch_state", "trace_metadata", "log_path"},
            "evidence": [
                (DISPATCH_SOURCE, 'MST_SESSION_ID="$MST_SESSION_ID"'),
                (RUN_SOURCE, '"mst_session_id": session_id'),
            ],
        },
        "request": {
            "routes": {"filesystem", "trace_path"},
            "evidence": [
                (REQUEST_JSON, '"id": "REQ-923"'),
                (REPO_ROOT / "skills" / "codex" / "SKILL.md", "--trace {REQ-ID}/{TASK-NUM}/{label}"),
            ],
        },
        "attempt": {
            "routes": {"dispatch_state", "structured_error", "fallback_metadata"},
            "evidence": [
                (DISPATCH_SOURCE, '"attempt_id",'),
                (DISPATCH_SOURCE, '"fallback_from",'),
                (DISPATCH_SOURCE, '"fallback_to",'),
            ],
        },
        "provider": {
            "routes": {"command_assembly", "trace_path", "dispatch_state"},
            "evidence": [
                (DISPATCH_SOURCE, 'provider = str(args.provider).strip().lower()'),
                (RUN_SOURCE, 'f"{provider}-{label}-{ts}.md"'),
            ],
        },
        "model": {
            "routes": {"command_assembly", "trace_metadata", "dispatch_state"},
            "evidence": [
                (DISPATCH_SOURCE, "--model {q(resolved_model)}"),
                (RUN_SOURCE, 'f"model: {model}"'),
            ],
        },
        "config_derived_value": {
            "routes": {"command_assembly", "process_control"},
            "evidence": [
                (DISPATCH_SOURCE, 'HB_INTERVAL="${MST_DISPATCH_HEARTBEAT_INTERVAL:-120}"'),
                (DISPATCH_SOURCE, "_resolve_provider_model(provider, args.model, requested_provider=legacy_provider)"),
            ],
        },
    }


def _write_stub_codex(bin_dir: Path, args_path: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / "codex"
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import pathlib",
                "import sys",
                f'path = pathlib.Path({json.dumps(str(args_path))})',
                "path.write_text(json.dumps(sys.argv[1:], ensure_ascii=False), encoding='utf-8')",
                "path.with_suffix(path.suffix + '.stdin').write_bytes(sys.stdin.buffer.read())",
                "print('stub-codex-ok')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _build_dispatch_command(
    workspace: Path,
    *,
    prompt_file: Path,
    log_file: Path,
    task_id: str,
    env: Optional[dict[str, str]] = None,
) -> str:
    result = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-dod010",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _read_state(workspace: Path, task_id: str) -> dict:
    state_path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


def _init_git_fixture(workspace: Path) -> None:
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "dod010@example.invalid"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "DOD010"], cwd=workspace, check=True)
    tracked = workspace / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=workspace, check=True, capture_output=True, text=True)


@pytest.mark.parametrize(
    ("case_id", "prompt_name", "prompt_text"),
    [
        ("space", "space prompt.md", "plain prompt"),
        ("quote", "quote'and\"double.md", "plain prompt"),
        ("semicolon", "semi;colon.md", "plain prompt"),
        ("glob", "glob[*]question?.md", "plain prompt"),
        ("leading_dash", "-leading-prompt.md", "plain prompt"),
        ("path_traversal_like", "..lookalike-prompt.md", "plain prompt"),
        ("command_substitution", "prompt.md", "hello $(touch SENTINEL_FROM_SUBSTITUTION)"),
        ("backtick", "prompt.md", "hello `touch SENTINEL_FROM_BACKTICK`"),
        ("newline_crlf", "prompt.md", "line1\r\nline2\nline3"),
        ("unicode_control", "prompt.md", "snowman-☃-\u001b[31mred"),
    ],
)
def test_malicious_fixture_matrix_blocks_sentinel_execution_and_preserves_argv(
    tmp_path: Path,
    case_id: str,
    prompt_name: str,
    prompt_text: str,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / prompt_name
    prompt_file.write_text(prompt_text, encoding="utf-8")
    log_file = workspace / f"{case_id}.log"
    args_path = workspace / f"{case_id}-argv.json"
    sentinel = workspace / f"{case_id}-sentinel.txt"

    _write_stub_codex(tmp_path / "bin", args_path)
    env = _env()
    env.pop("MST_CONTEXT_JSON", None)
    env["PATH"] = f"{tmp_path / 'bin'}:{env.get('PATH', '')}"

    task_id = f"dod010-malicious-{case_id}"
    command = _build_dispatch_command(
        workspace,
        prompt_file=prompt_file,
        log_file=log_file,
        task_id=task_id,
        env=env,
    )

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()
    assert not (workspace / "SENTINEL_FROM_SUBSTITUTION").exists()
    assert not (workspace / "SENTINEL_FROM_BACKTICK").exists()

    argv = json.loads(args_path.read_text(encoding="utf-8"))
    assert argv[:6] == ["exec", "--sandbox", "read-only", "-m", "gpt-test-dod010", "-C"]
    assert argv[-1] == "-"
    assert prompt_text not in argv
    assert args_path.with_suffix(args_path.suffix + ".stdin").read_bytes() == prompt_file.read_bytes()
    assert log_file.exists()
    assert "stub-codex-ok" in log_file.read_text(encoding="utf-8")
    state = json.loads(
        (workspace / ".gran-maestro" / "run" / f"{task_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["external_command_metadata"]["prompt_transport"] == "stdin_claimed_fd"
    assert state["prompt_execution"]["status"] == "verified"
    assert state["output_publish"]["descriptor_bound"] is True


def test_untrusted_input_inventory_covers_required_sources_and_routes() -> None:
    inventory = _inventory()
    required_sources = {
        "prompt_file",
        "files_pattern",
        "trace_label",
        "task_label",
        "context_path",
        "branch",
        "worktree",
        "session",
        "request",
        "attempt",
        "provider",
        "model",
        "config_derived_value",
    }
    assert required_sources <= set(inventory)

    for key, entry in inventory.items():
        assert entry["routes"]
        for evidence in entry.get("evidence", []):
            path, snippet = evidence
            assert snippet in _source_text(Path(path))

    branch_values = inventory["branch"]["values"]
    assert isinstance(branch_values["parent_session_branch"], str) and branch_values["parent_session_branch"]
    assert branch_values["original_base_branch"] == "master"


def test_execution_sink_inventory_classifies_forbidden_allowlisted_and_informational_patterns() -> None:
    patterns = {
        "forbidden": [r"shell=True", r"os\.system", r"\bpopen\b"],
        "allowlisted": [r"bash -c", r"sh -c", r"spawn\(", r"exec\("],
        "informational": [r"child_process"],
    }
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "skills", REPO_ROOT / "tests"]
    inventory: dict[str, list[tuple[str, int, str]]] = {key: [] for key in patterns}

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".sh", ".bats", ".mjs", ".js"}:
                continue
            lines = _source_text(path).splitlines()
            for line_no, line in enumerate(lines, start=1):
                for classification, regexes in patterns.items():
                    if any(re.search(regex, line) for regex in regexes):
                        inventory[classification].append((str(path.relative_to(REPO_ROOT)), line_no, line))

    forbidden_hits = [item for item in inventory["forbidden"] if item[0] != "tests/test_dod010_security_isolation.py"]
    allowlisted_hits = [item for item in inventory["allowlisted"] if item[0] != "tests/test_dod010_security_isolation.py"]
    informational_hits = [item for item in inventory["informational"] if item[0] != "tests/test_dod010_security_isolation.py"]

    assert forbidden_hits == []
    assert any("bash -c" in line or "sh -c" in line for _, _, line in allowlisted_hits)
    assert any("child_process" in line for _, _, line in informational_hits)


def test_argv_first_or_allowlisted_shell_evidence_is_explicit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    log_dir = workspace / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stub = workspace / "emit-argv.py"
    argv_path = workspace / "argv.json"
    sentinel = workspace / "argv-first-sentinel.txt"
    stub.write_text(
        "\n".join(
            [
                "import json",
                "import pathlib",
                "import sys",
                f'pathlib.Path({json.dumps(str(argv_path))}).write_text(json.dumps(sys.argv[1:], ensure_ascii=False), encoding=\"utf-8\")',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = f"REQ-923/01/phase2;$(touch {sentinel})\ntrace"
    raw_arg = f"raw-arg;`touch {sentinel}`\nwith-space"
    from scripts.mst_cmds import set_base_dir
    from scripts.mst_cmds.run import cmd_run

    workspace_dot = workspace / ".gran-maestro"
    workspace_dot.mkdir(parents=True, exist_ok=True)
    set_base_dir(workspace_dot)
    old_env = os.environ.copy()
    os.environ.update(_env())
    try:
        result = cmd_run(
            type(
                "Args",
                (),
                {
                    "task_id": "dod010-argv-first",
                    "provider": "codex",
                    "skill": "",
                    "model": "gpt-test-dod010",
                    "log_dir": str(log_dir),
                    "trace": trace,
                    "heartbeat_interval": None,
                    "timeout": None,
                    "attempt_id": None,
                    "label": None,
                    "output_path": None,
                    "transcript_summary_path": None,
                    "provider_task_id": None,
                    "parent_session_id": None,
                    "fallback_from": None,
                    "context_file": None,
                    "cli_command": ["--", sys.executable, str(stub), raw_arg],
                },
            )()
        )
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        set_base_dir(None)

    assert result == 0
    assert not sentinel.exists()

    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert argv == [raw_arg]

    state = _read_state(workspace, "dod010-argv-first")
    trace_evidence = state.get("trace_label_evidence")
    assert isinstance(trace_evidence, dict)
    assert trace_evidence["normalized"]
    assert trace_evidence["original_redacted"]

    trace_files = list((log_dir / "traces").glob("*.md"))
    assert len(trace_files) == 1
    trace_text = trace_files[0].read_text(encoding="utf-8")
    assert "trace_label_original_redacted:" in trace_text
    assert "touch" in trace_text


def test_normalized_redacted_collision_evidence_preserves_failed_attempt_before_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    env = _env()

    register_a1 = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        "dod010-collision",
        "--attempt-id",
        "dod010-a1",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test-dod010",
        "--label",
        "phase2;impl",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert register_a1.returncode == 0, register_a1.stderr
    final_a1 = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        "dod010-collision",
        "--attempt-id",
        "dod010-a1",
        "--final",
        "--exit-code",
        "17",
        "--status",
        "failed",
        "--structured-error-json",
        '{"kind":"provider_failed","message":"first attempt failed"}',
        env=env,
    )
    assert final_a1.returncode == 0, final_a1.stderr

    register_a2 = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        "dod010-collision",
        "--attempt-id",
        "dod010-a2",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test-dod010",
        "--label",
        "phase2/impl\n",
        "--fallback-from",
        "dod010-a1",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert register_a2.returncode == 0, register_a2.stderr
    final_a2 = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        "dod010-collision",
        "--attempt-id",
        "dod010-a2",
        "--final",
        "--exit-code",
        "0",
        "--fallback-from",
        "dod010-a1",
        env=env,
    )
    assert final_a2.returncode == 0, final_a2.stderr

    payload = _read_state(workspace, "dod010-collision")
    attempts = {item["attempt_id"]: item for item in payload["attempts"]}
    assert attempts["dod010-a1"]["status"] == "failed"
    assert attempts["dod010-a2"]["status"] == "fallback_completed"

    evidence = attempts["dod010-a2"].get("label_evidence")
    assert isinstance(evidence, dict)
    assert evidence["normalized"] == "phase2-impl"
    assert evidence["original_redacted"] != evidence["normalized"]
    collision = evidence.get("collision")
    assert isinstance(collision, dict)
    assert collision["attempt_id"] == "dod010-a1"
    assert attempts["dod010-a1"]["structured_error"]["message"] == "first attempt failed"


def test_dirty_tree_precheck_blocks_mutation_and_writes_only_diagnostic_artifact(tmp_path: Path) -> None:
    from scripts.mst_cmds.dispatch import dispatch_dirty_tree_precheck

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_fixture(workspace)
    (workspace / ".gran-maestro" / "run").mkdir(parents=True, exist_ok=True)

    staged = workspace / "staged.txt"
    staged.write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=workspace, check=True)
    (workspace / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (workspace / "generated.cache").write_text("generated\n", encoding="utf-8")
    (workspace / "tracked.txt").write_text("base\nunrelated dirty\n", encoding="utf-8")

    diagnostic_path = workspace / ".gran-maestro" / "diagnostics" / "dirty-tree.json"
    before_paths = {path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file()}
    evidence = dispatch_dirty_tree_precheck(
        workspace,
        diagnostic_path=diagnostic_path,
        generated_allowlist=["*.cache"],
        mst_session_id=SID,
        task_id="REQ-923-02",
        attempt_id="REQ-923-02-A1",
    )
    after_paths = {path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file()}

    assert evidence["status"] == "non_success"
    assert evidence["mutation_allowed"] is False
    assert evidence["structured_error"]["kind"] == "dirty_tree_precheck"
    categories = {entry["path"]: entry["category"] for entry in evidence["dirty_entries"]}
    assert categories["staged.txt"] == "staged"
    assert categories["untracked.txt"] == "untracked"
    assert categories["generated.cache"] == "generated_allowlisted"
    assert categories["tracked.txt"] == "unstaged"
    assert after_paths - before_paths == {diagnostic_path.relative_to(workspace)}
    assert not (workspace / ".gran-maestro" / "run" / "REQ-923-02.json").exists()
    assert json.loads(diagnostic_path.read_text(encoding="utf-8")) == evidence


def test_toctou_revalidation_stops_mutation_with_structured_non_success_evidence(tmp_path: Path) -> None:
    from scripts.mst_cmds.dispatch import guarded_dispatch_mutation

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_fixture(workspace)
    (workspace / ".gran-maestro" / "run").mkdir(parents=True, exist_ok=True)
    target = workspace / "mutation-target.txt"
    diagnostic_path = workspace / ".gran-maestro" / "diagnostics" / "toctou.json"

    def introduce_toctou_dirty_change() -> None:
        (workspace / "tracked.txt").write_text("base\ntoctou\n", encoding="utf-8")

    def mutation() -> None:
        target.write_text("mutated\n", encoding="utf-8")

    evidence = guarded_dispatch_mutation(
        workspace,
        mutation,
        diagnostic_path=diagnostic_path,
        before_mutation=introduce_toctou_dirty_change,
        mst_session_id=SID,
        task_id="REQ-923-02",
        attempt_id="REQ-923-02-A1",
    )

    assert evidence["status"] == "non_success"
    assert evidence["mutation_allowed"] is False
    assert evidence["mutation_executed"] is False
    assert evidence["structured_error"]["kind"] == "toctou_dirty_tree_change"
    assert evidence["precheck"]["status"] == "clean"
    assert evidence["revalidation"]["status"] == "non_success"
    assert not target.exists()
    assert not (workspace / ".gran-maestro" / "run" / "REQ-923-02.json").exists()
    assert json.loads(diagnostic_path.read_text(encoding="utf-8")) == evidence


def test_parallel_scope_conflict_detects_exact_glob_generated_and_logical_overlap() -> None:
    from scripts.mst_cmds.dispatch import evaluate_parallel_scope_conflicts

    evidence = evaluate_parallel_scope_conflicts(
        [
            {
                "task_id": "REQ-923-02-A",
                "exact_files": ["scripts/mst_cmds/dispatch.py", "src/app.py"],
                "globs": ["reports/*.json"],
                "generated_outputs": ["build/manifest.json"],
                "logical_resources": ["manifest-agent list", "hooks/hooks.json", "config/dashboard/defaults"],
            },
            {
                "task_id": "REQ-923-02-B",
                "exact_files": ["scripts/mst_cmds/dispatch.py", "reports/summary.json"],
                "globs": ["src/*.py"],
                "generated_outputs": ["build/manifest.json"],
                "logical_resources": [".claude/hooks/pre-tool-use.sh", "dashboard defaults", "version set"],
            },
        ]
    )

    assert evidence["mutation_allowed"] is False
    conflict_types = {conflict["type"] for conflict in evidence["conflicts"]}
    assert {
        "exact_file",
        "glob_overlap",
        "generated_output",
        "logical_resource",
    } <= conflict_types
    logical_groups = {
        conflict["resource_group"]
        for conflict in evidence["conflicts"]
        if conflict["type"] == "logical_resource"
    }
    assert "hook canonical/copy set" in logical_groups
    assert "config/dashboard/defaults" in logical_groups


def test_shared_state_boundary_classifies_paths_and_keeps_parallel_metadata_distinct(tmp_path: Path) -> None:
    from scripts.mst_cmds.dispatch import evaluate_shared_state_boundaries

    repo_root = tmp_path / "repo"
    worktree = repo_root / ".gran-maestro" / "worktrees" / "AGI-040" / "REQ-923" / "02"
    worktree.mkdir(parents=True)
    home = tmp_path / "home"
    plugin_cache = tmp_path / "plugin-cache"
    temp_dir = tmp_path / "tmp"
    sid_a = "MST-AGI-040-20260520T090000000Z-bounda1"
    sid_b = "MST-AGI-040-20260520T090000000Z-boundb2"

    writes = [
        {
            "path": repo_root / ".gran-maestro" / "requests" / "REQ-923" / "request.json",
            "mst_session_id": sid_a,
            "task_id": "REQ-923-02",
            "attempt_id": "REQ-923-02-A1",
        },
        {
            "path": worktree / ".gran-maestro" / "run" / "REQ-923-02.json",
            "mst_session_id": sid_a,
            "task_id": "REQ-923-02",
            "attempt_id": "REQ-923-02-A1",
        },
        {
            "path": home / ".claude" / "gran-maestro-policy" / "allowlist.json",
            "mst_session_id": sid_a,
            "task_id": "REQ-923-02",
            "attempt_id": "REQ-923-02-A1",
        },
        {
            "path": plugin_cache / "omx" / "cache.json",
            "mst_session_id": sid_b,
            "task_id": "REQ-923-03",
            "attempt_id": "REQ-923-03-A1",
        },
        {
            "path": temp_dir / sid_b / "scratch.json",
            "mst_session_id": sid_b,
            "task_id": "REQ-923-03",
            "attempt_id": "REQ-923-03-A1",
        },
    ]

    evidence = evaluate_shared_state_boundaries(
        writes,
        repo_root=repo_root,
        worktree_root=worktree,
        home_root=home,
        plugin_cache_root=plugin_cache,
        temp_root=temp_dir,
    )

    by_path = {Path(entry["path"]).name: entry for entry in evidence["writes"]}
    assert by_path["request.json"]["boundary"] == "repo-local"
    assert by_path["REQ-923-02.json"]["boundary"] == "worktree-local"
    assert by_path["allowlist.json"]["boundary"] == "user-global"
    assert by_path["cache.json"]["boundary"] == "plugin-cache"
    assert by_path["scratch.json"]["boundary"] == "temp-dir"
    assert evidence["metadata_mixed"] is False
    assert evidence["mutation_allowed"] is True

    mixed = dict(writes[1])
    mixed["mst_session_id"] = sid_b
    mixed["task_id"] = "REQ-923-03"
    mixed["attempt_id"] = "REQ-923-03-A1"
    mixed_evidence = evaluate_shared_state_boundaries(
        [writes[1], mixed],
        repo_root=repo_root,
        worktree_root=worktree,
        home_root=home,
        plugin_cache_root=plugin_cache,
        temp_root=temp_dir,
    )
    assert mixed_evidence["metadata_mixed"] is True
    assert mixed_evidence["mutation_allowed"] is False

def test_attempt_ordering_trace_namespace_preserves_unique_attempts_and_fallback_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    artifacts = workspace / "artifacts"
    env = _env()
    task_id = "dod010-attempt-ordering"

    for attempt_id, provider, label, fallback_from in (
        ("dod010-order-a1", "codex", "phase2;impl", None),
        ("dod010-order-a2", "gemini", "phase2/impl\n", "dod010-order-a1"),
        ("dod010-order-a3", "codex", "phase2 impl", None),
    ):
        register = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            task_id,
            "--attempt-id",
            attempt_id,
            "--pid",
            "12345",
            "--provider",
            provider,
            "--model",
            "gpt-test-dod010",
            "--label",
            label,
            "--worktree-dir",
            str(workspace),
            "--running-log-path",
            str(artifacts / provider / attempt_id / "running.log"),
            "--trace-path",
            str(artifacts / provider / attempt_id / "trace.md"),
            *(("--fallback-from", fallback_from) if fallback_from else ()),
            env=env,
        )
        assert register.returncode == 0, register.stderr

    final_a1 = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-order-a1",
        "--final",
        "--exit-code",
        "19",
        "--status",
        "failed",
        "--structured-error-json",
        '{"kind":"provider_failed","message":"primary evidence"}',
        env=env,
    )
    assert final_a1.returncode == 0, final_a1.stderr

    final_a2 = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-order-a2",
        "--final",
        "--exit-code",
        "0",
        "--status",
        "fallback_completed",
        "--fallback-from",
        "dod010-order-a1",
        env=env,
    )
    assert final_a2.returncode == 0, final_a2.stderr

    payload = _read_state(workspace, task_id)
    attempts = payload["attempts"]
    attempt_ids = [attempt["attempt_id"] for attempt in attempts]
    assert attempt_ids == ["dod010-order-a1", "dod010-order-a2", "dod010-order-a3"]
    assert len(attempt_ids) == len(set(attempt_ids))
    assert [attempt["attempt_sequence"] for attempt in attempts] == [1, 2, 3]
    assert payload["attempt_id"] == "dod010-order-a2"
    assert [attempt["current_attempt"] for attempt in attempts] == [False, True, False]

    trace_paths = [attempt["trace_path"] for attempt in attempts]
    assert len(trace_paths) == len(set(trace_paths))
    assert all(attempt["attempt_id"] in attempt["running_log_path"] for attempt in attempts)
    assert all(attempt["attempt_id"] in attempt["trace_path"] for attempt in attempts)

    by_id = {attempt["attempt_id"]: attempt for attempt in attempts}
    assert by_id["dod010-order-a1"]["structured_error"]["message"] == "primary evidence"
    assert by_id["dod010-order-a1"]["fallback_to"] == "dod010-order-a2"
    assert by_id["dod010-order-a2"]["fallback_from"] == "dod010-order-a1"
    assert by_id["dod010-order-a2"]["status"] == "fallback_completed"

    from scripts.mst_cmds.run import _write_trace_file

    log_dir = workspace / "same-second-traces"
    running_log = log_dir / "running.log"
    running_log.parent.mkdir(parents=True, exist_ok=True)
    running_log.write_text("trace source\n", encoding="utf-8")
    trace_1, evidence_1 = _write_trace_file(
        log_dir,
        task_id,
        "codex",
        "gpt-test-dod010",
        "REQ-923/03/phase2;impl",
        "2026-05-20T09:00:00+00:00",
        "2026-05-20T09:00:01+00:00",
        1000,
        0,
        running_log,
        SID,
    )
    trace_2, evidence_2 = _write_trace_file(
        log_dir,
        task_id,
        "codex",
        "gpt-test-dod010",
        "REQ-923/03/phase2;impl",
        "2026-05-20T09:00:00+00:00",
        "2026-05-20T09:00:01+00:00",
        1000,
        0,
        running_log,
        SID,
    )
    assert trace_1 != trace_2
    assert trace_1.exists() and trace_2.exists()
    assert evidence_1["normalized"] == evidence_2["normalized"]


def test_duplicate_stale_finalization_records_evidence_without_overwriting_latest_status(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    task_id = "dod010-duplicate-stale"
    env = _env()

    for attempt_id, provider in (("dod010-stale-a1", "codex"), ("dod010-stale-a2", "gemini")):
        result = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            task_id,
            "--attempt-id",
            attempt_id,
            "--pid",
            "12345",
            "--provider",
            provider,
            "--model",
            "gpt-test-dod010",
            "--worktree-dir",
            str(workspace),
            env=env,
        )
        assert result.returncode == 0, result.stderr

    current_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a2",
        "--final",
        "--exit-code",
        "0",
        "--status",
        "completed",
        env=env,
    )
    assert current_final.returncode == 0, current_final.stderr

    duplicate_same = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a2",
        "--final",
        "--exit-code",
        "0",
        "--status",
        "completed",
        env=env,
    )
    conflicting_duplicate = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a2",
        "--final",
        "--exit-code",
        "22",
        "--status",
        "failed",
        "--structured-error-json",
        '{"kind":"late_conflict","message":"must not replace success"}',
        env=env,
    )
    stale_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a1",
        "--final",
        "--exit-code",
        "17",
        "--status",
        "failed",
        env=env,
    )
    out_of_order_heartbeat = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a1",
        "--phase",
        "running",
        env=env,
    )
    late_same_attempt_heartbeat = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        "dod010-stale-a2",
        "--phase",
        "running",
        env=env,
    )
    assert duplicate_same.returncode == 0, duplicate_same.stderr
    assert conflicting_duplicate.returncode == 0, conflicting_duplicate.stderr
    assert stale_final.returncode == 0, stale_final.stderr
    assert out_of_order_heartbeat.returncode == 0, out_of_order_heartbeat.stderr
    assert late_same_attempt_heartbeat.returncode == 0, late_same_attempt_heartbeat.stderr

    payload = _read_state(workspace, task_id)
    assert payload["attempt_id"] == "dod010-stale-a2"
    assert payload["status"] == "completed"
    assert payload["phase"] == "done"
    assert payload["exit_code"] == 0
    attempts = {attempt["attempt_id"]: attempt for attempt in payload["attempts"]}
    assert attempts["dod010-stale-a2"]["status"] == "completed"
    assert attempts["dod010-stale-a1"]["status"] == "running"

    evidence = payload.get("finalization_evidence")
    assert isinstance(evidence, list)
    reasons = [item["reason"] for item in evidence]
    assert "identical_duplicate_finalization" in reasons
    assert "conflicting_duplicate_finalization" in reasons
    assert "stale_finalization_for_non_current_attempt" in reasons
    assert "out_of_order_heartbeat_for_terminal_task" in reasons
    assert "late_heartbeat_for_terminal_attempt" in reasons
    assert any(item["incoming_attempt_id"] == "dod010-stale-a1" for item in evidence)
    assert any(
        item["incoming_attempt_id"] == "dod010-stale-a2"
        and item["reason"] == "late_heartbeat_for_terminal_attempt"
        for item in evidence
    )


def test_provider_network_guard_uses_local_stub_and_preserves_fallback_security_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    stub = workspace / "guarded-provider.py"
    evidence_path = workspace / "network-guard-evidence.json"
    stub.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "import pathlib",
                "import socket",
                f"path = pathlib.Path({json.dumps(str(evidence_path))})",
                "if os.environ.get('MST_PROVIDER_NETWORK_GUARD') == 'deny':",
                "    path.write_text(json.dumps({'guard': 'deny', 'network_call_attempted': False, 'fallback_required': True}), encoding='utf-8')",
                "    raise SystemExit(42)",
                "socket.create_connection(('example.invalid', 443), timeout=0.01)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from scripts.mst_cmds import set_base_dir
    from scripts.mst_cmds.run import cmd_run

    workspace_dot = workspace / ".gran-maestro"
    workspace_dot.mkdir(parents=True, exist_ok=True)
    set_base_dir(workspace_dot)
    old_env = os.environ.copy()
    guarded_env = _env()
    guarded_env["MST_PROVIDER_NETWORK_GUARD"] = "deny"
    os.environ.clear()
    os.environ.update(guarded_env)
    try:
        result = cmd_run(
            type(
                "Args",
                (),
                {
                    "task_id": "dod010-provider-network-guard",
                    "provider": "codex",
                    "skill": "",
                    "model": "gpt-test-dod010",
                    "log_dir": str(workspace / "provider-logs"),
                    "trace": "REQ-923/03/provider-network-guard",
                    "heartbeat_interval": None,
                    "timeout": None,
                    "attempt_id": "dod010-provider-primary",
                    "label": "provider-primary",
                    "output_path": None,
                    "transcript_summary_path": None,
                    "provider_task_id": None,
                    "parent_session_id": None,
                    "fallback_from": None,
                    "context_file": None,
                    "cli_command": ["--", sys.executable, str(stub)],
                },
            )()
        )
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        set_base_dir(None)

    assert result == 42
    guard_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert guard_evidence == {
        "guard": "deny",
        "network_call_attempted": False,
        "fallback_required": True,
    }

    state = _read_state(workspace, "dod010-provider-network-guard")
    primary = state["attempts"][0]
    assert primary["attempt_id"] == "dod010-provider-primary"
    assert primary["status"] == "failed"
    assert primary["security_evidence"]["provider_network_guard"]["mode"] == "deny"
    assert primary["security_evidence"]["provider_network_guard"]["actual_provider_network_call"] is False

    fallback = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        "dod010-provider-network-guard",
        "--attempt-id",
        "dod010-provider-fallback",
        "--pid",
        "12345",
        "--provider",
        "gemini",
        "--model",
        "gpt-test-dod010",
        "--worktree-dir",
        str(workspace),
        "--fallback-from",
        "dod010-provider-primary",
        env=guarded_env,
    )
    assert fallback.returncode == 0, fallback.stderr
    fallback_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        "dod010-provider-network-guard",
        "--attempt-id",
        "dod010-provider-fallback",
        "--final",
        "--exit-code",
        "0",
        "--status",
        "fallback_completed",
        "--fallback-from",
        "dod010-provider-primary",
        env=guarded_env,
    )
    assert fallback_final.returncode == 0, fallback_final.stderr

    payload = _read_state(workspace, "dod010-provider-network-guard")
    attempts = {attempt["attempt_id"]: attempt for attempt in payload["attempts"]}
    assert attempts["dod010-provider-primary"]["structured_error"]["exit_code"] == 42
    assert attempts["dod010-provider-primary"]["fallback_to"] == "dod010-provider-fallback"
    assert attempts["dod010-provider-fallback"]["status"] == "fallback_completed"
    assert attempts["dod010-provider-fallback"]["fallback_from"] == "dod010-provider-primary"
