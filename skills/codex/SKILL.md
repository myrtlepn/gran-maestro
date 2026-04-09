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

1. 프롬프트/옵션 파싱 (`--network` 포함; 지정 시 `NETWORK_MODE=true`)
2. **프롬프트 소스**: `--prompt-file` 있으면 파일 우선 (미존재 시 에러 중단); 없으면 인라인 사용
3. `--dir` 지정 시 디렉토리 존재 확인 (없으면 에러 중단); 상대경로는 cwd 기준
4. `--trace` 모드 판별 (아래 섹션 참조)
5. **기본 모델 resolve (MANDATORY)**:
   > ⚠️ **tier 이름 직접 전달 금지**: `"premium"`, `"economy"` 등 tier 이름을 `-m` 플래그에 그대로 전달하면 Codex CLI가 모델을 찾지 못한다.
   > 반드시 아래 중 하나의 방법으로 실제 모델명으로 resolve 후 전달한다.
   >
   > **방법 A (권장) — mst.py 사용:**
   > ```bash
   > MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex")
   > # MODEL = "gpt-5.3-codex"  ← 실제 모델명, tier 이름 아님
   > ```
   >
   > **방법 B — 수동 2단계 lookup:**
   > ```bash
   > # 1단계: tier 이름 취득
   > #   config.models.providers.codex.default_tier = "premium"
   > # 2단계: tier 이름으로 모델명 lookup  ← 이 단계를 반드시 수행
   > #   config.models.providers.codex.<tier_name> = "gpt-5.3-codex"
   > # ⚠️ 잘못된 예: codex exec -m <tier_name>   (tier 이름 그대로 전달)
   > # ✅ 올바른 예: codex exec -m gpt-5.3-codex
   > ```
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
