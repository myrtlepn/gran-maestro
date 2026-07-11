# Outsource Brief Template

> ⚠️ **대체됨**: Phase 2 구현 요청은 `templates/impl-request.md`를 사용합니다.
> Phase 4 수정 요청은 `templates/fix-request.md`를 사용합니다.
> 이 파일은 하위 호환 및 `<error_context>` 재외주 시나리오를 위해 유지됩니다.

Phase 2에서 native-first route가 선택한 Codex/AGY/Claude provider agent에 전달하는 프롬프트 템플릿입니다.
이 파일은 에이전트가 아닌 **템플릿**으로, PM Conductor가 변수를 치환하여 사용합니다.

<outsource_brief>
<context>
You are working on task {TASK_ID} in a git worktree at {WORKTREE_PATH}.
This is an outsourced task from Gran Maestro. You must implement exactly
what the spec describes — no more, no less.
</context>

<spec>
{SPEC_CONTENT — spec.md의 전체 내용이 여기에 삽입됨}
</spec>

<rules>
- Implement ONLY what the acceptance criteria specify
- Do NOT modify files outside the specified scope
- Do NOT add features, refactoring, or "improvements" beyond the spec
- DELEGATION BOUNDARY (MANDATORY): complete the assigned task yourself; do not delegate or spawn another provider agent
- Do NOT invoke codex/claude provider CLIs, `/mst:codex`, `/mst:claude`, or a same-provider managed wrapper
- Do NOT call `mst.py delegation` lifecycle commands or edit `.gran-maestro/run`, session, or history state; the parent owns routing and evidence
- Write tests as specified in the test plan
- Commit your changes with a descriptive message: "[{TASK_ID}] {summary}"
- If you encounter a blocker, document it in exec-log.md and stop
</rules>

<verification_before_completion>
Before declaring completion, verify:
- [ ] All acceptance criteria addressed
- [ ] Type check passes (if applicable)
- [ ] Tests pass (if applicable)
- [ ] Changes are within specified scope
- [ ] Commit message follows convention
</verification_before_completion>

<previous_feedback>
{피드백 라운드 시: feedback-RN.md 내용이 여기에 삽입됨}
{첫 실행 시: "No previous feedback. This is the initial implementation."}
</previous_feedback>

<error_context>
{사전검증 실패 재외주 시에만 삽입됨. 첫 실행 및 피드백 재실행 시에는 이 섹션 생략}

The previous implementation attempt failed pre-checks with the following errors:

<!-- Step 5b formatter output; parser 실패 시 원문 passthrough -->
{ERROR_OUTPUT}

Fix these errors while maintaining all acceptance criteria from the spec.
After fixing, run the verification commands to confirm everything passes:
- {TEST_COMMAND}
- {TYPECHECK_COMMAND}

Important:
- Focus ONLY on fixing the reported errors
- Do NOT introduce new features or refactoring
- Verify your fix resolves the specific error messages shown above
</error_context>
</outsource_brief>

## 변수 목록

| 변수 | 설명 | 예시 |
|------|------|------|
| `{TASK_ID}` | 태스크 ID | `REQ-001-01` |
| `{WORKTREE_PATH}` | Git worktree 경로 | `.gran-maestro/worktrees/REQ-001-01` |
| `{SPEC_CONTENT}` | spec.md 전체 내용 | (Implementation Spec 문서) |
| `{summary}` | 커밋 메시지용 요약 | `Add JWT auth middleware` |
| `{ERROR_OUTPUT}` | 사전검증(tsc/test) 포맷된 에러 출력 (입력 3000자 캡, 파싱 실패 시 원문 passthrough) | `src/foo.ts:10 — TS2345 — Argument of type 'string' is not assignable...` |
| `{TEST_COMMAND}` | spec §5의 테스트 실행 명령어 | `npx vitest run` |
| `{TYPECHECK_COMMAND}` | spec §5의 타입 체크 명령어 | `npx tsc --noEmit` |

## 스킬 호출 방식

모든 provider 호출은 parent가 `mst.py host context --json`과 `mst.py delegation route`를 먼저 실행해 transport를 확정합니다. Same-host Codex/Claude는 native agent를 우선하며, `route=external`일 때만 내부 managed 스킬/runner가 기존 provider CLI adapter를 사용합니다. Child가 직접 provider CLI나 nested `/mst:codex`/`/mst:claude`를 호출해서는 안 됩니다.

**CRITICAL — Prompt-File 패턴**: 워크플로우 내에서는 brief를 파일로 먼저 저장한 뒤 `--prompt-file`로 전달합니다.
이렇게 하면 프롬프트가 Claude 컨텍스트를 통과하지 않아 토큰이 절약되고, 프롬프트 파일이 디스크에 남아 감사 추적이 가능합니다.

### Codex 실행 (2단계: Write → Skill)
```
# Step 1: 템플릿 치환 후 파일에 저장
Write → .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md

# Step 2: 파일 경로로 호출
/mst:codex --prompt-file .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md --dir {WORKTREE_PATH} --trace {REQ-ID}/{TASK-NUM}/phase2-impl
```

### AGY 실행 (2단계: Write → Skill)
```
# Step 1: 템플릿 치환 후 파일에 저장
Write → .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md

# Step 2: 파일 경로로 호출
/mst:agy --prompt-file .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md --trace {REQ-ID}/{TASK-NUM}/phase2-impl
```

### Claude 실행 (native-first)

`Assigned Agent: claude` / `claude-dev`인 경우 shared route를 적용합니다. Claude host의 `native_candidate`는 `Task`/`Agent`와 parent-owned lifecycle evidence를 사용하고, `route=external`일 때만 `/mst:claude` managed wrapper를 사용합니다. Same-host native 경로는 Claude CLI 설치를 요구하지 않습니다.

```
# Step 1: 템플릿 치환 후 파일에 저장
Write → .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md

# Step 2: parent route entrypoint로 호출 (same-host에서는 내부적으로 Task/Agent 우선)
/mst:claude --prompt-file .gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/prompts/phase2-impl.md --dir {WORKTREE_PATH} --trace {REQ-ID}/{TASK-NUM}/phase2-impl
```

병렬 실행이 필요한 native lane은 `Task(..., run_in_background: true)`로 실행하고 `TaskOutput`으로 폴링하며 start/acknowledge/attach/heartbeat/complete를 parent가 기록합니다. External lane만 managed wrapper로 병렬화합니다.

### 결과 파일 저장이 필요한 경우
```
/mst:codex --prompt-file {prompt_path} --dir {WORKTREE_PATH} --output {exec-log-path}
```

## 피드백 라운드 시 추가 삽입

피드백 라운드(Phase 4 → Phase 2 재실행)에서는 `{previous_feedback}` 섹션에
해당 라운드의 feedback 파일 내용이 삽입됩니다.

## 사전검증 실패 재외주 시 추가 삽입

사전검증 실패 재외주(Phase 2 Step 5b)에서는 `<error_context>` 섹션에
포맷된 에러 출력과 검증 명령어가 삽입됩니다 (포맷 불가 시 원문 유지). `<previous_feedback>` 섹션은 비어 있습니다.
