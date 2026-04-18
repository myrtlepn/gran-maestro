---
name: picks
description: "captures/ 큐에서 자연어로 항목을 선택하고, 변경 요청 시 /mst:plan --from-picks로 자동 전환합니다."
user-invocable: true
argument-hint: "[--list] [--all] [{자연어 선택/변경 요청}]"
---

# maestro:picks

사용자가 캡처 큐에서 항목을 자연어로 선택하고, 변경 요청 감지 시 `/mst:plan --from-picks`로 자동 전환합니다.

## 실행 제약 (CRITICAL -- 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` (status 업데이트용)

**그 외 모든 경로에 대한 Write/Edit 사용은 절대 금지입니다.**


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

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```

### Step 1: 캡처 목록 로드

1. `{PROJECT_ROOT}/.gran-maestro/captures/` 디렉토리 존재 확인
   - **미존재 시**: "캡처가 없습니다. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료
2. `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` 일괄 Read
3. 기본 필터: status가 `archived`, `done`, 또는 `consumed`인 항목 제외 (pending/selected 표시)
   - `--all` 옵션 시: archived/done/consumed 포함 전체 표시
4. `created_at` 기준 최신순 정렬, 기본 50개 제한
   - `--all` 사용 시 50개 제한 해제
5. **캡처가 0개일 때**: "표시할 캡처가 없습니다. `--all`로 consumed/done 포함 전체 확인 가능. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료

### Step 2: 목록 표시

#### 2-0: 대시보드 링크 정보 취득

목록 표시 전에 대시보드 URL 구성에 필요한 정보를 취득합니다:

1. **포트 취득**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get server.port)`로 `server.port` 값을 취득합니다. 키 미설정 또는 조회 실패 시 기본값 `3847`을 사용합니다.
2. **프로젝트 ID 취득**: 대시보드 API를 호출하여 현재 프로젝트의 ID를 취득합니다:
   ```bash
   curl -s "http://127.0.0.1:<port>/api/projects"
   ```
   응답 JSON 배열에서 `path`가 `{PROJECT_ROOT}/.gran-maestro`와 일치하는 항목의 `id`를 사용합니다.
   - API 호출 실패 또는 매칭 프로젝트 없음: 프로젝트 ID 없이 진행 (링크에서 `?project=` 파라미터 생략)

#### 2-1: 테이블 출력

캡처 목록을 요약 테이블로 표시합니다:

| ID | URL | Selector | Memo | Tags | Status | Age |
|----|-----|----------|------|------|--------|-----|

- **Age**: 상대 시간으로 표시 (예: "3일 전", "2h")
- **Status**: pending / selected / consumed / archived / done
- `ttl_warned_at`이 non-null인 항목: Status 옆에 `[⚠ 24h]` 표시 (TTL 경고)
- URL은 발췌 표시 (도메인 + 경로 앞부분)

#### 2-2: 대시보드 링크 표시

테이블 하단에 각 캡처의 대시보드 직접 링크를 표시합니다:

```
📎 Dashboard links:
  CAP-001 → http://localhost:<port>/picks/CAP-001?project=<project-id>
  CAP-002 → http://localhost:<port>/picks/CAP-002?project=<project-id>
  ...
```

- URL 형식: `http://localhost:<port>/picks/<CAP-ID>?project=<project-id>`
- 프로젝트 ID 취득 실패 시: `?project=<project-id>` 파라미터를 생략하여 `http://localhost:<port>/picks/<CAP-ID>` 형식으로 출력
- 대시보드 서버 미실행(2-0 API 호출 실패) 시에도 링크는 표시 (서버 시작 후 사용 가능)

**`--list` 옵션 시**: 목록만 표시 후 종료 (사용자 입력 대기 없음)

### Step 3: 사용자 입력 분석 (LLM)

사용자 입력을 LLM이 분석하여 아래 유형으로 분류합니다:

#### 3-A: 직접 ID 지정
- 예: "CAP-001, CAP-003"
- 지정된 ID에 해당하는 캡처를 선택 대상으로 확정
- 기본 필터에서 숨겨진 status(`consumed`/`done`/`archived`)도 ID 직접 지정 시 매칭 허용

#### 3-B: 자연어 필터
- 예: "헤더 관련", "버튼", "#ui 태그"
- LLM이 memo, tags, selector, url 등을 종합하여 매칭되는 캡처를 선택 대상으로 확정

#### 3-C: 변경 요청 감지
- 예: "이 버튼 색상 빨간색으로 바꿔", "수정해줘", "바꿔줘", "추가해줘"
- 변경 요청 키워드: 수정, 바꿔, 추가, 삭제, 변경, 고쳐, 업데이트, modify, change, fix, update, add, remove
- 선택 + 변경 요청이 동시에 포함된 것으로 처리 -> Step 4로 진행

#### 매칭 결과 처리

- **매칭 0건**: "일치하는 캡처가 없습니다. 다시 시도해주세요." 안내 -> 재입력 대기
- **재입력 최대 3회** 후에도 0건이면 종료
- **선택만 (변경 요청 없음)**: 선택된 캡처의 status를 `selected`로 업데이트 (capture.json Write) -> 목록 재표시 (갱신된 status 반영) -> 선택 완료 안내 + 클립보드 복사 제공 후 종료

클립보드 복사 내용:
```
/mst:plan --from-picks [CAP-003] [CAP-005] {요약}
```

### Step 4: 선택 확인 및 /mst:plan 전환

변경 요청이 감지된 경우 실행합니다.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

**실행 순서** (반드시 순차):

1. **status 업데이트 먼저**: 선택된 캡처의 status를 `selected`로 업데이트 (capture.json Write)
2. **`/mst:plan --from-picks` 호출**: 사용자 전체 입력에서 요청 텍스트를 추출하여 전달

```
Skill(skill: "mst:plan", args: "--from-picks [CAP-NNN] [CAP-NNN] {요청 텍스트}")
```

## 옵션 정리

| 옵션 | 설명 |
|------|------|
| `--list` | 캡처 목록만 표시 후 종료 (선택 대화 진입 안 함) |
| `--all` | archived/done/consumed 포함 전체 표시, 50개 제한 해제 |
| `--list --all` | 전체 캡처 목록 확인 (archived/done/consumed 포함, 제한 없음) |

## 에러 처리

- `captures/` 디렉토리 미존재: "캡처가 없습니다. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료
- `capture.json` 파싱 실패: 해당 항목 건너뛰기 + 경고 표시
- TTL 경고 대상 캡처: `ttl_warned_at` non-null 시 `[⚠ 24h]` 표시
