<!-- source-mapping: original=docs/spec.md sections=["Evidence"] -->
---
evidence:
  plan:
    artifact_paths:
      - src/lib.py
  runtime:
    integration_smoke_id: tests/smoke/test_lib_smoke.py
    verify_cmd: pytest tests/smoke/test_lib_smoke.py -q
    expected_signal: "1 passed"
---
# domain

missing entrypoint fixture
