---
name: claude
description: "Claude provider 전용 managed delegation entrypoint. 사용자가 '클로드로 실행', '클로드 서브에이전트'를 말하거나 /mst:claude를 호출할 때 사용한다. Gran Maestro 워크플로우 내 claude-dev 태스크 디스패치는 이 protected path를 경유한다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--trace {REQ/TASK/label}]"
---

# maestro:claude

PM Conductor 원칙 유지 목적으로 Claude provider 작업은 `mst.py run` lifecycle wrapper가 소유하는 managed delegation path로 위임한다. 직접 Claude one-shot print-mode argv를 구현 지침으로 노출하지 않으며, Codex/Gemini와 동일하게 provider subprocess detail은 runtime 내부 계약으로 취급한다.

## 실행 프로토콜

<!-- @include _shared/path-rules.md -->
> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
<!-- @end-include -->

1. `$ARGUMENTS` 파싱:
   - `--prompt-file {경로}`: 프롬프트 파일 경로 (우선)
   - `--dir {경로}`: 작업 디렉토리 (worktree 경로)
   - `--trace {REQ-ID}/{TASK-NUM}/{label}`: trace 파일 저장 경로
   - 나머지: 인라인 프롬프트

2. 프롬프트 준비:
   - `--prompt-file`이 있으면: 파일 내용을 provider prompt payload로 전달한다.
   - 없으면: 인라인 텍스트를 prompt payload로 사용한다.

3. Managed Claude delegation 실행 (wrapper 경유):
   - 기본 모델 resolve (MANDATORY):
     ```bash
     MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model claude default 2>/dev/null || echo "sonnet")
     ```
   - wrapper invocation contract:
     - `python3 {PLUGIN_ROOT}/scripts/mst.py run` is the canonical lifecycle boundary.
     - required wrapper fields: `--task-id`, `--provider claude`, `--model "$MODEL"`, `--log-dir "{task_dir}"`.
     - optional trace field: `--trace "{REQ-ID}/{TASK-NUM}/{label}"`.
     - prompt source is the inline payload or the contents of `{prompt_file}`.
   - provider subprocess detail contract:
     - provider argv assembly, prompt stdin/argv handoff, permission flags, and print-mode compatibility are runtime-owned internals.
     - active implementation guidance must not instruct direct Claude print-mode execution outside the wrapper.
   - preserved lifecycle contract:
     - register, heartbeat, running log tee, trace path, exit code propagation, session metadata, cwd/worktree binding, prompt source tracking, and output/failure contract remain wrapper-owned.

4. `--trace`가 있으면 wrapper가 trace 파일 저장:
   - 파일명 패턴: `claude-{label}-{YYYYMMDD-HHmmss}.md`
   - trace 경로: `{task_dir}/traces/`

5. **결과 반환**

   **`--trace` 모드**: Trace 문서 작성 후 부모 컨텍스트에는 exit code만 반환한다 (전체 결과 출력 안 함; 필요 시 Read 도구로 파일 접근).
   반환 후 부모 스킬의 후속 단계를 계속 진행한다. 추가 설명, 요약 등 부가 텍스트 출력 절대 금지.

   **`--trace` 미제공 시**: 서브에이전트 결과만 간결하게 반환한다. 추가 설명, 요약 등 부가 텍스트 출력 절대 금지.

   > **금지 마커 (MANDATORY)**: 이 스킬은 `NEXT_ACTION`, `step=returned`, `[MST skill=...]` 마커를 **절대 출력하지 않는다**.
   > 이 마커들은 부모 스킬(approve 등)의 책임이며, 서브스킬이 출력하면 부모가 "이미 처리됨"으로 혼동한다.

   > **Exit Code 캡처 (MANDATORY)**: `mst.py run`의 종료 코드를 반드시 확인한다.
   > 0이 아니어도 trace의 `exit_code` 필드에 해당 값을 반드시 기록한다.

## Codex/Gemini와의 차이점

- Codex: wrapper 뒤에서 `codex exec ...` 실행
- Gemini: wrapper 뒤에서 `gemini -p ...` 실행
- Claude: wrapper 뒤에서 provider-owned subprocess를 실행하며, user-facing contract는 `/mst:claude` managed delegation과 lifecycle evidence다.
- register/heartbeat/tee/final-state/trace 생성은 세 provider 모두 wrapper가 공통 담당

## Trace 파일 형식

저장 경로: `{task_dir}/traces/claude-{label}-{YYYYMMDD-HHmmss}.md`
내용: YAML frontmatter 메타데이터 (wrapper 출력 형식)

```yaml
---
task_id: {task_id}
provider: claude
model: {resolved_model}
trace_label: {REQ-ID}/{TASK-NUM}/{label}
started_at: {ISO8601}
terminated_at: {ISO8601}
duration_ms: {실행시간(ms)}
exit_code: {종료 코드}
running_log_path: {log_dir}/running.log
---
```

## 예시

```
/mst:claude "README의 설치 섹션을 업데이트해줘"
/mst:claude --prompt-file .gran-maestro/requests/REQ-001/tasks/01/prompts/phase2-impl.md --dir .gran-maestro/worktrees/REQ-001-01 --trace REQ-001/01/phase2-impl
```

## Agile Sub-plan Isolated Execution (수동 격리 실행)

agile Sprint loop에서 컨텍스트 압박이 심해질 때, sub-plan 전체 체인(plan→request→approve→accept)을 `/mst:claude` managed delegation으로 격리 실행할 수 있다. 이는 옵션 A(수동 escape hatch)로 제공되며, Sprint loop 자체를 우회하지 않고 plan/request/approve/accept 게이트를 모두 유지한다.

### 사용 예시

```bash
# 부모 세션에서 sub-plan worktree를 만들고 /mst:claude managed delegation으로 전체 체인 실행
/mst:claude --dir .gran-maestro/worktrees/AGI-001/sprint-3/sub-plan-2 \
  "/mst:plan -a '사용자 프로필 편집 기능' && /mst:request -a --plan PLN-NNN && /mst:approve -a && /mst:accept"
```

### worktree 경로 규칙

```
{PROJECT_ROOT}/.gran-maestro/worktrees/AGI-NNN/sprint-N/sub-plan-M/
```

### 결과 확인

격리 실행 완료 후 부모 Sprint 세션에서 다음을 확인:

1. 생성된 REQ ID(`.gran-maestro/requests/REQ-NNN/request.json`)
2. 최종 커밋 SHA(`git -C {worktree_path} log -1 --format=%H`)
3. 실행 성공 여부(`sprints/sprint-N/result.json`)

### 주의사항

- 격리 실행은 Sprint의 **순차 실행이 기본**이며 이 escape hatch는 컨텍스트 압박 예외 상황에서만 사용합니다.
- 실행 후 반드시 `auto-decisions.md` 또는 `retrospective.md`에 격리 실행 사유와 결과를 기록해야 합니다 (Anti-Rationalization Checklist 준수).
- 직접 Claude print-mode wrapper 호출은 DOD-002 이후 active implementation contract가 아니며, 필요한 lifecycle evidence는 `/mst:claude`가 유지한다.
- Sprint 2.2.3 자동 dispatch는 AGI-015에서 `config.agile.dispatch.enabled` 기반의 claude 단일 provider 경로로 재정의되었습니다 (ADR-005).
