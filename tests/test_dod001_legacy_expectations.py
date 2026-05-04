from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "SESSION-ID-MIGRATION.md"
DOD001_TEST_PATHS = sorted((REPO_ROOT / "tests").glob("test_dod001*.py")) + sorted(
    (REPO_ROOT / "tests" / "hooks").glob("test_dod001*.sh")
)

FORBIDDEN_DOC_PATTERNS = [
    (
        "Claude hook session_id described as canonical",
        re.compile(r"`session_id`[^.\n]*(?:canonical|정체성 축|source of truth)", re.IGNORECASE),
    ),
    (
        "transcript_path fallback described as canonical recovery",
        re.compile(r"transcript_path[^.\n]*(?:fallback|canonical|source)", re.IGNORECASE),
    ),
    (
        "PPID fallback remains fail-open",
        re.compile(r"PPID fallback|PPID를?[^.\n]*fallback|PPID 우선", re.IGNORECASE),
    ),
    (
        "owner_session_id is required as canonical owner",
        re.compile(r"owner_session_id[^.\n]*(?:공통 정체성|canonical|우선|기준)", re.IGNORECASE),
    ),
]

FORBIDDEN_TEST_PATTERNS = [
    (
        "DOD-001 canonical fixture is not structured mst_session_id",
        re.compile(r"\b(?:ROOT|STALE)_SESSION_ID\s*=\s*[\"'](?!MST-)"),
    ),
    (
        "legacy key used in canonical_id_set",
        re.compile(
            r"canonical_id_set[^=\n]*=.*(?:\bsession_id\b|owner_session_id|owner_ppid|MST_STATE_PPID)",
            re.IGNORECASE,
        ),
    ),
    (
        "legacy env alias expected as canonical field",
        re.compile(r"assert .*mst_session_id.*(?:MST_STATE_PPID|MST_SNAPSHOT_SESSION_ID|owner_ppid)"),
    ),
]

REQUIRED_DOC_PHRASES = [
    "AGI-030 DOD-001",
    "AGI-030 DOD-002",
    "`MST_SESSION_ID` / `mst_session_id`",
    "root MST ID, compact UTC start timestamp, and path-safe random segment",
    "diagnostic-only",
    "legacy compatibility",
    "canonical source, fallback, path partition, or equality input",
]


def _violations(path: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    results: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if "DOD-001 allow-legacy-wording" in line:
            continue
        lowered = line.lower()
        if any(token in line for token in ("아니다", "아니며", "될 수 없다")):
            continue
        if "not " in lowered or "diagnostic-only" in lowered:
            continue
        for label, pattern in patterns:
            if pattern.search(line):
                results.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {label}: {line.strip()}")
    return results


def test_session_id_migration_doc_marks_legacy_values_diagnostic_only() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    missing = [phrase for phrase in REQUIRED_DOC_PHRASES if phrase not in text]
    assert missing == []
    violations = _violations(DOC_PATH, FORBIDDEN_DOC_PATTERNS)
    assert violations == []


def test_dod001_tests_do_not_expect_legacy_values_as_canonical_identity() -> None:
    violations: list[str] = []
    for path in DOD001_TEST_PATHS:
        if path.name == Path(__file__).name:
            continue
        violations.extend(_violations(path, FORBIDDEN_TEST_PATTERNS))
    assert violations == []


def main() -> int:
    tests = [
        test_session_id_migration_doc_marks_legacy_values_diagnostic_only,
        test_dod001_tests_do_not_expect_legacy_values_as_canonical_identity,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
