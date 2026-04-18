---
name: stitch
description: "Stitch SDK를 사용해 UI 화면을 설계합니다. 명시적 디자인 요청, 새 화면 추가, 전체 디자인 변경 시 사용."
user-invocable: true
argument-hint: "[--auto] [--variants] [--init] [--req REQ-NNN] [--model pro|flash] [--edit SCREEN_ID] [--alt SCREEN_ID] [--reimagine] [--redesign SCREEN_ID] [--multi] [--screens \"화면1,화면2,...\"] {화면 설명}"
---

# maestro:stitch

## 선행 조건 확인

1. `config.stitch.enabled` 확인 → false면 즉시 종료 (안내 메시지 출력)
2. **모델 ID 해석**:
   - `config.stitch.model_id` 읽기 → 미설정(null/undefined)이면 `"MODEL_ID_UNSPECIFIED"`
   - `--model` 옵션 확인:
     - `--model pro` → `"GEMINI_3_PRO"` 오버라이드
     - `--model flash` → `"GEMINI_3_FLASH"` 오버라이드
     - 유효하지 않은 값 → "[Stitch] 알 수 없는 모델: {값}. config 기본값({config.stitch.model_id})을 사용합니다." 출력 후 config 값 유지
   - 결과를 `{STITCH_MODEL}` 변수에 보관 (이후 모든 SDK 호출에 사용)
3. `config.stitch.auto_detect` 확인:
   - false면: 사용자 명시 설정으로 간주 → 계속
   - true면:
     a. **UI 키워드 1차 필터**: 요청 텍스트/spec §1 요약에 아래 키워드 중 하나라도 포함되지 않으면 list_projects 호출 없이 skip:
        - whitelist: `화면`, `UI`, `페이지`, `page`, `screen`, `컴포넌트`, `component`, `레이아웃`, `layout`, `디자인`, `design`, `목업`, `mockup`, `시안`, `뷰`, `view`
     b. **세션 캐시 확인**: 현재 세션 중 이미 `list_projects`를 성공 호출한 결과가 있으면 재사용 (재호출 생략)
     c. 캐시 미존재 시: `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-projects")` 호출 (30초 타임아웃)
        - 성공: 결과를 세션 캐시에 저장 → 계속
        - 응답 JSON이 `ok=false` 이고 `auth_required=true`면 아래 가이드 흐름 실행:
          1) `setup_url`(없으면 `https://stitch.withgoogle.com/settings`) 확인 후 브라우저 열기 시도:
             - `Bash(command: "open {setup_url}")` (실패 시 URL을 그대로 출력하고 수동 접속 안내)
          2) `AskUserQuestion`으로 API Key 입력 요청:
             - 안내 문구에 `env_var`(기본 `STITCH_API_KEY`)와 `setup_url`을 포함
          3) 사용자가 입력한 값을 현재 세션에 설정:
             - `export STITCH_API_KEY="{USER_INPUT_API_KEY}"`
          4) 방금 실패한 동일 명령을 즉시 자동 재시도:
             - `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-projects")`
          5) 재시도 성공 시 세션 캐시에 저장 후 계속
          6) 영구 저장 안내:
             - `echo 'export STITCH_API_KEY="{USER_INPUT_API_KEY}"' >> ~/.zshrc`
             - `source ~/.zshrc`
        - 실패/타임아웃(또는 재시도 실패): `[Stitch] 연결 불가 — 건너뜀. /mst:stitch로 수동 실행 가능.` 출력 후 종료


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

## 시안 제시 금지 행위 (CRITICAL)

> ⚠️ **시안 제시 금지 행위 (CRITICAL)**: 시안 생성 완료 후 결과를 사용자에게 보여줄 때, 아래 행위는 **절대 금지**합니다:
> - `curl`로 HTML/이미지 다운로드하여 로컬에서 보여주기
> - `python3 -m http.server` 등 로컬 서버를 실행하여 시안 미리보기
> - Claude in Chrome(`navigate`, `tabs_create`, `computer` 등) 브라우저 자동화로 시안 표시
> - 기타 외부 도구를 사용한 시안 직접 미리보기
>
> 시안 확인은 **대시보드 Designs 탭**에서만 수행합니다.
> 모든 결과 보고에 `{DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}` URL만 안내하세요.
> 이 규칙은 최초 시안, Edit 결과, Alt 결과, Redesign 결과 등 **모든 시안 제시 시점**에 적용됩니다.

## DES 채번 및 프로젝트 확인/생성

<!-- @include _shared/path-rules.md -->
> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
<!-- @end-include -->

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (AskUserQuestion 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 `AskUserQuestion`과 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->


> ⚠️ **DES 채번 스킵 조건**: `--edit`, `--alt`, `--redesign`, `--list`, `--init` 플래그가 있으면
> 이 섹션(Step A~C-2)을 건너뛰고 해당 프로토콜로 직접 진행한다.

> ⚠️ 이 단계는 화면 생성 이전에 실행된다.

1. **Step A: DES 채번**

```
python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type des
```
출력: `DES-NNN` (예: `DES-001`)

최초 실행 시 `{PROJECT_ROOT}/.gran-maestro/designs/` 디렉토리와 `counter.json`이 자동 생성된다.

2. **Step B: DES-NNN 디렉토리 생성**

`{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/`

3. **Step C: design.json 초안 작성**

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`

```json
{
  "id": "DES-NNN",
  "title": "{사용자 요청 요약}",
  "status": "active",
  "created_at": "{TS}",
  "linked_plan": "{활성 PLN ID 또는 null}",
  "linked_req": "{활성 REQ ID 또는 null}",
  "stitch_project_id": null,
  "stitch_project_url": null,
  "screens": []
}
```

4. **Step C-1: DES 전용 Stitch 프로젝트 확인/생성**

`design.json`의 `stitch_project_id` 확인:
- **값 있으면**: `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-project --project-id {stitch_project_id}")` 호출로 유효성 검증
  - 실패(프로젝트 삭제/만료) 시: 아래 "null이면" 절차로 재생성
- **null이면**: `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs create-project --title 'DES-NNN: {design.json title}'")`로 DES 전용 프로젝트 생성
  - 프로젝트 이름: `"DES-NNN: {design.json title}"`
  - `design.json`에 즉시 갱신:
    ```json
    "stitch_project_id": "{생성된 project_id}",
    "stitch_project_url": "https://stitch.withgoogle.com/projects/{project_id}"
    ```

이후 모든 화면 생성(`generate_screen_from_text`, `generate_variants`)은 이 DES 전용 `stitch_project_id`를 사용한다.

5. **Step C-2: 대시보드 URL 구성**

대시보드 링크에 사용할 URL 변수를 DES 채번 직후 명시적으로 구성한다.

1. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get server.host server.port)`로 `server.host`, `server.port`를 확인한다.
2. `server.host`가 없거나 파일 Read에 실패하면 `127.0.0.1`을 사용한다.
3. `server.port`가 없거나 파일 Read에 실패하면 `3847`을 사용한다.
4. 아래 변수를 구성한다:
   - `{DASHBOARD_BASE_URL}` = `http://{server.host}:{server.port}`
5. 대시보드 API를 호출하여 현재 프로젝트의 `projectId`를 해석한다:
   - `curl -s "{DASHBOARD_BASE_URL}/api/projects"`
   - 응답 JSON 배열에서 `path`가 `{PROJECT_ROOT}/.gran-maestro`와 일치하는 항목의 `id`를 `{projectId}`로 사용한다.
   - 매칭 항목이 없으면 로컬 대시보드 링크 출력을 생략하고 원인을 사용자에게 안내한다.
