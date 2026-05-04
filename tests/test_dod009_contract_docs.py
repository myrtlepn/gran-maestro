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

SKILL_PATHS = [
    "skills/recover/SKILL.md",
    "skills/history/SKILL.md",
    "skills/resume/SKILL.md",
    "skills/request/SKILL.md",
    "skills/approve/SKILL.md",
    "skills/accept/SKILL.md",
    "skills/agile/SKILL.md",
]

GLOSSARY_REQUIRED_PHRASES = [
    "DOD-009 session identity glossary",
    "`mst_session_id`",
    "`MST_SESSION_ID`",
    "`MST-{root_mst_id}-{started_at_compact}-{random}`",
    "root resource ID",
    "root component",
    "not the full canonical session identity",
    "process diagnostic ID",
    "diagnostic output is allowed",
    "legacy aliases",
    "not canonical source, fallback, alias, migration requirement",
]

SKILL_REQUIRED_PHRASES = [
    ".gran-maestro/state/{mst_session_id}/snapshot.json",
    ".gran-maestro/sessions/{mst_session_id}/history.*",
    "source precedence",
    "child invocation",
]

FORBIDDEN_GLOSSARY_PATTERNS = [
    (r"resource ID.*canonical ((session )?identity )?source", "resource ID must not be a canonical identity source"),
    (r"resource ID.*fallback", "resource ID must not be a fallback"),
    (r"resource ID.*alias", "resource ID must not be a canonical alias"),
    (r"resource ID.*migration requirement", "resource ID must not be a migration requirement"),
    (r"root resource ID.*canonical ((session )?identity )?source", "root resource ID must not be a canonical identity source"),
    (r"root resource ID.*fallback", "root resource ID must not be a fallback"),
    (r"root resource ID.*alias", "root resource ID must not be a canonical alias"),
    (r"root resource ID.*migration requirement", "root resource ID must not be a migration requirement"),
    (r"process diagnostic ID.*canonical ((session )?identity )?source", "process diagnostic ID must not be a canonical source"),
    (r"process diagnostic ID.*fallback", "process diagnostic ID must not be a fallback"),
    (r"process diagnostic ID.*alias", "process diagnostic ID must not be a canonical alias"),
    (r"process diagnostic ID.*migration requirement", "process diagnostic ID must not be a migration requirement"),
    (r"owner_pid.*canonical ((session )?identity )?source", "owner_pid must not be a canonical source"),
    (r"owner_pid.*fallback", "owner_pid must not be a fallback"),
    (r"owner_pid.*alias", "owner_pid must not be a canonical alias"),
    (r"owner_pid.*migration requirement", "owner_pid must not be a migration requirement"),
    (r"MST_STATE_PPID.*canonical ((session )?identity )?source", "MST_STATE_PPID must not be a canonical source"),
    (r"MST_STATE_PPID.*fallback", "MST_STATE_PPID must not be a fallback"),
    (r"MST_STATE_PPID.*alias", "MST_STATE_PPID must not be a canonical alias"),
    (r"MST_STATE_PPID.*migration requirement", "MST_STATE_PPID must not be a migration requirement"),
    (r"hook `session_id`.*canonical ((session )?identity )?source", "hook session_id must not be a canonical source"),
    (r"hook `session_id`.*fallback", "hook session_id must not be a fallback"),
    (r"hook `session_id`.*alias", "hook session_id must not be a canonical alias"),
    (r"hook `session_id`.*migration requirement", "hook session_id must not be a migration requirement"),
    (r"transcript UUID.*canonical ((session )?identity )?source", "transcript UUID must not be a canonical source"),
    (r"transcript UUID.*fallback", "transcript UUID must not be a fallback"),
    (r"transcript UUID.*alias", "transcript UUID must not be a canonical alias"),
    (r"transcript UUID.*migration requirement", "transcript UUID must not be a migration requirement"),
    (r"legacy aliases.*canonical ((session )?identity )?source", "legacy aliases must not be a canonical source"),
    (r"legacy aliases.*fallback", "legacy aliases must not be a fallback"),
    (r"legacy aliases.*alias", "legacy aliases must not be a canonical alias"),
    (r"legacy aliases.*migration requirement", "legacy aliases must not be a migration requirement"),
]

