# Code Review Request — Self-Exploration Mode

- Request: {{REQ_ID}} / Task: {{TASK_ID}}
- Worktree: {{WORKTREE_PATH}}
- Base branch: {{BASE_BRANCH}}
- Spec: {{SPEC_PATH}}
- Plan: {{PLAN_PATH}}

## 변경 의도 (PM 작성 — 1~3줄 자유 형식)

{{INTENT}}

## 리뷰 관점

{{PERSPECTIVE}}

## impact_reviewer 전용 PERSPECTIVE (삽입용)

아래 블록은 `impact_reviewer` dispatch 시 `{{PERSPECTIVE}}`에 포함하여 사용한다.

```markdown
- 분석 모드 분기: `review.roles.impact_reviewer.enhanced_analysis` (기본값 `true`)
  - `true`: `git diff --name-only` 기준 변경 파일 식별 → 각 파일의 정적 `import`/`require`를 2단계 역추적(변경 파일 → 직접 의존자 → 간접 의존자) → 역추적된 의존 파일 소스를 Read 도구로 직접 읽고 변경 내용과 대조하여 기능 깨짐 여부 판단
  - `false`: 기존 1단계 역추적만 수행(변경 파일 → 직접 의존자), 기존 `[IMPACT]` 태그 체계 유지
- 제외 범위: 동적 import/런타임 의존성 추적 제외
- "기능 유지"는 코드를 안 건드리는 것이 아니라 기능이 정상 동작하는 상태를 의미한다. 필요하면 함께 수정이 필요한 파일을 식별하라.
- 영향 없으면 `영향 범위 분석 완료 — 해당 없음`으로 명시
- 영향 이슈는 기존 등급 판별 가이드와 함께 아래 Impact 전용 rubric을 적용해 `[CRITICAL]`, `[MAJOR]`, `[MINOR]` 태깅:
  - 공개 API/라우트에 영향: [CRITICAL]
  - 공유 컴포넌트/유틸리티에 영향: [MAJOR]
  - 내부 모듈에만 영향: [MINOR]
- `review-impact.md`에는 아래 항목을 반드시 포함:
  - 확인한 파일 목록
  - 판단 근거 (무엇을 읽고 어떤 비교로 판단했는지)
  - 함께 수정 필요 파일 (각 파일별 수정 방향)
```

## 자기탐색 지시

아래 순서로 변경사항을 직접 탐색하라. PM이 제공한 diff나 요약에 의존하지 말고 직접 확인하라.

0. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구) — 변경 의도·범위·수락 조건 파악
0.1. plan 직접 읽기 (source_plan이 있는 경우만): `{{PLAN_PATH}}`가 `"N/A"`가 아니면 `cat {{PLAN_PATH}}` (또는 Read 도구), `"N/A"`면 source_plan 없음으로 보고 이 단계를 skip
1. `git -C {{WORKTREE_PATH}} diff --name-only {{BASE_BRANCH}}...HEAD` — 변경된 파일 목록 파악
2. `git -C {{WORKTREE_PATH}} diff {{BASE_BRANCH}}...HEAD` — 전체 변경 내용 확인
3. 변경된 파일만 탐색할 것. 변경되지 않은 파일은 검토 범위 밖이다
4. 필요 시 관련 파일을 직접 읽어 문맥 파악
5. 빌드 확인 (프로젝트에 빌드 시스템이 있는 경우): `package.json`, `Makefile`, `pyproject.toml`, `deno.json` 등 빌드 설정이 존재하고 변경 파일이 컴파일/번들 대상이라면 빌드를 직접 실행하여 성공 여부를 확인한다. 빌드 실패 시 [CRITICAL] 이슈로 보고한다.

## 수락 조건 (검토 기준)

{{ACCEPTANCE_CRITERIA}}

## 포커스 힌트

{{FOCUS_HINTS}}

## 등급 판별 가이드

각 이슈에 아래 체크리스트를 적용하여 등급을 결정한다. 해당 등급의 질문 중 **2개 이상 YES**이면 그 등급으로 태깅한다. 상위 등급부터 순서대로 평가하여 처음 매칭되는 등급을 적용한다.

### [CRITICAL] 판별 (2개 이상 YES → CRITICAL)

1. 이 이슈가 런타임 오류, 데이터 손실, 또는 서비스 중단을 유발할 수 있는가?
2. 이 이슈가 spec §3 수락 조건(AC)을 직접적으로 위반하는가?
3. 이 이슈를 수정하지 않으면 후속 기능 개발이 불가능하거나 전체 워크플로우가 차단되는가?
4. 빌드/컴파일이 실패하는가?

