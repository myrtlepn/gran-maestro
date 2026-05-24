---
name: gemini
description: "Gemini CLI를 호출하여 대용량 컨텍스트 작업을 실행합니다. 사용자가 '제미니 실행', '제미니로', '대용량 분석'을 말하거나 /mst:gemini를 호출할 때 사용. Gran Maestro request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]"
---

# maestro:gemini

Gemini CLI 호출의 단일 진입점. request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다. 대용량 문서/프론트엔드/넓은 컨텍스트 작업에 적합. Maestro 모드 활성 여부 무관.

## DOD-004 Gemini Identity Protection Contract

- command_identity: `mst:gemini`
- `/mst:gemini` 호출은 path rules상 `/mst:plan`, `/mst:request`, built-in plan mode 후보로 재분류하지 않는다.
- `/mst:gemini 구현`, `/mst:gemini 수정`, `/mst:gemini 계획` 같은 구현/수정/계획형 입력도 `mst:gemini` command identity를 유지하며 다른 스킬로 재분류하지 않는다.
- 위 fixture 입력은 `/mst:codex` 보호 수준과 동등하게 유지하며 `/mst:plan`, `/mst:request`, built-in plan mode, `/mst:codex`로 rewrite하지 않는다.
- model resolve는 provider `gemini`의 configured default tier를 사용하고 실패 시 `gemini-3.1-pro-preview`로만 fallback한다.
- trace label은 호출자가 전달한 `--trace {REQ-ID}/{TASK-NUM}/{label}` 값을 유지하며 다른 MST skill identity로 rewrite하지 않는다.
- Codex parity baseline: DOD-003 context contract, forbidden marker contract, exit-code behavior, prompt-file path handling을 `/mst:codex`와 동등하게 유지한다.

## DOD-004 Gemini Delegation Failure and Fallback Contract

- context file path와 prompt-file path는 실행 전 직접 inspection 대상으로 남기고, output contract에는 worktree path, running log path, trace label, evidence path, evidence id를 포함한다.
- verification criteria는 verify_cmd, expected_signal, final exit code, structured failure_kind를 함께 기록한다.
- structured failure_kind 값은 `rate_limit`, `timeout`, `empty_result`, `nonzero_exit`로 구분한다. 429/rate-limit/quota 신호는 `rate_limit`으로 분류한다.
- Codex fallback 조건은 `gemini-dev → codex fallback` 정책에 맞춰 failure_kind, exit code, log/evidence path가 존재할 때만 충족된다.
- full provider runner replacement, lifecycle artifact schema 전면 구현, shell injection hardening 전체 범위는 DOD-004 범위가 아니다.

## DOD-003 Context Transfer Contract

이 entrypoint는 구현/분석 위임 시 prompt-file path와 context file path를 먼저 전달하는 wrapper-owned lifecycle boundary다. `--prompt-file`이 있으면 prompt-file path가 canonical prompt source이며, wrapper는 prompt source tracking과 함께 worktree path, task id, trace label, running log, exit code propagation을 공통 lifecycle evidence로 남긴다.

```text
[CONTEXT_FILES]
- objective: {path or NO_LINKED_OBJECTIVE}
- objective_ids: {path or NO_OBJECTIVE_IDS}
- plan: {path or NO_SOURCE_PLAN}
- plan_json: {path or NO_PLAN_JSON}
- plan_ids: {path or NO_PLAN_IDS}
- spec: {path}
- spec_context_manifest: {path or NO_CONTEXT_MANIFEST}
- previous_feedback: {path or N/A}
[/CONTEXT_FILES]

[WORK_CONTRACT]
- read_requirements: 구현 전 위 context file path와 spec_context_manifest를 직접 Read/inspection한다.
- output_contract: prompt-file path, worktree path, task id, trace label, running log path, output artifact 또는 completion report를 보고한다.
- verification_contract: verify_cmd, expected_signal, trace path, exit code propagation을 보고한다.
- failure_contract: timeout, empty result, blocked, missing_context, NO_SOURCE_PLAN, NO_CONTEXT_MANIFEST를 구조화해 남긴다.
[/WORK_CONTRACT]
```

- wrapper-owned lifecycle boundary: `mst.py run`이 register, heartbeat, running log tee, trace, session metadata, cwd/worktree binding, output/failure contract를 소유한다.
- provider subprocess detail: 실제 provider argv 조합과 permission flags는 runtime-owned internals이며 active implementation guidance는 이를 사용자 대면 계약으로 승격하지 않는다.

