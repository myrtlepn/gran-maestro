---
name: resume
description: "Gran Maestro workflow queue에서 다음 액션 하나를 pop하여 실행하는 단일 재진입 진입점. mst-loop wrapper에서 claude -p /mst:resume 한 줄로 호출됨. queue가 비어 있으면 즉시 종료."
user-invocable: false
argument-hint: ""
---

# maestro:resume

**목적**: `.gran-maestro/pending.ndjson` queue에서 다음 action을 하나 pop하여 해당 스킬을 호출한다. 외부 wrapper(`scripts/mst-loop.sh`) 또는 `claude -p "/mst:resume"` 한 줄로 재진입할 수 있는 **단일 진입점**. 세션 교차/재진입/동시 세션에서 디스크 상태(queue)만 보고 다음 action을 결정한다.

## Gate

### Entry

- `.gran-maestro/pending.ndjson` queue에서 정확히 **한 개**의 action만 pop하여 실행한다.
- AUTO_MODE 판정은 queue entry의 `auto` 필드와 `args` 내 `-a` 플래그를 그대로 사용한다. 재판단 금지.

### 경로 우선순위 (MANDATORY)

resume 경로는 **queue entry를 SSoT**로 사용합니다. plan.json 또는 tmp/mst-state-{PPID}.json의 `next_action.auto_mode` 등을 fallback으로 읽어 args를 재조합하지 **않습니다**. 자율 모드 의도는 enqueue 시점에 queue entry의 `auto` 필드와 `args` 내 `-a` 토큰으로 함께 표현되어야 하며, 이 불변 계약은 `scripts/mst_cmds/_common.py::queue_enqueue`가 강제합니다 (REQ-639 T01 참조).

### Exit

- 한 action의 Skill 호출이 완료되면 `complete` 또는 `fail`로 queue 상태를 확정한 뒤 **정상 종료**한다.
- queue가 비어있으면 "queue empty" 메시지 출력 후 즉시 종료.
- 한 iteration에서 2개 이상의 action을 pop하지 않는다 (mst-loop wrapper가 다음 iteration을 담당).

### 금지 패턴

- queue peek 없이 추측으로 action 선택
- complete/fail 없이 다음 iteration 진입
- Skill 호출 없이 queue만 비우는 동작
- queue entry의 `args`를 수정/재조합하여 Skill 호출

## Anti-Rationalization Checklist

- 합리화 패턴: "큐에 action 2개가 있으니 한 번에 다 처리하자." | 확인 증거: 한 iteration에서 `queue pop` 호출은 정확히 1회.
- 합리화 패턴: "auto 필드가 true인데 args에 -a가 없어 보여 내가 붙이자." | 확인 증거: args를 원본 그대로 전달한다. enqueue 시점에 -a 포함이 호출측 책임.
- 합리화 패턴: "complete가 귀찮으니 pop만 하고 끝내자." | 확인 증거: 각 iteration의 실행 로그에 complete 또는 fail 명령 호출이 존재.

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

### Step 1/5: 큐 확인 (peek)

현재 큐의 머리 entry를 확인한다. 상태를 변경하지 않는다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py queue peek --json
```

- 출력이 `null` 또는 빈 객체: "queue empty — nothing to resume" 알림 후 **즉시 종료** (정상 exit).
- 출력이 JSON entry: 다음 Step 진행. 메모리에 `action = {id, skill, args, source_skill, source_id, auto, resource_id, ...}` 보관.

### Step 2/5: 큐 Pop (큐 머리 entry를 running으로 전이)

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py queue pop --json
```

- 반환 entry 확인. status가 `running`으로 전이되고 `consumed_at` 기록됨.
- Step 1에서 peek한 entry와 `id`가 일치하는지 확인. 일치하지 않으면 (다른 세션이 중간에 pop) warn 출력 후 재진입 권장 종료.
- 일치하면 다음 Step 진행.

### Step 3/5: Skill 호출

