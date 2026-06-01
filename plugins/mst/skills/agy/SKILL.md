---
name: agy
description: "Antigravity AGY CLI를 호출하여 대용량 컨텍스트 작업을 실행합니다. 사용자가 'agy 실행', '안티그래비티로', '대용량 분석'을 말하거나 /mst:agy를 호출할 때 사용. Gran Maestro request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]"
---

# maestro:agy

AGY CLI 호출의 canonical 단일 진입점입니다. `/mst:gemini`는 한 릴리스 동안 deprecated compatibility wrapper로만 유지합니다.

## AGY Identity Protection Contract

- command_identity: `mst:agy`
- `/mst:agy` 호출은 path rules상 `/mst:plan`, `/mst:request`, built-in plan mode 후보로 재분류하지 않습니다.
- `/mst:agy 구현`, `/mst:agy 수정`, `/mst:agy 계획` 같은 구현/수정/계획형 입력도 `mst:agy` command identity를 유지합니다.
- model resolve는 provider `agy`의 configured default tier를 사용하되, AGY CLI argv에는 `--model`을 기본 전달하지 않습니다.
- trace label은 호출자가 전달한 `--trace {REQ-ID}/{TASK-NUM}/{label}` 값을 유지합니다.
- Codex parity baseline: DOD-003 context contract, forbidden marker contract, exit-code behavior, prompt-file path handling을 `/mst:codex`와 동등하게 유지합니다.

## Delegation Failure and Fallback Contract

- context file path와 prompt-file path는 실행 전 직접 inspection 대상으로 남기고, output contract에는 worktree path, running log path, trace label, evidence path, evidence id를 포함합니다.
- verification criteria는 verify_cmd, expected_signal, final exit code, structured failure_kind를 함께 기록합니다.
- structured failure_kind 값은 `rate_limit`, `timeout`, `empty_result`, `nonzero_exit`로 구분합니다. 429/rate-limit/quota 신호는 `rate_limit`으로 분류합니다.
- Codex fallback 조건은 `agy-dev -> codex fallback` 정책에 맞춰 failure_kind, exit code, log/evidence path가 존재할 때만 충족됩니다.

## DOD-003 Context Transfer Contract

이 entrypoint는 구현/분석 위임 시 prompt-file path와 context file path를 먼저 전달하는 wrapper-owned lifecycle boundary입니다. `--prompt-file`이 있으면 prompt-file path가 canonical prompt source이며, wrapper는 prompt source tracking과 함께 worktree path, task id, trace label, running log, exit code propagation을 공통 lifecycle evidence로 남깁니다.

## 실행 프로토콜

1. 프롬프트/옵션 파싱
2. `--prompt-file` 있으면 파일 우선, 없으면 인라인 prompt 사용
3. `--dir` 지정 시 디렉토리 존재 확인
4. `--files` 패턴으로 파일 목록 확인; 매칭 없으면 경고
5. `--trace` 모드 판별
6. 기본 모델 메타데이터:
   ```bash
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model agy default 2>/dev/null || echo "agy-default")
   ```
7. AGY CLI 실행:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider agy \
     --model "$MODEL" \
     --log-dir "{task_dir}" \
     --require-worktree \
     --worktree-dir "{working_dir}" \
     -- agy --print "$(cat {prompt_file})" --dangerously-skip-permissions --add-dir "{working_dir}"
   ```
8. `--trace` 모드에서는 `traces/agy-{label}-{ts}.md` 파일 생성을 기대하고, 부모 컨텍스트에는 요약과 exit code만 반환합니다.

> 이 스킬은 `NEXT_ACTION`, `step=returned`, `[MST skill=...]` 마커를 출력하지 않습니다.

## 옵션

- `--prompt-file {path}`: 파일에서 프롬프트 읽기
- `--dir {path}`: 작업 디렉토리 지정
- `--files {pattern}`: 컨텍스트에 포함할 파일 패턴
- `-y`: 자동 승인 모드
- `--trace {REQ/TASK/label}`: Trace 문서 자동 생성

## 예시

```bash
/mst:agy "전체 코드베이스 문서 생성해줘"
/mst:agy --prompt-file {prompt_path} --files src/**/*.ts --trace REQ-001/01/phase1-analysis
```

## 주의사항

- AGY CLI 필수 (`agy --version`)
- all-approve 동작은 `--dangerously-skip-permissions`로 고정합니다.
- AGY CLI help에 `--model`이 없으므로 모델 값은 lifecycle metadata로만 보존합니다.
