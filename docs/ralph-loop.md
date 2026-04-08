# Ralph Loop — Gran Maestro 외부 재진입 실행

Gran Maestro의 워크플로우를 **세션 외부에서 반복 호출**로 이어갈 수 있는 경로입니다. 인라인 Skill 체이닝이 세션 경계·프로세스·동시성 문제로 끊길 때, disk를 single source of truth로 사용해 어떤 세션에서 들어와도 다음 액션을 결정론적으로 수행합니다.

## 인라인 체이닝 vs ralph-loop

| 구분 | 인라인 체이닝 (기본) | ralph-loop (외부 재진입) |
|---|---|---|
| 실행 단위 | 세션 내부 연속 호출 | `claude -p /mst:resume` 반복 호출 |
| 상태 | 메모리 + PPID 임시 파일 | `.gran-maestro/pending.ndjson` (FIFO) |
| 세션 교차 | 불가 — 동일 세션 내에서만 | 가능 — 다른 세션에서 이어가기 |
| 크래시 복구 | 세션 재시작 시 일부 상실 | queue 기반 완전 복구 |
| 동시 실행 | 중복 위험 | lease로 직렬화 (Phase 3 예정) |
| 장점 | 빠름, 컨텍스트 공유 | 결정론, 외부 제어, ralph 철학 |
| 단점 | 세션 제약 | 매 iteration 시작 비용 |
| 권장 | 기본 워크플로우 | 장시간 루프, 배치, 재개, 백그라운드 |

**하이브리드 권장**: 기본은 인라인 체이닝. ralph-loop는 "세션 밖에서 이어가야 할 때"만 사용.

## 실행 예시

### 기본 호출

```bash
# 기본: 100 iteration, iteration 사이 3초 sleep
bash scripts/ralph-loop.sh

# 최대 20번만, 5초 sleep
bash scripts/ralph-loop.sh --max-iterations 20 --sleep 5

# dry-run (실제 claude 호출 없이 시뮬레이션)
bash scripts/ralph-loop.sh --dry-run

# 도움말
bash scripts/ralph-loop.sh --help
```

### 환경 변수

```bash
# PLUGIN_ROOT 커스터마이징 (기본: $HOME/.claude/plugins/marketplaces/gran-maestro)
PLUGIN_ROOT=/custom/path bash scripts/ralph-loop.sh
```

### 작동 원리

1. `mst.py queue count` → 0이면 즉시 exit
2. `claude --dangerously-skip-permissions -p "/mst:resume"` 호출
3. `/mst:resume` 스킬이 queue에서 한 action을 pop하여 해당 Skill을 호출
4. Skill 완료 후 complete/fail 기록, iteration 종료
5. wrapper가 sleep 후 다음 iteration 시작

## Queue 수동 관리

queue는 `scripts/mst.py queue` 서브커맨드로 직접 조작할 수 있습니다.

```bash
# enqueue — 새 action을 큐에 추가
python3 scripts/mst.py queue enqueue \
    --skill mst:request \
    --args "--plan PLN-437 -a" \
    --source-skill mst:plan \
    --source-id PLN-437 \
    --auto true \
    --json

# peek — 큐의 머리 entry 조회 (상태 변경 없음)
python3 scripts/mst.py queue peek --json

# list — 상태별 entry 목록
python3 scripts/mst.py queue list --status queued --json
python3 scripts/mst.py queue list --status running --json
python3 scripts/mst.py queue list --status done --json
python3 scripts/mst.py queue list --status failed --json
python3 scripts/mst.py queue list --status all --json

# count — 상태별 개수 (status 미지정 시 queued)
python3 scripts/mst.py queue count
python3 scripts/mst.py queue count --status done

# pop — 머리 entry를 running으로 전이 (수동 사용은 보통 /mst:resume이 담당)
python3 scripts/mst.py queue pop --json

# complete — running entry를 done으로 전이
python3 scripts/mst.py queue complete --id <action-id> --result "ok" --json

# fail — running entry를 failed로 전이
python3 scripts/mst.py queue fail --id <action-id> --error "문제 요약" --json
```

