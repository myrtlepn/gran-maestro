# FLOW Controller 제약 및 동작

> Gran Maestro Stop-hook의 판정 로직, 흐름 제어 제약, 차단 사유를 단일 문서로 통합한 참조 문서입니다.
> 이 문서는 DOD-007 (docs-consolidation 도메인)의 첫 번째 증분으로 작성되었습니다. 구현 상태는 문서 하단 참조.

## {#overview} 개요

Gran Maestro Stop-hook(`hooks/mst-stop-hook.sh`)은 Claude Code의 Stop 이벤트마다 실행되며, **사용자 대화가 멈추기 전 MST 스킬 체인이 silent drop 없이 정확히 흐르도록 보장**합니다. 모든 판정 경로는 `{"decision": "allow"|"block", "reason": "..."}` JSON을 stdout으로 반환하고, 분기 누락(unhandled path)은 fail-open + `flow-detail.ndjson` 기록으로 처리합니다.

핵심 원칙 (AD-001 Execution Continuity Principle):
- **원자성**: 스킬 state 전이, snapshot 쓰기, 로그 append, queue 조작 모두 temp-file + atomic rename 패턴.
- **관찰성**: 모든 hook 판정은 `flow-detail.ndjson`에 `decision/layer/reason/duration_ms` 기록.
- **결정성**: 모든 실행 경로는 allow·block 중 최종 상태에 도달해야 하며, unhandled path는 fail-open + `unhandled_path` 이벤트로 명시.

## {#layer-1-mode-gate} Layer 1: mst:on/off 모드 게이트

**판정 조건**: `.gran-maestro/config.resolved.json` 또는 `mst.py config get workflow.mode` 결과가 `off`이면 즉시 pass-through.

**반환**:
- `/mst:off` 모드: `{decision: "allow", layer: 1, reason: "mst-off mode pass-through"}`
- `/mst:on` 모드: Layer 2로 진행

**관찰 로그**: `flow-detail.ndjson`에 `layer=1, decision, reason` 기록.

**이유**: 사용자가 MST 모드를 끈 경우 hook이 Stop 이벤트에 간섭하지 않아야 합니다. Layer 1 pass-through는 비-MST 일반 코드 세션에 오버헤드를 주지 않습니다.

## {#layer-2-snapshot-gate} Layer 2: session_id snapshot 게이트

**판정 조건**: stdin JSON의 `session_id` 값으로 `.gran-maestro/state/{session_id}/snapshot.json` 파일 존재 여부 확인.

**반환**:
- snapshot 부재: `{decision: "allow", layer: 2, reason: "no-mst-session"}`
- snapshot 존재: Layer 3으로 진행

**session_id 추출 프로토콜**:
1. Primary: `stdin_json.session_id` 필드.
2. Fallback: `stdin_json.transcript_path` basename에서 UUID 추출 (`{path}/{session_uuid}.jsonl` 형식).
3. 모두 실패 시: `flow-detail.ndjson`에 `session_id_resolution_failed` 이벤트 + fail-open.

**TTL 없음**: session_id 자체가 Claude Code 대화 수명을 표현하므로 별도 TTL(이전 PPID 기반 30분 stale window)은 제거됨 (AD-002 session-id 전환).

## {#layer-3-namespace-gate} Layer 3: MST 네임스페이스 게이트

**판정 조건**: `snapshot.currentSkill`이 MST allowlist(`scripts/_mst_namespace.py`의 `MST_SKILL_NAMESPACE` 상수)에 포함되는지 확인.

**반환**:
- 범위 밖: `{decision: "allow", layer: 3, reason: "non-mst-skill"}`
- 범위 내: 3-way 판정으로 진행

**Allowlist 예시**: `mst:*`, `agile`, `request`, `resume`, `recover`, `review`, `approve`, `accept`, `feedback`, `cancel`, `intent`, `list`, `inspect`, `priority`, `explore`, `debug`, `discussion`, `ideation`, `plan`, `agile-plan` 등. 단일 상수 모듈에서 관리되므로 신규 스킬 추가 시 allowlist 업데이트 필요.

## {#three-way-judgment} 3-way 판정

Layer 3 통과 후 아래 세 축 + fallback 하나를 순차 평가합니다.

### {#return-to} return_to 분기

**조건**: `snapshot.returnTo` 필드 존재 또는 어시스턴트 출력 마커에서 `return_to=parent/N` 감지.

**반환**: `{decision: "block", layer: "return_to", reason: "[RETURN-TO] sub-skill returned return_to=parent/N", return_to: {parent, N}}`

**주입 메시지 예**: `Skill(skill: parent) at step N을 즉시 호출하여 상위 스킬로 복귀하세요.`

**이유**: 서브스킬이 완료되면 상위 스킬로 반드시 복귀해야 체인 흐름이 유지됩니다. return_to를 놓치면 체인이 끊어집니다.

### {#step-progress} step<total 분기

