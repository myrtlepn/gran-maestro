---
name: ideation
description: "설정된 AI 팀원들의 의견을 병렬 수집하고 종합 토론합니다. 사용자가 '아이디어', '브레인스토밍', '의견 수렴'을 말하거나 /mst:ideation을 호출할 때 사용. 구현 전 다각도 분석이 필요할 때 독립적으로 실행."
user-invocable: true
argument-hint: "{주제} [--focus {architecture|ux|performance|security|cost}]"
---

# maestro:ideation

설정된 AI 팀원들의 의견을 병렬 수집하고 PM이 종합하여 인터랙티브 토론을 진행합니다. Maestro 모드 활성 여부에 관계없이 사용 가능. REQ 워크플로우와 독립적으로 실행됩니다.

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

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/ideation/` 디렉토리 존재 확인, 없으면 생성
2. 새 세션 ID 채번 (IDN-NNN):
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type idn` → 출력 ID 사용
   - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/ideation/counter.json` 파일 Read
     - **파일 존재 시**: `next_id = last_id + 1`
     - **파일 미존재 시** (최초 또는 복구):
       a. `{PROJECT_ROOT}/.gran-maestro/ideation/` 하위의 기존 IDN-* 디렉토리 스캔
       b. `{PROJECT_ROOT}/.gran-maestro/archive/` 내 `ideation-*` tar.gz 파일명에서 ID 범위 추출 (예: `ideation-IDN001-IDN005-*.tar.gz` → max 5)
       c. 모든 소스에서 최대 번호 결정 → `counter.json` 생성: `{ "last_id": {max_number} }`
       d. `next_id = last_id + 1`
     - `counter.json` 업데이트: `{ "last_id": {next_id} }`
3. `{PROJECT_ROOT}/.gran-maestro/ideation/IDN-NNN/` 디렉토리 생성 (NNN은 3자리 zero-padded)
4. `session.json` 작성:

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "id": "IDN-NNN",
  "topic": "{사용자 주제}",
  "focus": "{focus 옵션 또는 null}",
  "status": "analyzing",
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "participants": [
    {
      "key": "architect(codex)",
      "role": "architect",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "codex",
      "started_at": null,
      "completed_at": null
    },
    {
      "key": "ux-strategist(agy)",
      "role": "ux-strategist",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "agy",
      "started_at": null,
      "completed_at": null
    },
    {
      "key": "risk-analyst(claude)",
      "role": "risk-analyst",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "claude",
      "started_at": null,
      "completed_at": null
    }
  ],
  "critics": {
    "claude": { "status": "pending", "provider": "claude" }
  },
  "critic_count": 1,
  "participant_config": { "codex": 3, "agy": 2, "claude": 1 }
}
```

`participants`는 config의 `ideation.agents`를 읽어 생성합니다 (`discussion`과 독립 운영).
### participants 동적 생성 규칙
1. 각 provider(codex, agy, claude)의 count 읽기
2. count == 1 → key는 `{role}(provider)` 형식
3. count > 1 → 순서대로 role 생성, `{participant.key}` 형태로 key 구성
4. 각 항목에 `provider` 필드 기록
5. 합계 검증: 2~7명, 위반 시 에러 후 중단
6. count == 0 → 해당 provider 완전 skip

`participants` 키 없으면 기본값 `{ codex:1, agy:1, claude:1 }`.

예시 (`ideation.agents.codex=3`, `ideation.agents.agy=2`, `ideation.agents.claude=1`):
```json
{
  "participants": [
    { "key": "architect(codex)", "role": "architect", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "ux(codex)", "role": "ux", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "security(codex)", "role": "security", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "architecture(agy)", "role": "architecture", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "cost(agy)", "role": "cost", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "risk(claude)", "role": "risk", "perspective": "", "type": "opinion", "status": "pending", "provider": "claude", "started_at": null, "completed_at": null }
  ]
}
```

### Step 1.5: PM 역할 배정 (Role Assignment)

PM이 주제와 focus를 분석하여 `participants` 수만큼 관점을 배정합니다.
- 주제 분석: 도메인, 복잡도, 기술적 깊이 파악
- 프로바이더 매칭: Codex(코드/구현/아키텍처), AGY(전략/디자인/트렌드), Claude(추론/리스크/평가)
- Critic 수: 기본 1, 복잡 주제 2
- Critic 배정: Claude ≥ 1 → Claude 우선, Claude = 0 → Codex → AGY. critic_count=2 → 2명 배정
- `session.json` 업데이트: `participants[].perspective`, `critics` 키, `participant_config`, `critic_count`, `status: "collecting"`

### AUTO-CONTINUE 원칙 (CRITICAL)

