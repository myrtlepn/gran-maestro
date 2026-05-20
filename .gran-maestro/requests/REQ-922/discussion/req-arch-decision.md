# REQ-922 Architecture Decision

```yaml
gate: open
reason: "risk_signal_review_required; DOD-013 touches smoke validators, request-level evidence, shared DOD registry linkage, docs/release boundary, and objective completion evidence"
confidence: 0.86
threshold: 0.7
triggers:
  A: true
  B: false
  C: true
result: none
arch_direction: "Reuse the DOD-011/DOD-012 request-evidence pattern and extend the shared DOD registry with a validator-linked DOD-013 entry. Keep all validation repository-local and prove Codex-only fork count, generated drift, 5-file version sync, canonical source coverage, and no-go boundary in machine-readable artifacts."
```

## Boundary

실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits 없이 repository-local fixtures/evidence로만 검증된다.

Do not edit `.claude/hooks`, `~/.codex`, `~/.agents`, `~/.claude`, or user-global config. Do not edit `objective.md` directly; objective status transitions happen only after implementation/review/accept through the helper.