6. 이후 모든 사용자 출력에서 로컬 대시보드 링크는 반드시 아래 형식을 사용한다:
   - `{DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}`

## 기존 화면 컨텍스트 수집 (선택)

기존 UI 화면이 있는 경우 레이아웃 일관성을 위해:
1. `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 로 기존 Stitch 화면 목록 조회
2. 기존 화면이 있으면: 최근 화면 1-2개의 핵심 레이아웃 패턴을 텍스트로 요약 (공통 Header/Sidebar 구조, 주요 컴포넌트 패턴)
3. 이 컨텍스트를 `generate_screen_from_text` 프롬프트에 포함

## 프로젝트 초기화 (--init)

`--init` 옵션이 전달되면 신규 화면 생성 전에 아래를 먼저 수행한다.

1. `config.stitch.project_id`를 확인한다. 미설정이면 에러 출력 후 종료한다.
2. 아래 명령으로 프로젝트 + 화면 컨텍스트를 수집한다:
   - `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs init --project-id {config.stitch.project_id}")`
3. JSON 응답의 `summary.theme`, `screens`, `project`를 바탕으로 DESIGN.md 초안을 생성한다.
4. 저장 경로: `{PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md`
5. `--init` 단독 호출이면 여기서 종료하고, 일반 생성 플로우와 함께 호출됐으면 아래 화면 생성 프로토콜을 계속 진행한다.

## 트리거 분기

### A. 명시적 디자인 요청 (즉시 실행)
- 감지: "화면 디자인해줘", "Stitch로 그려줘", "목업 만들어줘" 등 명시적 디자인 의도
- 처리: 사용자 확인 없이 바로 화면 생성 프로토콜 진행

### B. 새 화면 추가 요청 (사용자 선택)
- 강한 신호: 새 라우트 파일 생성 + 네비게이션 노출 예정
- 중간 신호: "새/추가/신규 화면/페이지" 키워드 포함
- config.stitch.auto_trigger=false(기본): "Stitch로 화면 먼저 설계할까요?" 물어봄
- config.stitch.auto_trigger=true: 자동 실행

### C. 전체 디자인 변경 (사용자 선택 + variants)
- 감지: "전체 디자인 바꿔줘", "리디자인", "전면 개편" 등
- 처리: B와 동일하게 확인 후, --variants 옵션으로 2-3개 방향 제안

### D. 약한 신호 (개입 안 함)
- 기존 화면 컴포넌트/스타일 수정만 → Stitch 개입 없음

### E. 멀티 스타일 요청 (--multi 플래그 또는 plan Step 4.5 진입)
- 감지: `--multi` 플래그 명시 or `mst:plan` Step 4.5 "스티치로 디자인 시안 보기" 선택 진입
- 처리: 사용자 확인 없이 바로 **멀티 스타일 생성 프로토콜** 진행

### F. Edit 요청 (--edit SCREEN_ID)
- 감지: `--edit` 플래그 + SCREEN_ID + 편집 프롬프트
- 처리: 사용자 확인 없이 **Edit 프로토콜** 진행

### G. Alt 요청 (--alt SCREEN_ID)
- 감지: `--alt` 플래그 + SCREEN_ID + 대안 프롬프트
- 처리: 기본은 variants(EXPLORE, 2개)로 **Alt 프로토콜** 진행
- 예외: `--alt SCREEN_ID --reimagine` 조합이면 **Redesign 프로토콜** 진행

### H. Redesign 요청 (--redesign SCREEN_ID)
- 감지: `--redesign` 플래그 + SCREEN_ID
- 처리: `--alt SCREEN_ID --reimagine`과 동일 처리 (**Redesign 프로토콜** alias)

## 화면 생성 프로토콜

0. **baseline_screen_ids 기록**:
   - `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출 → 응답의 `screens[].name`에서 screen ID를 추출하여
     `baseline_screen_ids` Set으로 저장
   - screen ID 추출: `name` 필드의 마지막 `/` 이후 값 (예: `"projects/.../screens/abc123"` → `"abc123"`)

1. **중복 체크 (diff hash)**:
   - REQ-NNN이 있을 경우: `request.json`의 `stitch_screens`에서 동일 `route + hash` 조합 확인 (기존 동일)
   - REQ-NNN 없고 PLN-NNN이 있을 경우: `plan.json`의 `stitch_screens`에서 확인
   - 둘 다 없을 경우: 중복 체크 생략
   - `status: "active"` 항목 발견 시: "이미 생성된 화면입니다." 출력 후 기존 URL 반환, 종료
   - `status: "pending"` 항목 발견 시: 이전 생성 시도가 타임아웃됐을 가능성 있음 → 서버 확인 진행
     - `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출로 실제 화면 존재 여부 확인
     - 발견 시: `get_screen`으로 URL 확보 → pending 항목을 active로 갱신 → 기존 URL 반환, 종료
       - **output_components HTML 확인**: `get_screen` 응답의 `output_components`를 확인하여 Step 4-2의 output_components 파싱 규칙을 따른다
         - 코드 포함 시: `html_content` 메모리 변수에 보관 (파일 저장은 Step D에서 md와 동시 수행)
         - 비어있거나 제안 텍스트인 경우: `html_content = null`
     - 매칭 기준:
       - pending 항목에 `baseline_screen_ids`가 있으면: 현재 screen IDs에서 baseline_screen_ids 제거(차집합) → 차집합이 비어있지 않으면 해당 화면 중 첫 번째 선택
       - `baseline_screen_ids`가 없으면(구버전 pending): `created_at` 이후 생성된 화면 중 최근 3개를 검사 (기존 방식 유지)
     - 미발견 시: `stale_at`(= `created_at` + 15분) 경과 여부 확인
       - `stale_at` 이내: pending 항목 유지 → "이전 생성 요청이 아직 처리 중일 수 있습니다. 잠시 후 다시 시도하세요." 출력 후 종료
       - `stale_at` 경과: pending 항목 제거 → 새 생성 진행

2. **pending 선기록**:
   - REQ-NNN이 있을 경우: `generate_screen_from_text` 호출 직전 `request.json`의 `stitch_screens`에 임시 항목 기록 (기존 동일):
     ```json
     { "status": "pending", "hash": "{hash}", "route": "{route}", "created_at": "{TS}", "baseline_screen_ids": ["{id1}", "{id2}", ...] }
     ```
   - REQ-NNN 없고 PLN-NNN이 있을 경우: `plan.json`의 `stitch_screens`에 기록 (형식 동일):
     ```json
     { "status": "pending", "hash": "{hash}", "created_at": "{TS}", "baseline_screen_ids": ["{id1}", "{id2}", ...] }
     ```
   - 둘 다 없을 경우: pending 선기록 생략
   - 빈 응답/타임아웃 발생 시 이 항목이 재실행 중복 방지에 사용됨

2.5. **프롬프트 향상 (references 기반)**:
   - 아래 파일을 먼저 Read:
     - `{PROJECT_ROOT}/skills/stitch/references/design-mappings.md`
     - `{PROJECT_ROOT}/skills/stitch/references/prompt-keywords.md`
   - 요청문을 그대로 전달하지 말고, 위 레퍼런스를 근거로 생성 프롬프트를 구조화한다.
   - 최종 프롬프트에는 최소 아래 섹션을 포함한다:
     - `**DESIGN SYSTEM**`
     - `**Page Structure**`
   - `{PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md`가 존재하면 톤/타이포/색상/레이아웃 지침을 `**DESIGN SYSTEM**`에 우선 반영한다.
   - Step 4의 `{화면 설명}` 자리에는 향상된 최종 프롬프트를 사용한다.

3. **대기 안내 메시지 출력**:
   ```
   [Stitch] 화면 생성 중... (최대 수 분 소요될 수 있습니다)
   ```

