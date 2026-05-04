from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_CONTRACT_FILES = [
    "skills/agile/SKILL.md",
    "skills/plan/SKILL.md",
    "skills/request/SKILL.md",
    "skills/approve/SKILL.md",
    "skills/accept/SKILL.md",
    "skills/agile-plan/SKILL.md",
    "skills/on/SKILL.md",
    "skills/off/SKILL.md",
    "skills/recover/SKILL.md",
]

LEGACY_TERMS = [
    "MST_STATE_PPID",
    "owner_ppid",
    "owner_session_id",
    "sessionId",
    "MST_SNAPSHOT_SESSION_ID",
]


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def test_skill_state_write_examples_do_not_inject_legacy_ppid() -> None:
    violations = []
    for relative_path in SKILL_CONTRACT_FILES:
        text = _text(relative_path)
        if 'MST_STATE_PPID="${PPID}"' in text:
            violations.append(f"{relative_path}: canonical skill state writes must inherit MST_SESSION_ID")

        for match in re.finditer(r"```bash\n(?P<body>.*?)```", text, re.DOTALL):
            body = match.group("body")
            if "state set" not in body:
                continue
            if "MST_STATE_PPID" in body:
                line = _line_number(text, match.start())
                violations.append(f"{relative_path}:{line}: state write block injects MST_STATE_PPID")

    assert not violations, "DOD-003 skill contract violations:\n" + "\n".join(violations)


def test_skill_docs_name_inherited_session_contract_for_state_writes() -> None:
    missing = []
    for relative_path in SKILL_CONTRACT_FILES:
        text = _text(relative_path)
        if "state set" not in text:
            continue
        if "MST_SESSION_ID" not in text or "structured context" not in text:
            missing.append(f"{relative_path}: must name inherited MST_SESSION_ID / structured context contract")

    assert not missing, "\n".join(missing)


def test_legacy_terms_in_session_docs_are_diagnostic_or_migration_only() -> None:
    text = _text("docs/SESSION-ID-MIGRATION.md")
    required_contract = (
        "`MST_STATE_PPID` is not a state management or skill execution contract; "
        "it is a diagnostic-only legacy compatibility value."
    )
    assert required_contract in text

    forbidden_patterns = [
        (r"uses?\s+`?MST_STATE_PPID`?\s+as\s+canonical", "MST_STATE_PPID must not be canonical"),
        (r"`?MST_STATE_PPID`?\s+fallback", "MST_STATE_PPID must not be a fallback"),
        (r"owner_ppid-only files are accepted", "owner_ppid must not be accepted as fallback"),
        (r"owner_session_id is authoritative", "owner_session_id must not be authoritative"),
        (r"sessionId.*canonical lookup", "sessionId must not be canonical lookup input"),
        (r"`?MST_SNAPSHOT_SESSION_ID`?\s+fallback", "MST_SNAPSHOT_SESSION_ID must not be fallback input"),
    ]
    violations = []
    for pattern, reason in forbidden_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            line = _line_number(text, match.start())
            violations.append(f"docs/SESSION-ID-MIGRATION.md:{line}: {reason}")

    for term in LEGACY_TERMS:
        for match in re.finditer(re.escape(term), text):
            paragraph_start = text.rfind("\n\n", 0, match.start()) + 2
            paragraph_end = text.find("\n\n", match.end())
            if paragraph_end == -1:
                paragraph_end = len(text)
            paragraph = text[paragraph_start:paragraph_end].lower()
            if not any(marker in paragraph for marker in ("diagnostic", "migration", "compatibility", "deprecated", "legacy")):
                line_number = _line_number(text, match.start())
                violations.append(
                    f"docs/SESSION-ID-MIGRATION.md:{line_number}: {term} lacks diagnostic/migration context"
                )

    assert not violations, "DOD-003 legacy docs context violations:\n" + "\n".join(violations)


def main() -> int:
    tests = [
        test_skill_state_write_examples_do_not_inject_legacy_ppid,
        test_skill_docs_name_inherited_session_contract_for_state_writes,
        test_legacy_terms_in_session_docs_are_diagnostic_or_migration_only,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