## 실행 프로토콜

> **Placeholder 유도 규칙 (MANDATORY)**:
> - `{task_id}`: 워크플로우에서 `{REQ-ID}-T{TASK-NUM}` 형식으로 자동 치환 (예: `REQ-001-T01`). 독립 호출 시에는 호출자가 임의 고유 ID 지정.
> - `{task_dir}`: `.gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/` 절대경로
> - `{working_dir}`: CLI 대상 작업 경로 (워크플로우에서는 worktree 경로). wrapper의 cwd와 다를 수 있음.

1. 프롬프트/옵션 파싱
2. **프롬프트 소스**: `--prompt-file` 있으면 파일 우선 (미존재 시 에러 중단); 없으면 인라인 사용
3. `--dir` 지정 시 디렉토리 존재 확인 (없으면 에러 중단); 상대경로는 cwd 기준
4. `--files` 패턴으로 파일 목록 확인; 매칭 없으면 경고
5. `--trace` 모드 판별 (아래 섹션 참조)
6. **기본 모델**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get models.providers.gemini.default_tier)`로 tier를 확인해 `models.providers.gemini[{default_tier}]`로 resolve하고, 실패 시 `gemini-3.1-pro-preview`를 fallback으로 사용
7. Gemini CLI 실행:
   ```bash
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model gemini default 2>/dev/null || echo "gemini-3.1-pro-preview")

   # 인라인 프롬프트
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider gemini \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     -- gemini -p "{prompt}" --model "$MODEL" --approval-mode yolo --sandbox=false

   # --prompt-file
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider gemini \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     -- gemini -p "$(cat {prompt_file})" --model "$MODEL" --approval-mode yolo --sandbox=false

   # --trace 모드
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider gemini \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     --trace "{REQ-ID}/{TASK-NUM}/{label}" \
     -- gemini -p "$(cat {prompt_file})" --model "$MODEL" --approval-mode yolo --sandbox=false
   ```
8. **결과 처리**: `--trace` → Trace 문서 자동 생성 후 exit code만 반환; 없음 → 결과 표시

## Trace 모드 (워크플로우 내 자동 문서화)

`--trace {REQ-ID}/{TASK-NUM}/{label}` 인자를 wrapper에 전달하면 실행 완료 시 `{task_dir}/traces/gemini-{label}-{ts}.md` 파일이 자동 생성됩니다.

형식: `--trace {REQ-ID}/{TASK-NUM}/{label}` (예: `REQ-001/01/phase1-analysis`)

실행 예:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py run \
  --task-id REQ-001-01 \
  --provider gemini \
  --model gemini-3.1-pro-preview \
  --log-dir .gran-maestro/requests/REQ-001/tasks/01 \
  --trace REQ-001/01/phase1-analysis \
  -- gemini -p "$(cat {prompt_file})" --model gemini-3.1-pro-preview --approval-mode yolo --sandbox=false
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

- `--prompt-file {path}`: 파일에서 프롬프트 읽기 (셸 치환으로 Claude 컨텍스트 미경유, 토큰 절약)
- `--dir {path}`: 작업 디렉토리 지정 (기본: 현재 디렉토리)
- `--files {pattern}`: 컨텍스트에 포함할 파일 패턴 (예: `src/**/*.ts`)
- `-y`: 자동 승인 모드
- `--trace {REQ/TASK/label}`: Trace 문서 자동 생성 (stdout 반환 안 함)

## 예시

```
/mst:gemini "전체 코드베이스 문서 생성해줘"
/mst:gemini --prompt-file {prompt_path} --files src/**/*.ts --trace REQ-001/01/phase1-analysis
```

## 주의사항 / 문제 해결

- Gemini CLI 필수 (`gemini --version`); 미설치 시 `npm install -g @google/gemini-cli`
- 컨텍스트 윈도우 최대 1M 토큰; 대용량 파일은 `--files` 패턴을 구체적으로 지정
- `--trace` 모드에서 전체 결과는 파일에만 저장, 부모 컨텍스트 반환 안 됨
- "trace 디렉토리 생성 실패" → `requests/{REQ-ID}/tasks/{TASK-NUM}/` 경로 확인
