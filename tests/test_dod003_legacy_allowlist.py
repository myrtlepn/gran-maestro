from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_DOCS = [
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


@dataclass(frozen=True)
class RequiredContext:
    path: str
    anchor: str
    legacy_text: str


@dataclass(frozen=True)
class ForbiddenContext:
    path: str
    pattern: re.Pattern[str]
    reason: str


REQUIRED_CONTEXTS = [
    RequiredContext("scripts/mst_cmds/_common.py", "legacy_session_diagnostics", "MST_STATE_PPID"),
    RequiredContext("scripts/mst_cmds/state.py", "_collect_migration_targets", "legacy PPID state directories"),
    RequiredContext("scripts/mst_cmds/state.py", "state migrate: PPID -> session_id migration entry point", "migrate"),
    RequiredContext("hooks/mst-stop-hook.sh", "owner_ppid-only workflow state ignored", "diagnostic"),
    RequiredContext("scripts/mst-statusline.sh", "deprecated alias: PPID-scoped compatibility only", "MST_STATE_PPID"),
    RequiredContext(
        "docs/SESSION-ID-MIGRATION.md",
        "diagnostic-only legacy compatibility value",
        "MST_STATE_PPID",
    ),
    RequiredContext(
        "docs/SESSION-ID-MIGRATION.md",
        "non-mutating compatibility diagnostics",
        "MST_SNAPSHOT_SESSION_ID",
    ),
    RequiredContext(
        "docs/SESSION-ID-MIGRATION.md",
        "canonical workflow state 선택 근거가 아니다",
        "owner_ppid",
    ),
]

FORBIDDEN_CONTEXTS = [
    ForbiddenContext(
        "scripts/mst-statusline.sh",
        re.compile(r"\.gran-maestro/state/\$\{legacy_ppid\}/snapshot\.json"),
        "statusline must not select PPID-scoped snapshots as canonical display state",
    ),
    ForbiddenContext(
        "scripts/mst-statusline.sh",
        re.compile(r"\.gran-maestro/state/default/snapshot\.json"),
        "statusline must not fall back to default snapshot as canonical display state",
    ),
    ForbiddenContext(
        "scripts/mst-statusline.sh",
        re.compile(r"\band\s+metadata_owner_ppid_matches\("),
        "flow rendering must not scope active work by owner_ppid",
    ),
    ForbiddenContext(
        "hooks/mst-stop-hook.sh",
        re.compile(r"owner_session_id is authoritative for session isolation"),
        "owner_session_id-only resource metadata must not be authoritative workflow evidence",
    ),
    ForbiddenContext(
        "hooks/mst-stop-hook.sh",
        re.compile(r"Legacy fallback: owner_ppid-only files are accepted"),
        "owner_ppid-only resource metadata may be diagnostic but not accepted as fallback",
    ),
]

FORBIDDEN_DOC_PATTERNS = [
    (
        re.compile(r'MST_STATE_PPID="\$\{PPID\}"'),
        "canonical docs must not inject MST_STATE_PPID",
    ),
    (
        re.compile(r"state/(?:\$\{PPID\}|default)/snapshot\.json"),
        "skill/docs state paths must not describe PPID/default as canonical",
    ),
    (
        re.compile(r"owner_session_id is authoritative", re.IGNORECASE),
        "owner_session_id must not be authoritative workflow evidence",
    ),
    (
        re.compile(r"owner_ppid-only files are accepted", re.IGNORECASE),
        "owner_ppid-only resources must not be accepted as fallback",
    ),
    (
        re.compile(r"(?:MST_STATE_PPID|MST_SNAPSHOT_SESSION_ID).*fallback", re.IGNORECASE),
        "legacy env aliases must not be fallback inputs",
    ),
]


def _text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def test_diagnostic_and_explicit_migration_legacy_contexts_are_allowlisted() -> None:
    missing = []
    for context in REQUIRED_CONTEXTS:
        text = _text(context.path)
        if context.anchor not in text or context.legacy_text not in text:
            missing.append(
                f"{context.path}: expected diagnostic/migration context "
                f"{context.anchor!r} with {context.legacy_text!r}"
            )
    assert not missing, "\n".join(missing)


def test_no_legacy_identity_in_canonical_mutation_or_control_flow_contexts() -> None:
    violations = []
    for context in FORBIDDEN_CONTEXTS:
        text = _text(context.path)
        for match in context.pattern.finditer(text):
            line = _line_number(text, match.start())
            snippet = text.splitlines()[line - 1].strip()
            violations.append(f"{context.path}:{line}: {context.reason}: {snippet}")

    paths = [*SKILL_DOCS, "docs/SESSION-ID-MIGRATION.md"]
    for relative_path in paths:
        text = _text(relative_path)
        for pattern, reason in FORBIDDEN_DOC_PATTERNS:
            for match in pattern.finditer(text):
                line = _line_number(text, match.start())
                snippet = text.splitlines()[line - 1].strip()
                violations.append(f"{relative_path}:{line}: {reason}: {snippet}")

    assert not violations, "Forbidden DOD-003 legacy identity contexts remain:\n" + "\n".join(violations)


def test_skill_docs_do_not_mention_legacy_identity_terms() -> None:
    violations = []
    for relative_path in SKILL_DOCS:
        text = _text(relative_path)
        for term in LEGACY_TERMS:
            for match in re.finditer(re.escape(term), text):
                line = _line_number(text, match.start())
                snippet = text.splitlines()[line - 1].strip()
                violations.append(f"{relative_path}:{line}: {term} must not appear in canonical skill contract: {snippet}")

    assert not violations, "Legacy identity terms remain in skill docs:\n" + "\n".join(violations)


def main() -> int:
    tests = [
        test_diagnostic_and_explicit_migration_legacy_contexts_are_allowlisted,
        test_no_legacy_identity_in_canonical_mutation_or_control_flow_contexts,
        test_skill_docs_do_not_mention_legacy_identity_terms,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
