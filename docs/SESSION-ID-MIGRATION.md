# Session ID Migration Plan (Gran Maestro)

## 1. Context (MST_SESSION_ID canonical 전환)

AGI-030 DOD-001 이후 신규 사용자와 신규 hook/statusline 예시는 `MST_SESSION_ID` / `mst_session_id`를 canonical session identity로 사용한다. `MST_STATE_PPID`와 `MST_SNAPSHOT_SESSION_ID`는 0.60.x에서만 읽히는 deprecated alias이며, legacy compatibility 문맥에서 기존 상태를 읽거나 migration 안내를 출력하기 위해 남아 있다.

Gran Maestro의 기존 owner 식별은 OS 프로세스 계층의 PPID를 중심으로 동작했다. 이 모델은 단일 터미널에서 짧게 실행되는 세션에는 충분하지만, Claude Code 대화의 의미론적 수명과 일치하지 않는다. AGI-018의 DOD-013/018/019/020은 이 불일치를 줄이기 위해 Claude hook 값과 durable ownership 값을 함께 기록하려던 historical migration plan이다. AGI-030 DOD-001에서는 이 계획을 canonical identity contract로 해석하지 않는다.

첫 번째 한계는 `claude --resume {uuid}` 시나리오다. 사용자가 동일 Claude Code 대화 UUID를 resume하더라도 새 프로세스 트리로 부트되면 PPID가 바뀐다. 기존 snapshot이나 request/plan JSON에 저장된 `owner_ppid`는 새 PPID와 불일치하므로 같은 대화의 자연 복구가 외부 세션처럼 보일 수 있다. DOD-001에서는 이런 값이 새 상태머신의 canonical source, fallback, path partition, or equality input이 될 수 없고 diagnostic-only evidence로만 남는다.

두 번째 한계는 수동 백업 복원 또는 레포 병합이다. PPID는 로컬 OS에서 짧게 재사용될 수 있고, 다른 시점의 `.gran-maestro/state/{ppid}` 또는 durable JSON이 같은 숫자 범위에 들어올 수 있다. 현재 PPID 중심 모델에는 snapshot `created_at`, transcript 시작 시각, UUID 형식 검증을 함께 사용해 "같은 UUID처럼 보이지만 실제 세션이 아닌" 충돌을 탐지하는 정책이 충분히 명세되어 있지 않다.

세 번째 한계는 `transcript_path` 기반 legacy session diagnostic의 계약이 명확하지 않다는 점이다. Claude Code hook stdin JSON에 diagnostic 값이 들어오지 않는 환경에서도 transcript 파일명이 UUID인 경우가 있으나, 이를 canonical 값으로 승격하면 세션 재개 중 snapshot이 잘못 선택될 수 있다. DOD-001에서는 실패 시 관찰 가능한 진단 이벤트를 남기되 새 `mst_session_id`를 만들거나 기존 state partition을 선택하지 않는다.

## 2. 현재 PPID 사용 지점

아래 표는 `rg -n "owner_ppid" hooks/ scripts/`, `rg -n "os\.getpid\(\)" scripts/`, `rg -n "transcript_path" hooks/ scripts/`, `rg -n "session_id" hooks/ scripts/` 및 주변 코드 확인 결과를 기반으로 작성했다. 라인은 이 worktree 기준이다.