4. **화면 생성**:
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs generate --project-id {stitch_project_id} --prompt \"{화면 설명}\n\n[기존 레이아웃 컨텍스트]\n{수집된 컨텍스트}\" --device-type DESKTOP --model-id {STITCH_MODEL}")
   ```
   - **응답 있음 (screen_id 포함)**: step 4-2(output_components 저장)로 진행
   - **빈 응답/null**: 비동기 수락으로 처리 → 폴링 루프(4-1) 진입 (재시도 금지)
   - **명시적 오류(예외)**: 실패 처리 (기존 동일)

4-2. **output_components HTML 저장** (step 4 응답 있음 시):
   - `output_components` 필드 확인:
     - **코드 포함 시** (HTML/CSS/JSX/React 코드를 담은 비어있지 않은 텍스트, 제안 문구 아님):
       - 스크린 파일 번호 산출: `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/screen-*.md` 파일 수 + 1 (없으면 `001`)
       - `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/screen-{NNN}.html` 에 저장
       - `html_file_path` 메모리 변수에 경로 보관 (Step D, E에서 사용)
     - **비어있거나 제안 텍스트인 경우** (예: "Yes, make them all"): `html_file_path = null`
   → step 5(get_screen)로 진행

4-1. **폴링 루프** (빈 응답인 경우만):
   최대 20회, 30초 간격 (총 최대 10분)
   > ⚠️ **MANDATORY**: 반드시 20회를 모두 채울 때까지 루프를 종료하지 않는다. 중간에 임의로 중단하는 것은 금지다.

   반복마다 (poll_count = 1부터 시작, 20 이하인 동안 반복):
   a. `python3 {PLUGIN_ROOT}/scripts/mst.py stitch sleep --interval 30` (Bash 호출)
   b. `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출
   c. `현재 screen IDs - baseline_screen_ids ≠ ∅` 인가?
      - YES: 차집합의 첫 번째 screen ID 선택 → step 5로 진행
      - NO: `[Stitch] 대기 중... ({poll_count}/20회)` 출력 후 poll_count += 1, 반복 계속

   20회 모두 미감지 시:
   - "[Stitch] 화면 생성 요청이 처리 중입니다 — 수 분 내 완료됩니다. 잠시 후 /mst:stitch --list로 확인하세요." 출력
   - pending 항목 유지 (`stale_at` = `created_at` + 15분)
   - 종료

5. **화면 URL 확보** (`get_screen` 최대 3회 재시도):
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {screen_id}")
   ```
   - 실패 시 5초 대기 후 재시도, 최대 3회
   - 3회 모두 실패 시: screen_id를 pending 항목에 기록하고 "[Stitch] 화면 URL 확보 실패 — screen_id: {id}. 나중에 /mst:stitch --list로 확인 가능합니다." 출력
   - **output_components HTML 확인** (폴링 경로 전용):
     - `html_file_path`가 이미 설정되어 있으면(동기 경로에서 Step 4-2가 저장 완료): 이 단계 skip
     - `html_file_path`가 미설정이면(폴링 경로): `get_screen` 응답의 `output_components`를 확인하여 Step 4-2의 output_components 파싱 규칙을 따른다
       - 코드 포함 시: `html_content` 메모리 변수에 보관 (파일 저장은 Step D에서 md와 동시 수행)
       - 비어있거나 제안 텍스트인 경우: **html 대기 루프**(30초 간격 최대 20회, 총 최대 10분)로 재확인
         - ⚠️ 이 루프는 screen_id 감지용 Step 4-1 폴링과 별도이며, screen_id 확보 이후에만 실행
         - `html_wait_count = 1`로 시작, `html_wait_count <= 20` 동안 반복:
           a. `python3 {PLUGIN_ROOT}/scripts/mst.py stitch sleep --interval 30`
           b. `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {screen_id}")` 재호출
           c. `output_components` 재확인:
              - 코드 포함 시: `html_content` 메모리 변수에 보관하고 루프 종료
              - 여전히 비어있거나 제안 텍스트면 `[Stitch] HTML 대기 중... ({html_wait_count}/20회)` 출력 후 `html_wait_count += 1`
         - 20회 모두 코드 미확인 시: `html_content = null`로 확정

6. **variants 요청 시** (--variants 또는 트리거 C):
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs variants --project-id {stitch_project_id} --screen-id {생성된 screen_id} --prompt \"다양한 레이아웃과 색상 방향으로 3가지 변형 생성\" --variant-count 3 --creative-range EXPLORE --model-id {STITCH_MODEL}")
   ```

## 멀티 스타일 생성 프로토콜

`--multi` 플래그 또는 plan Step 4.5 진입 시 이 프로토콜을 실행한다.

> **멀티 스타일 × 멀티 화면**: 이 프로토콜은 복수의 스타일 방향 각각에 대해 복수의 화면을 생성하는 구조를 지원한다.
> 총 생성 수 = 스타일 수(N) × 화면 수(M). 화면 목록이 1개이면 기존 동작과 동일하다.

-1. **기존 배치 재진입 체크** (Step 0 전 실행):

   REQ-NNN이 있을 경우 `request.json`, REQ-NNN 없고 PLN-NNN이 있을 경우 `plan.json`의
   `stitch_screens`에서 `type: "multi_style_batch"` + `status: "pending"` 항목 탐색.
   미발견 시: 이 단계 skip → Step 0부터 정상 실행.

   발견 시:
   a. `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출 → 현재 screen IDs 확인
   b. diff = 현재 screen IDs − pending 항목의 `baseline_screen_ids`
   c. 기대 화면 수 = `styles` 수 × `screen_list` 수 (screen_list 미존재 시 1로 간주 — 이전 버전 pending 항목(screen_list 필드 미포함) 호환용)
      - ※ 신규 pending 항목은 항상 `screen_list` 필드를 포함하여 저장한다 (Step 2 참조)
   d. diff 크기 판단:

      **diff >= 기대 화면 수 (화면 생성 완료):**
      - "[Stitch] 이전 세션에서 {N}개 스타일 × {M}개 화면이 생성되었습니다. 선택 화면으로 이동합니다." 출력
      - diff의 screen_ids(최신 N×M개)를 `accumulated_screens`로 로드
      - 각 screen_id에 대해 `get_screen` 호출로 `downloadUrl` 확보 (최대 3회 재시도)
        - **output_components HTML 확인**: 해당 `스타일명+화면명` 키가 html_file_path 맵에 이미 설정되어 있으면 skip. 미설정이면 `get_screen` 응답의 `output_components`를 확인하여 Step 4-2의 output_components 파싱 규칙을 따른다. 코드 포함 시 `스타일명+화면명 → html_content` 맵에 보관 (파일 저장은 Step 5.5에서 md와 동시 수행). 비어있거나 제안 텍스트인 경우 null.
      - `styles` 배열 순서 × `screen_list` 순서로 스타일명+화면명 매핑 (인덱스 기반)
      - 멀티 스타일 프로토콜 **Step 6(사용자 표시) → Q7부터 재개** (새 generation 없음)
      - ⚠️ Step 0~5 전체 skip

      **diff < 기대 화면 수 + stale_at(= `created_at` + 15분) 이내 (생성 진행 중):**
      - "[Stitch] 이전 배치 생성이 진행 중입니다 — 폴링을 재개합니다." 출력
      - `accumulated_screens` = 이미 수집된 diff 항목들 (부분 완료분)
      - pending 항목의 `baseline_screen_ids`를 현재 baseline으로 재사용 (list_screens 재호출 불필요)
      - 나머지 화면 수 = 기대 화면 수 − diff 크기 → 폴링 목표로 설정
      - 멀티 스타일 프로토콜 **Step 4(폴링 루프)부터 재개** (Step 2~3 skip)

      **diff < 기대 화면 수 + stale_at 초과 (배치 만료):**
      - "[Stitch] 이전 배치가 만료되었습니다. 새로 생성합니다." 출력
      - 기존 pending 항목 제거 (`stitch_screens` 배열에서 삭제)
      - Step 0부터 정상 실행 (새 배치 생성)

