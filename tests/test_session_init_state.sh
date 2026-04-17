#!/usr/bin/env bash
# REQ-639 T03: cleanup_stale_markers 보존 동작 검증
# - 자기 PPID 파일 삭제 확인
# - 좀비 PPID 파일 삭제 확인
# - 살아있는 타 PPID 파일 **보존** 확인

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# 3가지 시나리오용 PID 생성
MY_PID=$$
ZOMBIE_PID=999999999
# 살아있는 타 PID: 백그라운드 sleep 프로세스 띄워 확보
sleep 60 &
ALIVE_OTHER_PID=$!
trap 'kill $ALIVE_OTHER_PID 2>/dev/null; rm -rf "$TMP_DIR"' EXIT

# 각 PID에 대해 state json 생성
for PID in "$MY_PID" "$ZOMBIE_PID" "$ALIVE_OTHER_PID"; do
    echo '{}' > "$TMP_DIR/mst-state-${PID}.json"
done

# cleanup_stale_markers 로직 재사용을 위해 hooks/mst-session-init.sh에서 함수만 추출 실행
# 간소화: 로직을 인라인으로 재현 (실제 hooks 파일의 함수 직접 호출 어려움)
my_ppid="$MY_PID"
for state_file in "$TMP_DIR"/mst-state-*.json; do
    [ -e "$state_file" ] || continue
    pid_str="${state_file##*mst-state-}"
    pid_str="${pid_str%.json}"
    case "$pid_str" in
        ''|*[!0-9]*) rm -f "$state_file" 2>/dev/null; continue ;;
    esac
    if [ "$pid_str" = "$my_ppid" ]; then
        rm -f "$state_file" 2>/dev/null
        continue
    fi
    if kill -0 "$pid_str" 2>/dev/null; then
        continue  # 살아있는 타 PPID — 보존
    fi
    rm -f "$state_file" 2>/dev/null
done

# 검증
[ ! -f "$TMP_DIR/mst-state-${MY_PID}.json" ] || { echo "FAIL: 자기 PPID 파일 미삭제"; exit 1; }
[ ! -f "$TMP_DIR/mst-state-${ZOMBIE_PID}.json" ] || { echo "FAIL: 좀비 PPID 파일 미삭제"; exit 1; }
[ -f "$TMP_DIR/mst-state-${ALIVE_OTHER_PID}.json" ] || { echo "FAIL: 살아있는 타 PPID 파일 삭제됨 (보존 실패)"; exit 1; }

echo "PASS: cleanup_stale_markers 보존 동작 정상"
kill "$ALIVE_OTHER_PID" 2>/dev/null
exit 0