| 파일:라인 | 함수/변수 | 맥락 |
|-----------|-----------|------|
| `hooks/mst-pre-tool-use.sh:181` | `payload.get("owner_ppid")` | pre-tool-use hook의 boundary payload 출력에서 owner PPID를 tab 필드로 전달한다. |
| `hooks/mst-stop-hook.sh:999` | `read_owner_ppid_field()` | stop-hook이 request/plan JSON에서 legacy `owner_ppid`를 읽는 helper 함수다. |
| `hooks/mst-stop-hook.sh:1018` | `owner_ppid = payload.get("owner_ppid")` | snapshot/status JSON 파싱 중 `owner_ppid` 필드를 정수로 강제 변환한다. |
| `hooks/mst-stop-hook.sh:1127` | Legacy compatibility 주석 | request JSON에 `owner_session_id`가 없을 때 `owner_ppid`만 있는 파일을 warning과 함께 진단한다. |
| `hooks/mst-stop-hook.sh:1137` | `owner_ppid_value = "$PPID"` 비교 | non-terminal request의 historical owner branch이며 DOD-001 canonical equality input이 아니다. |
| `hooks/mst-stop-hook.sh:1188` | Legacy compatibility 주석 | plan JSON에도 request와 동일한 `owner_ppid` only 진단 경로가 남아 있다. |
| `hooks/mst-stop-hook.sh:1198` | `owner_ppid_value = "$PPID"` 비교 | non-terminal plan의 historical owner branch이며 DOD-001 canonical equality input이 아니다. |
| `hooks/mst-stop-hook.sh:1395` | `payload.get("owner_ppid")` | stop-hook 내부 boundary payload 출력에서도 owner PPID를 하위 판정으로 전달한다. |
| `hooks/mst-stop-hook.sh:1425` | `owner_ppid = data.get("owner_ppid")` | boundary 판단 입력에서 `owner_ppid`를 읽어 current PPID와 비교할 준비를 한다. |
| `hooks/mst-stop-hook.sh:1553` | `session_mismatch ppid=%s owner=%s` | boundary exit 단계에서 current PPID와 owner PPID 불일치 시 enforcement를 건너뛴다. |
| `scripts/mst_cmds/_common.py:191` | `MST_STATE_PPID` / `os.getppid()` | deprecated alias compatibility only: skill state base 탐색 시 기존 PPID 기반 session 디렉토리를 읽는다. |
| `scripts/mst_cmds/_common.py:385` | `is_pid_alive(state_pid)` | stale state 파일을 검사할 때 PID liveness를 사용해 현재 실행 가능한 next action인지 판단한다. |
| `scripts/mst_cmds/state.py:35` | `_resolve_owner_ppid()` | deprecated alias compatibility only: owner metadata의 legacy `owner_ppid` 보강에만 사용한다. |
| `scripts/mst_cmds/state.py:42` | `_snapshot_session_id()` | `MST_SESSION_ID`가 canonical이며, `MST_SNAPSHOT_SESSION_ID`/`MST_STATE_PPID`는 deprecated alias compatibility only 진단 값이다. |
| `scripts/mst_cmds/state.py:124` | `data["owner_ppid"] = ppid` | request/plan JSON에 `owner_ppid`가 없으면 현재 PPID를 보강 기록한다. |
| `scripts/mst_cmds/worktree.py:1136` | `_coerce_int(request_data.get("owner_ppid"))` | worktree boundary 검사에서 request owner PPID와 current PPID를 비교한다. |

참고로 `hooks/mst-stop-hook.sh:401`의 `resolve_timeout_session_id()`, `scripts/_snapshot_probe.py:40`의 `resolve_session_id()`, `scripts/_snapshot_probe.py:30`의 `transcript_path` basename 추출, `scripts/mst_cmds/state.py:98`의 `_resolve_owner_session_id()`처럼 legacy compatibility 경로가 이미 일부 존재한다. DOD-001 검증에서는 이 경로들이 canonical field, file partition, fallback source, 또는 equality comparison input으로 쓰이면 실패다.

## 3. Legacy session diagnostic 경로

1차 diagnostic 경로는 Claude Code hook stdin JSON의 `session_id` 필드다. hook은 stdin payload를 JSON으로 파싱하고, 값이 비어 있지 않은 문자열이면 hook boundary evidence의 `claude_session_id`로 기록할 수 있다. 예시는 `{"session_id":"123e4567-e89b-42d3-a456-426614174000","transcript_path":"/path/to/123e4567-e89b-42d3-a456-426614174000.jsonl"}` 형태다. 이 값은 `.gran-maestro/state/{mst_session_id}/snapshot.json` 선택에 사용하지 않는다.

2차 diagnostic 경로는 transcript basename에서 UUID처럼 보이는 값을 관찰하는 방식이다. 예를 들어 `/Users/me/.claude/projects/x/123e4567-e89b-42d3-a456-426614174000.jsonl`이 들어오면 basename의 `.jsonl` suffix를 제거해 진단 값으로 기록할 수 있다. 이 값은 hook stdin의 diagnostic 값이 없을 때 원인 파악을 돕는 보조 evidence이며 canonical `mst_session_id`를 대체하지 않는다.

3차 diagnostic 경로는 `MST_SESSION_ID`가 없고 hook/transcript 진단 값도 신뢰할 수 없는 경우다. 마이그레이션 공존 기간에는 `session_id_invalid` 또는 `session_id_resolution_failed` warning을 남긴다. mutating path는 이 상황에서 새 canonical ID를 만들지 않고 fail-closed해야 하며, inspect-only path만 mutation 없이 failure diagnostic을 반환할 수 있다.

## 4. 전환 단계 (Phase 1~5)

Phase 1은 historical 공존 단계다. snapshot과 durable request/plan JSON에 `owner_ppid`와 `owner_session_id`를 모두 기록한다. 검증은 기존 PPID 진단을 유지하고, `owner_session_id`는 로그와 진단에만 보조적으로 사용한다. 이 단계의 목적은 동작 변경 없이 실제 hook stdin의 diagnostic 확보율과 transcript diagnostic 성공률을 관찰하는 것이다.