**조건**: `snapshot.currentStep < snapshot.totalSteps`

**반환**: `{decision: "block", layer: "step_progress", reason: "skill {skill} step {N+1}/{total} 계속 진행"}`

**주입 메시지 예**: `현재 스킬 {skill}의 step {N+1}/{total}을 계속 진행하세요.`

**이유**: 스킬 중간에 사용자 대화가 멈추지 않도록 다음 step 진행을 강제합니다.

### {#completion} 완료 분기

**조건**: `snapshot.status == "committed"` 또는 `currentStep == totalSteps`

**반환**: `{decision: "allow", layer: "completion", reason: "skill completed"}`

**이유**: 스킬 완료 시 정상적으로 Stop 이벤트를 허용합니다.

### {#unhandled-path} Unhandled path fallback

**조건**: 위 어느 분기에도 해당하지 않음 (프로그래밍 오류 방지).

**반환**: `{decision: "allow", layer: "unhandled", reason: "unhandled_path fallback"}`

**관찰**: `flow-detail.ndjson`에 `event_type=unhandled_path` 이벤트 (stack trace + snapshot dump 포함).

**이유**: 분기 누락이 있더라도 fail-open으로 사용자 세션을 보호하고 로그로 감지 가능성을 확보합니다. DOD-004 7번 "분기 커버리지 테스트"로 미래에 unhandled path를 줄여갑니다.

## {#hook-failure} Hook 자체 실패 정책

Hook 실행 자체가 실패(예: `mst.py state get` crash, JSON 파싱 오류, 파일 I/O 실패, 판정 경로 `hook.judge_timeout_ms` 초과)하는 경우, **Stop을 허용(`decision: "allow"`)** 하고 실패 사유를 `flow-detail.ndjson`에 기록합니다 (AD-001 결정성 + fail-open 원칙).

**기록 필드** (`event_type=hook_failure` 또는 `judge_timeout`):
- `timestamp`: ISO 8601 UTC
- `event_type`: `hook_failure` | `judge_timeout` | `session_id_resolution_failed`
- `session_id`: stdin JSON 기반 또는 `unknown`
- `signal` / `exit_code`: 프로세스 종료 신호
- `stack_trace`: Python exception stack 또는 bash `ERR` trap 정보
- `stdin_json_digest`: stdin JSON 해시 (민감정보 보호)
- `ppid`: 디버그 보조
- `snapshot_snapshot`: snapshot 파일 존재 시 복사본

**judge_timeout 추가 필드**:
- `budget_ms`: 적용된 타임아웃 상한 (기본 500ms, `config.hook.judge_timeout_ms` 또는 `MST_HOOK_JUDGE_TIMEOUT_MS` env로 조정)
- `fail_open`: `true` (항상)
- `hook`: `"stop-hook"`
- `observed_ms_approx`: 시작 시각 대비 관측된 경과 시간

**stderr**: 실패 요약 한 줄 출력 (Claude Code가 받을 수 있도록).

**이유**: Hook이 block을 반환한 채 실패하면 사용자 세션이 영구 차단될 위험이 있습니다. fail-open으로 사용자 진행을 보장하되, `flow-detail.ndjson` 관찰 기록으로 사후 디버깅을 확보합니다.

## {#takeover} Takeover 프로토콜 (Advisory Ownership, AD-004)

Durable 리소스(AGI/REQ/PLN)의 `owner_session_id`는 **diagnostic-only advisory 필드**입니다. 읽기와 canonical 뮤테이션 권한은 `owner_session_id`가 아니라 현재 `MST_SESSION_ID`와 durable payload의 `mst_session_id` equality로 결정됩니다.

**뮤테이션 규칙**:
1. `fcntl.flock` 직렬화로 동시성 제어.
2. payload `mst_session_id`와 현재 `MST_SESSION_ID`가 불일치하면 non-zero fail-closed.
3. `owner_session_id` 불일치는 warning/audit diagnostic으로만 기록하며 mutation permission, recovery equality, takeover 필요 여부를 결정하지 않는다.
4. 명시적 cleanup/takeover가 실행되면 단일 atomic JSON write (`temp + fsync + rename + dir fsync`, flock 전체 기간 유지)로 diagnostic owner field와 `takeover_log`만 갱신한다.

**Takeover Storm 감지**: 최근 5분 내 동일 AGI에 대해 양방향 diagnostic owner cleanup >= 2회 감지 시 `takeover_storm` 판정 → cleanup 차단 + 대시보드 경고.

**사용자 인터페이스**:
- 대시보드 헤더에 owner pill 지속 표시 (클릭 시 banner 재오픈).
- SSE `takeover` 이벤트 수신 시 자동 mutation UI 재활성화 + toast.
- 사용자 페이지 수동 리로드 없이 소유권 전환 체감 가능.

## {#session-id-migration} session_id 전환 가이드 (AD-002)

