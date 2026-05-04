from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "CLAUDE.md",
    REPO_ROOT / "docs" / "skills-reference.md",
    REPO_ROOT / "skills" / "recover" / "SKILL.md",
]

REQUIRED_PHRASES = [
    "recover/resume",
    "canonical `mst_session_id`",
    "root MST ID",
    "state snapshot",
    "history context",
    "다음 실행에 전달한다",
    "동일 `MST_SESSION_ID` env",
    "structured `mst_session_id` context",
    "validated history ledger",
    "validated state snapshot",
    "prompt summary는 diagnostic-only 보조 정보",
    "canonical fallback source가 아니다",
]

DIAGNOSTIC_ONLY_TERMS = [
    "MST_STATE_PPID",
    "owner_ppid",
    "owner_session_id",
    "owner_pid",
    "Claude hook `session_id`",
    "transcript UUID",
    "MST_SNAPSHOT_SESSION_ID",
    "legacy aliases `sessionId`/`session_id`",
]


def test_recover_resume_docs_contract_is_consistent() -> None:
    missing: list[str] = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for phrase in REQUIRED_PHRASES:
            if phrase not in text:
                missing.append(f"{path.relative_to(REPO_ROOT)} missing {phrase!r}")
        for term in DIAGNOSTIC_ONLY_TERMS:
            if term not in text:
                missing.append(f"{path.relative_to(REPO_ROOT)} missing diagnostic-only term {term!r}")

    assert not missing, "\n".join(missing)


def main() -> int:
    test_recover_resume_docs_contract_is_consistent()
    print("PASS test_recover_resume_docs_contract_is_consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