Phase 2는 historical 검증 단계다. `mst-pre-tool-use.sh`와 `mst-stop-hook.sh`에서 현재 hook stdin의 diagnostic, snapshot diagnostic, durable resource의 `owner_session_id` 일치 여부를 비교하되 동작은 바꾸지 않는다. mismatch가 있으면 stderr와 `flow-detail.ndjson`에 warning을 기록한다. 이 단계에서 PPID와 diagnostic 판정 결과가 갈리는 실제 케이스를 수집한다.

Phase 3은 historical 전환 단계다. owner 검증의 우선순위를 diagnostic UUID로 바꾸려던 계획이었으나, AGI-030 DOD-001에서는 `mst_session_id`만 state partition을 고른다. UUID v4 검증 실패는 `session_id_invalid`, snapshot의 `created_at`과 transcript 시작 시각 delta가 비정상인 경우는 `session_id_mismatch_suspected` 이벤트로 기록한다.

Phase 4는 마이그레이션 CLI 단계다. `mst.py state migrate` 또는 동등한 CLI가 기존 snapshot에 diagnostic 값이 없을 때 transcript 추적, bridge file, 사용자 안내를 통해 `owner_session_id`를 채운다. 실행 중에는 `.gran-maestro/state/.MIGRATING` sentinel을 만들고, 중단 후에는 `--resume`으로 이어가거나 `--rollback`으로 Phase N에서 N-1 상태로 되돌릴 수 있어야 한다.

Phase 5는 PPID 제거 단계다. owner 판정용 `owner_ppid` 필드와 관련 helper, PID liveness 기반 stale 판단을 제거한다. PPID는 hook failure, debug, audit log에만 보조 정보로 남길 수 있다. 각 Phase는 독립 Sprint 단위로 완료 가능해야 하며, 이전 Phase 산출물을 되돌릴 수 있는 rollback 지점이 있어야 한다.

## 5. UUID v4 검증 정책

Legacy Claude session diagnostic은 UUID v4 lowercase string일 때만 신뢰 가능한 진단 값으로 취급한다. 마이그레이션 최종 정책의 정규식은 다음 원문을 사용한다.

```text
^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$
```

검증 순서는 hook stdin의 diagnostic 값을 먼저 검사하고, 실패하면 `session_id_invalid` 이벤트를 기록한 뒤 transcript basename도 진단 evidence로만 검사한다. basename도 UUID v4 정책을 통과하지 못하면 공존 기간에는 deprecated PPID branch 사용 사실을 stderr와 `flow-detail.ndjson`에 남긴다. DOD-001 mutating path는 이 branch를 canonical source로 사용하지 않는다.

UUID 충돌 또는 잘못 복원된 snapshot 감지는 시간 정보로 보강한다. snapshot에는 `created_at`을 기록하고, Layer 2 진입 전에 transcript 시작 시각과 비교한다. delta가 음수이거나 24시간 이상이면 같은 UUID처럼 보이는 파일이라도 현재 대화의 snapshot으로 신뢰하지 않는다. 이 경우 `session_id_mismatch_suspected` 이벤트를 기록하고 기존 snapshot을 `state/{uuid}/snapshot.stale-{ts}.json`으로 격리한 뒤, durable state 기반 복구 또는 사용자 안내 경로로 전환한다.

## 6. 리스크·롤백 전략

마이그레이션 중 SIGINT 또는 프로세스 종료가 발생하면 `.gran-maestro/state/.MIGRATING` sentinel이 남아야 한다. `hooks doctor`는 이 sentinel을 unclean 상태로 진단하고, 사용자가 `--resume` 또는 `--rollback` 중 하나를 선택하도록 안내한다. sentinel에는 시작 시각, 대상 Phase, backup 경로, 마지막 완료 단계가 들어가야 한다.

Legacy 경로와 신 경로가 혼재할 위험은 Phase별 rollback으로 다룬다. `--rollback`은 Phase N의 파일 스키마와 디렉토리 이동을 Phase N-1 상태로 되돌리고, `--resume`은 sentinel과 migration log를 읽어 이미 완료된 원자 작업을 건너뛴다. rollback은 `.gran-maestro/backups/state-migrate-{ts}/` 백업을 우선 사용하고, 백업이 없으면 변경된 파일을 건드리지 않고 진단만 출력한다.

Takeover storm은 DOD-019의 핵심 위험이다. `takeover_log`에서 5분 내 동일 AGI에 대해 양방향 takeover가 2회 이상 발생하면 `takeover_storm` 이벤트를 기록하고, 해당 durable resource에 대한 mutation을 차단한다. 대시보드는 글로벌 배너와 owner pill을 통해 사용자가 어떤 세션들이 ownership을 주고받고 있는지 확인하게 해야 한다.