DIAGNOSTIC_BAN_PATTERNS = [
    r"diagnostic output (is )?(forbidden|banned|prohibited)",
    r"diagnostics output (is )?(forbidden|banned|prohibited)",
    r"diagnostic values must not be printed",
    r"diagnostic visibility is forbidden",
]


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _heading_or_paragraph_block(text: str, marker: str) -> str:
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


def _dod009_block(text: str) -> str:
    return _heading_or_paragraph_block(text, "DOD-009 session identity glossary")


def _dod007_block(text: str) -> str:
    return _heading_or_paragraph_block(text, "DOD-007 canonical identity boundary")


def _negated_or_diagnostic_context(paragraph: str) -> bool:
    lowered = paragraph.lower()
    return (
        any(token in paragraph for token in ("아니다", "아니며", "될 수 없다"))
        or "not " in lowered
        or "diagnostic-only" in lowered
        or "diagnostic output is allowed" in lowered
    )


def test_dod009_docs_define_session_identity_glossary_terms() -> None:
    violations = []
    for relative_path in DOC_PATHS:
        block = _dod009_block(_text(relative_path))
        if not block:
            violations.append(f"{relative_path}: missing DOD-009 glossary block")
            continue
        for phrase in GLOSSARY_REQUIRED_PHRASES:
            if phrase not in block:
                violations.append(f"{relative_path}: DOD-009 block missing {phrase!r}")

    assert not violations, "DOD-009 glossary docs violations:\n" + "\n".join(violations)


def test_dod009_skill_docs_use_canonical_state_history_recover_terms() -> None:
    violations = []
    for relative_path in SKILL_PATHS:
        block = _dod009_block(_text(relative_path))
        if not block:
            violations.append(f"{relative_path}: missing DOD-009 glossary block")
            continue
        for phrase in SKILL_REQUIRED_PHRASES:
            if phrase not in block:
                violations.append(f"{relative_path}: DOD-009 skill block missing {phrase!r}")

    assert not violations, "DOD-009 skill docs terminology violations:\n" + "\n".join(violations)


def test_dod009_docs_do_not_describe_resource_or_diagnostic_ids_as_canonical_sources() -> None:
    violations = []
    for relative_path in DOC_PATHS:
        text = _text(relative_path)
        block = _dod009_block(text)
        if not block:
            violations.append(f"{relative_path}: missing DOD-009 glossary block")
            continue
        block_start = text.find(block)
        for pattern, reason in FORBIDDEN_GLOSSARY_PATTERNS:
            for match in re.finditer(pattern, block, re.IGNORECASE):
                paragraph_start = block.rfind("\n\n", 0, match.start()) + 2
                paragraph_end = block.find("\n\n", match.end())
                if paragraph_end == -1:
                    paragraph_end = len(block)
                paragraph = block[paragraph_start:paragraph_end]
                if _negated_or_diagnostic_context(paragraph):
                    continue
                line = _line_number(text, block_start + match.start())
                violations.append(f"{relative_path}:{line}: {reason}")

    assert not violations, "DOD-009 forbidden docs phrasing:\n" + "\n".join(violations)


def test_dod009_docs_preserve_dod007_diagnostic_visibility_boundary() -> None:
    violations = []
    for relative_path in DOC_PATHS:
        text = _text(relative_path)
        dod007_block = _dod007_block(text)
        dod009_block = _dod009_block(text)
        if not dod007_block:
            violations.append(f"{relative_path}: missing DOD-007 boundary block")
            continue
        if "diagnostic-only" not in dod007_block:
            violations.append(f"{relative_path}: DOD-007 block must keep diagnostic-only visibility wording")
        if "structured non-success" not in dod007_block:
            violations.append(f"{relative_path}: DOD-007 block must keep non-mutating failure wording")
        for pattern in DIAGNOSTIC_BAN_PATTERNS:
            if re.search(pattern, dod009_block, re.IGNORECASE):
                violations.append(f"{relative_path}: DOD-009 block must not ban diagnostic output itself")

    assert not violations, "DOD-009 diagnostic visibility regressions:\n" + "\n".join(violations)


def main() -> int:
    tests = [
        test_dod009_docs_define_session_identity_glossary_terms,
        test_dod009_skill_docs_use_canonical_state_history_recover_terms,
        test_dod009_docs_do_not_describe_resource_or_diagnostic_ids_as_canonical_sources,
        test_dod009_docs_preserve_dod007_diagnostic_visibility_boundary,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
