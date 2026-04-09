---
name: claude
description: "Claude CLI를 호출하여 코드 작업을 실행합니다. 사용자가 '클로드로 실행', '클로드 서브에이전트'를 말하거나 /mst:claude를 호출할 때 사용. Gran Maestro 워크플로우 내 claude-dev 태스크 디스패치는 이 스킬을 경유합니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--trace {REQ/TASK/label}]"
---

# maestro:claude

PM Conductor 원칙 유지 목적으로 Claude CLI를 `mst.py run` wrapper 경유로 호출해 구현을 위임합니다. Codex/Gemini와 동일한 CLI 기반 디스패치 패턴을 사용합니다.

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```

1. `$ARGUMENTS` 파싱:
   - `--prompt-file {경로}`: 프롬프트 파일 경로 (우선)
   - `--dir {경로}`: 작업 디렉토리 (worktree 경로)
   - `--trace {REQ-ID}/{TASK-NUM}/{label}`: trace 파일 저장 경로
   - 나머지: 인라인 프롬프트

2. 프롬프트 준비:
   - `--prompt-file`이 있으면: 실행 시 `$(cat {prompt_file})`로 파일 내용을 CLI에 직접 전달
   - 없으면: 인라인 텍스트 사용

3. Claude CLI 실행 (wrapper 경유):
   - 기본 모델 resolve (MANDATORY):
     ```bash
     MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model claude default 2>/dev/null || echo "sonnet")
     ```
   - 인라인 프롬프트:
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py run \
       --task-id "{task_id}" \
       --provider claude \
       --model "$MODEL" \
       --log-dir "{task_dir}" \
       -- claude -p "{prompt}" --model "$MODEL" --permission-mode bypassPermissions
     ```
   - `--prompt-file`:
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py run \
       --task-id "{task_id}" \
       --provider claude \
       --model "$MODEL" \
       --log-dir "{task_dir}" \
       -- claude -p "$(cat {prompt_file})" --model "$MODEL" --permission-mode bypassPermissions
     ```
   - `--trace`:
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py run \
       --task-id "{task_id}" \
       --provider claude \
       --model "$MODEL" \
       --log-dir "{task_dir}" \
       --trace "{REQ-ID}/{TASK-NUM}/{label}" \
       -- claude -p "$(cat {prompt_file})" --model "$MODEL" --permission-mode bypassPermissions
     ```

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
- Claude: wrapper 뒤에서 `claude -p ...` 실행 (`--model` + `--permission-mode bypassPermissions` 유지)
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