손상 snapshot은 복구 가능한 durable state와 분리한다. JSON parse 실패, 필수 필드 누락, UUID/time 검증 실패가 발생하면 원본을 `.gran-maestro/backups/corrupt-{ts}/`로 격리한다. 이후 `/mst:recover`는 objective, request/plan JSON, checkpoint, flow log 같은 durable state만으로 새 `state/{current_session_id}/snapshot.json`을 부분 재구성하고, "잃은 컨텍스트" 요약을 사용자에게 보여준다.

## 7. 후속 Sprint 분해 예시

Sprint N+1은 Phase 1 공존 구현이다. snapshot과 request/plan JSON에 `owner_session_id` 필드를 추가하되 검증은 PPID diagnostic을 유지한다. 사용자 관찰 변화는 `jq '.owner_session_id' .gran-maestro/requests/*/request.json` 실행 시 UUID 또는 `null` 필드가 존재하는 것이다.

Sprint N+2는 Phase 2 검증 로그 구현이다. `mst-pre-tool-use.sh`와 `mst-stop-hook.sh`가 현재 stdin session_id, snapshot session id, durable `owner_session_id`를 비교하고 mismatch warning을 한 줄 기록한다. 사용자 관찰 변화는 hook 실행 시 stderr 또는 `flow-detail.ndjson`에 session_id 비교 로그가 남는 것이다.

Sprint N+3은 Phase 3 historical diagnostic 검증 구현이다. owner 판정은 diagnostic UUID 비교를 먼저 보려던 계획이었으나, AGI-030 이후 새 write path는 `mst_session_id` 계약을 따른다. 사용자 관찰 변화는 UUID 형식 실패 시 `session_id_invalid` 이벤트가 보이는 것이다.

Sprint N+4는 Phase 3 stale snapshot 격리 구현이다. snapshot `created_at`과 transcript 시작 시각 delta를 검사하고, 음수 또는 24시간 이상이면 `session_id_mismatch_suspected`를 기록한다. 사용자 관찰 변화는 잘못 복원된 snapshot이 `state/{uuid}/snapshot.stale-{ts}.json`으로 이동하고 hook이 silent drop 대신 진단을 출력하는 것이다.

Sprint N+5는 Phase 4 마이그레이션 CLI 구현이다. `mst.py state migrate --dry-run|--resume|--rollback`을 제공하고 `.gran-maestro/state/.MIGRATING` sentinel을 사용한다. 사용자 관찰 변화는 legacy snapshot이 있으면 `/mst:on` 또는 doctor에서 migration 안내가 뜨고, 1회 명령으로 session_id 기반 경로로 이동하는 것이다.

Sprint N+6은 Phase 4 recover/takeover 보강이다. 손상 snapshot 격리, durable state 기반 부분 복구, `takeover_log` storm 감지를 연결한다. 사용자 관찰 변화는 `/mst:recover --rewind-to {skill}/{step}` 또는 대시보드 "rewind to here"가 새 session_id snapshot을 만들고, storm 상황에서는 mutation이 차단되는 것이다.

Sprint N+7은 Phase 5 PPID owner 제거다. owner 판정 helper에서 `owner_ppid`와 `is_pid_alive(state_pid)` 의존을 제거하고, PPID는 debug/audit log 보조 필드로만 남긴다. 사용자 관찰 변화는 새 request/plan JSON에 owner 판정 필드로 `owner_session_id`만 필요하며, PPID 불일치 때문에 resume/recover가 막히지 않는 것이다.


## 8. 0.61.0 legacy alias removal readiness

- Legacy alias list: `MST_STATE_PPID`, `MST_SNAPSHOT_SESSION_ID`. Both are deprecated aliases for compatibility only; new user docs and examples must use `MST_SESSION_ID`.
- Allowed residual locations during 0.60.x: `scripts/mst_cmds/env_alias_compat.py`, `scripts/mst_cmds/hooks.py` doctor reporting, `scripts/mst_cmds/state.py` and `_common.py` compatibility fallbacks, `scripts/_flow_logger.py`, `scripts/mst-statusline.sh`, `hooks/mst-auto-chain-context.sh`, `hooks/lib/pre_tool_use_fast.py`, and compatibility tests.
- Remove in 0.61.0: env alias fallback helper/warning marker in `env_alias_compat.py`, direct-alias allowlist entries in `tests/test_env_alias_compatibility.py`, doctor legacy-env-alias report branch, runtime compatibility fallback reads in hooks/statusline/state helpers, and these deprecated alias documentation notes.
- Doctor token contract until removal: when either deprecated alias is present, output includes `legacy-env-alias`, `MST_SESSION_ID`, `deprecated`, and `migration`.
