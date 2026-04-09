---
name: gemini
description: "Gemini CLI를 호출하여 대용량 컨텍스트 작업을 실행합니다. 사용자가 '제미니 실행', '제미니로', '대용량 분석'을 말하거나 /mst:gemini를 호출할 때 사용. Gran Maestro request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]"
---

# maestro:gemini

Gemini CLI 호출의 단일 진입점. request 워크플로우(--trace 모드 포함)에서 단일 진입점 역할. discussion/ideation/debug/explore/plan-review의 병렬 dispatch에서는 Bash 직접 호출을 사용합니다. 대용량 문서/프론트엔드/넓은 컨텍스트 작업에 적합. Maestro 모드 활성 여부 무관.

## 실행 프로토콜

1. 프롬프트/옵션 파싱
2. **프롬프트 소스**: `--prompt-file` 있으면 파일 우선 (미존재 시 에러 중단); 없으면 인라인 사용
3. `--dir` 지정 시 디렉토리 존재 확인 (없으면 에러 중단); 상대경로는 cwd 기준
4. `--files` 패턴으로 파일 목록 확인; 매칭 없으면 경고
5. `--trace` 모드 판별 (아래 섹션 참조)
6. **기본 모델**: `config.resolved.json`의 `models.providers.gemini[default_tier]`로 resolve하고, 실패 시 `gemini-3.1-pro-preview`를 fallback으로 사용
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
