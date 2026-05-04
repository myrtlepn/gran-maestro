# Gran Maestro 스킬 레퍼런스

[← README](../README.md)

Gran Maestro 플러그인이 제공하는 31개 스킬의 전체 레퍼런스입니다.
각 스킬은 `/mst:{name}` 형식으로 호출합니다.

---

## 목차

- [카테고리 개요](#카테고리-개요)
- [오케스트레이션](#오케스트레이션)
  - [/mst:request](#mstrequest)
  - [/mst:plan](#mstplan)
  - [/mst:approve](#mstapprove)
  - [/mst:accept](#mstaccept)
  - [/mst:feedback](#mstfeedback)
  - [/mst:cancel](#mstcancel)
  - [/mst:recover](#mstrecover)
  - [/mst:priority](#mstpriority)
  - [/mst:review](#mstreview)
- [모니터링](#모니터링)
  - [/mst:list](#mstlist)
  - [/mst:inspect](#mstinspect)
  - [/mst:history](#msthistory)
  - [/mst:dashboard](#mstdashboard)
- [분석 도구](#분석-도구)
  - [/mst:ideation](#mstideation)
  - [/mst:discussion](#mstdiscussion)
  - [/mst:debug](#mstdebug)
  - [/mst:explore](#mstexplore)
- [CLI 직접 호출](#cli-직접-호출)
  - [/mst:codex](#mstcodex)
  - [/mst:gemini](#mstgemini)
  - [/mst:claude](#mstclaude)
- [설계 도구](#설계-도구)
  - [/mst:stitch](#mststitch)
  - [/mst:ui-designer](#mstui-designer)
  - [/mst:schema-designer](#mstschema-designer)
  - [/mst:feedback-composer](#mstfeedback-composer)
- [관리](#관리)
  - [/mst:settings](#mstsettings)
  - [/mst:on](#mston)
  - [/mst:off](#mstoff)
  - [/mst:cleanup](#mstcleanup)
  - [/mst:archive](#mstarchive)
  - [/mst:setup-omx](#mstsetup-omx)
  - [/mst:setup-extension](#mstsetup-extension)
- [자율 실행 모드 (-a / --auto)](#자율-실행-모드--a----auto)
- [한국어 자연어 트리거](#한국어-자연어-트리거)

---

## 카테고리 개요

| 카테고리 | 스킬 수 | 설명 |
|---------|---------|------|
| 오케스트레이션 | 9 | 워크플로우 시작·승인·피드백·취소·복구·리뷰 등 핵심 흐름 |
| 모니터링 | 4 | 요청/태스크 현황 조회 및 대시보드 |
| 분석 도구 | 4 | 아이디어·토론·디버그·탐색 — 모드 독립적으로 사용 가능 |
| CLI 직접 호출 | 3 | Codex/Gemini/Claude 서브에이전트 직접 디스패치 |
| 설계 도구 | 4 | UI·DB·피드백 설계 전문 에이전트 |
| 관리 | 7 | 모드 전환, 설정, 세션 정리, OMX 설치, Extension 설치 |

---

## 오케스트레이션

Gran Maestro 워크플로우(Phase 1→2→3→5)를 제어하는 핵심 스킬 그룹입니다.

---

### /mst:request

**한 줄 설명**: 새 요청을 시작하고 PM 분석 워크플로우에 진입합니다.

**인자**: `[--auto|-a] {요청 내용}`

#### 목적

사용자의 요청을 받아 PM(Claude) 분석 Phase에 진입하는 Gran Maestro 워크플로우의 진입점입니다. Maestro 모드가 비활성 상태이면 자동으로 초기화(부트스트래핑)합니다.

#### 사용 시점

- 새로운 기능 구현, 리팩터링, 버그 수정 등 코드 작업을 요청할 때
- PM이 요청을 분석하고 스펙을 작성하게 하려 할 때
- `--auto` 플래그로 스펙 작성 후 사용자 승인 없이 즉시 실행하려 할 때

#### 사용 예시

```
/mst:request 로그인 화면에 구글 소셜 로그인 버튼을 추가해줘
/mst:request --auto JWT 토큰 만료 시간을 30분으로 변경
```

#### --auto 동작

`--auto`(`-a`) 플래그를 전달하면:
- Spec Pre-review Pass를 건너뜁니다
- 스펙 작성 완료 즉시 `/mst:approve REQ-NNN --auto`를 자동 호출합니다 (사용자 확인 없음)
- `config.auto_mode.request=true`로 상시 활성화할 수 있습니다 (CLI 플래그가 우선)

---

### /mst:plan

**한 줄 설명**: 요구사항 미결 항목을 사용자와 Q&A로 정제하고 실행 가능한 plan.md를 작성합니다.

**인자**: `[-a|--auto] {플래닝 주제}`

#### 목적

구현을 시작하기 전에 요청의 핵심 미결 항목을 사용자와 대화로 정제합니다. 모호한 요구사항을 구체화하고, 범위와 제약을 합의한 뒤 `.gran-maestro/plans/PLN-NNN/plan.md`로 저장합니다. plan.md 생성 후 `/mst:request`로 이어집니다.

> **범위 제한**: plan은 REQ 단위 분리(어떤 요청을 만들지)까지만 고민합니다. 각 REQ 내부의 태스크 분해는 `/mst:request` 단계에서 코드베이스를 직접 탐색한 후 결정합니다.

#### 사용 시점

- 요청이 복잡하거나 결정해야 할 사항이 여러 개일 때
- 여러 요청을 묶어서 일괄로 `/mst:approve` 하려 할 때
- 구현 범위와 우선순위를 사전에 명확히 정리하고 싶을 때
- 버그 조사 결과(`/mst:debug`)를 바탕으로 수정 범위를 정제할 때

#### 사용 예시

```
/mst:plan 알림 시스템 전체 리팩터링
/mst:plan -a 결제 모듈 추가 — Stripe 연동 범위 논의   # 자율 모드
/mst:plan --from-debug DBG-012                        # 디버그 세션 연결
```

#### --auto 동작

`--auto`(`-a`) 플래그를 전달하면:
- `AskUserQuestion` 없이 PM이 미결 항목을 자율 결정합니다
- 확신이 낮은 항목은 `mst:discussion`을 자동 호출해 결론을 도출합니다
- 모든 결정 근거를 `plans/PLN-NNN/auto-decisions.md`에 기록합니다
- plan.md 저장 후 `/mst:request -a`를 자동 호출하여 전 과정을 연속 실행합니다
- `config.auto_mode.plan=true`로 상시 활성화할 수 있습니다

#### 베스트 프랙티스

여러 기능을 독립적으로 계획하고 싶을 때:
```
/mst:plan 기능 A
/mst:plan 기능 B
/mst:plan 기능 C
/mst:approve PLN-001 PLN-002 PLN-003   # 일괄 승인 후 병렬 실행
```

---

### /mst:approve

**한 줄 설명**: PM이 작성한 구현 스펙을 승인하고 Phase 2 실행을 시작합니다.

**인자**: `[REQ-ID...] [--auto] [--stop-on-fail | --continue] [--parallel] [--priority <level>]`

#### 목적

PM이 분석·작성한 스펙을 검토 후 승인하여 실제 구현(Phase 2)을 시작합니다. 단건 및 배치 승인을 모두 지원합니다. Phase 3 리뷰 PASS 후 최종 수락(`/mst:accept`)은 기본적으로 자동 실행됩니다.

#### 사용 시점

- PM이 스펙 작성을 완료하고 "승인해주시면 진행하겠습니다"라고 했을 때
- 여러 REQ를 한 번에 일괄 승인할 때

#### 사용 예시

```
/mst:approve                          # 승인 대기 중인 첫 번째 REQ 자동 선택
/mst:approve REQ-007                  # 단건 승인
/mst:approve REQ-007 REQ-008 REQ-009  # 다건 배치 승인
/mst:approve --parallel               # 병렬 실행
/mst:approve REQ-007 --auto           # 자율 모드 (리뷰~수락 무인 완주)
/mst:approve REQ-007 --stop-on-fail   # 실패 시 중단
```

#### --auto 동작

`--auto` 플래그 또는 `request.json.auto_approve=true`(자동 연계 시 설정됨)이면:
- Stitch 디자인 제안 단계를 건너뜁니다
- `review.auto_review=false`여도 **항상** `/mst:review --auto`를 호출합니다
- 리뷰 CRITICAL 이슈 없으면 `/mst:accept`를 자동 실행합니다 (`workflow.auto_accept_result` 설정 따름)
- MAJOR/MINOR 이슈는 `severity_auto_fix` 설정에 따라 PM이 직접 수정 후 루프를 재진입합니다

---

### /mst:accept

**한 줄 설명**: 리뷰를 통과한 결과물을 최종 수락하여 main 브랜치에 머지합니다 (Phase 3 → Phase 5).

**인자**: `[REQ-ID]`

#### 목적

Phase 3 리뷰 PASS 상태인 요청의 Worktree를 main 브랜치에 머지하고 정리합니다. 기본적으로 `/mst:approve`에서 자동 호출됩니다. `workflow.auto_accept_result=false` 설정 시 수동으로 호출합니다.

#### 사용 시점

- `workflow.auto_accept_result=false`로 설정하여 최종 수락을 수동으로 제어할 때
- 리뷰 결과를 직접 확인한 후 명시적으로 머지하고 싶을 때

#### 사용 예시

```
/mst:accept           # 수락 대기 중인 첫 번째 REQ 자동 선택
/mst:accept REQ-007   # 특정 REQ 수락
```

---

### /mst:feedback

**한 줄 설명**: Gran Maestro 워크플로우 내에서 진행 중인 요청에 수동 피드백을 제공합니다 (Phase 4).

**인자**: `{REQ-ID} {피드백 내용}`

#### 목적

자동 리뷰와 별개로 사용자의 직접 관찰이나 추가 요구사항을 피드백으로 전달합니다. 피드백은 Feedback Composer 에이전트가 구조화된 문서로 변환하여 구현 수정 루프(Phase 4)를 트리거합니다.

#### 사용 시점

- 자동 리뷰가 놓친 사항을 사용자가 직접 발견했을 때
- 구현 결과를 검토 후 추가 수정 요청이 있을 때

#### 사용 예시

```
/mst:feedback REQ-007 버튼 클릭 시 로딩 스피너가 표시되지 않음
/mst:feedback REQ-007 모바일 뷰에서 레이아웃이 깨집니다
```

---

### /mst:cancel

**한 줄 설명**: 진행 중인 요청 또는 태스크를 취소하고 관련 리소스를 정리합니다.

**인자**: `{REQ-ID} [--force]`

#### 목적

실행 중인 에이전트/CLI 프로세스를 종료하고 Git worktree와 임시 브랜치를 정리합니다.

#### 사용 시점

- 잘못 시작된 요청을 중단할 때
- 요구사항 변경으로 현재 진행 중인 작업이 불필요해졌을 때

#### 사용 예시

```
/mst:cancel REQ-007          # 취소 확인 후 진행
/mst:cancel REQ-007 --force  # 확인 없이 강제 취소
```

---

### /mst:recover

**한 줄 설명**: Claude Code 세션 종료 후 미완료 요청을 복구하고 마지막 Phase부터 재개합니다.

**인자**: `[{REQ-ID}] [{TASK-ID}]`

#### 목적

파일 기반 상태에서 자동으로 복구 가능한 태스크를 탐색하여 인터럽트된 워크플로우를 재개합니다.

#### 사용 시점

- Claude Code 세션이 끊긴 후 진행 중이던 작업을 이어서 할 때
- 특정 요청 또는 태스크만 재개하고 싶을 때

#### 사용 예시

```
/mst:recover                      # 복구 가능한 요청 자동 탐색 후 재개
/mst:recover REQ-007              # 특정 REQ 복구
/mst:recover REQ-007 02           # 특정 태스크 복구
```

---

### /mst:priority

**한 줄 설명**: 태스크의 우선순위 및 실행 순서를 변경합니다.

**인자**: `{TASK-ID} --before {TASK-ID}`

#### 목적

PM이 자동으로 결정한 태스크 실행 순서를 사용자가 오버라이드합니다. `request.json`의 `execution_order` 배열을 수정하고, 종속성 충돌이 있으면 경고합니다.

#### 사용 시점

- 특정 태스크를 먼저 실행하고 싶을 때
- 전체 태스크 실행 순서를 재정의하고 싶을 때

#### 사용 예시

```
/mst:priority REQ-001-02 --before REQ-001-01   # 02를 01보다 먼저 실행
/mst:priority REQ-001-03 --after REQ-001-01    # 03을 01 다음에 실행
/mst:priority REQ-001 --reorder 03,01,02       # 전체 순서 지정
```

---

### /mst:review

**한 줄 설명**: 구현 완성도를 반복 검토합니다. AC 검증 + 병렬 코드/아키텍처/UI 리뷰 수행

**인자**: `[REQ-ID] [--auto]`

#### 목적

모든 태스크가 `committed` 상태에 도달한 후, 수락 조건(AC) 충족 여부를 검증하고 병렬로 코드/아키텍처/UI 리뷰를 수행합니다. 갭이 발견되면 추가 태스크를 생성하여 재실행하며, 최대 반복 횟수(`review.max_iterations`)까지 자동 반복합니다.

#### 의존 설정

- `review.auto_review` — 자동 리뷰 활성화 여부
- `review.severity_auto_fix` — 심각도 기반 자동 수정 설정

#### 사용 시점

- Phase 2 구현 완료 후 Phase 3 리뷰를 수행할 때
- `review.auto_review=true`이면 `/mst:approve` 루프에서 자동 호출됩니다
- 수동으로 특정 REQ의 리뷰를 트리거하고 싶을 때

#### 사용 예시

```
/mst:review REQ-007           # 특정 REQ 수동 리뷰
/mst:review REQ-007 --auto    # 자동 모드 리뷰
/mst:review                   # 현재 활성 REQ 자동 선택
```

---

## 모니터링

진행 중이거나 완료된 요청/태스크의 상태를 조회하는 스킬 그룹입니다.

---

### /mst:list

**한 줄 설명**: 모든 요청 및 태스크의 현황 목록을 터미널에 표시합니다.

**인자**: `[--all | --active | --completed]`

#### 목적

`.gran-maestro/requests/` 디렉토리의 모든 요청을 상태별로 분류하여 요약 목록을 출력합니다. Python 스크립트(`mst.py`) 우선 실행, 실패 시 직접 파일 스캔으로 fallback합니다.

#### 사용 시점

- 현재 활성 요청이 몇 개인지 빠르게 확인하고 싶을 때
- 특정 요청의 상세 상태 조회는 `/mst:inspect` 사용

#### 사용 예시

```
/mst:list             # 활성 요청 목록
/mst:list --all       # 완료된 요청 포함 전체 목록
/mst:list --completed # 완료된 요청만
```

---

### /mst:inspect

**한 줄 설명**: 특정 요청의 상세 상태를 표시합니다.

**인자**: `{REQ-ID}`

#### 목적

특정 REQ의 Phase 진행 상황, 태스크별 상태, 에이전트 활동, 피드백 라운드 이력 등 상세 정보를 출력합니다.

#### 사용 시점

- 특정 요청이 어느 Phase에 있는지 확인할 때
- 태스크 실행 결과나 에러 원인을 파악할 때

#### 사용 예시

```
/mst:inspect REQ-007
```

---

### /mst:history

**한 줄 설명**: 완료된 요청의 이력을 조회합니다. 실행 중 PM flow의 canonical event ledger는 `mst.py history log|verify|head --session {mst_session_id}`로 조회합니다.

**인자**: `[{REQ-ID}] [--limit {N}]`

#### 목적

`status: completed` 또는 `status: cancelled` 요청의 이력을 조회합니다. 요청별 요약, 소요 시간, 에이전트 사용량, 피드백 라운드 수 등을 확인할 수 있습니다.

#### DOD-005 history ledger

MST 호출, skill lifecycle event, hook event의 source of truth는
`.gran-maestro/sessions/{mst_session_id}/history.*` 단일 ledger입니다.

```
python3 scripts/mst.py history log --session {mst_session_id}
python3 scripts/mst.py history verify --session {mst_session_id}
python3 scripts/mst.py history head --session {mst_session_id}
```

- `history log`: 같은 `mst_session_id` ledger의 event row를 seq 순서로 읽고 핵심 필드를 read-time validation합니다.
- `history verify` / `history head`: append-only ledger tail, local `history.head`, active policy mirror head, `history.verify`를 같은 session key로 대조합니다.
- split-ledger violation은 structured non-success로 다루며, PPID, Claude hook `session_id`, `owner_session_id`, global hook ledger, default history로 fallback하지 않습니다.
- `mst.py hook log`는 hook event 확인용 backward-compatible subset입니다. canonical query는 `mst.py history ... --session {mst_session_id}`입니다.
- 이 범위는 DOD-005 event row 조회와 head/verify에 한정됩니다. DOD-006 recover bundle restoration과 DOD-017 dashboard/execution-flow projection 완료를 의미하지 않습니다.

#### 사용 시점

- 과거에 완료한 작업을 되돌아볼 때
- 특정 REQ의 전체 작업 흐름을 상세히 확인할 때

#### 사용 예시

```
/mst:history               # 완료 이력 목록 (최근순)
/mst:history REQ-007       # 특정 REQ 상세 이력
/mst:history --limit 10    # 최근 10건
```

---

### /mst:dashboard

**한 줄 설명**: Gran Maestro 로컬 대시보드 서버를 시작하고 브라우저에서 엽니다.

**인자**: `[--port {포트}] [--stop] [--restart]`

#### 목적

워크플로우 그래프, 에이전트 활동 스트림, 문서 브라우저를 웹 UI로 제공합니다. 하나의 서버 인스턴스에서 여러 프로젝트를 관리하는 허브 구조로 동작합니다. Deno 런타임이 필요합니다.

#### 사용 시점

- CLI 터미널 출력 대신 시각적 UI로 워크플로우를 모니터링하고 싶을 때
- 여러 프로젝트의 상태를 한 화면에서 확인하고 싶을 때

#### 사용 예시

```
/mst:dashboard              # 서버 시작 후 브라우저 오픈
/mst:dashboard --port 8080  # 포트 지정
/mst:dashboard --stop       # 서버 중지
/mst:dashboard --restart    # 서버 재시작
```

---

## 분석 도구

Maestro 모드 활성 여부에 관계없이 독립적으로 사용할 수 있는 AI 협업 분석 스킬입니다.

---

### /mst:ideation

**한 줄 설명**: 설정된 AI 팀원들의 의견을 병렬 수집하고 PM이 종합 요약합니다.

**인자**: `{주제} [--focus {architecture|ux|performance|security|cost}]`

#### 목적

여러 AI 에이전트(Codex, Gemini 등)의 의견을 1회 병렬 수집하고 PM(Claude)이 종합하는 브레인스토밍 스킬입니다. 다양한 관점을 발산적으로 수집하는 것이 목적이며, 합의까지는 요구하지 않습니다.

#### 사용 시점

- 구현 전 다각도 의견이 필요할 때
- 특정 기술 결정에 대한 여러 관점을 빠르게 수집하고 싶을 때
- 합의까지는 필요 없고 아이디어 발굴이 목적일 때

#### 사용 예시

```
/mst:ideation 실시간 알림 시스템 아키텍처 선택 (WebSocket vs SSE vs Polling)
/mst:ideation 모바일 앱 네비게이션 패턴 --focus ux
/mst:ideation 데이터베이스 샤딩 전략 --focus performance
```

---

### /mst:discussion

**한 줄 설명**: AI 팀원들이 합의에 도달할 때까지 반복 토론합니다.

**인자**: `{주제 또는 IDN-NNN} [--max-rounds {N}] [--focus {분야}]`

#### 목적

PM(Claude)이 사회자 역할로 AI 팀원들 간 의견 발산점을 식별하고 반론을 전달하며 수렴을 유도합니다. `/mst:ideation`이 1회 발산이라면, `/mst:discussion`은 N회 반복을 통한 수렴을 목표로 합니다.

#### ideation과의 차이

| 항목 | /mst:ideation | /mst:discussion |
|------|--------------|----------------|
| 목적 | 다양한 관점 수집 (발산) | 합의 도달 (수렴) |
| 라운드 | 1회 | N회 반복 |
| 종료 조건 | PM 종합 완료 | 참여자 합의 또는 max rounds |

#### 사용 시점

- 이전 ideation 결과를 심화·수렴하고 싶을 때
- 기술 선택에서 팀 합의가 필요할 때

#### 사용 예시

```
/mst:discussion IDN-003                           # 기존 ideation 이어서 심화
/mst:discussion REST vs GraphQL API 설계 결정 --max-rounds 3
/mst:discussion 마이크로서비스 분리 기준 합의 --focus architecture
```

---

### /mst:debug

**한 줄 설명**: 여러 AI가 병렬로 버그를 조사하고 종합 디버그 리포트를 생성합니다.

**인자**: `{버그/이슈 설명} [--focus {파일패턴}]`

#### 목적

설정된 AI 팀원들이 병렬로 버그를 독립 조사하고, PM(Claude)도 능동적으로 조사에 참여하여 모든 결과를 합쳐 종합 디버그 리포트(`debug-report.md`)를 생성합니다. 리포트에는 근본 원인, 우선순위별 수정 제안(P0~P2), 영향 파일 목록이 포함됩니다. 리포트 생성 후 `/mst:plan --from-debug DBG-NNN`으로 자연스럽게 이어집니다.

#### 사용 시점

- 버그의 근본 원인이 불명확할 때
- 여러 파일에 걸친 복잡한 문제를 조사할 때
- 수정 전 정확한 원인 파악을 원할 때

#### 사용 예시

```
/mst:debug 로그인 후 대시보드가 빈 화면을 표시함
/mst:debug API 응답이 간헐적으로 500 에러를 반환 --focus src/api/
/mst:debug 빌드 후 테스트 전체가 실패함
```

---

### /mst:explore

**한 줄 설명**: 에이전트들이 코드베이스를 백그라운드로 자율 탐색해 원하는 정보를 찾아옵니다

**인자**: `{탐색 목표 설명} [--focus {파일패턴}]`

#### 목적

PM(Claude)이 탐색 목표를 분석하여 Codex(코드 구조/구현 패턴)와 Gemini(아키텍처/흐름/연결 관계)에 역할을 배정합니다. 모든 탐색 에이전트를 백그라운드로 동시 실행한 뒤, 개별 결과를 종합하여 `explore-report.md`를 작성합니다. Maestro 모드 활성 여부에 관계없이 독립적으로 사용 가능합니다.

#### 의존 설정

- `archive.auto_archive_on_create` — 세션 생성 시 초과분 자동 아카이브
- `archive.max_active_sessions` — 최대 활성 세션 수

#### 사용 시점

- 코드베이스의 특정 기능이 어디에 구현되어 있는지 찾고 싶을 때
- 문서와 실제 코드 간의 갭을 분석하고 싶을 때
- 스펙 작성 전 코드 구조를 파악하고 싶을 때

#### 사용 예시

```
/mst:explore 이 프로젝트의 인증 로직이 어디에 구현되어 있는지 찾아줘
/mst:explore 설정 파일과 코드 간의 갭 분석 --focus docs/
/mst:explore 사용되지 않는 코드 경로 탐색
```

---

## CLI 직접 호출

외부 AI CLI 도구와 Claude 서브에이전트를 직접 디스패치하는 스킬입니다. Maestro 모드 활성 여부에 관계없이 사용 가능합니다.

---

### /mst:codex

**한 줄 설명**: Codex CLI를 호출하여 코드 작업을 실행합니다.

**인자**: `{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--json] [--trace {REQ/TASK/label}]`

#### 목적

Codex CLI 호출의 단일 진입점입니다. Gran Maestro 워크플로우 내·외부 모든 Codex 호출이 이 스킬을 경유합니다.

#### 사용 시점

- Codex CLI를 직접 실행하고 싶을 때
- 워크플로우 내 PM이 Codex에게 구현 태스크를 디스패치할 때
- `--prompt-file`로 긴 프롬프트를 파일로 전달할 때

#### 사용 예시

```
/mst:codex "src/auth.ts에서 JWT 검증 로직을 구현해줘"
/mst:codex --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
/mst:codex "테스트 작성" --trace REQ-007/01/tests
```

---

### /mst:gemini

**한 줄 설명**: Gemini CLI를 호출하여 대용량 컨텍스트 작업을 실행합니다.

**인자**: `{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]`

#### 목적

Gemini CLI 호출의 단일 진입점입니다. 대용량 문서, 프론트엔드 전체 분석, 넓은 컨텍스트가 필요한 작업에 적합합니다.

#### 사용 시점

- 프론트엔드 전체 코드베이스를 분석해야 할 때
- 대용량 문서 작업(예: 30개 스킬 레퍼런스 일괄 갱신)에 Gemini의 넓은 컨텍스트 창이 필요할 때
- `--files` 옵션으로 여러 파일을 컨텍스트로 전달할 때

#### 사용 예시

```
/mst:gemini "이 코드베이스의 아키텍처를 분석해줘" --files "src/**/*.ts"
/mst:gemini --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
```

---

### /mst:claude

**한 줄 설명**: Claude 서브에이전트를 호출하여 코드 작업을 실행합니다.

**인자**: `{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--trace {REQ/TASK/label}]`

#### 목적

PM Conductor의 "I conduct, I don't code" 원칙을 유지하면서, 별도 Claude 서브에이전트 프로세스를 스폰하여 구현 작업을 분리합니다. Codex/Gemini CLI가 설치되지 않은 환경이나 Claude의 파일 편집 도구(Read/Write/Edit/Bash/Glob/Grep)가 필요한 작업에 활용합니다.

#### 사용 시점

- Codex나 Gemini CLI가 설치되지 않은 환경에서 구현 작업을 위임할 때
- Gran Maestro 워크플로우 내 `claude-dev` 태스크를 디스패치할 때
- 파일 읽기/쓰기/편집 도구가 필요한 태스크를 서브에이전트에게 분리 실행할 때

#### 사용 예시

```
/mst:claude "src/components/LoginForm.tsx 파일을 수정하여 구글 로그인 버튼을 추가해줘"
/mst:claude --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
/mst:claude "타입 오류 수정" --trace REQ-007/01/typefix
```

---

## 설계 도구

PM Conductor가 변수를 치환하여 실행하는 Design Wing 전문 에이전트 스킬입니다.

---

### /mst:stitch

**한 줄 설명**: Google Stitch MCP를 통해 UI 화면 목업/시안을 생성합니다.

**인자**: `[--auto] [--variants] [--req REQ-NNN] {화면 설명}`

#### 목적

Stitch MCP 툴을 사용하여 UI 화면 시안을 생성하고 Stitch 프로젝트 URL과 화면 이미지를 반환합니다. 기존 화면 컨텍스트를 수집하여 레이아웃 일관성을 유지하고, 중복 생성을 방지합니다.

#### 사용 시점

- 화면 시안이나 목업을 생성해야 할 때 ("화면 디자인해줘", "목업 만들어줘")
- 새 라우트/페이지를 추가하기 전에 UI를 먼저 확정하려 할 때
- 전체 디자인 변경 방향을 여러 variants로 탐색하고 싶을 때

#### 선행 조건

`config.stitch.enabled: true`가 설정되어 있어야 합니다.

#### 트리거 분기

| 트리거 | 처리 방식 |
|--------|----------|
| "화면 디자인해줘", "Stitch로 그려줘", "목업 만들어줘" | 즉시 화면 생성 |
| 새 라우트 파일 생성 + 네비게이션 노출 예정 | 사용자 확인 후 생성 |
| "전체 디자인 바꿔줘", "리디자인" | 확인 후 variants 2-3개 제안 |
| 기존 화면 컴포넌트/스타일만 수정 | Stitch 개입 없음 |

#### 사용 예시

```
/mst:stitch 로그인 화면 — 이메일/비밀번호 입력 폼 + 구글 로그인 버튼
/mst:stitch --variants 대시보드 메인 화면 전체 리디자인
/mst:stitch --req REQ-007 알림 설정 패널
```

---

### /mst:ui-designer

**한 줄 설명**: 화면 설계, 컴포넌트 구조, 인터랙션 흐름, 디자인 시스템을 설계하는 Design Wing 에이전트입니다.

**인자**: PM Conductor가 변수를 치환하여 `/mst:codex`로 실행

#### 목적

UI 스펙 문서를 생성합니다. 컴포넌트 트리와 props/state 흐름, 사용자 경로(happy/error/edge), 디자인 시스템 토큰(색상/간격/타이포그래피), 반응형 브레이크포인트를 정의합니다. 구현 코드는 작성하지 않습니다.

#### 사용 시점

- PM이 프론트엔드 기능 구현 전 UI 설계 단계를 별도로 수행할 때
- 컴포넌트 계층과 상태 흐름을 미리 문서화하고 싶을 때

---

### /mst:schema-designer

**한 줄 설명**: DB 스키마, 데이터 모델, ERD, 마이그레이션 계획을 설계하는 Design Wing 에이전트입니다.

**인자**: PM Conductor가 변수를 치환하여 `/mst:codex`로 실행

#### 목적

데이터 모델 설계 문서를 생성합니다. Entity-Relationship 다이어그램, 필드 타입/제약/기본값, 데이터 무결성을 보존하는 마이그레이션 전략, 쿼리 패턴에 맞는 인덱스 설계를 포함합니다. 구현 코드는 작성하지 않습니다.

#### 사용 시점

- PM이 데이터 모델 변경을 포함하는 기능을 구현하기 전 설계 단계를 수행할 때
- ERD와 마이그레이션 전략을 문서로 먼저 확정하고 싶을 때

---

### /mst:feedback-composer

**한 줄 설명**: 리뷰 결과를 분석해 외주 에이전트가 한 번에 수정할 수 있는 정밀하고 실행 가능한 피드백 문서를 작성하는 에이전트입니다.

**인자**: PM Conductor가 변수를 치환하여 `/mst:codex`로 실행

#### 목적

여러 리뷰어의 검토 결과를 하나의 명확한 피드백 문서로 종합합니다. 각 이슈에 파일:라인 참조, 문제점, 수정 방법을 포함하고, CRITICAL > HIGH > MEDIUM > LOW 우선순위와 `implementation_error | spec_insufficient` 분류를 제공합니다.

#### 사용 시점

- Phase 3 리뷰 FAIL 후 구체적인 수정 지침이 필요할 때 PM이 자동 호출합니다
- 여러 리뷰어 피드백을 하나의 실행 가능한 문서로 정리할 때

---

## 관리

Maestro 모드 전환, 설정 관리, 세션 정리를 담당하는 스킬 그룹입니다.

---

### /mst:settings

**한 줄 설명**: Gran Maestro 설정을 조회하거나 변경합니다.

**인자**: `[{key} [{value}]]`

#### 목적

`.gran-maestro/config.json` 파일을 관리합니다. 인자 없이 호출 시 전체 설정을 표시하고, key만 지정 시 해당 값을 표시하며, key와 value 모두 지정 시 설정을 변경합니다.

#### 사용 시점

- 워크플로우 설정(auto_accept, parallel 실행 등)을 확인하거나 변경할 때
- Stitch 연동 활성화/비활성화가 필요할 때

#### 사용 예시

```
/mst:settings                                    # 전체 설정 표시
/mst:settings workflow.auto_accept_result        # 특정 설정값 조회
/mst:settings workflow.auto_accept_result false  # 설정 변경
/mst:settings stitch.enabled true               # Stitch 연동 활성화
```

---

### /mst:on

**한 줄 설명**: Gran Maestro 모드를 활성화합니다.

**인자**: 없음

#### 목적

Maestro 오케스트레이션 스킬을 활성화하고 `.gran-maestro/mode.json`을 `active: true`로 업데이트합니다. 활성화 시 Extension 최신 버전을 자동 확인하여 안정 경로에 동기화합니다(`extension ensure-copy` — 비차단). `/mst:request`를 호출하면 자동 부트스트래핑이 포함되어 있어 `/mst:on`을 별도로 호출할 필요가 없습니다.

#### 사용 시점

- 명시적으로 Maestro 모드를 켜고 싶을 때
- 모드 상태를 확인하면서 수동으로 활성화하려 할 때

#### 사용 예시

```
/mst:on
```

---

### /mst:off

**한 줄 설명**: Gran Maestro 모드를 비활성화합니다.

**인자**: `[--force]`

#### 목적

`.gran-maestro/mode.json`을 `active: false`로 업데이트합니다. 활성 요청이 있으면 경고를 표시합니다. `--force` 사용 시 활성 요청의 status를 `paused`로 변경합니다.

#### 사용 시점

- Maestro 워크플로우를 일시적으로 중단하고 싶을 때
- 다른 작업 모드로 전환하기 전

#### 사용 예시

```
/mst:off           # 활성 요청 없으면 즉시 비활성화
/mst:off --force   # 활성 요청을 paused 처리하고 강제 비활성화
```

---

### /mst:cleanup

**한 줄 설명**: ideation/discussion/requests 세션을 일괄 정리합니다.

**인자**: `[--run] [--dry-run]`

#### 목적

한 번의 호출로 모든 타입의 세션을 정리합니다. ideation과 discussion은 최근 N개만 유지하고 초과분을 아카이브하며, completed requests를 자동 아카이브하고 오래된 활성 requests는 사용자 선택으로 정리합니다. Maestro 모드 활성 여부에 관계없이 사용 가능합니다.

#### /mst:archive와의 차이

| 항목 | /mst:cleanup | /mst:archive |
|------|-------------|-------------|
| 목적 | 한 번에 전부 정리 | 타입별 세밀 관리 |
| 동작 | 3단계 자동 + 인터랙티브 | 수동 지정 |
| 복원 | 지원 안 함 | 지원 (`--restore`) |
| 대상 | ideation + discussion + requests 일괄 | `--type`으로 개별 지정 |

#### 사용 시점

- 세션이 많이 쌓여서 한 번에 정리하고 싶을 때
- 빠른 전체 정리가 필요할 때

#### 사용 예시

```
/mst:cleanup --dry-run  # 정리될 항목 미리 확인
/mst:cleanup --run      # 실제 정리 실행
```

---

### /mst:archive

**한 줄 설명**: 세션 아카이브를 타입별로 세밀하게 관리합니다.

**인자**: `[--run [--type {ideation|discussion|requests}]] [--restore {ID}] [--purge [--max-age-days N] [--dry-run]] [--list]`

#### 목적

각 타입 디렉토리 하위의 `archived/`에 tar.gz 압축 보관합니다. `max_active_sessions`(기본 200) 기준으로 초과분을 아카이브하고, 필요 시 복원(`--restore`)이나 영구 삭제(`--purge`)도 지원합니다.

#### 사용 시점

- 특정 타입(ideation/discussion/requests)만 선택적으로 아카이브할 때
- 아카이브된 세션을 복원해야 할 때
- 오래된 아카이브를 영구 삭제하려 할 때

#### 사용 예시

```
/mst:archive --list                              # 아카이브 현황 조회
/mst:archive --run --type ideation               # ideation만 아카이브
/mst:archive --restore IDN-003                   # 특정 세션 복원
/mst:archive --purge --dry-run                  # 삭제 대상 미리보기
/mst:archive --purge --max-age-days 30          # 30일보다 오래된 아카이브 삭제
```

---

### /mst:setup-omx

**한 줄 설명**: Codex CLI 프로젝트에 oh-my-codex를 설치·초기화·gitignore·AGENTS.md 주입

**인자**: `[--dir {프로젝트 경로}] [--skip-install]`

#### 목적

Codex CLI 프로젝트에 oh-my-codex(OMX)를 4단계로 자동 설정합니다: 전역 설치 → 초기화 + doctor → .gitignore 등록 → AGENTS.md 주입. 독립 유틸리티 스킬로 config.json 참조 없이 동작합니다.

#### 사용 시점

- 새로운 Codex CLI 프로젝트에 OMX를 설정할 때
- 기존 프로젝트에 Gran Maestro의 AGENTS.md를 주입하고 싶을 때

#### 사용 예시

```
/mst:setup-omx                              # 현재 디렉토리에 OMX 설정
/mst:setup-omx --dir ./my-codex-project     # 특정 프로젝트 경로에 설정
/mst:setup-omx --skip-install               # 설치 단계 건너뛰고 초기화만
```

---

### /mst:setup-extension

**한 줄 설명**: Chrome Extension(UI Picker)을 설치합니다. Extension을 안정 경로에 복사 + chrome://extensions 페이지 오픈 + 경로 클립보드 복사 + 연결 확인.

**인자**: `[--skip-open]`

#### 목적

Gran Maestro Chrome Extension(UI Picker)을 Chrome에 로드하는 설치 절차를 안내합니다. `extension ensure-copy`를 실행하여 Extension을 안정 경로(`~/.gran-maestro/chrome-extension/`)에 복사한 뒤, `chrome://extensions` 페이지를 자동으로 열고 Extension 경로를 클립보드에 복사하며 Dashboard 서버와의 연결 상태를 확인합니다. 안정 경로를 사용하면 플러그인 업데이트 시에도 Chrome 재등록이 불필요합니다. 독립 유틸리티 스킬로 config.json 참조 없이 동작합니다.

#### 사용 시점

- Chrome Extension을 처음 설치할 때
- 플러그인 업데이트 후 Extension을 새로고침할 때
- Extension과 Dashboard 서버 간 연결 문제를 확인할 때

#### 사용 예시

```
/mst:setup-extension                 # chrome://extensions 자동 오픈 + 경로 복사 + 연결 확인
/mst:setup-extension --skip-open     # chrome:// 자동 오픈 생략 (이미 열어 둔 경우)
```

#### 옵션

- `--skip-open` — `chrome://extensions` 자동 오픈을 생략합니다. 이미 해당 페이지를 열어 둔 경우 사용합니다.

> 자세한 설치 절차는 [Chrome Extension 설치 가이드](extension-setup.md)를 참고하세요.

---

## 자율 실행 모드 (-a / --auto)

`-a` 또는 `--auto` 플래그를 전달하면 사람 개입 없이 전 과정을 자동으로 완주하는 **자율 실행 모드**가 활성화됩니다. 각 스킬에서 동작이 다릅니다.

### 스킬별 동작

| 스킬 | --auto 효과 |
|------|------------|
| `/mst:plan -a` | AskUserQuestion 없이 PM이 미결 항목을 자율 결정. 결정 근거를 `auto-decisions.md`에 기록. 완료 후 `/mst:request -a` 자동 연계 |
| `/mst:request -a` | Spec Pre-review 건너뜀. 스펙 작성 완료 즉시 `/mst:approve --auto` 자동 호출 |
| `/mst:approve --auto` | Stitch 디자인 제안 건너뜀. `review.auto_review` 설정 무관하게 항상 리뷰 실행. CRITICAL 없으면 자동 수락 |

### 전체 연계 흐름

```
/mst:plan -a "주제"
  └→ plan.md 저장 (자율 결정 + auto-decisions.md 기록)
     └→ /mst:request --plan PLN-NNN -a
           └→ spec.md 작성 (Spec Pre-review 없음)
              └→ /mst:approve REQ-NNN --auto
                    └→ Phase 2 실행 (codex/gemini)
                       └→ /mst:review --auto
                              └→ /mst:accept  (auto_accept_result=true 시)
```

`/mst:plan -a` 한 번으로 plan → spec → 구현 → 리뷰 → 수락까지 전 과정이 무인 실행됩니다.

### config로 상시 활성화

CLI 플래그 없이 항상 자율 모드로 실행하려면:

```json
{
  "auto_mode": {
    "plan": true,
    "request": true
  }
}
```

```
/mst:settings auto_mode.plan true
/mst:settings auto_mode.request true
```

> CLI `-a` 플래그는 config 설정보다 항상 우선합니다.

### 주의사항

- **plan**: 확신이 낮은 항목은 `mst:discussion`을 자동 호출해 결론을 도출합니다. `config.auto_mode.confidence_threshold`로 임계값을 조정할 수 있습니다.
- **approve**: CRITICAL 이슈 발생 시 자동 흐름이 멈추고 사용자 개입을 요청합니다.
- **approve**: MAJOR/MINOR 이슈는 `severity_auto_fix` 설정에 따라 PM이 직접 수정 후 루프를 재진입합니다.

---

## 한국어 자연어 트리거

Gran Maestro는 사용자의 자연어 발화에서 의도를 감지하여 해당 스킬을 자동으로 실행합니다. 아래는 주요 트리거 키워드와 그에 대응하는 스킬입니다.

### 오케스트레이션 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "구현해줘", "만들어줘", "개발해줘", "추가해줘", "작성해줘" | `/mst:request` |
| "계획 세워줘", "플랜 짜줘", "정제해줘", "범위 잡아줘" | `/mst:plan` |
| "리뷰", "코드 검토", "구현 검증" | `/mst:review` |
| "승인", "진행해", "OK 진행", "시작해", "실행해" | `/mst:approve` |
| "수락", "머지", "최종 수락", "합쳐줘" | `/mst:accept` |
| "피드백", "수정 요청", "이건 틀렸어", "다시 해줘" (워크플로우 내) | `/mst:feedback` |
| "취소", "중단", "그만", "멈춰" | `/mst:cancel` |
| "복구", "재개", "이어서", "계속해줘", "다시 시작" | `/mst:recover` |
| "우선순위 변경", "순서 변경", "먼저 실행", "앞으로" | `/mst:priority` |

### 모니터링 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "현황", "상태 보여줘", "목록", "뭐 하고 있어" | `/mst:list` |
| "상세 상태", "자세히 보여줘", "REQ-NNN 상태" | `/mst:inspect` |
| "이력", "히스토리", "완료된 요청", "과거 작업" | `/mst:history` |
| "대시보드", "대시보드 열어", "모니터링", "시각화" | `/mst:dashboard` |

### 분석 도구 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "아이디어", "브레인스토밍", "의견 수렴", "관점 모아줘" | `/mst:ideation` |
| "토론", "합의", "디스커션", "심화 논의" | `/mst:discussion` |
| "버그", "에러", "오류", "안 돼", "안 됨", "고쳐", "문제 분석", "디버그" | `/mst:debug` |
| "탐색", "코드 찾아줘", "어디 있어", "구조 분석" | `/mst:explore` |

### 설계 도구 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "화면 디자인해줘", "목업 만들어줘", "Stitch로 그려줘", "UI 시안", "페이지 설계" | `/mst:stitch` |

### CLI 직접 호출 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "코덱스 실행", "코덱스로", "Codex로 작업" | `/mst:codex` |
| "제미나이 실행", "제미나이로", "Gemini로 분석", "대용량 분석" | `/mst:gemini` |
| "클로드로 실행", "클로드 서브에이전트", "Claude 서브에이전트" | `/mst:claude` |

### 관리 트리거

| 자연어 키워드 / 발화 패턴 | 자동 실행 스킬 |
|--------------------------|--------------|
| "설정", "설정 변경", "환경 설정", "config" | `/mst:settings` |
| "마에스트로 켜", "마에스트로 시작", "지휘자 모드 켜" | `/mst:on` |
| "마에스트로 꺼", "지휘자 모드 끝", "Maestro 비활성" | `/mst:off` |
| "정리", "클린업", "청소", "세션 정리 전부" | `/mst:cleanup` |
| "아카이브", "세션 아카이브", "압축 보관" | `/mst:archive` |
| "OMX 설치", "oh-my-codex 설정" | `/mst:setup-omx` |
| "Extension 설치", "크롬 확장 설정" | `/mst:setup-extension` |

---

*이 문서는 Gran Maestro 플러그인의 `skills/` 디렉토리를 기반으로 자동 탐색하여 작성되었습니다. 스킬 추가·변경 시 함께 업데이트하세요.*
