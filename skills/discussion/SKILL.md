---
name: discussion
description: "설정된 AI 팀원들이 합의에 도달할 때까지 반복 토론합니다. 사용자가 '토론', '합의', '디스커션'을 말하거나 /mst:discussion를 호출할 때 사용. 1회성 의견 수집은 /mst:ideation 사용."
user-invocable: true
argument-hint: "{주제 또는 IDN-NNN} [--max-rounds {N}] [--focus {분야}]"
---

# maestro:discussion

설정된 AI 팀원들이 **합의에 도달할 때까지** 반복 토론합니다. PM(Claude)이 사회자 역할로 발산점을 식별하고 수렴을 유도합니다. Maestro 모드 활성 여부에 관계없이 사용 가능합니다.

## ideation과의 차이

| | ideation | discussion |
|---|---|---|
| 목적 | 다양한 관점 수집 (발산) | 합의 도달 (수렴) |
| 라운드 | 1회 | N회 반복 |
| 종료 조건 | PM 종합 완료 | 참여자 합의 또는 max rounds |
| 출력 | synthesis.md | consensus.md |

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

1. `{PROJECT_ROOT}/.gran-maestro/discussion/` 디렉토리 존재 확인, 없으면 생성
2. 새 세션 ID 채번 (DSC-NNN):
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type dsc` → 출력 ID 사용
   - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/discussion/counter.json` 파일 Read
     - **파일 존재 시**: `next_id = last_id + 1`
     - **파일 미존재 시** (최초 또는 복구):
       a. `{PROJECT_ROOT}/.gran-maestro/discussion/` 하위의 기존 DSC-* 디렉토리 스캔
       b. `{PROJECT_ROOT}/.gran-maestro/archive/` 내 `discussion-*` tar.gz 파일명에서 ID 범위 추출 (예: `discussion-DSC001-DSC006-*.tar.gz` → max 6)
       c. 모든 소스에서 최대 번호 결정 → `counter.json` 생성: `{ "last_id": {max_number} }`
       d. `next_id = last_id + 1`
     - `counter.json` 업데이트: `{ "last_id": {next_id} }`
3. `{PROJECT_ROOT}/.gran-maestro/discussion/DSC-NNN/` 디렉토리 생성 (NNN은 3자리 zero-padded)
4. `session.json` 작성:

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "id": "DSC-NNN",
  "topic": "{사용자 주제}",
  "source_ideation": "{IDN-NNN 또는 null}",
  "focus": "{focus 또는 null}",
  "status": "analyzing",
  "max_rounds": "{Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get discussion.default_max_rounds) 출력값}",
  "current_round": 0,
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "participants": [
    { "key": "architect(codex)", "role": "architect", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "ux(codex)", "role": "ux", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "security(codex)", "role": "security", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "architecture(gemini)", "role": "architecture", "perspective": "", "type": "opinion", "status": "pending", "provider": "gemini", "started_at": null, "completed_at": null },
    { "key": "cost(gemini)", "role": "cost", "perspective": "", "type": "opinion", "status": "pending", "provider": "gemini", "started_at": null, "completed_at": null },
    { "key": "risk(claude)", "role": "risk", "perspective": "", "type": "opinion", "status": "pending", "provider": "claude", "started_at": null, "completed_at": null }
  ],
  "critics": {
    "claude": { "status": "pending", "provider": "claude" }
  },
  "critic_count": 1,
  "participant_config": { "codex": 3, "gemini": 2, "claude": 1 },
  "rounds": []
}
```

`participants`는 config의 `discussion.agents`를 읽어 생성합니다.
### participants 동적 생성 규칙
1. 각 provider(codex, gemini, claude)의 count 읽기
2. count == 1 → key는 `{role}(provider)` 형태
3. count > 1 → role 키를 순차 생성, `{role}(provider)` 형태 유지
4. 각 항목에 `provider` 필드 기록
5. 합계 검증: 2~7명, 위반 시 에러 후 중단
6. count == 0 → 해당 provider 완전 skip

`participants` 키 없으면 기본값 `{ codex:1, gemini:1, claude:1 }` 사용.

### Step 1.5: PM 역할 배정

PM이 주제/포커스를 분석해 `participants` 수만큼 관점을 배정하고 `critics`를 결정합니다.
- Codex/Gemini/Claude 강점에 맞춰 관점 배정
- Critic 규칙: Claude 1명+ → Claude 우선, Claude 0명 → Codex → Gemini. critic_count 2 → 2명 배정

`session.json`에 `participants`, `critics`, `critic_count`, `participant_config`, `status: "initializing"` 기록.

### AUTO-CONTINUE 원칙 (CRITICAL)

> - 백그라운드 작업 완료 시 사용자에게 확인 질문 금지
> - 모든 단계는 사용자 입력 없이 자동 진행
> - 모든 호출이 모두 완료되면 즉시 다음 step 진행
> - Step 4e 종료 판단은 PM이 자율적으로 처리
> - 최종 사용자 보고는 Step 6에서만
> - ⚠️ Step 4c 건너뜀 금지: critic_count > 0이면 opinions 수집 후 반드시 Critic 평가 수행

### 프롬프트 파일 생성 원칙 (CRITICAL)

`shared-context.md`는 단독 Write, 프롬프트 파일은 **단일 combined 파일 Write → 스크립트 split** 패턴을 사용합니다:
- `session.json`, `shared-context.md` 작성은 기존대로 단일 응답 내 Write 처리
- 프롬프트 파일(N+M개)은 `prompts/combined-prompts.txt` **1개**에 `===SPLIT: {filename}===` 구분기호로 모두 포함
- combined-prompts.txt Write 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/NN/prompts` 실행

