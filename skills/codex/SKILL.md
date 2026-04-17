---
name: codex
description: "Codex CLI를 호출하여 코드 작업을 실행합니다. 사용자가 '코덱스 실행', '코덱스로', '코드 작업'을 말하거나 /mst:codex를 호출할 때 사용. Gran Maestro request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--json] [--trace {REQ/TASK/label}] [--network]"
---

# maestro:codex

Codex CLI 호출의 단일 진입점. request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다. Maestro 모드 활성 여부 무관.

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
>
> **Placeholder 유도 규칙 (MANDATORY)**:
> - `{task_id}`: 워크플로우에서 `{REQ-ID}-T{TASK-NUM}` 형식으로 자동 치환 (예: `REQ-001-T01`). 독립 호출 시에는 호출자가 임의 고유 ID 지정.
> - `{task_dir}`: `.gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/` 절대경로
> - `{working_dir}`: codex `-C` 대상 경로 (워크플로우에서는 worktree 경로). wrapper의 cwd와 다를 수 있음.

1. 프롬프트/옵션 파싱 (`--network` 포함; 지정 시 `NETWORK_MODE=true`)
2. **프롬프트 소스**: `--prompt-file` 있으면 파일 우선 (미존재 시 에러 중단); 없으면 인라인 사용
3. `--dir` 지정 시 디렉토리 존재 확인 (없으면 에러 중단); 상대경로는 cwd 기준
4. `--trace` 모드 판별 (아래 섹션 참조)
5. **기본 모델 resolve**: `MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default)` (resolve 실패 시 `gpt-5.3-codex` fallback)
6. Codex sandbox 플래그 resolve:
   ```bash
   SANDBOX_ARGS="--full-auto"
   if [ "${NETWORK_MODE:-false}" = "true" ]; then
     SANDBOX_ARGS="-s danger-full-access -a on-request"
   fi
   ```
7. Codex CLI 실행:
   ```bash
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex")
   SANDBOX_ARGS="--full-auto"
   [ "${NETWORK_MODE:-false}" = "true" ] && SANDBOX_ARGS="-s danger-full-access -a on-request"

   # 인라인 프롬프트
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "{prompt}"

   # --prompt-file
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "$(cat {prompt_file})"

   # --trace 모드
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     --trace "{REQ-ID}/{TASK-NUM}/{label}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "$(cat {prompt_file})"
   ```
8. **결과 처리**: `--trace` → Trace 문서 자동 생성 후 exit code만 반환; `--output` → 파일 저장; 둘 다 없음 → 결과 표시

## Trace 모드 (워크플로우 내 자동 문서화)

`--trace {REQ-ID}/{TASK-NUM}/{label}` 인자를 wrapper에 전달하면 실행 완료 시 `{task_dir}/traces/codex-{label}-{ts}.md` 파일이 자동 생성됩니다.

형식: `--trace {REQ-ID}/{TASK-NUM}/{label}` (예: `REQ-001/01/phase2-impl`)

실행 예:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py run \
  --task-id REQ-001-01 \
  --provider codex \
  --model gpt-5.3-codex \
  --log-dir .gran-maestro/requests/REQ-001/tasks/01 \
  --trace REQ-001/01/phase2-impl \
  -- codex exec --full-auto -m gpt-5.3-codex -C {worktree} "$(cat {prompt_file})"
```

wrapper는 자동으로 다음을 처리합니다.
- `.gran-maestro/run/{task_id}.json`에 dispatch 상태 기록 (register + heartbeat)
- stdout/stderr를 `{log_dir}/running.log`에 tee
- 종료 시 exit_code 및 final phase 기록
- `--trace` 전달 시 `traces/*.md` 자동 생성

> **금지 마커 (MANDATORY)**: 이 스킬은 `NEXT_ACTION`, `step=returned`, `[MST skill=...]` 마커를 **절대 출력하지 않는다**.
> 이 마커들은 부모 스킬(approve 등)의 책임이며, 서브스킬이 출력하면 부모가 "이미 처리됨"으로 혼동한다.

> **Exit Code 캡처 (MANDATORY)**: `mst.py run`의 종료 코드를 반드시 확인한다.
> 0이 아니어도 trace의 `exit_code` 필드에 해당 값을 반드시 기록한다.

## 옵션

- `--prompt-file {path}`: 프롬프트를 파일에서 읽기 (인라인 프롬프트 대신). 셸 치환(`$(cat)`)으로 파일→CLI 직접 전달하여 Claude 컨텍스트를 경유하지 않으므로 토큰 절약
- `--dir {path}`: 작업 디렉토리 지정 (기본: 현재 디렉토리)
- `--json`: JSON 형태로 구조화된 출력
- `--ephemeral`: 상태를 보존하지 않는 일회성 실행
- `--output {file}`: 결과를 파일로 저장 (독립 호출용)
- `--trace {REQ/TASK/label}`: 워크플로우 trace 문서 자동 생성 (stdout 반환 안 함)
- `--network`: Codex sandbox를 `-s danger-full-access -a on-request`로 전환 (미지정 시 `--full-auto`)

> `--trace`와 `--output`이 동시에 지정되면 `--trace`가 우선합니다.
> `--prompt-file`과 인라인 프롬프트가 동시에 지정되면 `--prompt-file`이 우선합니다.

## 예시

```
/mst:codex "이 프로젝트의 아키텍처를 분석해줘"
/mst:codex --prompt-file .gran-maestro/requests/REQ-001/tasks/01/prompts/phase2-impl.md --dir {worktree} --trace REQ-001/01/phase2-impl
/mst:codex --network --prompt-file .gran-maestro/requests/REQ-001/tasks/01/prompts/phase2-impl.md --dir {worktree} --trace REQ-001/01/phase2-impl
```

## 주의사항 / 문제 해결

- Codex CLI 필수 (`codex --version`); 미설치 시 `npm install -g @openai/codex`
- `--network`는 명시적으로 위험 권한을 허용하므로 네트워크가 반드시 필요한 작업에서만 사용
- `--full-auto` 모드는 기본 sandbox(workspace-write) 기준 파일 수정 권한이 있으므로 주의
- `--trace` 모드에서는 전체 결과가 파일에만 저장되고 부모 컨텍스트에 반환 안 됨
- "타임아웃" → `/mst:settings timeouts.cli_large_task_ms` 확인
- "trace 디렉토리 생성 실패" → `requests/{REQ-ID}/tasks/{TASK-NUM}/` 경로 확인

## Agile Sub-plan Isolated Execution (수동 격리 실행)

agile Sprint loop에서 컨텍스트 압박이 심해질 때, sub-plan 전체 체인(plan→request→approve→accept)을 깨끗한 codex exec 격리 컨텍스트에서 실행할 수 있습니다. 이는 옵션 A(수동 escape hatch)로 제공되며, Sprint loop 자체를 우회하지 않고 plan/request/approve/accept 게이트를 모두 유지합니다.

### 사용 예시

```bash
# 부모 세션에서 sub-plan worktree를 만들고 codex exec로 전체 체인 실행
/mst:codex exec --dir .gran-maestro/worktrees/AGI-001/sprint-3/sub-plan-2 \
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
- Sprint 2.2.3 자동 dispatch는 AGI-015에서 `config.agile.dispatch.enabled` 기반의 claude 단일 provider 경로로 재정의되었으며, codex/gemini 자동 dispatch 분기는 지원하지 않습니다.