### [MAJOR] 판별 (2개 이상 YES → MAJOR)

1. 이 이슈가 엣지케이스 미처리, 예외 처리 누락 등 특정 조건에서 오작동을 유발하는가?
2. 이 이슈가 설계 의도와 구현 방향의 불일치를 나타내는가?
3. 이 이슈를 방치하면 유지보수 비용이 현저히 증가하거나 기술 부채가 누적되는가?
4. plan.md 및 spec.md의 범위를 벗어난 불필요한 파일 수정 또는 관련 없는 로직 변경이 있는가?
5. plan.md에 명시된 상위 목표·방향과 실제 구현이 충돌하는가?

### [MINOR] 판별 (위 등급에 해당하지 않는 경우)

1. 이 이슈가 코드 스타일, 네이밍, 포맷팅 등 가독성 관련인가?
2. 이 이슈가 기능 동작에 영향을 주지 않는 개선 제안인가?
3. 이 이슈가 문서화 누락, 주석 부족 등 비기능적 사항인가?

> 어느 등급에도 2개 이상 YES가 아니면 [MINOR]로 태깅한다.

## 안티패턴 갤러리 (Severity 캘리브레이션)

아래 예시는 모두 **관찰 가능한 기준**으로만 작성되며, 해당 조건이 재현되면 지정된 severity를 기본값으로 사용한다.

### MAJOR 경계 예시

- MAJOR 경계 예시 1 — 에러 핸들링 누락
  - 관찰 기준: `public` API 함수(라우트 핸들러/SDK export 함수)에서 `throw` 가능한 호출을 `try/catch`로 감싸지 않아, 실패 시 원본 예외 메시지/스택이 그대로 호출자 응답 또는 상위 레이어 로그로 전파된다.
  - 판정: `[MAJOR]` (특정 실패 조건에서 오작동/예외 전파 발생)
- MAJOR 경계 예시 2 — 경쟁 조건
  - 관찰 기준: 동시 요청(2개 이상)을 재현했을 때 공유 변수(메모리 캐시/카운터/상태 플래그) 갱신 순서가 보장되지 않아 최종 상태가 요청 순서와 다르게 기록된다.
  - 판정: `[MAJOR]` (엣지 케이스 동시성 조건에서 상태 불일치 발생)
- MAJOR 경계 예시 3 — 접근성 미비
  - 관찰 기준: 인터랙티브 요소가 `Tab` 키로 포커스되지 않거나, 스크린리더가 필요로 하는 `role`/`aria-*` 속성이 누락되어 키보드/보조기기 사용자 경로가 차단된다.
  - 판정: `[MAJOR]` (설계 의도와 구현 불일치, 사용자 경로 기능 저하)

### MINOR 경계 예시

- MINOR 경계 예시 1 — 변수명 불일치
  - 관찰 기준: 동일 모듈에서 `camelCase`와 `snake_case`가 혼용되지만 테스트/실행 결과가 동일하고 런타임 동작 차이가 없다.
  - 판정: `[MINOR]` (가독성/일관성 이슈)
- MINOR 경계 예시 2 — 불필요한 `console.log`
  - 관찰 기준: 디버그 로그가 남아 있으나 상태 변경, 예외 처리, 반환값, 네트워크 호출에는 영향이 없다.
  - 판정: `[MINOR]` (출력 노이즈만 증가)
- MINOR 경계 예시 3 — import 정렬
  - 관찰 기준: import 문이 알파벳/컨벤션 순서와 다르지만 빌드/테스트/런타임 결과가 동일하다.
  - 판정: `[MINOR]` (스타일 정합성 이슈)

## 보안 오버라이드

아래 보안 키워드와 관련된 이슈는 **체크리스트 점수와 무관하게** 반드시 `[CRITICAL]`로 태깅한다:

- 인증(authentication), 인가(authorization), 권한 우회
- 인젝션(injection), SQL injection, 코드 인젝션
- XSS(Cross-Site Scripting), CSRF(Cross-Site Request Forgery)
- 시크릿(secret) 노출, API 키 하드코딩, 자격 증명 유출
- 경로 탐색(path traversal), 디렉토리 트래버설

## 출력 형식

- **결과**: PASS / FAIL / PARTIAL
- **이슈 목록**: 각 이슈에 반드시 `[CRITICAL]`, `[MAJOR]`, `[MINOR]` 등급을 태깅한다.
  - 형식: `파일:라인 | [CRITICAL] | 설명`
  - 형식: `파일:라인 | [MAJOR] | 설명`
  - 형식: `파일:라인 | [MINOR] | 설명`
- **개선 제안**: 필수 수정 사항 외 선택적 개선 (있는 경우만)