### 수동 enqueue 예시 — 다음에 실행할 액션 예약

```bash
# 세션 A에서 plan을 만들고 세션 B에서 이어가기 위해 queue에 적재
python3 scripts/mst.py queue enqueue \
    --skill mst:request \
    --args "--plan PLN-437 -a" \
    --auto true \
    --json

# 이후 세션 B에서 ralph-loop 실행하면 자동으로 pop되어 실행됨
bash scripts/ralph-loop.sh
```

### state set-workflow + queue 동시 기록 (선택)

기존 `workflow_state.next_action`은 유지되며, `--enqueue` 플래그를 추가하면 queue에도 동일 action을 적재할 수 있습니다 (기본 OFF):

```bash
python3 scripts/mst.py state set-workflow \
    --active true \
    --skill mst:plan \
    --next-skill mst:request \
    --next-source PLN-437 \
    --auto true \
    --enqueue true
```

## 현재 제한사항 (Phase 1+2 스코프)

본 기능은 단계적 도입의 Phase 1(Queue 인프라) + Phase 2(resume + wrapper)만 포함합니다. 다음 항목은 후속 plan에서 추가됩니다.

### Phase 3 예정: Lease Manager

현재는 queue 파일 자체의 원자성은 보장되지만, **동일 리소스에 대한 도메인 레벨 직렬화**는 없습니다. 예를 들어 세션 A와 세션 B가 동시에 ralph-loop를 실행하면 각자 다른 action을 pop하지만, 같은 REQ/AGI에 대한 작업이면 git/파일 충돌이 날 수 있습니다.

**우회 방법 (현재)**: 한 리소스(같은 AGI/REQ/PLN)에 대해서는 한 번에 하나의 ralph-loop만 실행하세요.

### Phase 4 예정: Outbox 패턴 + Event log

백그라운드 codex/gemini dispatch 중 세션 크래시 시 재진입 복원이 불완전할 수 있습니다. 현재는 각 Skill 호출이 iteration 내에서 동기 완료되는 경로만 안전합니다.

### 기타 제한사항

- **POSIX 파일시스템 가정**: `fcntl.flock`은 로컬 파일시스템에서만 안정적입니다. NFS/네트워크 파일시스템은 지원하지 않습니다.
- **인라인 체이닝과 공존**: 기존 스킬들의 인라인 `Skill()` 호출 체인은 그대로 작동합니다. queue + resume은 **외부 재진입 경로**이며 인라인 경로를 대체하지 않습니다.
- **한 iteration = 한 action**: `/mst:resume`은 한 번 호출에 한 action만 처리합니다. wrapper의 loop에서 다음 iteration을 담당합니다.
- **Python 3.10+**: queue 인프라는 Python 3.10 이상이 필요합니다 (type hints).
- **bash 3.2+**: wrapper는 `#!/usr/bin/env bash`이므로 macOS 기본 bash도 호환됩니다.

## 관련 파일

- `scripts/mst.py` — `queue` 서브커맨드 그룹 (enqueue/peek/pop/list/complete/fail/count)
- `.gran-maestro/pending.ndjson` — queue 파일 (append-only NDJSON)
- `skills/resume/SKILL.md` — `/mst:resume` 스킬 정의
- `scripts/ralph-loop.sh` — 외부 wrapper 스크립트
- `tests/test_queue.py` — queue 단위 테스트 (9건)
- `tests/test_resume_skill.py` — resume + queue 통합 테스트

## 로드맵

- **Phase 1** (완료): Intent Queue 인프라 — `mst.py queue` 서브커맨드 + NDJSON + fcntl 락
- **Phase 2** (완료): `/mst:resume` 스킬 + `scripts/ralph-loop.sh` + 이 문서
- **Phase 3** (예정): Lease manager — `.gran-maestro/locks/{resource}.lease` 기반 동시성 직렬화
- **Phase 4** (예정): Outbox 패턴 + 전역 event log + stop-hook queue 우선 drain
