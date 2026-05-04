from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

DOC_PATHS = [
    "README.md",
    "docs/CLAUDE.md",
    "docs/SESSION-ID-MIGRATION.md",
    "docs/skills-reference.md",
    "skills/recover/SKILL.md",
    "skills/history/SKILL.md",
    "skills/resume/SKILL.md",
    "skills/request/SKILL.md",
    "skills/approve/SKILL.md",
    "skills/accept/SKILL.md",
    "skills/agile/SKILL.md",
]

LEGACY_TERMS = [
    "MST_STATE_PPID",
    "owner_ppid",
    "owner_session_id",
    "owner_pid",
    "Claude hook `session_id`",
    "transcript UUID",
    "MST_SNAPSHOT_SESSION_ID",
    "legacy aliases `sessionId`/`session_id`",
]

REQUIRED_PHRASES = [
    "DOD-007 canonical identity boundary",
    "`MST_SESSION_ID` / `mst_session_id`만 canonical identity source",
    "diagnostic-only",
    "canonical source, fallback, alias, migration requirement가 아니다",
    "session/state/history/snapshot/recovery/lock mutation 없이 structured non-success",
    "canonical identity가 우선",
    "override/repair/merge/persist source가 될 수 없다",
]

FORBIDDEN_PATTERNS = [
    (r"MST_STATE_PPID.*canonical (identity )?source", "MST_STATE_PPID must not be a canonical source"),
    (r"owner_ppid.*canonical (identity )?source", "owner_ppid must not be a canonical source"),
    (r"owner_session_id.*canonical (identity )?source", "owner_session_id must not be a canonical source"),
    (r"owner_pid.*canonical (identity )?source", "owner_pid must not be a canonical source"),
    (r"sessionId.*canonical (lookup|identity|source)", "sessionId must not be canonical lookup input"),
    (r"MST_SNAPSHOT_SESSION_ID.*fallback", "MST_SNAPSHOT_SESSION_ID must not be a fallback"),
    (r"legacy.*override.*canonical", "legacy values must not override canonical identity"),
    (r"legacy.*repair.*canonical", "legacy values must not repair canonical identity"),
]


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def test_dod007_docs_name_canonical_only_identity_boundary() -> None:
    missing = []
    for relative_path in DOC_PATHS:
        text = _text(relative_path)
        for phrase in REQUIRED_PHRASES:
            if phrase not in text:
                missing.append(f"{relative_path}: missing {phrase!r}")

    assert not missing, "DOD-007 canonical identity docs missing:\n" + "\n".join(missing)


def _dod007_block(text: str) -> str:
    marker = "DOD-007 canonical identity boundary"
    start = text.find(marker)
    if start == -1:
        return ""
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith("#"):
        next_heading = re.search(r"\n#{1,6}\s+", text[start + len(marker) :])
        if next_heading:
            return text[line_start : start + len(marker) + next_heading.start()]
        return text[line_start:]
    end = text.find("\n\n", start)
    if end == -1:
        end = len(text)
    return text[start:end]


def test_dod007_docs_list_all_legacy_terms_as_diagnostic_only() -> None:
    violations = []
    for relative_path in DOC_PATHS:
        block = _dod007_block(_text(relative_path))
        if not block:
            violations.append(f"{relative_path}: missing DOD-007 boundary block")
            continue
        if "diagnostic-only" not in block:
            violations.append(f"{relative_path}: DOD-007 block must say legacy input is diagnostic-only")
        for term in LEGACY_TERMS:
            if term not in block:
                violations.append(f"{relative_path}: DOD-007 block missing legacy diagnostic term {term}")

    assert not violations, "DOD-007 legacy diagnostic docs violations:\n" + "\n".join(violations)


def test_dod007_docs_do_not_describe_legacy_as_fallback_or_repair_source() -> None:
    violations = []
    for relative_path in DOC_PATHS:
        text = _text(relative_path)
        for pattern, reason in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                paragraph_start = text.rfind("\n\n", 0, match.start()) + 2
                paragraph_end = text.find("\n\n", match.end())
                if paragraph_end == -1:
                    paragraph_end = len(text)
                paragraph = text[paragraph_start:paragraph_end]
                lowered = paragraph.lower()
                if any(token in paragraph for token in ("아니다", "아니며", "될 수 없다")):
                    continue
                if "not " in lowered or "diagnostic-only" in lowered:
                    continue
                line = _line_number(text, match.start())
                violations.append(f"{relative_path}:{line}: {reason}")

    assert not violations, "DOD-007 forbidden docs phrasing:\n" + "\n".join(violations)


def main() -> int:
    tests = [
        test_dod007_docs_name_canonical_only_identity_boundary,
        test_dod007_docs_list_all_legacy_terms_as_diagnostic_only,
        test_dod007_docs_do_not_describe_legacy_as_fallback_or_repair_source,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