0. **baseline_screen_ids 기록** (1회):
   - `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출 → 응답의 `screens[].name`에서 screen ID 추출 → `baseline_screen_ids` Set으로 저장
   - screen ID 추출: `name` 필드에서 마지막 `/` 이후 값

0.5. **화면 목록 사전 정의** (Step 1 전 실행):
   - `--screens` 옵션이 있으면: 쉼표 구분 문자열을 파싱하여 `screen_list` 배열 생성
     - 예: `--screens "로그인,대시보드,설정"` → `["로그인", "대시보드", "설정"]`
   - `--screens` 옵션이 없으면:
     1. PM이 요청 텍스트/plan 내용을 분석하여 컨텍스트에 적합한 추천 화면 목록 도출
     2. `AskUserQuestion`으로 화면 목록 선택 요청:

     **옵션 구성** (PM이 컨텍스트 기반으로 동적 결정):
     - 옵션 1: `"{주요 화면 1개}"` — label: 화면명, description: "단일 화면만 생성"
     - 옵션 2: `"{주요 화면}, {연관 화면 1}"` — label: "화면명1, 화면명2", description: "2개 화면 생성"
     - 옵션 3: `"{주요 화면}, {연관 화면 1}, {연관 화면 2}"` — label: "화면명1, 화면명2, 화면명3", description: "3개 화면 생성"
     - Other (자유 입력): 직접 쉼표 구분 입력 가능 (예: `"로그인, 대시보드, 설정"`)

     **예시** (요청이 "로그인 화면 디자인"인 경우):
     - 옵션 1 label: `"로그인"`, description: `"로그인 화면 1개만 생성"`
     - 옵션 2 label: `"로그인, 회원가입"`, description: `"인증 관련 2개 화면 생성"`
     - 옵션 3 label: `"로그인, 회원가입, 비밀번호 찾기"`, description: `"인증 플로우 3개 화면 생성"`

     **컨텍스트가 모호한 경우 범용 폴백 옵션 사용**:
     - 옵션 1: `"메인 화면"`, 옵션 2: `"메인 화면, 서브 화면"`, 옵션 3: `"메인 화면, 서브 화면, 설정 화면"`

     **선택값 처리**:
     - 옵션 선택: 쉼표 구분 파싱 → `screen_list` 배열 생성 (기존과 동일)
     - Other 자유 입력: 쉼표 구분 파싱 → `screen_list` 배열 생성
     - Other 선택 후 빈 입력 확인 시: `screen_list = ["{기본 화면 설명}"]` (기존 동작 유지, 변경 없음)
     - 단일 화면 선택 또는 화면명 1개 입력: `screen_list = ["{화면명}"]`
   - 각 화면명에 대해 slug 생성: 소문자 + 하이픈 변환 (공백→하이픈, 특수문자 제거, 한글은 그대로 유지)
     - 예: "로그인" → "로그인", "Sign Up Page" → "sign-up-page"
   - `screen_list`를 이후 Step 3의 중첩 루프에서 사용

1. **스타일 세트 도출** (LLM 자율 판단):
   - 요청 텍스트/화면 설명을 분석해 2~3개 스타일 도출 (최대 3개)
   - 각 스타일: 이름(예: "Minimal & Clean") + slug(예: "minimal") + 차별화 포인트 요약
   - slug 변환 규칙: 소문자 + 하이픈 (공백→하이픈, 특수문자 제거, 영문 기준)
     - 예: "Minimal & Clean" → "minimal", "Dark & Modern" → "dark-modern", "Vibrant & Colorful" → "vibrant-colorful"
   - 스타일 예시: Minimal & Clean / Dark & Modern / Vibrant & Colorful / Corporate & Professional
   - 맥락에 맞지 않는 스타일은 제외하고 적합한 스타일로 대체

2. **배치 pending 선기록**:
   - REQ-NNN이 있을 경우: `request.json`의 `stitch_screens`에 배치 항목 기록:
     ```json
     {
       "status": "pending",
       "type": "multi_style_batch",
       "batch_id": "{uuid}",
       "styles": ["Minimal & Clean", "Dark & Modern", "Vibrant & Colorful"],
       "screen_list": ["로그인", "대시보드", "설정"],
       "baseline_screen_ids": ["{id1}", "{id2}", "..."],
       "created_at": "{TS}"
     }
     ```
   - REQ-NNN 없고 PLN-NNN이 있을 경우: `plan.json`의 `stitch_screens`에 동일 형식으로 기록
   - 둘 다 없을 경우: 선기록 생략

3. **스타일 × 화면 전체 병렬 호출** (총 N×M회, N = 스타일 수, M = 화면 수):

   - 먼저 모든 스타일 폴더를 생성:
     ```
     for each style in styles:
       mkdir {PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/styles/{style_slug}/
     ```
   - 이후 N×M개의 `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs generate ...")` 호출을 **단일 메시지에 모두 포함시켜 동시에 발송** (순차 대기 금지):
     ```
     [병렬] for each (style, screen) in styles × screen_list:
       Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs generate --project-id {stitch_project_id} --prompt \"{screen 화면 설명}\n\n[스타일 방향] {스타일명}: {스타일 차별화 포인트}\" --device-type DESKTOP --model-id {STITCH_MODEL}")
     ```
   - 모든 응답 수집 후 처리:
     - 응답 있음(screen_id 포함): screen_id 임시 보관 → output_components 코드 포함 시
       `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/styles/{style_slug}/screen-{화면순번:001,002,...}.html` 저장
       → 스타일명+화면명→html_file_path 맵 보관
     - 빈 응답/null: 해당 (스타일, 화면) 쌍을 pending 목록에 추가 → Step 4에서 일괄 폴링
     - 명시적 오류: 해당 화면 실패 기록

   > **단일 화면 최적화**: `screen_list`가 1개이고 스타일도 1개이면 병렬 호출은 1회만 실행되어 기존 동작과 동일.

4. **폴링 루프** (즉시 응답 없는 화면이 있는 경우):
   - 대기 안내 출력:
     ```
     [Stitch] 멀티 스타일 시안 생성 중... ({N}개 스타일 × {M}개 화면, 최대 10분 소요)
     ```
   - 수집 목표 수 = 기대 전체 화면 수(N×M) − 이미 수집된 screen_id 수
   - 최대 20회, 30초 간격:
     > ⚠️ **MANDATORY**: 반드시 20회를 모두 채울 때까지 루프를 종료하지 않는다. 중간에 임의로 중단하는 것은 금지다.
     poll_count = 1로 초기화, poll_count <= 20인 동안 반복:
     a. `python3 {PLUGIN_ROOT}/scripts/mst.py stitch sleep --interval 30` (Bash 호출)
     b. `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs list-screens --project-id {stitch_project_id}")` 호출
     c. `현재 screen IDs - baseline_screen_ids`의 차집합 크기 >= 수집 목표 수?
        - YES: 차집합에서 목표 수만큼 screen ID 선택 → Step 5로 진행
        - NO: `[Stitch] 대기 중... ({poll_count}/20회)` 출력 후 poll_count += 1, 반복 계속
   - 20회 모두 미감지 시:
     - "[Stitch] 일부 스타일 생성이 지연되고 있습니다 — 잠시 후 /mst:stitch --list로 확인하세요." 출력
     - pending 항목 유지 (`stale_at` = `created_at` + 15분)
     - 수집된 screen IDs만으로 진행 (0개이면 종료)

5. **각 화면 URL 확보** (`get_screen` 최대 3회 재시도):
   - 각 screen_id에 대해:
     ```
     Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {screen_id}")
     ```
   - `screenshot.downloadUrl` 추출 (없으면 null)
   - **output_components HTML 확인** (폴링 경로 전용):
     - 해당 `스타일명+화면명` 키가 html_file_path 맵에 이미 설정되어 있으면(동기 경로에서 Step 3가 저장 완료): 이 단계 skip
     - 미설정이면(폴링 경로): `get_screen` 응답의 `output_components`를 확인하여 Step 4-2의 output_components 파싱 규칙을 따른다
       - 코드 포함 시: `스타일명+화면명 → html_content` 맵에 보관 (파일 저장은 Step 5.5에서 md와 동시 수행)
       - 비어있거나 제안 텍스트인 경우: **html 대기 루프**(30초 간격 최대 20회, 총 최대 10분)로 재확인
         - ⚠️ 이 루프는 screen_id 수집용 Step 4 폴링과 별도이며, 각 screen_id별로 독립 카운터를 사용
         - 각 screen_id마다 `html_wait_count = 1`로 시작, `html_wait_count <= 20` 동안 반복:
           a. `python3 {PLUGIN_ROOT}/scripts/mst.py stitch sleep --interval 30`
           b. 동일한 `screen_id`로 `Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {screen_id}")` 재호출
           c. `output_components` 재확인:
              - 코드 포함 시: 해당 `스타일명+화면명 → html_content` 맵에 보관하고 루프 종료
              - 여전히 비어있거나 제안 텍스트면 `[Stitch] HTML 대기 중... ({html_wait_count}/20회, screen_id: {screen_id})` 출력 후 `html_wait_count += 1`
         - 20회 모두 코드 미확인 시: 해당 `스타일명+화면명` 키에 null 확정
   - 스타일명 + 화면명과 screen_id, downloadUrl을 매핑하여 보관

5.5. **screen-NNN.md 일괄 생성** (스타일 폴더 구조):
   - 수집된 각 스크린(screen_id + downloadUrl + 스타일명 + 화면명)에 대해 순차 실행:
     a. 스타일별 폴더 확인/생성: `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/styles/{style_slug}/`
     b. 스크린 번호 산출: 해당 스타일 폴더 내 기존 `screen-*.md` 및 `screen-*.html` 파일 수 + 1부터 순차 증가
     c. **Step D** 실행: `styles/{style_slug}/screen-{NNN}.md` 파일 작성 (「화면 메타데이터 저장」섹션의 Step D 포맷 준수)
        - **html 동시 저장**: 해당 `스타일명+화면명` 키의 `html_content`가 존재하고, html_file_path 맵에 해당 키가 미설정이면, md 파일과 동일 stem으로 `styles/{style_slug}/screen-{NNN}.html`을 동시 저장한다. 저장 후 html_file_path 맵에 경로 설정. 해당 키가 이미 설정되어 있으면(동기 경로에서 Step 3가 저장 완료) html 저장 skip.
     d. **Step E** 실행: `design.json`의 `screens[]`에 메타데이터 추가 (`style` 필드에 해당 `style_slug`(폴더명), `screen_title` 필드에 화면명 기입)
   - `downloadUrl`이 null인 스크린: screen-NNN.md의 이미지 라인에 "이미지 미확보" 표시, `image_url: null`로 기록

   **파일 구조 예시** (3 스타일 × 2 화면):
   ```
   designs/DES-NNN/
     design.json
     styles/
       minimal/
         screen-001.md    ← 화면 1 (로그인)
         screen-001.html
         screen-002.md    ← 화면 2 (대시보드)
         screen-002.html
       dark-modern/
         screen-001.md
         screen-001.html
         screen-002.md
         screen-002.html
       vibrant-colorful/
         screen-001.md
         screen-001.html
         screen-002.md
         screen-002.html
   ```

5.6. **design.json `styles` 배열 갱신**:
   - `design.json`에 `styles` 배열을 추가/갱신:
     ```json
     {
       "styles": [
         {
           "name": "Minimal & Clean",
           "slug": "minimal",
           "screens": ["screen-001", "screen-002"]
         },
         {
           "name": "Dark & Modern",
           "slug": "dark-modern",
           "screens": ["screen-001", "screen-002"]
         }
       ]
     }
     ```
   - 각 스타일의 `screens` 배열은 해당 `styles/{slug}/` 폴더 내 screen ID 목록
   - `design.json`의 기존 `screens[]` 배열에는 모든 스크린이 플랫하게 나열됨 (Step E에서 추가된 항목들)

6. **사용자에게 표시**:
   ```
   [Stitch] {N}개 스타일 × {M}개 화면 시안이 생성되었습니다.

   대시보드에서 확인: {DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}
   Stitch 프로젝트: https://stitch.withgoogle.com/projects/{stitch_project_id}
   ```

7. **Q1: 어떤 스타일을 탐색할까요?** (`AskUserQuestion`, `multiSelect: true`):
   - 선택지: A({스타일명1}) / B({스타일명2}) / C({스타일명3}) / 다시 생성 (다른 스타일로)
   - 스타일은 최대 3개 도출되므로 A/B/C + "다시 생성" = 최대 4개 선택지 (AskUserQuestion 4개 제한 준수)
   - **복수 선택 가능** — 선택한 스타일 모두에 대해 variants를 생성함
   - "다시 생성" 단독 선택 시: Step 1로 돌아가 새 스타일 세트 도출 (accumulated_screens 유지)
   - 스타일 1개 이상 선택 시: Step 8로 진행

8. **Q2: 선택한 시안들에 variants를 몇 개씩 만들까요?** (`AskUserQuestion`):
   - 선택지: 0개 / 1개 / 2개 / 3개 (선택된 모든 스타일에 동일 적용)
   - **빠른 완료 조건**: Q1에서 정확히 1개 선택 + Q2에서 0개
     → Step 11(메타데이터 갱신) 직행, 그 1개가 최종 선택 (Q_final 스킵)
   - 그 외: Step 9로 진행

9. **선택된 스타일별 variants 생성** (Q2 > 0인 경우):
   - Q1에서 선택된 각 스타일에 대해:
     ```
     Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs variants --project-id {stitch_project_id} --screen-ids {스타일의_모든_screen_id_csv} --prompt \"선택된 스타일을 유지하면서 레이아웃과 색상을 다양하게 변형\" --variant-count {Q2 선택값} --creative-range EXPLORE --model-id {STITCH_MODEL}")
     ```
   - 생성된 variant screen_id들을 accumulated_screens에 추가

10. **전체 시안 표시 및 탐색 계속 여부** (`AskUserQuestion`):
    - 지금까지 accumulated_screens에 쌓인 모든 시안을 스타일별·화면별로 표시:
      ```
      [Stitch] 현재까지 생성된 시안 ({N}개 스타일 × {M}개 화면):

      ## A. {스타일명1}
      - {화면명1}: ![{스타일명1}-{화면명1}]({downloadUrl})
      - {화면명2}: ![{스타일명1}-{화면명2}]({downloadUrl})
        └ variant 1: ![v1]({v1_url})
        └ variant 2: ![v2]({v2_url})

      ## B. {스타일명2}
      - {화면명1}: ![{스타일명2}-{화면명1}]({downloadUrl})
      - {화면명2}: ![{스타일명2}-{화면명2}]({downloadUrl})
      ...
      ```
    - 선택지:
      - "더 탐색하기" → Step 7(Q1)으로 돌아가기 (accumulated_screens 유지)
      - "이대로 완료" → Step 10.5(Q_final)로 진행

10.5. **Q_final: 최종 시안을 선택해주세요** (`AskUserQuestion`, `multiSelect: false`):
    - accumulated_screens 전체 시안을 스타일 단위로 선택지 제시 (스타일명 — 해당 스타일의 모든 화면이 포함됨)
    - **variant 포함 스타일의 최종 기록 화면 규칙**:
      - variant가 없는 스타일: 기존대로 스타일명을 단일 선택지로 표시
      - variant가 있는 스타일: 스타일 선택 후 별도 `AskUserQuestion`을 통해 원본 또는 각 variant 중 하나를 선택하도록 안내
        - 예: "A. 원본" / "B. variant 1" / "C. variant 2"
        - variant 수는 Q2 선택지(최대 3개)와 연동 → 원본 1 + variant 최대 3 = 최대 4개 (AskUserQuestion 4개 제한 준수)
      - 최종 선택된 단일 화면의 `stitch_screen_id`를 Step 11에서 기록한다
      - **`screen_title` 기록 규칙**: variant 선택 시 `screen_title`은 `"{원본 화면명} (variant {N})"` 형식으로 기록 (예: "로그인 화면 (variant 1)"); 원본 선택 시 원본 화면명 그대로 기록
    - 사용자가 1개 스타일(및 variant 포함 시 1개 화면) 선택 → Step 11로 진행

11. **메타데이터 갱신**:
    - 최종 선택된 스타일의 배치 pending 항목을 아래 형식으로 갱신 (active):
    - `stitch_screen_id`에는 Q_final에서 실제 선택된 화면의 ID를 기록한다 (variant 선택 시 해당 variant의 screen_id, 원본 선택 시 원본 screen_id).
      ```json
      {
        "stitch_screen_id": "{실제 선택된 화면의 screen_id}",
        "url": "https://stitch.withgoogle.com/projects/{stitch_project_id}",
        "image_url": "{downloadUrl 또는 null}",
        "style": "{선택된 스타일명}",
        "screen_title": "{화면명}",
        "status": "active"
      }
      ```
    - 선택되지 않은 스타일의 screen_id들은 `archived` 상태로 각각 기록:
      ```json
      {
        "stitch_screen_id": "{screen_id}",
        "style": "{스타일명}",
        "screen_title": "{화면명}",
        "status": "archived"
      }
      ```
    - variants 생성 시: 각 variant를 `status: "variant"` 항목으로 추가 기록
    - design.md 갱신: 선택된 스타일 + variants 항목 기록 (기존 `## PLN 컨텍스트 감지 및 design.md 저장` 프로토콜 준수)

### 하위호환 규칙 (플랫 구조 판별)

기존에 생성된 DES 데이터는 `styles/` 폴더 없이 플랫 구조를 사용한다. 읽기/표시 시 다음 규칙으로 자동 판별:

1. **`styles/` 디렉토리 존재 여부 확인**:
   - `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/styles/` 디렉토리가 **존재하면**: 스타일 폴더 구조 (멀티 스타일 × 멀티 화면)
   - `styles/` 디렉토리가 **존재하지 않으면**: 기존 플랫 구조 (DES-NNN/ 직하에 screen-NNN.md/html)

2. **플랫 구조 (기존)**:
   ```
   designs/DES-NNN/
     design.json
     screen-001.md
     screen-001.html
     screen-002.md
     screen-002.html
   ```
   - `design.json`에 `styles` 배열 없음
   - `screens[]`의 각 항목에 `style` 필드가 null 또는 미존재

3. **스타일 폴더 구조 (신규)**:
   ```
   designs/DES-NNN/
     design.json          ← styles[] 배열 포함
     styles/
       {style_slug}/
         screen-NNN.md
         screen-NNN.html
   ```
   - `design.json`에 `styles` 배열 존재
   - `screens[]`의 각 항목에 `style` 필드 기입

4. **마이그레이션 없음**: 기존 플랫 구조 DES 데이터를 스타일 폴더 구조로 변환하지 않는다. 기존 데이터는 그대로 유지.

## 메타데이터 기록

REQ-NNN이 있는 경우 `request.json`의 `stitch_screens` 배열의 pending 항목을 다음으로 갱신 (없으면 신규 추가):

> **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "screen_id": "uuid-{random}",
  "stitch_screen_id": "{Stitch screen_id}",
  "req_id": "REQ-NNN",
  "title": "REQ-NNN {화면명}",
  "route": "{경로 또는 null}",
  "hash": "{요청 텍스트 hash}",
  "url": "{Stitch 화면 URL}",
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "status": "active"
}
```

## REQ 문서 자동 첨부

REQ-NNN의 spec.md 하단에 Stitch 섹션 추가:
```markdown
## Stitch 디자인
- {화면명}: {Stitch URL}
```

## 화면 메타데이터 저장 (screen-NNN.md)
DES 채번 및 프로젝트 생성은 화면 생성 이전 단계에서 수행되며,
이 섹션에서는 `screen-NNN.md` 저장과 metadata 동기화만 수행한다.

### Step D: screen-NNN.md 파일 작성 (스크린별)

스크린 번호는 001부터 순차 증가. 각 화면마다 파일 1개.

**html 동시 저장**: `html_content`가 존재하고 `html_file_path`가 미설정이면, md 파일과 동일 stem으로 `screen-{NNN}.html`을 동시 저장한다.
- 저장 경로: md 파일과 동일 디렉토리에 `screen-{NNN}.html` (예: `screen-001.md` → `screen-001.html`)
- 저장 후 `html_file_path`를 해당 경로로 설정
- `html_file_path`가 이미 설정되어 있으면(동기 경로에서 Step 4-2가 저장 완료): html 저장 skip

```markdown
## {화면 제목}

