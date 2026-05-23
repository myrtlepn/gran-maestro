---
name: "off"
description: "Maestro 모드를 비활성화합니다. 사용자가 '마에스트로 꺼', '지휘자 모드 끝'을 말하거나 /mst:off를 호출할 때 사용. 요청 취소에는 /mst:cancel을 사용."
user-invocable: true
argument-hint: "[--force]"
---

# maestro:off

Gran Maestro 모드를 비활성화합니다.

## 실행 프로토콜

1. 플러그인 루트 경로 확인
2. `mode.json` 확인 → `active: false`이면 "이미 비활성 상태" 알림 후 종료
3. 활성 요청 존재 여부 확인 (requests/*/request.json 스캔, terminal 상태 제외)
4. 활성 요청이 있으면: `--force` 없이 경고+확인; `--force`이면 status를 `"paused"`로 업데이트
5. `mode.json` 업데이트: `active:false`, `activated_at` 유지, `deactivated_at` 현재 timestamp, `auto_deactivate:true`
6. 모드 전환 직후 현재 세션 snapshot pause 마크:
   ```bash
   SESSION_ID="${MST_SESSION_ID:?MST_SESSION_ID is required for paused snapshot mark}"
   python3 {PLUGIN_ROOT}/scripts/mst.py state mark-paused --session-id "$SESSION_ID" >/dev/null 2>&1 || true
   PAUSED_COUNT="$(python3 {PLUGIN_ROOT}/scripts/mst.py state paused-count --session-id "$SESSION_ID" 2>/dev/null || printf '0')"
   case "$PAUSED_COUNT" in ''|*[!0-9]*) PAUSED_COUNT=0 ;; esac
   echo "진행 중 체인 ${PAUSED_COUNT}건 일시 정지. /mst:on으로 재개하세요."
   ```

## 자동 비활성화

`auto_deactivate: true`이고 모든 요청이 terminal 상태(`done`/`completed`/`cancelled`/`failed`)이면 자동 비활성화됩니다. 수동 호출 불필요.

## 옵션

- `--force`: 활성 요청이 있어도 강제로 비활성화

## 출력/경고

비활성화 완료 시: "Gran Maestro 모드가 비활성화되었습니다."
진행 중 snapshot pause 마크 후: "진행 중 체인 N건 일시 정지. /mst:on으로 재개하세요." Paused snapshot state commands inherit the canonical `MST_SESSION_ID` structured context.
활성 요청 존재 시: 요청 목록 표시 + "계속하시겠습니까? `/mst:off --force`로 강제 전환하거나 요청을 먼저 완료해주세요."

## 쉘에서 상태 확인

`~/.claude/scripts/maestro-status.sh` (mst:on 실행 시 설치): 인자 없이 실행 시 "on/off" 출력; `--json` 전체 출력; `-q` exit code만; `--field active` 특정 필드

## 문제 해결

- "이미 비활성 상태" → mode.json의 `active` 확인
- "활성 요청이 남아있음" → `--force` 강제 비활성화 또는 먼저 `/mst:cancel`/`/mst:approve`로 완료