### Step 2: 초기 의견 수집

**IDN-NNN 입력 시**: ideation 의견 파일들을 `rounds/00/{participant.key}.md`로 복사 → Step 4 진입

**새 주제인 경우**:
1. **단일 응답에서 동시 Write 후 split 실행**:
   - `rounds/00/shared-context.md` — 주제 배경 + 핵심 논점
   - `rounds/00/prompts/combined-prompts.txt` — N+M개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함
     (participant N개 + critic M개, 아래 포맷 그대로 적용)

   combined-prompts.txt Write 완료 직후:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/00/prompts
   ```
   → `rounds/00/prompts/{participant.key}-prompt.md` × N, `rounds/00/prompts/critique-{criticKey}-prompt.md` × M 자동 생성

개별 프롬프트 포맷 (Round 0):
```markdown
# {Role} 관점 의견 요청 — DSC-NNN Round 0


<!-- @include _shared/skill-execution-marker.md -->
## 스킬 실행 마커 (MANDATORY)

- 모든 응답의 첫 줄 또는 각 Step 시작 줄에 아래 마커를 출력한다.
- 기본 마커 포맷: `[MST skill={name} step={N}/{M} return_to={parent_skill/step | null}]`
- 필드 규칙:
  - `skill`: 현재 실행 중인 스킬 이름
  - `step`: 현재 단계(`N/M`) 또는 서브스킬 종료 시 `returned`
  - `return_to`: 최상위 스킬이면 `null`, 서브스킬이면 `{parent_skill}/{step_number}`
- 서브스킬 종료 마커: `[MST skill={subskill} step=returned return_to={parent/step}]`
- C/D 분리 마커 규칙을 추가로 사용하지 않는다. 반드시 단일 MST 마커만 사용한다.
- 예시:
  - `[MST skill={name} step=1/3 return_to=null]`
  - `[MST skill={subskill} step=returned return_to={parent_skill}/{step_number}]`
<!-- @end-include -->

## 공유 컨텍스트
{absolute_path}/rounds/00/shared-context.md 파일을 Read하세요.

## 당신의 역할
{perspective} 관점에서 분석합니다.

## 질문
{역할별 핵심 질문 1~3개}

