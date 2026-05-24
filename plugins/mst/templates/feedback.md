# Feedback - {TASK_ID} Round {N}

- Date: {DATE}
- Source: auto_review | user_manual
- Previous Rounds: {이전 피드백 라운드 수}

## Root Cause Classification

- [ ] Implementation Error → re-execute (Phase 2)
- [ ] Spec Insufficient → revise spec (Phase 1)

## Issues (Priority Order)

### [CRITICAL] {issue title}

- File: {file}:{line}
- Problem: {what's wrong}
- Expected: {what should happen}
- Fix: {specific instruction}
- AC Reference: AC-{N}

### [HIGH] {issue title}

- File: {file}:{line}
- Problem: {what's wrong}
- Expected: {what should happen}
- Fix: {specific instruction}
- AC Reference: AC-{N}

### [MEDIUM] {issue title}

- File: {file}:{line}
- Problem: {what's wrong}
- Expected: {what should happen}
- Fix: {specific instruction}

### [LOW] {issue title}

- File: {file}:{line}
- Problem: {what's wrong}
- Suggestion: {recommendation}

## Unresolved from Previous Rounds

- {carry forward any issues not fixed from prior feedback}
- {reference: feedback-R{N-1}.md}

## Summary

{총 이슈 수} issues found. {CRITICAL 수} critical, {HIGH 수} high.
Routing to Phase {2|1}.