> **이 스킬의 Step 1~3은 사용자 입력 없이 자율적으로 진행합니다.**
> - 백그라운드 작업(Codex/AGY/Claude)이 완료될 때, 사용자에게 "계속할까요?" "진행할까요?" 등을 **절대 묻지 마세요**.
> - 개별 백그라운드 작업 완료 알림에는 간단히 확인만 하고 **모든 작업이 완료될 때까지 대기**하세요.
> - 모든 작업이 완료되면 **즉시 다음 Step**으로 진행하세요 (Step 2 (participants + critics 동시 dispatch) → 2.5 (완료 대기 + 진행 상황 출력) → 2.7 (critic 완료 확인) → 3 → 사용자 보고).
> - 사용자 상호작용은 Step 4(인터랙티브 토론)에서만 발생합니다.
> - 이 원칙은 mst-loop/ultrawork 모드가 아니어도 항상 적용됩니다.

### 프롬프트 파일 생성 원칙 (CRITICAL)

`context.md`는 단독 Write, 프롬프트 파일은 **단일 combined 파일 Write → 스크립트 split** 패턴을 사용합니다:
- `session.json` 업데이트, `context.md` 작성은 기존대로 단일 응답 내 Write 처리
- 프롬프트 파일(N+M개)은 `prompts/combined-prompts.txt` **1개**에 `===SPLIT: {filename}===` 구분기호로 모두 포함
- combined-prompts.txt Write 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts` 실행
- Task() 병렬 발송은 마찬가지로 모든 `Task(run_in_background: true)` 호출을 단일 응답에 포함합니다.

### Step 2: 병렬 의견 수집 (Direct File Write)

**단일 응답에서 아래를 동시 Write한 뒤, 모든 Task()를 단일 응답 내에서 동시 발송합니다.**

1. **Dispatch 프롬프트 조립 — feature flag 분기**

   config 확인:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py config get prompt_builder.enabled prompt_builder.fallback_on_error
   ```

   #### (a) prompt_builder.enabled=true (하이브리드 JSON 경로, 권장)
   1. `context.md` 본문을 `.gran-maestro/tmp/ctx-{session_id}.md`로 Write (기존 context.md와 동일 내용, tmp 복사본)
   2. `dispatch-input.json`을 아래 스키마로 Write:
      ```json
      {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
          "topic": "{IDN-NNN 주제}",
          "constraints": ["..."],
          "reference_context_file": ".gran-maestro/tmp/ctx-{session_id}.md"
        },
        "tasks": [
          {"role": "{participant.key}", "angle": "{perspective}", "ask": "핵심 질문 1~3개 ≤200자"},
          {"role": "{participant.key}", "angle": "{perspective}", "ask_file": ".gran-maestro/tmp/task-{role}-ask.md"}
        ]
      }
      ```
      - `format: "mst.dispatch"`, `schema_version: 1`
      - `common`: `topic`, `constraints[]`, `reference_context_file: ".gran-maestro/tmp/ctx-{session_id}.md"`
      - `tasks[]`: 각 participant/critic마다 `{role: "{participant.key}", angle: "{perspective}", ask: "...≤200자"}` 또는 `ask_file: "..."}`
      - 200자 초과 질문은 `.gran-maestro/tmp/task-{role}-ask.md`로 Write 후 `ask_file` 경로 참조
   3. CLI 호출:
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py prompt build \
        --input {absolute_path}/dispatch-input.json \
        --out-dir {absolute_path}/prompts \
        --sid {session_id}
      ```
      (metrics는 자동 기본 경로로 적재됨)
   4. 성공 시 생성된 `prompts/combined-prompts.txt`를 기존대로 `session split-prompts`로 분할 (기존 3단계 스크립트 호출 유지):
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts
      ```
   5. 실패 시 (exit != 0) → (b) fallback 경로로 자동 전환

   #### (b) prompt_builder.enabled=false 또는 CLI fallback (기존 직접 조립 경로)
   - `context.md` — 공통 배경 컨텍스트 (주제 상세, 코드베이스 현황, 핵심 제약)
   - `prompts/combined-prompts.txt` — N+M개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함
     (participant N개 + critic M개, 아래 포맷 그대로 적용)

   combined-prompts.txt Write 완료 직후:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts
   ```
   → `prompts/{participant.key}-prompt.md` × N, `prompts/critique-{criticKey}-prompt.md` × M 자동 생성

   #### fallback 규약 (MANDATORY)
   (a) 경로 실행 중 `mst.py prompt build`가 exit 2/3 등 실패 반환 시:
   - stderr 로그와 구조화 errors JSON을 Read
   - PM이 지적된 오류를 기반으로 JSON을 1회 수정 후 재시도 (repair 1회)
   - 재시도 실패 시 즉시 (b) 기존 직접 조립 경로로 전환 (workflow 차단 금지)
   - `config.prompt_builder.fallback_on_error=false`이면 repair 실패 시 워크플로우를 중단하고 사용자 에스컬레이션

   참고: `mst.py prompt build`는 오류 반환만 담당하며, repair 1회/fallback 전환은 본 스킬(ideation)의 책임이다.

   이후 2번(participant Task 발송)부터는 기존 내용 그대로 진행.

개별 프롬프트 포맷:
```markdown
# {Role} 관점 의견 요청

## 공유 컨텍스트
{absolute_path}/context.md 파일을 Read하세요.

## 당신의 역할
{perspective} 관점에서 분석합니다.