[Stitch에서 보기 ↗]({stitch_web_url})

![{화면 제목} 미리보기]({image_url})

> ⚠️ 이미지 URL은 수 시간 후 만료됩니다. 만료 시 `/mst:stitch`로 재생성하세요.

**구현 코드**: `{html_file_path 또는 "N/A"}`

{화면 설명 (있으면)}
```

### Step E: design.json의 screens[] 갱신

screen-NNN.md 저장 후 design.json의 `screens` 배열에 메타데이터 추가:

```json
{
  "id": "screen-NNN",
  "parent_screen_id": "{부모 screen-NNN 또는 null}",
  "stitch_screen_id": "{Stitch screen_id}",
  "title": "{화면 제목}",
  "url": "{stitch_web_url}",
  "image_url": "{image_url 또는 null}",
  "html_file": "{html_file_path 또는 null}",
  "style": "{style_slug 또는 null}",
  "created_at": "{ISO timestamp}",
  "status": "active"
}
```

### Step F: PLN 링크 (PLN 존재 시에만)

활성 PLN이 있으면 `plan.json`에 `linked_designs` 배열 추가/갱신:

```json
{
  "linked_designs": ["DES-NNN"]
}
```
(기존 `stitch_screens[]` 배열은 유지 — 하위 호환)

### Step G: REQ 링크 (REQ 존재 시에만)

활성 REQ가 있으면 `request.json`에 `linked_designs` 추가/갱신:

```json
{
  "linked_designs": ["DES-NNN"]
}
```

### 이전 design.md 생성 중단

`{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/design.md` 파일은 더 이상 생성하지 않는다.
기존 파일이 있으면 유지 (삭제하지 않음 — 하위 호환).

## 사용자 보고

생성 완료 후:
```
[Stitch] {N}개 화면이 생성되었습니다.
📋 생성된 화면: "{화면명1}", "{화면명2}", ...  ← 생성된 screen_title 목록 (단일 화면 시 생략 가능)
🔗 DES-NNN 시안 보기: https://stitch.withgoogle.com/projects/{stitch_project_id}
🌐 대시보드에서 확인: {DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}
📄 이미지 미리보기: design.md 참고
```

variants 생성 시:
```
[Stitch] 3가지 디자인 방향이 생성되었습니다.
🔗 원본: {URL}
🔗 변형 1: {URL}
🔗 변형 2: {URL}
🔗 변형 3: {URL}
```

## 오류 처리

| 오류 | 처리 |
|------|------|
| list_projects 타임아웃 (30초) | "[Stitch] 연결 불가 — 건너뜀. /mst:stitch로 수동 실행 가능." 출력 후 종료 |
| generate_screen 빈 응답 | 비동기 수락으로 처리 — 재시도 금지. 폴링 루프(30초×20회) 진입. 20회 미감지 시 pending 유지(stale_at = created_at + 15분) + 사용자 안내 후 종료. |
| get_screen 실패 | 5초 간격으로 최대 3회 재시도. 모두 실패 시 screen_id를 pending 항목에 기록하고 URL 미확보 안내 출력 |
| 화면 생성 실패 | "[Stitch] 화면 생성 실패 — {오류}. 텍스트 명세로 진행합니다." |
| enabled=false | "[Stitch] 비활성화됨 (config.stitch.enabled=false)" |

## Edit 프로토콜

`--edit SCREEN_ID "편집 프롬프트"`로 기존 화면을 단일 결과로 수정한다.

> **DES 채번 스킵**: Edit는 DES 채번/프로젝트 생성을 건너뛰고, `SCREEN_ID`가 속한 DES의 `design.json`에서 `stitch_project_id`를 읽어 사용한다.
> **project_id 해석**: Edit는 `config.stitch.project_id`를 사용하지 않는다. `SCREEN_ID`가 속한 DES의 `design.json`에서 `stitch_project_id`를 읽어 사용한다.
> **화면 ID 해석**: 입력 `SCREEN_ID`는 로컬 ID(`screen-001`) 기준이며, `design.json`의 `screens[]`에서 매칭 후 `stitch_screen_id`를 실제 SDK 호출 ID로 사용한다.

1. **대상 DES + 화면 식별**:
   - 활성 DES(`design.json`) 중 `screens[].id == {SCREEN_ID}` 항목을 찾는다.
   - 미발견 시: "[Stitch] 화면을 찾을 수 없습니다 — screen_id: {SCREEN_ID}" 출력 후 종료
   - `stitch_project_id`가 없으면: "[Stitch] DES stitch_project_id가 없습니다 — Edit 실행 불가" 출력 후 종료
   - 매칭 화면의 `stitch_screen_id`를 `{SOURCE_STITCH_SCREEN_ID}`로 보관

2. **대상 화면 유효성 확인**:
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {SOURCE_STITCH_SCREEN_ID}")
   ```
   - 실패 시: "[Stitch] 원본 화면 조회 실패 — stitch_screen_id: {SOURCE_STITCH_SCREEN_ID}" 출력 후 종료

3. **edit 실행** (`screen.edit(prompt)` 단일 결과):
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs edit --project-id {stitch_project_id} --screen-id {SOURCE_STITCH_SCREEN_ID} --prompt \"{EDIT_PROMPT}\" --model-id {STITCH_MODEL}")
   ```
   - 응답의 결과 screen에서 새 `stitch_screen_id`를 추출

4. **결과 저장**:
   - `get_screen`으로 새 화면 URL/이미지/`output_components`를 확보한다 (기존 Step 4-2, Step 5 규칙 재사용).
   - `screen-NNN.md`/`screen-NNN.html`을 생성한다 (기존 Step D 규칙 재사용).
   - `design.json` `screens[]`에 새 항목 추가:
     ```json
     {
       "id": "screen-NNN",
       "parent_screen_id": "{SCREEN_ID}",
       "stitch_screen_id": "{새 stitch_screen_id}",
       "title": "{화면 제목}",
       "url": "{stitch_web_url}",
       "image_url": "{image_url 또는 null}",
       "html_file": "{html_file_path 또는 null}",
       "style": "{style_slug 또는 null}",
       "created_at": "{ISO timestamp}",
       "status": "active"
     }
     ```

5. **결과 안내** (대시보드 URL만 사용):
   ```
   [Stitch] Edit 완료.
   🌐 대시보드에서 확인: {DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}
   ```
   > ⚠️ curl/로컬서버/브라우저 자동화로 시안을 직접 보여주는 행위는 금지입니다.

6. **반복 정제 루프 진입**:
   - 현재 화면 컨텍스트를 방금 생성된 `screen-NNN`으로 갱신하고 `## Edit/Alt 반복 정제 루프`를 시작한다.