기존 PPID 기반 snapshot·owner_ppid를 Claude Code 대화 UUID(`session_id`) 기반 모델로 전환합니다.

**마이그레이션 CLI**: `mst.py state migrate` (PLN-522 기준, 구현 단계에 따라 변경 가능)
- 무중단 업그레이드: `.gran-maestro/state/.MIGRATING` sentinel 생성 후 1회 수행.
- SIGINT 중단 시: `hooks doctor` CLI에서 `unclean` 진단 → `--rollback` / `--resume` 경로 제공.
- `/mst:on` 실행 시 legacy snapshot 탐지 + 안내.
- 대시보드 글로벌 배너로 migration 필요 상태 노출.

**session_id 검증 (DOD-020)**:
- UUID v4 regex 검증.
- `state/{uuid}/` 디렉토리 실존 확인.
- snapshot에 `created_at` 기록, Layer 2 진입 전 transcript 시작 시각과 delta 검증 (음수 또는 24h 이상 차이 시 `session_id_mismatch_suspected` + snapshot을 `state/{uuid}/snapshot.stale-{ts}.json`으로 격리).

## {#troubleshooting} 흔한 block/allow 사유와 해결법

### `mst-off mode pass-through` (Layer 1 allow)
- **원인**: `/mst:off` 모드 활성 상태.
- **해결**: MST 워크플로우를 사용하려면 `/mst:on` 실행.

### `no-mst-session` (Layer 2 allow)
- **원인**: 현재 session_id로 snapshot이 생성된 적 없음 (MST 스킬 한 번도 호출 안 함).
- **해결**: `/mst:request`, `/mst:agile-plan`, `/mst:agile` 등 MST 스킬로 시작하면 snapshot이 자동 생성됩니다.

### `non-mst-skill` (Layer 3 allow)
- **원인**: `snapshot.currentSkill`이 MST allowlist에 없음. 일반 코드 세션 또는 allowlist 미등록 신규 스킬.
- **해결**: 신규 MST 스킬이라면 `scripts/_mst_namespace.py`의 `MST_SKILL_NAMESPACE`에 추가. 아니라면 정상 동작.

### `[RETURN-TO] ...` block (return_to 분기)
- **원인**: 서브스킬이 완료되어 상위로 복귀해야 함.
- **해결**: 지시된 `Skill(skill: parent) at step N` 호출로 상위 스킬 복귀.

### `skill X step N+1/total 계속 진행` block (step_progress 분기)
- **원인**: 현재 스킬의 step이 아직 남아있음.
- **해결**: 지시대로 다음 step의 작업을 수행. 스킬 중간에 대화 멈춤 금지.

### `hook_failure: ...` (hook 자체 실패)
- **원인**: hook Python 스크립트 crash, I/O 실패, timeout budget 초과 등.
- **해결**: `.gran-maestro/state/{session_id}/flow-detail.ndjson`에서 `hook_failure` / `judge_timeout` 이벤트 확인. 반복 발생 시 `mst.py hooks doctor` (DOD-008에서 제공 예정) 실행.

### `session_id_resolution_failed`
- **원인**: stdin JSON의 session_id/transcript_path 모두 파싱 실패.
- **해결**: Claude Code 버전 확인 (REF-011 hook stdin schema). 필요 시 hook bootstrap 로그 확인.

## 운영·디버그 노트 (DOD-012 보안 연계)

### 로그 공유 주의

`.gran-maestro/state/{session_id}/flow-detail.ndjson`은 hook 자체 실패 시 snapshot 일부, 내부 파일 경로, 환경 변수, stdin JSON digest 등 **민감한 정보를 포함할 수 있습니다**. PR 첨부·외부 공유 시 민감 정보 여부를 확인 후 공유하십시오.

### 대시보드 localhost-only

대시보드는 `src/server.ts` 기준 localhost(127.0.0.1)에만 서빙됩니다. 원격 호스팅은 별도 인증/HTTPS가 필요하며 현재 지원 범위에 포함되지 않습니다.

## {#구현-상태} 구현 상태

본 문서(`docs/FLOW-CONSTRAINTS.md`)는 DOD-007 증분 #1로 작성되었고, 증분 #2에서 Stop-hook stdout JSON의 `details_anchor` 선택 필드가 연결되었습니다.

- **증분 #2 (완료)**: `hooks/mst-stop-hook.sh`의 최종 stdout JSON에 `details_anchor`를 추가했습니다. 값은 `docs/FLOW-CONSTRAINTS.md#<slug>` 또는 `null`이며, 기존 `decision`/`reason` 필드는 호환성을 위해 그대로 유지됩니다.
- **증분 #3 (후속 sprint)**: 대시보드 Event Detail Drawer에 in-app markdown viewer로 해당 앵커 섹션 즉시 표시. `frontend/` 신규 컴포넌트 필요.

증분 #3이 완료되면 대시보드에서 이 앵커를 직접 렌더링하도록 본 섹션을 추가 갱신합니다.