`action.skill` 필드에 해당하는 Skill 도구를 호출한다. **args는 원본 그대로 전달한다** (재조합/수정 금지).

```
Skill(skill: "{action.skill}", args: "{action.args}")
```

예시:
- `action.skill == "mst:request"` → `Skill(skill: "mst:request", args: "--plan PLN-437 -a")`
- `action.skill == "mst:approve"` → `Skill(skill: "mst:approve", args: "-a REQ-584")`
- `action.skill == "mst:agile"` → `Skill(skill: "mst:agile", args: "--resume AGI-010 -a")`

**AUTO_MODE / `-a` 전파 규칙**:
- queue entry의 `auto: true`이면 `args`에 `-a` 또는 `--auto`가 이미 포함되어 있어야 한다 (enqueue 시점에 호출측이 기록).
- resume은 `auto` 필드를 재판단하거나 `args`에 `-a`를 추가하지 않는다 — 원본 그대로 전달한다.
- 호출된 하위 스킬이 `args`의 `-a`를 감지하여 AUTO_MODE를 활성화한다 (기존 스킬 프로토콜 그대로).
- 이로써 "-a가 스킬 경계에서 흐려지는" 문제를 해결한다: queue에 한 번만 기록하면 이후 pop/호출에서도 유지된다.

### Step 4/5: 완료 기록 (complete | fail)

Step 3의 Skill 호출 결과를 기준으로 queue 상태를 확정한다.

**성공 시**:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py queue complete --id {action.id} --result "ok" --json
```

**실패 시** (Skill 호출 중 예외 또는 하위 스킬이 명시적 실패 반환):
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py queue fail --id {action.id} --error "{요약 메시지}" --json
```

- complete/fail 중 하나는 **반드시** 호출한다. 생략 시 entry가 영구 `running` 상태로 남아 다음 iteration이 처리할 수 없다.
- 중복 complete/fail은 no-op + warn이므로 안전하다 (queue 서브커맨드의 멱등성).

### Step 5/5: Exit

- 한 iteration 종료. 다음 action은 wrapper의 다음 iteration에서 처리한다.
- "한 iteration = 한 action" 원칙. 루프 내부에서 여러 action을 처리하지 않는다.
- 종료 메시지 예시: `[resume] completed action {id} ({action.skill})` 또는 `[resume] failed action {id}: {error}`

## 예시: mst-loop wrapper에서 호출

```bash
# 무한 루프 (wrapper가 queue count=0 감지 시 break)
bash scripts/mst-loop.sh

# 또는 사용자가 직접 한 번만 호출
claude --dangerously-skip-permissions -p "/mst:resume"
```

## 현재 제한사항 (Phase 1+2 스코프)

- **Lease 없음 (Phase 3 예정)**: 동일 리소스(AGI/REQ/PLN)에 대한 동시 pop이 race condition을 일으킬 수 있다. 현재는 사용자가 수동으로 중복 실행을 피해야 한다. `fcntl.flock`으로 queue 파일 자체의 원자성은 보장되지만, "동일 REQ에 대해 두 세션이 각각 pop해서 동시 실행" 같은 도메인 레벨 직렬화는 Phase 3에서 lease manager로 해결 예정.
- **Outbox 없음 (Phase 4 예정)**: 백그라운드 codex/gemini dispatch 중 세션 크래시 시 재진입 복원이 불완전할 수 있다. 현재는 각 Skill 호출이 단일 iteration 내에서 동기적으로 완료되는 경로만 안전하게 재진입 가능.
- **POSIX 파일시스템 가정**: `fcntl.flock`은 로컬 파일시스템에서만 안정. NFS/네트워크 FS는 미지원.
- **인라인 체이닝과 공존**: 기존 스킬들의 인라인 `Skill()` 체이닝은 그대로 작동한다. queue + resume은 **외부 재진입 경로**이며 인라인 경로를 대체하지 않는다.