## Alt 프로토콜

`--alt SCREEN_ID "대안 프롬프트"`로 기존 화면의 대안을 생성한다.

> **기본 모드**: EXPLORE + variant 2개
> **재설계 모드**: `--alt SCREEN_ID --reimagine`이면 Redesign 프로토콜로 위임
> **DES 채번 스킵**: Alt는 DES 채번/프로젝트 생성을 건너뛰고, `SCREEN_ID`가 속한 DES의 `design.json`에서 `stitch_project_id`를 읽어 사용한다.
> **project_id 해석**: 기본 Alt는 Edit와 동일하게 대상 DES의 `stitch_project_id`를 사용한다.

1. **reimagine 분기**:
   - `--reimagine`이 있으면 즉시 `## Redesign 프로토콜`을 실행한다 (`--redesign`과 동일).

2. **대상 DES + 화면 식별**:
   - 활성 DES(`design.json`) 중 `screens[].id == {SCREEN_ID}` 항목을 찾는다.
   - 미발견 시: "[Stitch] 화면을 찾을 수 없습니다 — screen_id: {SCREEN_ID}" 출력 후 종료
   - `stitch_project_id`가 없으면: "[Stitch] DES stitch_project_id가 없습니다 — Alt 실행 불가" 출력 후 종료
   - 매칭 화면의 `stitch_screen_id`를 `{SOURCE_STITCH_SCREEN_ID}`로 보관