## 출력 요구사항
- {absolute_path}/rounds/00/{participant.key}.md에 저장
- {response_char_limit}자 이내
```

Critic 프롬프트 템플릿 (Round 0):
```markdown
# Critic 평가 요청 — {session_id}  Round 0

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/rounds/00/{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/rounds/00/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

2. **participant Task() + critic Task() 동시 발송** (단일 응답):

   > **모델 결정**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get discussion.agents.claude.tier models.providers.claude.default_tier)`로 tier를 구한 뒤 `models.providers.claude[{tier}]`로 resolve (opus / sonnet)

   participant 발송 (`participants` 동적 순회):
   - `provider: "codex"`:
     ```
     Bash(
       run_in_background: true,
       command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/00/prompts/{participant.key}-prompt.md)\" > {absolute_path}/rounds/00/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/{participant.key}.md; exit $EC"
     )
     ```
   - `provider: "gemini"`:
     ```
     Bash(
       run_in_background: true,
       command: "gemini -p \"$(cat {absolute_path}/rounds/00/prompts/{participant.key}-prompt.md)\" --model {config.models.providers.gemini[discussion.agents.gemini.tier || default_tier]} --approval-mode yolo --sandbox=false > {absolute_path}/rounds/00/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/{participant.key}.md; exit $EC"
     )
     ```
   - `provider: "claude"`:
     ```
     Task(
       subagent_type: "general-purpose",
       model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
       run_in_background: true,
       prompt: "{absolute_path}/rounds/00/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. 결과를 {absolute_path}/rounds/00/{participant.key}.md에 Write. 완료 후 '완료'"
     )
     ```

   critic 동시 발송 (`critics` 동적 순회):
   - `provider: "codex"`:
     ```
     Bash(
       run_in_background: true,
       command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/rounds/00/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/critique-{criticKey}.md; exit $EC"
     )
     ```
   - `provider: "gemini"`:
     ```
     Bash(
       run_in_background: true,
       command: "gemini -p \"$(cat {absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md)\" --model {config.models.providers.gemini[discussion.agents.gemini.tier || default_tier]} --approval-mode yolo --sandbox=false > {absolute_path}/rounds/00/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/critique-{criticKey}.md; exit $EC"
     )
     ```
   - `provider: "claude"`:
     ```
     Task(
       subagent_type: "general-purpose",
       model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
       run_in_background: true,
       prompt: "{absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판적 시각으로 분석. 결과를 {absolute_path}/rounds/00/critique-{criticKey}.md에 Write. 완료 후 '완료'"
     )
     ```

3. **진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
의견 수집 중  ({session_id}  Round 0)
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

각 호출은 `Task(run_in_background: true)`로 병렬 실행됩니다.

### Step 3: PM 초기 종합

`rounds/00/synthesis.md` 생성: `rounds/00/{participant.key}.md` 순회 → `templates/discussion-round-synthesis.md` 템플릿 사용 → `status: "debating"`, `current_round: 0`

#### Step 3.5: Critic 초기 평가 (단일 라운드 수렴 시)

`critic_count >= 1`이면: `rounds/00` 응답 기반으로 `rounds/00/prompts/critique-{criticKey}-prompt.md` 생성 → Step 4c와 동일 방식으로 `rounds/00/critique-{criticKey}.md` 저장. Step 4 미실행 시에도 Critic 평가 보장.

> **NOTE**: "Step 4c와 동일 방식"은 Step 2 (R0) critic 발송 블록의 Bash 직접 호출 패턴을 가리킵니다. `provider: "codex"` → `Bash(codex exec ...)`, `provider: "gemini"` → `Bash(gemini -p ...)`, `provider: "claude"` → `Task(...)` 방식으로 dispatch하되, 경로는 `rounds/00/prompts/critique-{criticKey}-prompt.md` → `rounds/00/critique-{criticKey}.md`를 사용합니다.

### Step 3.6: Round 0 완료 상태 업데이트

`participants` 순회 → `rounds/00/{participant.key}.md` 존재 여부 확인 (성공: `"done"`, 실패: `"failed"`)

`session.json` 단일 Write:
- `participants` 상태 반영, `rounds` 배열에 `{ "round": 0, "status": "completed" }` 추가, `current_round: 0`, `status: "debating"`

### Step 4: 토론 라운드 (반복)

#### 4a. PM이 맞춤 프롬프트 작성

이전 라운드 발산점 기반으로 **단일 응답에서 Write 후 split 실행**:
- `rounds/NN/shared-context.md` — 이전 라운드 입장 요약 테이블 + 발산점 목록
- `rounds/NN/prompts/combined-prompts.txt` — N개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함

combined-prompts.txt Write 완료 직후:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/NN/prompts
```
→ `rounds/NN/prompts/{participant.key}-prompt.md` × N 자동 생성

> Round N의 critic 프롬프트가 있는 경우 같은 combined 파일에 포함하여 함께 split

`shared-context.md` 구조 (Round N):
```markdown
# DSC-NNN Round N — 공유 컨텍스트

## 이전 라운드 입장 요약
| 역할 | 핵심 주장 |
|------|----------|
| {role} ({provider}) | {1~2줄 요약} |
...

## 핵심 발산점
1. {발산점 1}
2. {발산점 2}

## 이번 라운드 목표
{PM이 수렴 방향 제시}
```

개별 프롬프트 포맷 (Round N):
```markdown
# {Role} 반론 수용 요청 — DSC-NNN Round N

## 공유 컨텍스트
{absolute_path}/rounds/NN/shared-context.md 파일을 Read하세요.

## 당신의 역할
{role} 관점에서 응답합니다.
이전 라운드 당신의 핵심 입장: {1~2줄}

## 이번 라운드 질문
{역할에 맞춘 반론/수렴 질문 1~3개}

## 출력 요구사항
- {absolute_path}/rounds/NN/{participant.key}.md에 저장
- {response_char_limit}자 이내
```

#### 4b. 역할 기반 병렬 호출

**단일 응답에서** participant 프롬프트 파일 + critic 프롬프트 파일을 함께 생성 후, participant Task() + critic Task() 동시 발송.

Critic 프롬프트 템플릿 (Round N):
```markdown
# Critic 평가 요청 — {session_id}  Round {N}

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/rounds/NN/{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/rounds/NN/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

participant 발송 (`participants` 동적 순회):
- `provider: "codex"`:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md)\" > {absolute_path}/rounds/NN/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/{participant.key}.md; exit $EC"
  )
  ```
