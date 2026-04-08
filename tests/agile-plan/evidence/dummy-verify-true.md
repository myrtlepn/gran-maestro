<!-- source-mapping: original=docs/spec.md sections=["Evidence"] -->
---
evidence:
  plan:
    artifact_paths:
      - src/foo.py
    entrypoint_path: src/foo.py:main
  runtime:
    integration_smoke_id: tests/smoke/test_cli.py
    verify_cmd: true
    expected_signal: "ok"
---
# domain

dummy verify true
