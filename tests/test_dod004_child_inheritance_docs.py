from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    REPO_ROOT / "skills" / "request" / "SKILL.md",
    REPO_ROOT / "skills" / "approve" / "SKILL.md",
    REPO_ROOT / "skills" / "agile" / "SKILL.md",
    REPO_ROOT / "skills" / "plan" / "SKILL.md",
]

REQUIRED_PHRASES = [
    "child invocation, subprocess, and hook execution inherit parent `MST_SESSION_ID`",
    "children must not issue arbitrary `mst_session_id`",
    "matches the inherited parent `MST_SESSION_ID`",
]


def test_child_inheritance_docs_contract_is_consistent() -> None:
    missing: list[str] = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for phrase in REQUIRED_PHRASES:
            if phrase not in text:
                missing.append(f"{path.relative_to(REPO_ROOT)} missing {phrase!r}")

    assert not missing, "\n".join(missing)


def main() -> int:
    test_child_inheritance_docs_contract_is_consistent()
    print("PASS test_child_inheritance_docs_contract_is_consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
