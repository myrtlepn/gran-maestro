from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
FAST = REPO_ROOT / "hooks" / "lib" / "pre_tool_use_fast.py"
MST = REPO_ROOT / "scripts" / "mst.py"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
SID = "MST-REQ-851-20260510T104009000Z-a1b2c3d4"
ZERO_HASH = "0" * 64


@dataclass(frozen=True)
class ContractExpectation:
    fixture_id: str
    decision: str
    normalized_reason_code: str
    stdout_contract_id: str
    stderr_contract_id: str
    exit_code: int


@dataclass(frozen=True)
class DecisionTuple:
    decision: str
    normalized_reason_code: str
    stdout_contract_id: str
    stderr_contract_id: str
    exit_code: int


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".gran-maestro" / "tmp").mkdir(parents=True)
    return project


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return home


def _env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "MST_CLAUDE_HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "MST_FLOW_DISABLE_ATEXIT": "1",
        "MST_SESSION_ID": SID,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if extra:
        env.update(extra)
    return env


def _payload(tool_name: str, tool_input: dict) -> dict:
    return {
        "mst_session_id": SID,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _state_path(project: Path) -> Path:
    return project / ".gran-maestro" / "tmp" / f"mst-state-{SID}.json"


def _history_paths(project: Path, home: Path) -> tuple[Path, Path, Path]:
    session_dir = project / ".gran-maestro" / "sessions" / SID
    history_head = session_dir / "history.head"
    verify_state = session_dir / "history.verify"
    mirror_head = home / ".claude" / "gran-maestro-policy" / "ledger-heads" / f"{SID}.head"
    return history_head, verify_state, mirror_head


def _seed_empty_fast_path_cursor(project: Path, home: Path) -> None:
    history_head, verify_state, mirror_head = _history_paths(project, home)
    history_head.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    history_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
    mirror_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
    verify_state.write_text(f"{ZERO_HASH}\tmissing\t0\n", encoding="utf-8")


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


def _rewrite_manifest(policy_project: Path) -> None:
    rules = []
    for rule_file in sorted((policy_project / "rules.d").glob("*.json")):
        rules.append(
            {
                "path": rule_file.relative_to(policy_project).as_posix(),
                "sha256": hashlib.sha256(rule_file.read_bytes()).hexdigest(),
                "last_modified": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    manifest = policy_project / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "rules": rules}, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest, stat.S_IRUSR | stat.S_IWUSR)


def _install_phase_gate_rule(project: Path, home: Path) -> None:
    result = _run_mst(project, home, "policy", "init")
    assert result.returncode == 0, result.stderr
    policy_project = _policy_project(home, project)
    rule_path = policy_project / "rules.d" / "phase-gate.json"
    rule_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "GM-PHASE-GATE",
                        "description": "Phase gate is enforced by hooks/lib/pre_tool_use_fast.py for mutating tool and Bash calls.",
                        "severity": "warn",
                        "trigger": {"tool": "__never__"},
                        "action": {
                            "decision": "warn",
                            "message": "phase gate enforcement is hardcoded",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(rule_path, stat.S_IRUSR | stat.S_IWUSR)
    _rewrite_manifest(policy_project)


def _install_unknown_predicate_rule(project: Path, home: Path) -> None:
    result = _run_mst(project, home, "policy", "init")
    assert result.returncode == 0, result.stderr
    policy_project = _policy_project(home, project)
    rule_path = policy_project / "rules.d" / "unknown.json"
    rule_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "GM-UNKNOWN",
                        "severity": "block",
                        "trigger": {"tool": "Read"},
                        "condition": {"predicate": "unknown_xyz"},
                        "action": {
                            "decision": "block",
                            "message": "unknown predicate must fail closed",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(rule_path, stat.S_IRUSR | stat.S_IWUSR)
    _rewrite_manifest(policy_project)


def _tamper_manifest_rule(project: Path, home: Path) -> None:
    result = _run_mst(project, home, "policy", "init")
    assert result.returncode == 0, result.stderr
    policy_project = _policy_project(home, project)
    rule_path = policy_project / "rules.d" / "core-bypass.json"
    rule_path.write_text(rule_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")


def _corrupt_history_cursor(project: Path, home: Path) -> None:
    _seed_empty_fast_path_cursor(project, home)
    history_file = project / ".gran-maestro" / "sessions" / SID / "history.ndjson"
    history_file.write_text("{not-json}\n", encoding="utf-8")


def _write_workflow_state(project: Path, payload: dict) -> None:
    _state_path(project).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _workflow_active_state() -> dict:
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {"workflow_active": True, "updated_at": updated_at}


def _run_shell_wrapper(project: Path, home: Path, payload: dict | str) -> subprocess.CompletedProcess[str]:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=project,
        env=_env(home),
        input=data,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_python_fast_path(project: Path, home: Path, payload: dict | str) -> subprocess.CompletedProcess[str]:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return subprocess.run(
        ["python3", str(FAST), str(project)],
        cwd=project,
        env=_env(home),
        input=data,
        text=True,
        capture_output=True,
        check=False,
    )


def _stdout_contract_id(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        return "stdout.empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return "stdout.text"
    return "stdout.json_object" if isinstance(payload, dict) else "stdout.json_non_object"


def _stderr_contract_id(stderr: str) -> str:
    stripped = stderr.strip()
    if not stripped:
        return "stderr.empty"
    if "[core-block]" in stripped:
        return "stderr.core_block"
    if "[policy-block]" in stripped:
        return "stderr.policy_block"
    if "history ledger mismatch" in stripped:
        return "stderr.history_mismatch"
    return "stderr.text"


def _normalized_reason_code(stderr: str) -> str:
    if "unknown_predicate" in stderr:
        return "unknown_predicate"
    if "manifest_sha256_mismatch" in stderr:
        return "manifest_sha256_mismatch"
    if "payload_parse_failure" in stderr:
        return "payload_parse_failure"
    if "history ledger mismatch" in stderr:
        return "history_ledger_mismatch"
    for line in stderr.splitlines():
        if "rule=" in line:
            return line.split("rule=", 1)[1].split()[0]
    return ""


def _decision_tuple(result: subprocess.CompletedProcess[str]) -> DecisionTuple:
    if result.returncode == 0:
        decision = "allow"
    elif result.returncode == 2:
        decision = "block"
    else:
        decision = "error"
    return DecisionTuple(
        decision=decision,
        normalized_reason_code=_normalized_reason_code(result.stderr),
        stdout_contract_id=_stdout_contract_id(result.stdout),
        stderr_contract_id=_stderr_contract_id(result.stderr),
        exit_code=result.returncode,
    )


def _assert_contract(
    actual: DecisionTuple,
    expected: ContractExpectation,
    *,
    fixture_id: str,
    policy_contract_id: str,
    policy_path: str,
) -> None:
    assert actual == DecisionTuple(
        decision=expected.decision,
        normalized_reason_code=expected.normalized_reason_code,
        stdout_contract_id=expected.stdout_contract_id,
        stderr_contract_id=expected.stderr_contract_id,
        exit_code=expected.exit_code,
    ), (
        f"fixture_id={fixture_id} policy_contract_id={policy_contract_id} policy_path={policy_path} "
        f"expected_decision={expected.decision} actual_decision={actual.decision} "
        f"expected_reason_code={expected.normalized_reason_code} actual_reason_code={actual.normalized_reason_code} "
        f"expected_exit_code={expected.exit_code} actual_exit_code={actual.exit_code}"
    )


def test_decision_tuple_matches_between_shell_wrapper_and_python_fast_path(tmp_path: Path) -> None:
    fixtures = [
        (
            ContractExpectation(
                fixture_id="schedule_wakeup_active",
                decision="block",
                normalized_reason_code="MST-SCHEDULE-WAKEUP-BLOCK",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.core_block",
                exit_code=2,
            ),
            lambda project, home: _write_workflow_state(
                project,
                _workflow_active_state(),
            ),
            _payload("ScheduleWakeup", {"delaySeconds": 1500}),
        ),
        (
            ContractExpectation(
                fixture_id="ask_user_question_active",
                decision="block",
                normalized_reason_code="MST-ASK-USER-QUESTION-BLOCK",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.core_block",
                exit_code=2,
            ),
            lambda project, home: _write_workflow_state(
                project,
                _workflow_active_state(),
            ),
            _payload("AskUserQuestion", {"question": "Continue?"}),
        ),
        (
            ContractExpectation(
                fixture_id="phase_gate_mutating_bash",
                decision="block",
                normalized_reason_code="GM-PHASE-GATE",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.policy_block",
                exit_code=2,
            ),
            _install_phase_gate_rule,
            _payload("Bash", {"command": "git commit -m x"}),
        ),
        (
            ContractExpectation(
                fixture_id="protected_policy_rule_write",
                decision="block",
                normalized_reason_code="META-BYPASS-RULE-FILE",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.core_block",
                exit_code=2,
            ),
            lambda project, home: None,
            _payload(
                "Write",
                {"file_path": "~/.claude/gran-maestro-policy/projects/demo/rules.d/x.json", "content": "{}"},
            ),
        ),
        (
            ContractExpectation(
                fixture_id="protected_history_write",
                decision="block",
                normalized_reason_code="META-BYPASS-HISTORY-NDJSON",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.core_block",
                exit_code=2,
            ),
            lambda project, home: None,
            _payload(
                "Write",
                {
                    "file_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                    "content": "tamper",
                },
            ),
        ),
    ]

    for expected, setup_fn, payload in fixtures:
        project = _project(tmp_path / expected.fixture_id)
        home = _home(tmp_path / f"{expected.fixture_id}-home")
        _seed_empty_fast_path_cursor(project, home)
        setup_fn(project, home)

        shell_result = _run_shell_wrapper(project, home, payload)
        fast_result = _run_python_fast_path(project, home, payload)

        shell_tuple = _decision_tuple(shell_result)
        fast_tuple = _decision_tuple(fast_result)
        _assert_contract(
            shell_tuple,
            expected,
            fixture_id=expected.fixture_id,
            policy_contract_id="DOD-004-PAC-1",
            policy_path="shell_wrapper",
        )
        _assert_contract(
            fast_tuple,
            expected,
            fixture_id=expected.fixture_id,
            policy_contract_id="DOD-004-PAC-1",
            policy_path="python_fast_path",
        )
        assert shell_tuple == fast_tuple, (
            f"fixture_id={expected.fixture_id} policy_contract_id=DOD-004-PAC-1 "
            f"shell_wrapper={shell_tuple} python_fast_path={fast_tuple}"
        )


def test_matcher_coverage_audit_classifies_declared_fixtures_exactly_once() -> None:
    hooks_payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    matchers = {
        entry.get("matcher")
        for entry in hooks_payload["hooks"].get("PreToolUse", [])
        if isinstance(entry, dict)
    }
    coverage = {
        "skill_runtime_hook": "runtime_guaranteed" if "Skill" in matchers else "out_of_scope",
        "schedule_wakeup_runtime_hook": "runtime_guaranteed" if "ScheduleWakeup" in matchers else "out_of_scope",
        "ask_user_question_direct_fixture": "direct_fixture_only",
        "phase_gate_mutating_bash_direct_fixture": "direct_fixture_only",
        "protected_write_direct_fixture": "direct_fixture_only",
        "alias_function_indirection": "out_of_scope",
    }

    valid_labels = {"runtime_guaranteed", "direct_fixture_only", "out_of_scope"}
    assert all(label in valid_labels for label in coverage.values()), coverage
    assert coverage["skill_runtime_hook"] == "runtime_guaranteed", coverage
    assert coverage["schedule_wakeup_runtime_hook"] == "runtime_guaranteed", coverage
    for fixture_id in (
        "ask_user_question_direct_fixture",
        "phase_gate_mutating_bash_direct_fixture",
        "protected_write_direct_fixture",
    ):
        assert coverage[fixture_id] == "direct_fixture_only", (
            f"fixture_id={fixture_id} must not be labeled runtime_guaranteed without hooks/hooks.json matcher coverage"
        )
    assert coverage["alias_function_indirection"] == "out_of_scope", coverage


def test_failure_modes_fail_closed_with_contract_evidence(tmp_path: Path) -> None:
    fixtures = [
        (
            "parse_failure",
            "DOD-004-PAC-3",
            lambda project, home: _seed_empty_fast_path_cursor(project, home),
            "{",
            ContractExpectation(
                fixture_id="parse_failure",
                decision="block",
                normalized_reason_code="payload_parse_failure",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.policy_block",
                exit_code=2,
            ),
        ),
        (
            "unknown_predicate",
            "DOD-004-PAC-3",
            _install_unknown_predicate_rule,
            _payload("Read", {"file_path": "README.md"}),
            ContractExpectation(
                fixture_id="unknown_predicate",
                decision="block",
                normalized_reason_code="unknown_predicate",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.policy_block",
                exit_code=2,
            ),
        ),
        (
            "manifest_mismatch",
            "DOD-004-PAC-3",
            _tamper_manifest_rule,
            _payload("Read", {"file_path": "README.md"}),
            ContractExpectation(
                fixture_id="manifest_mismatch",
                decision="block",
                normalized_reason_code="manifest_sha256_mismatch",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.policy_block",
                exit_code=2,
            ),
        ),
        (
            "ledger_corruption",
            "DOD-004-PAC-3",
            _corrupt_history_cursor,
            _payload("Read", {"file_path": "README.md"}),
            ContractExpectation(
                fixture_id="ledger_corruption",
                decision="block",
                normalized_reason_code="history_ledger_mismatch",
                stdout_contract_id="stdout.empty",
                stderr_contract_id="stderr.history_mismatch",
                exit_code=2,
            ),
        ),
    ]

    for fixture_id, contract_id, setup_fn, payload, expected in fixtures:
        project = _project(tmp_path / fixture_id)
        home = _home(tmp_path / f"{fixture_id}-home")
        if fixture_id != "ledger_corruption":
            _seed_empty_fast_path_cursor(project, home)
        setup_fn(project, home)

        for policy_path, runner in (
            ("shell_wrapper", _run_shell_wrapper),
            ("python_fast_path", _run_python_fast_path),
        ):
            result = runner(project, home, payload)
            actual = _decision_tuple(result)
            _assert_contract(
                actual,
                expected,
                fixture_id=fixture_id,
                policy_contract_id=contract_id,
                policy_path=policy_path,
            )
