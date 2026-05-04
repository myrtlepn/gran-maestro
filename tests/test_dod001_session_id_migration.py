from __future__ import annotations

from test_dod001_legacy_expectations import (
    test_dod001_tests_do_not_expect_legacy_values_as_canonical_identity,
    test_session_id_migration_doc_marks_legacy_values_diagnostic_only,
)


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