2.5. **대상 화면 유효성 확인**:
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {stitch_project_id} --screen-id {SOURCE_STITCH_SCREEN_ID}")
   ```
   - 실패 시: "[Stitch] 원본 화면 조회 실패 — stitch_screen_id: {SOURCE_STITCH_SCREEN_ID}" 출력 후 종료

3. **variants 생성** (EXPLORE, 2개):
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs variants --project-id {stitch_project_id} --screen-id {SOURCE_STITCH_SCREEN_ID} --prompt \"{ALT_PROMPT}\" --variant-count 2 --creative-range EXPLORE --model-id {STITCH_MODEL}")
   ```

4. **2개 대안 제시 + 선택** (`AskUserQuestion`):
   - 선택지: A(variant 1) / B(variant 2)
   - 사용자가 선택한 variant를 `{SELECTED_VARIANT_STITCH_SCREEN_ID}`로 확정

5. **선택 결과 저장**:
   - 선택된 variant만 `screen-NNN.md`/`screen-NNN.html` + `design.json screens[]`에 저장한다.
   - 저장 항목의 `parent_screen_id`는 `{SCREEN_ID}`로 기록한다.

6. **결과 안내** (대시보드 URL만 사용):
   ```
   [Stitch] Alt 완료.
   🌐 대시보드에서 확인: {DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}
   ```
   > ⚠️ curl/로컬서버/브라우저 자동화로 시안을 직접 보여주는 행위는 금지입니다.

