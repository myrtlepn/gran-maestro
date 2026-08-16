import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGILE_SKILL_MD = PROJECT_ROOT / "skills" / "agile" / "SKILL.md"
DISPOSITION_JSON = PROJECT_ROOT / ".gran-maestro" / "agile" / "AGI-040" / "sprints" / "S02" / "dod-002-disposition.json"
DISPOSITION_SKIP_REASON = (
    "requires local workflow evidence: "
    ".gran-maestro/agile/AGI-040/sprints/S02/dod-002-disposition.json "
    "is ignored and may be absent in clean checkouts"
)
ALLOWED_CLAUDE_PRINT_MODE_PATHS = {
    "tests/test_dod005_agent_dispatch_replacement_contract.py": "negative_fixture_allowlist",
    "tests/test_dispatch_build.py": "external_adapter_contract_fixture",
}
CANONICAL_CLAUDE_EXTERNAL_ADAPTER_PATH = "scripts/mst_cmds/dispatch_shards/part_001.py"
CLAUDE_EXTERNAL_FALLBACK_MARKER = "MST_EXTERNAL_FALLBACK_ONLY"
CLAUDE_PRINT_MODE_SCAN_ROOTS = ("skills", "scripts", "hooks", "docs", "tests")
CLAUDE_PRINT_MODE_DIRECT_RE = re.compile(r"claude\s+(-p|--print)\b")
CLAUDE_PRINT_MODE_ARGV_RE = re.compile(
    r"[\[\(]\s*['\"]claude['\"]\s*,\s*['\"](-p|--print)['\"]",
    re.DOTALL,
)


def _skill_text() -> str:
    return AGILE_SKILL_MD.read_text(encoding="utf-8")


def _text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _disposition_rows() -> dict[str, dict]:
    if not DISPOSITION_JSON.exists():
        pytest.skip(DISPOSITION_SKIP_REASON)
    data = json.loads(DISPOSITION_JSON.read_text(encoding="utf-8"))
    return {row["stable_id"]: row for row in data["rows"]}


def _line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _line_at(text: str, line_number: int) -> str:
    lines = text.splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()
    return ""


def _claude_print_mode_hits_in_text(relative_path: str, text: str) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    seen: set[tuple[int, str]] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        if CLAUDE_PRINT_MODE_DIRECT_RE.search(line):
            stripped = line.strip()
            hits.append((relative_path, line_number, stripped))
            seen.add((line_number, stripped))

    for match in CLAUDE_PRINT_MODE_ARGV_RE.finditer(text):
        line_number = _line_number_for_offset(text, match.start())
        stripped = _line_at(text, line_number)
        if (line_number, stripped) not in seen:
            hits.append((relative_path, line_number, stripped))
            seen.add((line_number, stripped))

    return hits


def _claude_print_mode_hits() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for root_name in CLAUDE_PRINT_MODE_SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            hits.extend(_claude_print_mode_hits_in_text(relative_path, text))
    return hits


def test_dispatch_d_uses_provider_neutral_managed_delegation():
    text = _skill_text()
    forbidden_print_mode = "claude" + " " + "-p"

    assert 'PROVIDER=$(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.dispatch.provider' in text
    assert 'MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model "$PROVIDER" default' in text
    assert "--provider codex" in text
    assert "codex exec --approve-for-me" in text
    assert "--provider agy" in text
    assert "agy --print" in text
    assert "--dangerously-skip-permissions" in text
    assert "gemini" + " -p" not in text
    assert (
        'Skill(skill: "mst:claude", args: "--prompt-file sprint-prompt.md '
        '--dir {PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/ '
        '--trace {AGI_ID}/S{NN}/dispatch")'
    ) in text
    assert "MST_PARENT_BINDING" not in text
    assert "python3 {PLUGIN_ROOT}/scripts/mst.py run" in text
    assert '--task-id "{AGI_ID}-S{NN}"' in text
    assert '--provider "$PROVIDER"' in text
    assert '--model "$MODEL"' in text
    assert '--log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/"' in text
    assert "sprint dispatch lifecycle tuple" in text
    assert "prompt source: `sprint-prompt.md`" in text
    assert "cwd/worktree: `{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/`" in text
    assert "running log path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/running.log`" in text
    assert "trace path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/traces/{provider}-*.md`" in text
    assert "running log tee / trace path / session metadata / output-failure contract / exit code propagation" in text
    assert forbidden_print_mode not in text


def test_dispatch_d_exit_handling_preserved():
    text = _skill_text()

    assert "4. 종료 신호 수신:" in text
    assert "provider exit code를 확인" in text
    assert "dispatch-result.json" in text
    assert "실패 조건: `exit_code != 0` 또는 `dispatch-result.json` 미생성." in text
    assert (
        "python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} --status failed --summary "
        "\"{failure_reason}\""
    ) in text


