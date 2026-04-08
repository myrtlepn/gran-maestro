<!-- source-mapping: original=docs/spec.md sections=["Evidence", "Parser"] -->
---
evidence:
  plan:
    artifact_paths:
      - src/foo.py
      - tests/test_foo.py
    entrypoint_path: src/foo.py:main
  runtime:
    integration_smoke_id: TBD
    verify_cmd: TBD
    expected_signal: TBD
---
# domain

coexist fixture