## 질문
{역할별 핵심 질문 1~3개}

## 출력 요구사항
- {absolute_path}/opinion-{participant.key}.md에 저장
- {opinion_char_limit}자 이내
```

Critic 프롬프트 템플릿:
```markdown
# Critic 평가 요청 — {session_id}

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/opinion-{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

**도구 사용 원칙 (CRITICAL)**
> - 모든 호출은 `Task(run_in_background: true)` 래핑으로 병렬 실행
> - 각 응답은 파일로 직접 쓰기, 프롬프트도 파일로 저장 후 `--prompt-file` 사용
> - agent는 프롬프트 파일 실행 전 반드시 공유 컨텍스트 파일을 Read해야 합니다

> **모델 결정**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get ideation.agents.claude.tier models.providers.claude.default_tier)`로 tier를 구한 뒤 `models.providers.claude[{tier}]`로 resolve (opus / sonnet)

2. **participant Task() 발송** (`participants` 동적 순회):

- `provider: "codex"`:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex ideation 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/prompts/{participant.key}-prompt.md)\" > {absolute_path}/opinion-{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/opinion-{participant.key}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/prompts/{participant.key}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/opinion-{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/opinion-{participant.key}.md; exit $EC"
  )
  ```
- `provider: "claude"`:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[ideation.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. 결과를 opinion-{participant.key}.md에 Write. 완료 후 '완료'"
  )
  ```

3. **critic Task() 동시 발송** (`critics` 동적 순회, participant Task()와 동일 응답):

- `provider: "codex"`:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex ideation 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/prompts/critique-{criticKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "claude"`:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[ideation.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판 관점에서 분석. 결과를 critique-{criticKey}.md에 Write. 완료 후 '완료'"
  )
  ```

4. **진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
의견 수집 중  ({session_id})
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- participants가 없으면 상단 섹션만 출력
- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

결과 확인: `participants` 순회 → `opinion-{participant.key}.md` 존재 여부로 성공/실패 판단.

### Step 2.5: 완료 확인 및 상태 업데이트

각 백그라운드 태스크 완료 알림 도착 시 아래 형식으로 출력:
```
  [✓] {role} ({provider})  완료  [{n}/{participants_total + critics_total}]
```

모든 participants + critics가 완료되면:
```
의견 수집 완료  (참여자 {P}/{P}, 비평 {C}/{C})
→ synthesis 시작...
```

`participants` 순회 → 파일 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`. 세션 상태 일괄 업데이트 후 다음 Step 진행.

### Step 2.7: Critic 완료 확인

`critics` 키 순회 → `critique-{criticKey}.md` 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`.
실패 시 에러 처리는 기존 에러 처리 섹션 준수.

### Step 3: PM 종합 (Delegated Synthesis)

의견 파일 목록은 `participants` 항목 순회로 동적 생성:
- `opinion-{participant.key}.md` + 관점: `{participant.perspective}`
- `critique-{criticKey}.md` 순회

Synthesis prompt는 템플릿 `templates/ideation-synthesis.md` 사용.
세션 정보 또한 고정 인원 표기가 아닌 `participants` 동적 나열 형식으로 구성.

### Step 4: 인터랙티브 토론

**Step 4 진입 시 컨텍스트 판별 (최우선):**
`/mst:request`가 ideation을 서브 호출할 때는 호출 인자에 `--from-start` 플래그가 포함됨.
이 플래그 존재 여부로 분기한다.

- **[경로 A] `/mst:request` 서브 호출 (`--from-start` 포함):**
  1. `synthesis.md`를 호출자(/mst:request)에게 반환
  2. `session.json`의 `status`를 즉시 `"completed"`로 갱신

- **[경로 B] 독립 실행 (flags 없음):**
  1. `synthesis.md` 표시
  2. 사용자 질의 반영 토론 진행
  3. 내용 append: `discussion.md`
  4. `session.json`의 `status`를 `"discussing"` → 완료 시 `"completed"`로 갱신

## 에러 처리

참여자 수 대비 처리:
- 과반 이상 성공: 실패/누락 항목을 제외하고 합성 진행
- 과반 미만 성공: PM 자체 분석으로 보완 후 진행
- 전원 실패: 에러 메시지 + 재시도 안내
- CLI 미설치: 해당 AI 스킵, 사용 가능한 AI로만 진행

## 옵션

- `--focus {architecture|ux|performance|security|cost}`: 분석 범위를 특정 분야로 제한

## 세션 파일 구조

```
.gran-maestro/ideation/IDN-NNN/
├── session.json
├── context.md                          # 공통 배경 컨텍스트 (Step 2 병렬 Write)
├── prompts/
│   ├── {participant.key}-prompt.md     # 경량 프롬프트 (context.md Read 지시 포함)
│   ├── critique-{criticKey}-prompt.md
│   └── synthesis-prompt.md
├── opinion-{participant.key}.md
├── critique-{criticKey}.md
└── synthesis.md
```

## 예시

```
/mst:ideation "마이크로서비스 vs 모놀리식 아키텍처"
```