def test_inline_marker_directive_present():
    text = _skill_text()

    assert "**추가: inline 경로 경량 추적 마커 (MANDATORY)**" in text
    assert "{PROJECT_ROOT}/.gran-maestro/run/{AGI_ID}-S{NN}.json" in text
    assert '"task_id": "{AGI_ID}-S{NN}"' in text
    assert '"phase": "running"' in text
    assert '"inline": true' in text
    assert "`terminated_at`, `exit_code`, `last_heartbeat`" in text
    assert "inline 경로는 `dispatch-result.json`을 **생성하지 않는다** (ADR-007 하위 호환 유지)." in text


def test_dod002_disposition_covers_target_rows():
    rows = _disposition_rows()

    expected_ids = {
        "DOD001-P010",
        "DOD001-P053",
        "DOD001-P054",
        "DOD001-P062",
        "DOD001-P063",
        "DOD001-P064",
        "DOD001-P067",
        "DOD001-P068",
        "DOD001-P069",
        "DOD001-P070",
        "DOD001-P108",
        "DOD001-S004",
        "DOD001-S009",
    }

    assert set(rows) == expected_ids
    for row in rows.values():
        assert row["disposition"] in {
            "remove_runtime",
            "rewrite_guidance_to_new_contract",
            "temporary_exception",
            "reclassify_nonruntime",
        }
        assert row["reason"]
        assert row["replacement_contract"]
        assert row["verification_status"]


def test_dod002_continuation_and_agile_rows_use_expected_contracts():
    rows = _disposition_rows()

    for stable_id in ("DOD001-P053", "DOD001-P054"):
        row = rows[stable_id]
        assert row["disposition"] == "temporary_exception"
        assert row["reason"] == "continuation_exception_until_lifecycle_runner"
        assert row["expiry_dod"] == "DOD-003-or-lifecycle-runner"
        assert row["allowed_active_state"] == "active"
        assert row["allowed_runtime_boundary"] == "plugin_canonical"

    agile_row = rows["DOD001-P108"]
    assert agile_row["disposition"] == "rewrite_guidance_to_new_contract"
    assert "mst:claude" in agile_row["replacement_contract"]
    assert "lifecycle contract preserved" in agile_row["verification_status"]


def test_dod006_claude_print_mode_hits_are_allowlisted_nonruntime_only():
    assert "hooks" in CLAUDE_PRINT_MODE_SCAN_ROOTS

    hits = _claude_print_mode_hits()

    unexpected: list[str] = []
    seen_allowlist: set[str] = set()
    canonical_adapter_hits: list[tuple[int, str]] = []

    for relative_path, line_number, line in hits:
        if relative_path == CANONICAL_CLAUDE_EXTERNAL_ADAPTER_PATH:
            assert CLAUDE_EXTERNAL_FALLBACK_MARKER in line
            canonical_adapter_hits.append((line_number, line))
            continue
        if relative_path in ALLOWED_CLAUDE_PRINT_MODE_PATHS:
            seen_allowlist.add(relative_path)
            assert relative_path.startswith("tests/")
            assert "DIRECT_CLI_TOKENS" in line
            continue
        unexpected.append(f"{relative_path}:{line_number}: {line}")

    assert len(canonical_adapter_hits) == 1
    assert seen_allowlist == set(ALLOWED_CLAUDE_PRINT_MODE_PATHS)
    assert not unexpected, "unexpected direct Claude print-mode hits:\n" + "\n".join(unexpected)

    dispatch_runner = (PROJECT_ROOT / CANONICAL_CLAUDE_EXTERNAL_ADAPTER_PATH).read_text(
        encoding="utf-8"
    )
    adapter_match = re.search(
        r'^    elif provider == "claude":\n(?P<body>.*?)(?=^    else:)',
        dispatch_runner,
        re.DOTALL | re.MULTILINE,
    )
    assert adapter_match is not None
    adapter_contract = adapter_match.group("body")
    assert adapter_contract.count(CLAUDE_EXTERNAL_FALLBACK_MARKER) == 1
    assert CLAUDE_PRINT_MODE_DIRECT_RE.search(adapter_contract)
    assert "--permission-mode acceptEdits" in adapter_contract
    assert "--dangerously-skip-permissions" not in adapter_contract
    assert "--add-dir {q(str(worktree_dir))}" in adapter_contract

    shared_route_contract = _text("skills/_shared/delegation-routing.md")
    claude_skill = _text("skills/claude/SKILL.md")
    assert "`route=external`: 이 경우에만" in shared_route_contract
    assert "**External lane only** — `route=external`인 경우에만" in claude_skill
    assert "provider argv assembly" in claude_skill


def test_dod006_claude_print_mode_scanner_detects_argv_style_invocations():
    cli = "claude"
    short_print = "-p"
    long_print = "--print"
    fixtures = [
        f"cmd = [{cli!r}, {short_print!r}, 'prompt']",
        f"cmd = [{cli!r}, {long_print!r}, 'prompt']",
        f"subprocess.run(({cli!r}, {short_print!r}, 'prompt'))",
        f"const cmd = [{cli!r}, {long_print!r}, prompt];",
    ]

    for index, fixture in enumerate(fixtures, start=1):
        hits = _claude_print_mode_hits_in_text(f"source/runtime/fixture-{index}", fixture)
        assert hits, fixture