- `provider: "gemini"`:
  ```
  Bash(
    run_in_background: true,
    command: "gemini -p \"$(cat {absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md)\" --model {config.models.providers.gemini[discussion.agents.gemini.tier || default_tier]} --approval-mode yolo --sandbox=false > {absolute_path}/rounds/NN/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/{participant.key}.md; exit $EC"
  )
  ```
- `provider: "claude"`:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. 결과를 {absolute_path}/rounds/NN/{participant.key}.md에 Write. 완료 후 '완료'"
  )
  ```

critic 동시 발송 (`critics` 동적 순회):
- `provider: "codex"`:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/rounds/NN/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "gemini"`:
  ```
  Bash(
    run_in_background: true,
    command: "gemini -p \"$(cat {absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md)\" --model {config.models.providers.gemini[discussion.agents.gemini.tier || default_tier]} --approval-mode yolo --sandbox=false > {absolute_path}/rounds/NN/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "claude"`:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판적 시각으로 분석. 결과를 {absolute_path}/rounds/NN/critique-{criticKey}.md에 Write. 완료 후 '완료'"
  )
  ```

**진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
토론 라운드 {N}  ({session_id})
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

### Step 4c. Critic 완료 확인 ⚠️ MANDATORY

> **절대 건너뛰기 금지**: `critic_count > 0`이면 Step 4d로 진행하기 전 `critique-{criticKey}.md` 파일이 존재해야 한다.

`critics` 키 순회 → `rounds/NN/critique-{criticKey}.md` 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`.
실패 시 에러 처리는 기존 에러 처리 섹션 준수.

### Step 4d. 라운드 종합

> **사전 조건**: `critic_count > 0`이면 `rounds/NN/critique-{criticKey}.md` 존재 필수. 없으면 Step 4c로 복귀.

- 입력: `rounds/{NN-1}/synthesis.md` + `rounds/NN/{participant.key}.md` + `rounds/NN/critique-{criticKey}.md`
- 출력: `rounds/NN/synthesis.md` (`templates/discussion-round-synthesis.md` 동적 표 사용)
- `status`, `current_round` 업데이트

### Step 4d.5: Round N 완료 상태 업데이트

`participants` 순회 → `rounds/NN/{participant.key}.md` 존재 여부 (성공: `"done"`, 실패: `"failed"`)
`critics` 순회 → `rounds/NN/critique-{criticKey}.md` 존재 여부 (성공: `"done"`, 실패: `"failed"`)

`session.json` 단일 Write: `participants`/`critics` 상태 반영, `rounds` 배열에 `{ "round": N, "status": "completed" }` 추가, `current_round: N`

### Step 4e. 수렴 판단

PM이 합의 정도 판정: 기준 충족 또는 최대 라운드 도달 시 Step 5, 미충족 시 다음 라운드 수행.

### Step 5: 합의문 작성

최종 consensus.md 생성: `participants` 키/Provider 동적 나열, 미합의 사항 행 반복, 라운드 합의 이력 및 critic 기여 기록.

## 에러 처리

- 과반 이상 성공: 실패 항목 제외 후 진행
- 과반 미만 성공: PM 자체 보완 분석
- 전원 실패: 에러 + 재시도 안내

## 세션 파일 구조

```
.gran-maestro/discussion/DSC-NNN/
├── session.json
├── rounds/
│   ├── 00/
│   │   ├── shared-context.md           # 공유 배경 컨텍스트 (Step 2 병렬 Write)
│   │   ├── prompts/
│   │   │   ├── {participant.key}-prompt.md  # 경량 프롬프트 (shared-context.md Read 지시 포함)
│   │   │   ├── critique-{criticKey}-prompt.md
│   │   │   └── synthesis-prompt.md
│   │   ├── {participant.key}.md
│   │   ├── critique-{criticKey}.md
│   │   └── synthesis.md
│   └── NN/
│       ├── shared-context.md           # 이전 입장 요약 + 발산점 (Step 4a 병렬 Write)
│       ├── prompts/
│       │   ├── {participant.key}-prompt.md  # 경량 프롬프트 (shared-context.md Read 지시 포함)
│       │   └── critique-{criticKey}-prompt.md
│       ├── {participant.key}.md
│       ├── critique-{criticKey}.md
│       └── synthesis.md
├── consensus.md
```

## 옵션

- `--focus {architecture|ux|performance|security|cost}`: 분석 포커스 지정
- `--max-rounds {N}`: 최대 토론 라운드 지정

## 참고

총합 2~7명 규칙과 participants/critics 동적 배정은 ideation과 동일.