7. **반복 정제 루프 진입**:
   - 현재 화면 컨텍스트를 선택된 `screen-NNN`으로 갱신하고 `## Edit/Alt 반복 정제 루프`를 시작한다.

## Edit/Alt 반복 정제 루프

Edit/Alt로 결과가 생성된 직후 아래 루프를 실행한다.

1. **루프 상태 초기화**:
   - `refine_count = 0`
   - `minor_edit_streak = 0`
   - `current_screen_id = {직전 결과 screen-NNN}`

2. **반복 질문** (`AskUserQuestion`):
   - 선택지: `추가 수정(Edit)` / `대안 보기(Alt)` / `확정(Accept)`

3. **분기 처리**:
   - `추가 수정(Edit)`:
     - 편집 프롬프트를 다시 입력받아 현재 화면 기준 Edit 프로토콜 Step 3~5를 재실행한다.
     - `refine_count += 1`
     - `minor_edit_streak += 1`
   - `대안 보기(Alt)`:
     - 대안 프롬프트를 다시 입력받아 현재 화면 기준 Alt 프로토콜 Step 3~6을 재실행한다.
     - `refine_count += 1`
     - `minor_edit_streak = 0`
   - `확정(Accept)`:
     - 루프 종료, 현재 화면을 최종안으로 확정한다.

4. **넛지 규칙 (3회)**:
   - `minor_edit_streak >= 3`이면 아래 메시지를 출력하고 streak를 0으로 리셋:
   ```
   [Stitch] 같은 방향의 미세 수정이 3회 연속 수행되었습니다. "대안 보기(Alt)"로 탐색 폭을 넓히는 것을 권장합니다.
   ```

5. **하드캡 (20회)**:
   - `refine_count >= 20` 상태에서 사용자가 Edit/Alt를 다시 선택하면 강제 확인 질문을 띄운다.
   - 강제 확인 선택지: `확정(Accept)` / `중단(Abort)`
   - 이 단계에서는 추가 Edit/Alt 실행을 허용하지 않는다.

## Redesign 프로토콜

`--alt SCREEN_ID --reimagine` 또는 `--redesign SCREEN_ID`로 기존 화면을 근본적으로 재설계한다.

> **alias 규칙**: `--redesign SCREEN_ID`는 내부적으로 `--alt SCREEN_ID --reimagine`과 동일하게 처리한다.
> **project_id 해석**: Redesign은 DES 채번/프로젝트 생성을 건너뛰고 `config.stitch.project_id`를 직접 사용한다. 미설정 시 에러 종료.
> **대시보드 URL 해석**: 결과 표시 전에 "Step C-2: 대시보드 URL 구성"과 동일한 절차로 `{DASHBOARD_BASE_URL}`을 먼저 구성한다. 단, Redesign은 DES 채번을 건너뛰므로 `{DES-NNN}`이 없다. 활성 REQ/PLN에 `linked_designs`가 존재하면 해당 DES-NNN을 사용하고, 없으면 대시보드 링크를 생략한다.

1. **대상 화면 유효성 확인**:
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs get-screen --project-id {config.stitch.project_id} --screen-id {SCREEN_ID} --name \"projects/{config.stitch.project_id}/screens/{SCREEN_ID}\"")
   ```
   - 성공 시: 응답에서 `{원본_TITLE}` 및 프로젝트 URL `https://stitch.withgoogle.com/projects/{config.stitch.project_id}`을 `{원본_URL}`로 보관
   - 실패 시: "[Stitch] 화면을 찾을 수 없습니다 — screen_id: {SCREEN_ID}" 출력 후 종료

2. **사용자 확인** (`AskUserQuestion`):
   - **Q1: variants 수를 선택해주세요** (기본 3):
     - 선택지: 1개 / 2개 / 3개 / 4개 / 5개
   - **Q2: 변경할 aspects를 선택해주세요** (`multiSelect: true`, 기본 전체):
     - 선택지: LAYOUT / COLOR_SCHEME / IMAGES / TEXT_FONT / TEXT_CONTENT / 전체 (기본)
     - "전체" 선택 시: 모든 aspects 적용

3. **variants 생성**:
   ```
   Bash(command: "node {PLUGIN_ROOT}/scripts/stitch-sdk.mjs variants --project-id {config.stitch.project_id} --screen-id {SCREEN_ID} --prompt \"기존 화면을 근본적으로 재설계\" --variant-count {Q1 선택 수} --creative-range REIMAGINE --aspects {Q2 선택 aspects csv} --model-id {STITCH_MODEL}")
   ```

4. **결과 표시**:
   - `generate_variants` 응답의 각 variant screen에서 `stitch_screen_id`를 수집
   - 프로젝트 URL: `https://stitch.withgoogle.com/projects/{config.stitch.project_id}`
   ```
   [Stitch] {N}가지 Redesign 방향이 생성되었습니다.
   🔗 원본: {원본_URL} ({원본_TITLE})
   🔗 프로젝트: {프로젝트 URL}
   🌐 대시보드에서 확인: {DASHBOARD_BASE_URL}/designs/{DES-NNN}?project={projectId}  ← linked_designs에서 DES-NNN 확보 시에만 표시
   ```
   > ⚠️ curl/로컬서버/브라우저 자동화로 시안을 직접 보여주는 행위는 금지입니다.

5. **메타데이터 기록** (기존 메타데이터 패턴 재사용):
   - REQ-NNN이 있을 경우 `request.json`의 `stitch_screens` 배열에 각 variant를 기록:
     ```json
     {
       "stitch_screen_id": "{variant_screen_id}",
       "source_screen_id": "{SCREEN_ID}",
       "url": "https://stitch.withgoogle.com/projects/{config.stitch.project_id}",
       "type": "redesign",
       "creative_range": "REIMAGINE",
       "created_at": "{ISO8601}",
       "status": "active"
     }
     ```
   - design.json의 `screens[]`에도 각 variant 메타데이터 추가 (`parent_screen_id`는 `{SCREEN_ID}`로 기록)
   - Redesign 결과 확정 후 `## Edit/Alt 반복 정제 루프`를 동일하게 적용한다.

## 옵션

- `--auto`: 사용자 확인 없이 자동 실행
- `--variants`: 화면 생성 후 3가지 변형 추가 생성
- `--init`: 기존 Stitch 프로젝트의 디자인 테마/화면 정보를 수집해 DESIGN.md 초안 생성 (SDK `init` 명령 사용)
- `--req REQ-NNN`: 특정 REQ에 연결 (메타데이터 기록)
- `--edit SCREEN_ID`: 기존 화면 수정
- `--alt SCREEN_ID`: 대안 2개 생성 (기본 EXPLORE). 결과 선택 후 반복 정제 루프 진입
- `--reimagine`: `--alt`와 함께 사용할 때 Redesign 모드(REIMAGINE) 활성화
- `--list`: 현재 Stitch 프로젝트의 화면 목록 조회
- `--multi`: 멀티 스타일 시안 생성 모드. 2~3개 스타일(최대 3개)을 자동 도출하여 각 스타일별로 화면을 생성하고, 사용자가 선택 후 variants 추가 가능. `--screens`와 함께 사용하면 스타일당 복수 화면 생성.
- `--screens "화면1,화면2,..."`: `--multi`와 함께 사용. 각 스타일별로 생성할 화면 목록을 쉼표 구분으로 지정. 미지정 시 사용자에게 입력 요청.
- `--model pro|flash`: 생성에 사용할 모델 지정. `pro` = GEMINI_3_PRO, `flash` = GEMINI_3_FLASH. 미지정 시 `config.stitch.model_id` 사용.
- `--redesign SCREEN_ID`: `--alt SCREEN_ID --reimagine` alias. 하위호환을 위해 유지.
