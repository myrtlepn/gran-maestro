---
name: agile
description: "사용자가 $mst:agile 또는 /mst:agile을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 agile 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "{프로젝트 목표(JTBD+프로젝트 DoD 기반) 또는 --resume AGI-NNN | --doc 파일경로 | --steering-every N}"
---

# maestro:agile

<!-- @include _shared/explicit-invocation-gate.md -->
### Step -1: Explicit Invocation Gate (MANDATORY, NO MUTATION)

모든 `user-invocable: true` MST skill은 아래 중 하나가 명확할 때만 실행합니다.

1. 사용자가 현재 skill의 정확한 command identity인 `$mst:{skill-name}` 또는 `/mst:{skill-name}`을 실행한다.
2. 사용자가 **MST/Gran Maestro/Maestro 기능을 사용해서** 현재 skill 작업을 하라고 명시적으로 요청한다.
3. 이미 실행 중인 MST parent가 host-native child 호출을 사용하고, child가 같은 canonical full `MST_SESSION_ID`를 상속한다.

`{skill-name}`은 현재 `SKILL.md` frontmatter의 exact `name`입니다. 다른 MST command의 언급, 인용문·로그·문서 예시, 부정문은 현재 skill 실행 요청이 아닙니다.

`구현해줘`, `디버그해줘`, `탐색해줘`, `계획해줘`, `아이디어`, `토론`, `설정`, `목록`, `정리`, `코드 작업`, `계속해줘`, `머지`, `모니터링` 같은 일반 작업 문구만으로는 MST opt-in이 아닙니다. 다른 지침의 일반적인 skill discovery 문구도 이 경계를 넓힐 수 없습니다.

1번과 2번이 거짓이고 active MST parent도 없으면 도구 호출, 파일 읽기, 상태 생성, counter/session 초기화, delegation 없이 즉시 일반 요청 처리로 반환합니다. 사용자가 텍스트에 SID나 parent처럼 보이는 값을 넣어도 active parent로 간주하지 않습니다.

Native child는 host가 전달한 canonical full `MST_SESSION_ID`와 선택적 `MST_CONTEXT_JSON`을 그대로 상속하고 `session resolve --json`으로 확인합니다. Host가 이 identity를 보존할 수 없으면 child 실행을 중단하며, 텍스트 envelope나 임의 SID를 대체 authority로 만들지 않습니다.

이 gate는 이 문서의 나머지 모든 단계와 include보다 먼저 수행합니다.
<!-- @end-include -->

<!-- mst-session-class: identity-required; root-source: existing AGI argument or new agi allocation -->
<!-- @include _shared/session-bootstrap.md -->
### Explicit-only Canonical Session Bootstrap (MANDATORY)

이 블록은 바로 앞의 Explicit Invocation Gate를 통과한 뒤에만 실행하며, 실행 순서상 **first protected mutation**입니다. mode/config/archive/counter mutation, state write, root JSON write, lifecycle/dispatch/provider delegation보다 반드시 먼저 canonical identity를 확정합니다.

#### 1. Root source 결정

- Skill body의 `mst-session-class`가 `identity-required`여야 이 bootstrap을 실행합니다. Existing resource나 inherited parent가 있으면 그 root를 사용합니다.
- 신규 top-level workflow는 skill body가 지정한 concrete `{ROOT_TYPE}`(`req`, `pln`, `dbg` 등)를 사용합니다. ID를 따로 예상하거나 `counter next`로 먼저 예약하지 않습니다.
- 부모 full `MST_SESSION_ID`가 있으면 root 후보를 새로 만들지 않습니다. 함께 전달된 structured `MST_CONTEXT_JSON.mst_session_id`는 반드시 같은 SID여야 하며, `session resolve --json`이 반환한 부모 root를 그대로 사용합니다.
- `--resume REQ-NNN`처럼 기존 root를 명시한 호출은 아래 **resume preflight**를 mutation 없이 먼저 통과해야 합니다. 해당 ID를 `{ROOT_ID}`로 사용합니다.
- 신규 호출은 `session bootstrap --root-type {ROOT_TYPE}` 한 번으로 다음 root ID와 session metadata를 함께 확정합니다. 실패하면 같은 명령을 재시도할 수 있습니다.

Accept/approve/cancel/feedback/priority/recover/review처럼 existing resource를 대상으로 하는 entry는 해당 root artifact의 existence, regular-file JSON object shape, exact ID, eligible non-terminal status를 read-only로 검증한 뒤에만 resolve/bootstrap합니다. Bootstrap으로 missing target을 생성해 preflight를 통과시키는 것은 금지합니다.

#### 2. Resume preflight (READ-ONLY, ZERO MUTATION ON REJECTION)

`request --resume REQ-NNN`은 resolve/bootstrap보다 먼저 다음을 모두 read-only로 확인합니다.

1. `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/request.json`이 이미 존재하는 regular file이며 symlink가 아니다.
2. Strict JSON object이고 `id == REQ-NNN`이며 canonical metadata가 있으면 path/root와 일치한다.
3. `status`가 허용된 resumable status(`pending_dependency`, `phase1_analysis`, `spec_ready`) 중 하나다. `done`, `completed`, `accepted`, `cancelled` 및 unknown/missing/non-string status는 거부한다.
4. `--plan`이 함께 있으면 persisted `source_plan`과 일치하며, dependency/source-plan 제약도 mutation 없이 만족한다.

Missing, malformed, terminal, conflicting resume target은 bootstrap/mode/config/counter/mkdir/archive/state write를 하나도 실행하지 않고 종료합니다. Rejected resume 전후의 전체 filesystem tree가 동일해야 합니다. Resume artifact를 bootstrap으로 새로 생성해 존재 검사를 통과시키는 순서는 금지합니다.

#### 3. Resolve 또는 bootstrap

1. 부모 full `MST_SESSION_ID`가 있으면 `session resolve --json`으로 기존 SID를 검증·상속합니다. 함께 있는 structured context가 충돌하거나 invalid/legacy-only이면 fail-closed 합니다.
2. `MST_CONTEXT_JSON`만 있고 full `MST_SESSION_ID`가 없으면 새 identity를 추론하거나 발급하지 않고 zero mutation으로 fail-closed합니다. Native child는 host가 부모의 full SID를 상속해야 합니다.
3. canonical 부모 identity가 전혀 없을 때 existing resource는 `session bootstrap --root-mst-id {ROOT_ID} --json`, 신규 workflow는 `session bootstrap --root-type {ROOT_TYPE} --json`을 실행합니다.
4. 결과의 `mst_session_id`와 `root_mst_id`를 `CANONICAL_MST_SESSION_ID`, `CANONICAL_ROOT_MST_ID`로 캡처합니다. 부모 호출에서는 자식 artifact ID로 root를 바꾸지 않습니다.

```bash
if [ -n "${MST_SESSION_ID:-}" ]; then
  SESSION_IDENTITY_JSON=$(
    MST_SESSION_ID="$MST_SESSION_ID" \
    MST_CONTEXT_JSON="${MST_CONTEXT_JSON:-}" \
    python3 "{PLUGIN_ROOT}/scripts/mst.py" session resolve --json
  ) || exit 1
elif [ -n "${MST_CONTEXT_JSON:-}" ]; then
  echo "context-only identity cannot replace a full MST_SESSION_ID" >&2
  exit 1
else
  SESSION_IDENTITY_JSON=$(
    python3 "{PLUGIN_ROOT}/scripts/mst.py" session bootstrap \
      --root-type "{ROOT_TYPE}" --json
  ) || exit 1
fi
```

#### 4. Shell-safe canonical context 생성

기존 context의 모든 비-identity 필드를 보존하면서 canonical SID/root를 병합합니다. raw JSON을 single-quoted shell literal로 삽입하지 않습니다. `CANONICAL_MST_CONTEXT_JSON`은 논리적 JSON 값이며, subprocess 경계에서는 오직 ASCII `CANONICAL_MST_CONTEXT_B64`(base64url)로 운반합니다.

```bash
CANONICAL_MST_CONTEXT_B64=$(
  SESSION_IDENTITY_JSON="$SESSION_IDENTITY_JSON" \
  INPUT_MST_CONTEXT_JSON="${MST_CONTEXT_JSON:-}" \
  python3 - <<'PY'
import base64, json, os, sys

MAX_CONTEXT_BYTES = 262144

identity = json.loads(os.environ["SESSION_IDENTITY_JSON"])
raw_context = os.environ.get("INPUT_MST_CONTEXT_JSON", "")
context = json.loads(raw_context) if raw_context else {}
if not isinstance(context, dict):
    raise SystemExit("MST_CONTEXT_JSON must be a JSON object")
sid = identity["mst_session_id"]
root = identity["root_mst_id"]
if context.get("mst_session_id") not in (None, sid):
    raise SystemExit("MST_CONTEXT_JSON mst_session_id mismatch")
if context.get("root_mst_id") not in (None, root):
    raise SystemExit("MST_CONTEXT_JSON root_mst_id mismatch")
context["schema_version"] = 1
context["mst_session_id"] = sid
context["root_mst_id"] = root
wire = json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
if len(wire) > MAX_CONTEXT_BYTES:
    raise SystemExit("canonical MST context exceeds MAX_CONTEXT_BYTES")
sys.stdout.write(base64.urlsafe_b64encode(wire).decode("ascii"))
PY
) || exit 1
```

#### 5. MST_BOUND_SUBPROCESS — 모든 별도 subprocess에 재바인딩

서로 다른 tool/exec 호출은 별도 subprocess이므로 한 `export`에 의존하면 안 됩니다. shell function에도 의존하지 않습니다. 이후 **모든 별도** `mst.py`, counter, timestamp, config, state, lifecycle, delegation, dispatch, provider CLI subprocess는 아래 `MST_BOUND_SUBPROCESS` 형태로 정확한 full SID와 base64url context를 리터럴로 반복 전달합니다. 뒤 단계의 prefix 없는 command 예시는 축약 표기일 뿐이며 실제 실행 전에 반드시 이 형태로 확장합니다.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 "{PLUGIN_ROOT}/scripts/mst.py" {NEXT_COMMAND}
```

Decoder는 `base64.b64decode(..., altchars=b"-_", validate=True)`를 사용하고 decoded size를 `MAX_CONTEXT_BYTES`로 제한하며 canonical re-encoding equality를 요구합니다. Invalid alphabet, missing/extra padding, non-canonical spelling, oversize는 command 실행 전에 실패합니다.

Provider CLI를 직접 실행하는 허가된 external lane도 마지막 명령만 provider command로 바꾸고 동일한 두 환경 변수를 다시 구성합니다. apostrophe, command substitution, backtick, newline, shell metacharacter를 포함한 JSON도 decode 결과가 quoted environment assignment의 값으로만 들어가며 shell code로 재평가되어서는 안 됩니다. Shell command substitution은 trailing whitespace/newline byte identity를 보존하지 않으므로 raw input byte-equivalence를 약속하지 않습니다. 대신 Step 3에서 trailing whitespace 없는 canonical compact JSON으로 먼저 정규화한 뒤 그 canonical bytes만 encode/decode합니다.

#### Canonical Root Metadata Merge (MANDATORY)

`session bootstrap`은 root artifact의 JSON(`session.json`, `plan.json`, `request.json`)에 canonical metadata를 먼저 기록합니다. 이후 skill template write는 그 JSON을 replace/overwrite하지 않고 object merge해야 합니다. 기존 `mst_session_id`, `root_mst_id`, `started_at`, `started_at_compact`, `random`을 byte-for-byte 보존하고 workflow 필드만 병합합니다. 기존 canonical 필드가 bootstrap 결과와 다르면 fail-closed하며 identity를 재발급하지 않는다. 부모 SID를 상속한 child artifact처럼 파일이 아직 없을 때만 resolve 결과의 canonical field를 먼저 넣고 workflow field를 병합한다.

`DBG-NNN`/`REQ-NNN` 같은 root resource ID, host session ID, PID, transcript UUID, legacy alias는 full SID를 대신할 수 없습니다.
<!-- @end-include -->

**목적**: 프로젝트 목표를 받아 JTBD+프로젝트 DoD 기반 objective 흐름을 `agile-plan`으로 초기화하고, 프로젝트 건강 우선 스프린트 루프를 진행합니다.

핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/objective.md` (신규 생성 시 Step 1에서만)

**그 외 모든 경로(스킬 파일, 소스 코드, 설정 파일, objective.md 직접 수정 등)에 대한 Write/Edit 사용은 절대 금지입니다.**

- **objective.md 상태 전이(status 변경, checklist 체크 등)는 반드시 `mst.py agile objective-transition` / `mst.py agile objective-check`를 통해서만 수행한다.** LLM이 objective.md를 직접 편집하는 것은 엄격히 금지된다.
- 스프린트 루프에서 plan 생성은 반드시 `Skill(skill: "mst:plan", args: "-a ...")` 서브스킬 호출로 수행한다.

허용 경로 외 수정 요청 시: 즉시 중단 → mst.py 스크립트 사용 안내 출력

## Gate

### Entry

- `/mst:agile` 호출 시 Step 0~1 전체 프로토콜을 실행 대상으로 잠근다.
- 시작 전에 Write/Edit 허용 경로가 `AGI-*` 산출물 경로인지 확인한다.
- `--resume AGI-NNN`이 있으면 기존 세션 재개 경로로 분기한다.

### Exit

- Step 1에서 `agile-plan` 서브스킬 반환 마커 확인 후 Step 2로 진입한다.
- Step 2/3 루프는 단일 스프린트 모델로 반복 실행한다.
- Step 2.2.4.5 sprint-close 호출 완료 (`{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprint-log.json`에 현재 Sprint 레코드 존재)를 확인한다.

### 금지 패턴

- LLM이 objective.md를 직접 Write/Edit로 수정하는 행위.
- `mst.py agile objective-transition` / `objective-check` 우회.
- Step 0(세션 초기화) 없이 바로 objective 생성으로 진입.
- 스프린트 횟수/완료 시점을 예측·확정·암시하는 표현을 objective/plan 입력/중간 보고/스티어링 보고에 기재하는 행위. ("예상 스프린트", "N회 스프린트", "X주 내 완료", "4~8주 소요" 등 포함)
- 과거 실적을 현재 프로젝트의 완료 시점/스프린트 횟수 예측 근거로 인용하는 행위.
- 스프린트 진행 중/완료 직후 `"계속 진행하시겠습니까?"` 등 스프린트 간 확인 질문을 `AskUserQuestion`으로 삽입하는 행위.
- `AUTO_MODE=true` 또는 `STEERING_DISABLED=true`인 루프에서 텍스트 출력으로 확인/정지 질문을 생성하는 행위.
- 컨텍스트 길이/요약/정리를 사유로 스프린트 간 정지하는 행위.
- `AUTO_MODE=true` 또는 `STEERING_DISABLED=true`에서 스프린트 완료 후 선언 뒤 확인 질문을 삽입하는 행위.
- 스프린트 루프 중 어떤 자체 판단 사유로든 자발적으로 정지하는 행위.
- Sprint 간 대기 금지: wrapper 미사용 시 `/mst:resume`으로 수동 재개하고, 모델이 자체 페이싱으로 ScheduleWakeup을 호출하지 않는다.
- 루프가 남아 있는데 `"마무리"`, `"별도 세션"`, `"나머지는"` 등 루프 종료/이관을 암시하는 표현을 기재하는 행위.
- 정기 스티어링 해당 Sprint에서 Step 3을 건너뛰고 Step 2를 계속 진행하는 행위.
- 정기 스티어링 미해당 Sprint에서 자의적으로 확인 질문을 삽입하는 행위.
- 2.2.0.7 누적 통합 리뷰의 `verdict.force_wire_recommended=true`를 **사유 기록 없이** 무시하는 행위.
- 2.2.0.7 Escape Hatch를 동일 세션에서 **연속 2회 이상** 사용하는 행위.
- 2.2.4 Sprint 종류 자기선언을 누락(`sprint_kind` 미지정)하거나 `foundational`로 선언하면서 `--foundational-reason`을 생략하는 행위.
- `foundational` Sprint를 `config.agile.foundational_streak_max` 초과로 연속 선언하는 행위 (Sprint 0 제외).
- `foundational` Sprint에서 DoD를 곧바로 `done`으로 승격하는 행위 (반드시 `proposed_done`으로만 기록하고, 후속 `user_observable` Sprint에서 `--deferred-promote`로만 승격).
- 2.2.0.8 alignment 판정 `objective_stale`에서 비상 스티어링 진입 없이 Sprint를 계속 진행하는 행위.
- "컨텍스트 압박"을 이유로 sub-plan chain을 우회하여 직접 `codex exec` + master 커밋으로 전환하는 행위. 격리 실행이 필요하면 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 경로를 사용한다.
- 허용 표현: DoD 진행률(%), 완료/미완료 항목 수, 스티어링 방향 추천, 종료 후 총 스프린트 수 사후 집계, `proposed_done` 대기 DoD 수, 분류별 변경 파일 비율, alignment 판정 분포.

### AskUserQuestion 허용 지점 (Whitelist)

| 허용 지점 | 필수 마커 | AUTO_MODE=true 시 |
|-----------|-----------|-------------------|
| Step 3.3 DoD 제안 approve/reject | `[스티어링 체크포인트]` | skip → PM 자율 판단 |
| Step 3 비상 스티어링 강제 진입 후 | `[비상 스티어링]` | skip → PM 자율 판단 |
| Step 2.1 Sprint 0 smoke test 실패 후 | `[Sprint 0]` | skip → PM 자율 판단 |
| Step 2.2.6 소스 검증 3회 실패 초과 | `[자동 중단]` | skip → 자동 중단 전환 |
| Step 3.5 변경 후 정합성 정책 레벨 확인 | `[스티어링 체크포인트]` | skip → PM 자율 판단 |

동기화 규칙: 위 허용 지점/마커 목록을 변경하면 `hooks/mst-stop-hook.sh`의 agile AskUserQuestion 화이트리스트를 같은 PR에서 동시에 갱신한다. stop hook 화이트리스트에 없는 마커가 포함된 AskUserQuestion은 스프린트 루프에서 허용되지 않는다.

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

<!-- @include _shared/delegation-routing.md -->
### Provider Delegation Routing Protocol (MANDATORY)

이 프로토콜은 이 스킬 아래의 모든 provider 실행 예시보다 우선한다. provider 작업을 시작하기 전에 parent host가 route와 lifecycle evidence를 소유하고, child는 실제 할당 작업만 수행한다.

#### 0. 모델과 추론 난이도를 함께 확정한다

각 호출은 provider 시작 전에 호출 종류의 `{selector}`(예: `ideation`, `review.roles.security_reviewer`, `models.roles.developer.0`)로 `MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py resolve-execution "{provider}" "{selector}" --pretty`를 반드시 실행한다.

응답의 `model`, `reasoning_effort`, `reasoning_effort_source`는 하나의 binding이다. null(`inherit`)이면 override/CLI flag를 생략하고, invalid·unsupported·capability 부재는 우회 없이 **blocked**다.
우선순위는 호출별 concrete > provider `default_reasoning_effort`이며 호출별 `inherit`은 기본값을 건너뛴다. non-null effort는 Codex native `reasoning_effort`, Claude native `effort`, lifecycle/dispatch `--reasoning-effort`로 전달하고 항상 `--selector`를 함께 쓴다. Orca는 이미 `route=external`인 실행의 launch surface일 뿐이며 지원 범위와 binding을 바꾸지 않는다.

#### 1. Route를 먼저 확정한다

1. `MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py host context --json`을 실행하고 JSON의 `host`를 읽는다. 이 호출 실패, 잘못된 JSON, 알 수 없는 host는 임의 추정하지 말고 **blocked**로 종료한다.
2. 이어서 반드시 아래 중앙 planner를 호출한다. `{scope}`는 현재 작업의 실제 scope(`implementation`, `review`, `exploration`, `ideation`, `discussion`, `debug`, `analysis`)이고, `{provider}`는 선택된 `codex | claude | agy`다.

   ```bash
   MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
   MST_CONTEXT_JSON="$(
     MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
     python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
   )" \
   python3 {PLUGIN_ROOT}/scripts/mst.py delegation route \
     --host "{host}" \
     --provider "{provider}" \
     --scope "{scope}" \
     --worktree-dir "{worktree_path}" \
     --capability-status "{available|unknown|unavailable}"
   ```

3. route 결과 외의 근거로 transport를 바꾸지 않는다.
   - `route=native_candidate`: 같은 host/provider의 native bridge만 사용한다. `handshake_required=true`이면 실제 host tool 가용성을 확인한 뒤 진행한다.
   - `route=external`: 이 경우에만 아래에 남아 있는 managed wrapper, `dispatch build`, provider CLI adapter 예시를 사용할 수 있다.
   - `route=blocked`, CLI non-zero, lifecycle 응답의 `status=blocked`, 또는 현재 attempt의 `phase=reconciling`: 즉시 fail closed 한다. 같은 task/worktree에 새 agent나 external process를 시작하지 않는다.

   `requested_launch_surface=orca`, `launch_surface=orca`이면 transport는 계속 `external`이고 MST 보호 runner만 Orca background terminal에서 시작된다. Caller가 Orca Run/Task/Dispatch를 호출하거나 terminal을 직접 만들지 않는다. 중앙 Python launcher만 exact `path:{worktree_path}` selector와 `MST/{task_id}/{attempt_id}` title을 사용한다. Terminal create 호출 전 확정 실패만 원래 route로 돌아갈 수 있으며, 호출 이후 response/handle 불명은 fallback 또는 재실행하지 않고 기존 attempt를 reconcile한다.

#### 2. `native_candidate` 실행과 evidence

Native spawn **전** parent가 `delegation start`를 호출하고 반환된 `attempt_id`를 이후 모든 CAS 호출에 사용한다. `start`는 lifecycle 준비만 하며, 신규 응답이나 exact replay 모두 그 자체로 spawn 권한을 주지 않는다(`spawn_allowed=false`).

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py delegation start \
  --task-id "{task_id}" \
  --idempotency-key "{task_id}:start:{stable_key}" \
  --host "{host}" \
  --provider "{provider}" \
  --capability-status available \
  --route-reason "{route.reason_code}" \
  --worktree-dir "{worktree_path}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --scope "{scope}" \
  --prompt-file "{prompt_file}" \
  --output-path "{output_path}"
```

`analysis|review|exploration|ideation|discussion|debug`가 실제 read-only 작업이고 별도 linked worktree를 쓰지 않는 경우에만 `--read-only`를 추가한다. 구현·수정 작업에는 이 예외를 사용하지 않는다.

그 다음 parent invocation별 고유한 `{claimant_id}`로 single-use spawn claim을 요청한다. **오직 이 호출에서 `spawn_allowed=true`와 non-empty private `claim_token_file`을 함께 받은 단 한 caller만** native host tool을 한 번 호출할 수 있다. raw bearer token은 CLI JSON, argv, process listing, tool transcript, child prompt에 노출하지 않는다.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py delegation claim-spawn \
  --task-id "{task_id}" \
  --attempt-id "{attempt_id}" \
  --claimant-id "{claimant_id}" \
  --idempotency-key "{task_id}:claim:{claimant_id}"
```

`spawn_allowed=false`, `claim_status=claim_replay|already_claimed|reconciling|provider_task_in_flight|terminal`, 빈 `claim_token_file`, 또는 claim 응답 유실/불명확 상태에서는 host tool을 호출하지 않는다. `claim_replay|already_claimed`는 winner의 claim lease가 살아 있는 동안 **wait만** 하며 `recover`/`cancel`로 ownership을 빼앗지 않는다. lease 만료 뒤에만 `delegation recover`로 reconcile하고, 그 외에는 `next_action`에 따라 기존 provider task에 attach/wait한다. claim exact replay는 bearer token/파일을 다시 발급하지 않는다. 따라서 claim 결과를 잃은 caller도 외부 fallback이나 중복 native spawn을 시도하지 않는다.

- `host=codex, provider=codex`: Codex collaboration native tools를 사용한다. `collaboration.spawn_agent`로 spawn하고, resolved effort가 non-null이면 `reasoning_effort`를 전달한다. host가 제공하는 attach/follow-up 수단으로 같은 task에 연결하며, `collaboration.wait_agent`로 대기한 뒤 전달된 completion result를 수집한다. 병렬 fan-out은 독립 task마다 native agent를 하나씩 spawn한다.
- `host=claude, provider=claude`: Claude의 `Task(...)` 또는 `Agent(...)` native tool로 spawn하고, resolved effort가 non-null이면 `effort`를 전달한다. background task는 host의 `TaskOutput`/resume 결과로 대기·수집한다.
- 정상 same-host 경로에서 `codex exec`, `claude` CLI, `mst.py run --provider {same_provider}`, 같은 provider의 managed wrapper, 또는 nested `/mst:claude`/`/mst:codex`를 호출하지 않는다.

Native tool 응답마다 claim winner parent가 다음 순서로 evidence를 기록한다. `{claim_token_file}`은 winner 응답의 mode `0400` private one-shot handle이며 `acknowledge` 성공 시 삭제된다. 내용을 읽거나 복사하거나 child/user/log에 전달하지 않는다. 각 명령의 JSON 응답에서 `status`/`phase`를 확인하고 blocked/reconciling이면 더 진행하지 않는다. 아래 인라인 lifecycle command도 생략된 `python3 {PLUGIN_ROOT}/scripts/mst.py`와 함께 문서 최상단의 정확한 `MST_BOUND_SUBPROCESS` 두 환경 변수 prefix를 매번 리터럴로 확장하며, bare command로 실행하지 않는다.

1. spawn 성공 및 provider task ID 수신: `delegation acknowledge --task-id "{task_id}" --attempt-id "{attempt_id}" --claim-token-file "{claim_token_file}" --spawn-status created_with_task_id --provider-task-id "{provider_task_id}" --idempotency-key "{task_id}:ack:{stable_key}"`
2. host task 연결 확인: `delegation attach --task-id "{task_id}" --attempt-id "{attempt_id}" --attach-status attached --idempotency-key "{task_id}:attach:{stable_key}"`
3. 대기 중 주기적 생존 증거: `delegation heartbeat --task-id "{task_id}" --attempt-id "{attempt_id}" --provider-state running --idempotency-key "{task_id}:heartbeat:{sequence}"`
4. host result 수집 직후 parent가 성공 결과의 **비어 있지 않은 전체 내용**을 bound `{output_path}`의 sibling temp file에 먼저 쓰고 atomic replace한 뒤, fresh hash/size를 확인한다. child에게 이 파일 쓰기를 맡기거나 기존 파일을 재사용하지 않는다.
5. 결과 파일 evidence가 준비된 뒤에만: `delegation complete --task-id "{task_id}" --attempt-id "{attempt_id}" --completion-signal "{succeeded|failed|timeout|unknown}" --output-path "{output_path}" --idempotency-key "{task_id}:complete:{stable_key}"`

Native spawn이 task 생성 전에 **명확히** 실패한 경우에만 claim winner가 같은 `--claim-token-file "{claim_token_file}"`로 `spawn-status=definitive_not_created`를 acknowledge한 뒤 `delegation fallback --expected-attempt-id "{attempt_id}" ...`를 요청할 수 있다. 그 후 capability를 `unavailable`로 route planner에 다시 전달해 `route=external`을 받은 경우에만 external lane을 실행한다. claim 결과 유실, `accepted`, task ID 발급, attach 실패/timeout, child 실패, unknown/indeterminate 결과 뒤에는 external fallback을 금지하고 reconcile 상태를 유지한다.

#### 2-A. External lane authorization

`route=external` 판정만으로 provider command를 직접 만들지 않는다. Fresh headless/cross-provider external lane은 command 생성 전에 중앙 planner 결과를 state에 고정한다.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py dispatch authorize-external \
  --provider "{provider}" \
  --task-id "{task_id}" \
  --prompt-file "{prompt_file}" \
  --worktree-dir "{worktree_path}" \
  --running-log-path "{running_log}" \
  --trace-path "{trace_path}" \
  --output-path "{output_path}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --scope "{scope}" \
  --idempotency-key "{task_id}:external-authorize:{stable_key}" \
  {read_only_flag}
```

이 명령은 실제 host를 다시 확인하고 중앙 route가 여전히 `external`일 때만 current external attempt와 model/running/trace/output binding을 저장한다. 구현·수정 lane은 registered linked worktree를 사용하고 `{read_only_flag}`를 비운다. 실제 read-only scope만 `--read-only`를 사용한다. 반환된 `attempt_id`와 동일한 artifact binding을 external wrapper에 전달한다.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py dispatch build \
  --provider "{provider}" \
  --task-id "{task_id}" \
  --prompt-file "{prompt_file}" \
  --worktree-dir "{worktree_path}" \
  --log-file "{running_log}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --expected-attempt-id "{external_attempt_id}"
```

Native definitive non-creation fallback이면 새 authorization을 만들지 않고 `delegation fallback`이 반환한 external `attempt_id`를 `--expected-attempt-id`로 사용한다. Builder는 current attempt의 task/provider/resolved worktree/prompt hash/route를 재검증하므로 native, reconciling, stale attempt, 또는 mismatch 상태에서는 command를 만들지 않는다. Codex/Claude와 Orca-enabled AGY 보호 wrapper는 provider command나 split claim/finalize shell을 포함하지 않고 `dispatch run-external` 단일 감독자만 호출한다. `launch_surface=orca`일 때 builder는 중앙 `dispatch launch-external`을 호출하고, 그 launcher가 만든 terminal 안에서 동일한 `dispatch run-external`을 실행한다. 성공 finalize 뒤에만 tab을 닫고 실패·취소·unknown은 보존하며 terminal 출력이 아니라 MST output/lifecycle evidence를 authoritative로 본다. 감독자는 먼저 side effect가 없는 anonymous exec gate를 띄워 PID/PGID/start identity를 CAS로 attach하고, 같은 task lock 안에서 취소보다 먼저 exec 권한이 확정된 경우에만 실제 provider를 release한다. claim에서 캡처한 정확한 prompt bytes를 전달하고, provider process group을 회수한 뒤 fresh single-link inode로 claim해 계속 보유한 non-following output descriptor로 결과를 게시한다. prompt/snapshot/running/trace/output alias와 MST state·lock·history reserved path alias는 provider spawn 전에 차단한다. `claim-external`/`heartbeat-external`/`finalize-external`을 별도로 호출하거나 prompt snapshot/output pathname을 shell에서 다시 열지 않는다. Orca `terminal create --command`에는 task/attempt/session 같은 안전한 식별자만 넣고 prompt 본문·snapshot/running/trace/output path·claim secret·descriptor number를 넣지 않는다.

#### 3. Child prompt 격리 규칙

모든 native child prompt에는 다음 제약을 그대로 포함한다.

```text
DELEGATION BOUNDARY (MANDATORY)
- Complete the assigned task yourself; do not delegate or spawn another provider agent.
- Do not invoke codex/claude provider CLIs, /mst:codex, /mst:claude, or a same-provider managed wrapper.
- Do not call `mst.py delegation` lifecycle commands and do not edit `.gran-maestro/run`, session, or history state; the parent owns routing and evidence.
- Work only in the assigned worktree/scope and return the result/evidence to the parent.
```

아래 skill별 dispatch 예시는 이 protocol의 route로 gate한다. Provider CLI/managed wrapper 예시는 오직 `route=external`일 때만 사용한다. `Task`/`Agent`/Codex collaboration 예시는 host와 provider가 일치하는 `route=native_candidate`일 때만 사용하고 child boundary와 native lifecycle evidence를 함께 적용한다.
<!-- @end-include -->

직후에 `.claude/hooks/mst-stop-hook.sh` 파일 존재를 `Bash("test -f ...")`로 반드시 검증한다.
- 파일이 존재하면 다음 단계로 계속 진행한다.
- 파일이 여전히 없으면 `"[warn] stop hook 미설치 — 자발 정지 가드가 동작하지 않을 수 있음"` 경고를 출력하되 agile 진입은 계속 허용한다 (graceful fallback, 에러 아님).

State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

Parent session inheritance contract: child invocation, subprocess, and hook execution inherit parent `MST_SESSION_ID`; children must not issue arbitrary `mst_session_id`. Hook payload `mst_session_id` is allowed only when it matches the inherited parent `MST_SESSION_ID`.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

---

### Step 0: 세션 초기화

`[MST skill=agile step=0/4 return_to=null]`

#### 0.1 인자 파싱

args 전체 토큰에서 아래 플래그를 감지한다:

| 플래그 | 설명 |
|--------|------|
| `-a`, `--auto` | 자율 모드 활성화 |
| `--resume AGI-NNN` | 기존 세션 재개 |
| `--doc 파일경로` | 기존 문서 지정 (파싱 모드) |
| `--steering-every N` | 스티어링 체크포인트 간격 (기본값: 3) |

- `-a` 또는 `--auto`가 args 어디에든 포함되면 `AUTO_MODE=true`, 없으면 `AUTO_MODE=false`.
- `AUTO_MODE=false`인 경우 section preload: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get auto_mode.agile agile.steering_every --json)` 결과를 `agile_bootstrap_config`로 보관한다. 없으면 `templates/defaults/config.json` 확인 → `auto_mode.agile == true`면 `AUTO_MODE=true`.
- 우선순위: CLI 플래그(`-a`/`--auto`)가 config보다 우선한다.
- `--steering-every` 미지정 시: 같은 `agile_bootstrap_config`의 `agile.steering_every` 값을 사용한다. preload가 없거나 config에도 없으면 기본값 `3`.
- `STEERING_DISABLED`는 `STEERING_EVERY == 0`이면 `true`, 아니면 `false`로 계산한다.

#### 0.2 분기: --resume 있는 경우

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile status AGI-NNN --json` 실행
2. session.json 로드 성공 시: `AGI_ID`, `CURRENT_SPRINT`, `STEERING_EVERY`를 메모리에 보관
3. 아래 workflow state를 활성화한다 (non-blocking):
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --auto {AUTO_MODE} \
  --steering-disabled {STEERING_DISABLED} \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```
4. 세션 상태 출력: `[재개] AGI-{NNN} — 스프린트 {N} 상태: {status}`
5. Step 1 건너뜀 → 스프린트 루프(2.2)로 진행
6. 로드 실패 또는 AGI-NNN 미존재 시: 에러 메시지 출력 + `.gran-maestro/agile/` 디렉토리 확인 안내 후 중단

#### 0.3 분기: 신규 세션 (--resume 없는 경우)

1. 신규 세션 생성과 objective 초기화는 Step 1의 `agile-plan` 서브스킬에서 수행한다.
2. 사용자 입력 목표(`PROJECT_GOAL`)와 선택 플래그(`DOC_PATH`, `STEERING_EVERY`)를 메모리에 보관한다.
3. `[신규 세션 준비] agile-plan 위임 예정 (steering-every: {STEERING_EVERY})` 출력
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --auto {AUTO_MODE} \
  --steering-disabled {STEERING_DISABLED} \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```
4. Step 1로 진행

---

### Step 1: Objective 준비 (agile-plan 서브스킬 위임)

`[MST skill=agile step=1/4 return_to=null]`

신규 세션(`--resume` 없음)은 Step 1 전체를 아래 1줄 호출로 수행한다:

```text
Skill(skill: "mst:agile-plan", args: "{PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")
```

규칙:
- `--doc` 입력이 있으면 `DOC_FLAG_IF_ANY`에 `--doc {DOC_PATH}`를 포함하여 그대로 전달한다.
- `--doc` 입력이 없으면 `{PROJECT_GOAL_OR_DOC}`에 사용자 목표 문장을 전달한다.
- 서브스킬 종료 마커 `[MST skill=agile-plan step=returned return_to=agile/1]` 확인 후 stop-hook re-feed로 Step 1.5에 자동 진입한다.

---

### Step 1.5: 스티어링 설정 확정

`[MST skill=agile step=1.5/4 return_to=null]`

> 목적: agile-plan이 objective 준비를 마치고 복귀한 직후, 스프린트 루프 진입 전에 스티어링 주기와 비상 스티어링 활성화 여부를 확정한다.

**진입 가드**: `--resume` 경로는 이 단계를 skip한다 (session.json의 기존 `steering_every` 값 사용). 신규 세션(Step 1에서 복귀)에서만 실행한다.

**AUTO_MODE=true 분기**:
1. `STEERING_EVERY` 우선순위: CLI `--steering-every N` → config `agile.steering_every` → 기본값 `3`
2. `STEERING_DISABLED = (STEERING_EVERY == 0)`, `EMERGENCY_STEERING_ENABLED = true` (기본값 고정)
3. `STEERING_EVERY`가 기본값 3과 다르면 `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --steering-every {STEERING_EVERY} --json`으로 동기화
4. `[자율] 스티어링 설정: {STEERING_EVERY} 스프린트마다, 비상 {활성/비활성}` 출력, 사용자 질의 없음

**AUTO_MODE=false 분기**:
1. CLI `--steering-every N` 사전 지정 시: Q&A skip하고 해당 값 적용. `STEERING_EVERY > 0`이고 기본값 3과 다르면 `mst.py agile update --steering-every {STEERING_EVERY}` 호출.
2. CLI 미지정 시 `AskUserQuestion` 1회 호출 (`questions` 배열 2개 탭 동시 제시):
   - 탭 1 (`id: regular_steering`, `header: 정기 스티어링`)
     - `question`: `정기 스티어링 체크포인트를 어떤 주기로 운영할까요?`
     - `options`:
       - `label`: `3 스프린트마다 (기본값)` — Sprint 3/6/9 완료 직후 Step 3 자동 실행. 탐색/구현 균형 유지.
       - `label`: `5 스프린트마다` — Sprint 5/10/15 완료 직후 Step 3 실행. 긴 실행 구간 확보.
       - `label`: `비활성화 (정기 스티어링 없이 진행)` — `STEERING_EVERY=0`, 비상 스티어링만 사용.
   - 탭 2 (`id: emergency_steering`, `header: 비상 스티어링`)
     - `question`: `이상 징후 발생 시 비상 스티어링 자동 개입을 사용할까요?`
     - `options`:
       - `label`: `활성화 (연속실패/drift/blocked 등 이상 시 자동 개입)` — 기본 권장 설정.
       - `label`: `비활성화 (모든 스티어링 비활성화)` — 자동 개입 없이 연속 실행만 원할 때.
3. 응답 매핑:
   - `3 스프린트마다 (기본값)` → `STEERING_EVERY=3`, `STEERING_DISABLED=false`
   - `5 스프린트마다` → `STEERING_EVERY=5`, `STEERING_DISABLED=false`
   - `비활성화 (정기 스티어링 없이 진행)` → `STEERING_EVERY=0`, `STEERING_DISABLED=true`
   - 비상 활성화/비활성화 → `EMERGENCY_STEERING_ENABLED=true/false`
4. `STEERING_EVERY > 0` 이고 값이 3(기본값)과 다르면:
   ```bash
   MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --steering-every {STEERING_EVERY} --json
   ```
   `STEERING_EVERY == 0`이면 `STEERING_DISABLED=true`로만 해석하고 `agile update`는 호출하지 않는다.
5. `[확정] 스티어링 설정: {STEERING_EVERY} 스프린트마다, 비상 {활성/비활성}` 출력

Step 1.5 완료 후 Step 2(스프린트 루프)로 진행한다.

---

### Step 2: 스프린트 루프

`[MST skill=agile step=2/4 return_to=null]`

#### 2.0 상태 복원

세션 초기화(Step 0) 또는 Step 1 복귀 결과로 `CURRENT_SPRINT`, `STEERING_EVERY`를 복원한다.
- `STEERING_DISABLED`: 기본값 `false`, `STEERING_EVERY == 0`이면 즉시 `true`로 해석.
- `EMERGENCY_STEERING_ENABLED`: 기본값 `true`, 세션/복귀 컨텍스트에 명시값이 있으면 우선 적용.
- `--resume AGI-NNN` 진입: session.json에서 `current_sprint`를 복원. 손상 또는 `current_sprint` 필드 누락 시 에러 출력 + 파일 점검 안내 후 중단.
- 신규 세션(Step 1에서 복귀): `agile-plan` 생성 결과의 `AGI_ID` 사용, `CURRENT_SPRINT=0`으로 시작.

분기:
- `CURRENT_SPRINT == 0` 또는 Sprint 0 미완료 → **2.1 (Sprint 0)** 으로 진행
- `CURRENT_SPRINT >= 1` 및 Sprint 0 완료 → **2.2 (Sprint N 루프)** 로 진행

---

#### 2.1 Sprint 0: 테스트 환경 구축

**목표**: 프로젝트의 테스트 러너/프레임워크를 감지하고, smoke test 1개 이상이 통과한 것을 확인한 후 Sprint 1로 진입한다.

##### 2.1.0 Sprint 0 시작 기록 (MANDATORY)

Sprint 0 진입 즉시 `in_progress` 상태의 result를 기록하여 대시보드 타임라인에 표시한다:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint 0 \
  --status in_progress \
  --summary "테스트 환경 구축 중" \
  --json
```

##### 2.1.1 테스트 러너 감지

아래 파일을 순서대로 확인하여 테스트 러너를 감지한다:

1. `package.json` — `scripts.test` 필드 (jest, vitest, mocha 등)
2. `Makefile` — `test` 타깃
3. `pyproject.toml` / `setup.cfg` / `pytest.ini` — pytest
4. `Cargo.toml` — `cargo test` (Rust)
5. `go.mod` — `go test ./...` (Go)
6. `.github/workflows/` — CI 설정에서 테스트 명령어 추출

감지 결과를 `TEST_RUNNER` 변수에 저장 후 `[Sprint 0] 테스트 러너 감지: {TEST_RUNNER}` 출력

##### 2.1.2 테스트 환경 미존재 시

테스트 러너 감지 실패 시:

1. `[Sprint 0] 테스트 환경 없음 — 기본 환경 구축 시작` 출력
2. 아래 서브스킬 호출로 기본 테스트 환경 자동 구축:

```text
Skill(skill: "mst:plan", args: "-a 프로젝트에 최소한의 smoke test 1개를 포함한 테스트 환경을 구축한다. 테스트 러너를 선택하고 설정 파일을 작성하며, 항상 통과하는 smoke test 1개를 작성한다.")
```

3. 완료 후 2.1.1로 재시도 (최대 1회). 재시도 실패 시 사용자 안내 후 중단.

##### 2.1.3 Smoke Test 실행 및 Sprint 1 진입 조건

1. 감지된 `TEST_RUNNER`로 smoke test 실행하여 **최소 1개 테스트 통과** 확인
2. 통과 시:
  - `[Sprint 0] smoke test 통과 — Sprint 1 진입 조건 충족` 출력
  - Sprint 0 결과 기록 (완료):
    ```bash
    MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
      --sprint 0 \
      --status done \
      --planned "테스트 환경 구축" \
      --completed "테스트 환경 구축" \
      --pln {PLN_ID_IF_EXISTS} \
      --req {REQ_ID_IF_EXISTS} \
      --summary "smoke test 통과" \
      --json
    ```
    - `PLN_ID_IF_EXISTS` / `REQ_ID_IF_EXISTS`: Sprint 0에서 `mst:plan`을 호출한 경우에만 전달. plan 호출 없이 통과한 경우 `--pln`/`--req` 인자 생략.
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --current-sprint 1 --json` 실행
  - `CURRENT_SPRINT=1` 설정 후 Sprint N 루프(2.2)로 진입
3. 실패 시:
  - `[Sprint 0] smoke test 실패 — 원인 분석 후 수동 확인 필요` 출력 + 실패 로그 요약
  - `AUTO_MODE=true`: AskUserQuestion 없이 PM이 1회 재시도 후, 재실패 시 자동 중단 전환.
  - `AUTO_MODE=false`: `AskUserQuestion`으로 사용자 확인 후 재시도 또는 중단.

---

#### 2.2 Sprint N 루프 (프로젝트 건강 우선)

**목표**: 매 Sprint 시작 시 프로젝트 건강을 먼저 점검하고, 문제를 우선 해결한 뒤 프로젝트 DoD를 MoSCoW+의존성 기반으로 진행한다.

스프린트 시작 시 아래 체크포인트 마커를 반드시 출력한다:
`[LOOP {CURRENT_SPRINT}] DOD 진행: {done}/{total} | 잔여: {remaining}`

반복 시작 전 매번 공통 게이트를 아래 순서로 수행한다:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active true \
  --active true \
  --skill mst:agile \
  --auto {AUTO_MODE} \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```

##### 2.2.0.5 Accept Preflight 검증 (이전 Sprint REQ 완료 확인)

`state set-workflow` 직후, `objective-check` 호출 전에 직전 Sprint REQ의 accept 완료 여부를 선검증한다.

1. `CURRENT_SPRINT == 1`이면 Sprint 0은 smoke test이므로 preflight를 skip하고 objective-check로 진행한다.
2. `CURRENT_SPRINT > 1`이면 직전 Sprint 결과에서 REQ ID를 추출한다.
```bash
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT-1}/result.json)
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT-1}/result.md)
```
- 결과에서 `REQ-<숫자>` 패턴이 없으면(예: 건강 이슈 수정 Sprint) preflight를 skip하고 objective-check로 진행한다.
3. `Read({PROJECT_ROOT}/.gran-maestro/requests/{PREV_REQ_ID}/request.json)` 후 `status`를 확인한다.
- `status`가 `done`, `completed`, `accepted` 중 하나이면 정상 완료로 간주하고 preflight를 skip한다.
- 그 외(`phase2_execution`, `phase3_review`, `spec_ready` 등)는 미완료로 간주한다.
4. 미완료로 판정되면 브랜치 존재 여부를 교차 검증한다.
```bash
git show-ref --verify --quiet refs/heads/gran-maestro/{PREV_REQ_ID}
```
- 브랜치가 존재하면 accept 미실행으로 확정한다.
5. accept를 선행 실행한다.
```text
Skill(skill: "mst:accept", args: "{PREV_REQ_ID}")
```
6. `[CRITICAL][NO-SELF-MOTIVATED-PAUSE]` accept 반환 후 어떤 사유로든 정지를 **절대 금지**하고 즉시 아래 결과 확인 + objective-check를 실행한다.
- 성공 조건: `request.json.status`가 `done`/`completed`/`accepted` 중 하나 + 관련 브랜치 정리됨
- 실패 조건: 위 성공 조건 미충족 → `[비상 스티어링]` 마커로 사용자 개입 요청 후 Sprint 진행 중단.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json
```

- `all_done: true`이면 루프를 종료하고 2.3으로 이동한다.
- `all_done: false`이면 Sprint를 계속 진행한다.
- 정기 스티어링은 `STEERING_DISABLED=true` 또는 `STEERING_EVERY == 0`이면 skip한다.
- `[CRITICAL][NO-AD-HOC-PAUSE]` 정기 스티어링 미해당 Sprint에서는 확인 질문 없이 즉시 Step 2.2.1로 진행한다.
- `STEERING_EVERY > 0` 이고 `CURRENT_SPRINT > 0` 이고 `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0`이면 `[MANDATORY][STEERING-DUE]` Step 3(스티어링 체크포인트)를 수행 후 이 루프로 복귀한다.

##### 2.2.0.7 누적 통합 리뷰 (MANDATORY)

**목적**: 이번 Sprint가 기존 산출물 위에 쌓는지 vs 격리 헬퍼를 또 만드는지를 선검증한다 (slide-craft 재발 패턴 차단). `CURRENT_SPRINT <= 1`이면 skip하고 2.2.0.8로 진행한다.

1. 결정론 헬퍼 호출:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile integration-review {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --depth 3 \
  --json
```

  - 인자 생략 시 `--depth`는 `config.agile.integration_review_depth`(기본 3), `--threshold`는 `config.agile.new_island_threshold`(기본 0.20) 자동 fallback.

2. 헬퍼 출력 JSON에서 아래 필드를 확인한다:
   - `files.total / modify / wire / new_island`, `ratios.new_island`
   - `verdict.exceeded` (= `ratios.new_island > threshold`), `verdict.force_wire_recommended`
   - `wire_streak.current / max / exceeded`

3. 헬퍼는 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/integration-context.md`를 자동 생성한다. 2.2.3 plan -a `[누적층]` 컨텍스트에서 **MANDATORY Read 대상**이다.

4. 분기:
   - `verdict.exceeded=false` → 2.2.0.8로 진행
   - `verdict.exceeded=true` → **강제 wire 전환**: `SELECTED_WORK_ITEM`을 "직전 누적 new-island를 기존 진입점과 통합"으로 재지정, 2.2.2 DoD 선택 skip, `selection_reason`에 `integration-review forced wire` 기록
   - `wire_streak.exceeded=true` (연속 `agile.integration_wire_streak_max`=3회) → 비상 스티어링(Step 3) 즉시 강제 진입

##### LLM 스티어링 게이트 (wire_streak.exceeded=true 시)

`config.agile.llm_steering_gate_enabled == true`이면 비상 스티어링 진입 전 LLM 분석을 수행한다:

1. `new_island` 파일 목록 + 테스트 PASS/FAIL 상태 + `integration-context.md` 분석
2. `false_positive`: `wire_streak.exceeded`를 false로 override + 근거를 `llm_gate`에 기록 → 정상 Sprint 진행. `true_positive`: 비상 스티어링 진입.
3. `llm_steering_gate_enabled == false`이면 게이트 skip

5. **PM Escape Hatch** (grep false positive, 동적 import 언어 등): `AUTO_MODE=true` → `auto-decisions.md`에 `[integration-review override] reason: {...}` 기록 필수. `AUTO_MODE=false` → `retrospective.md`에 `integration_review_override` 섹션으로 사유 기록. 동일 세션 **연속 2회 이상 override 금지**.
- **Dispatch 결과 수집**: `config.agile.dispatch.enabled == true`면 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/dispatch-result.json`을 Read하여 통합 검증 대상에 포함한다.

##### 2.2.0.8 기획-구현 정합성 점검 (MANDATORY)

##### 2.2.0.8-pre: drift-report.json 신뢰 소스 우선 참조 (AD-RV-004)

본 단계의 3축 판정 전, `.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT-1:02d}/drift-report.json`이 존재하면 해당 파일의 `classification` 필드를 우선 사용한다.

| classification | 처리 |
|----------------|------|
| `aligned` | alignment 판정을 **aligned**로 확정, 3축 판정 skip |
| `drift_warning` | **drift_warning**으로 확정, drift 카운터 경로 진입 |
| `objective_stale` | **objective_stale**로 확정, 비상 스티어링 강제 진입 |
| `pending` | MVP skeleton 상태 → 기존 3축 판정으로 fallback |
| 파일 미존재/파싱 실패 | 기존 3축 판정으로 fallback (graceful) |

##### 2.2.0.8-recall: Recall Patch Manifest 자동 생성 (AD-SU)

drift-report classification이 `drift_warning` 또는 `objective_stale`이면 `.gran-maestro/agile/{AGI_ID}/sprints/S{N}/recall-patch-manifest.json` 초안을 자동 생성한다.

- `drift_warning` → Level 2 manifest (DoD 추가/삭제/순서/병합/문구 정밀화만 허용, `requires_user_approval: false`)
- `objective_stale` → Level 3 manifest (의미 변경, `requires_user_approval: true`)

manifest는 MVP에서 placeholder + TODO 마커로 기록되며, 실제 patch apply는 `mst.py agile recall --apply`로 처리한다. 자동 block 없음 (dashboard 표시만).

**목적**: 기획(objective.md) ↔ 구현(누적 변경) 정합성 점검. "DoD가 코드 현실과 어긋나는 기획 노후화"를 감지한다. `CURRENT_SPRINT <= 1`이면 skip하고 2.2.1로 진행한다.

1. alignment 데이터 패키지 조회:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile alignment-package {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --depth 3 \
  --json
```

  - 반환: `{objective_dods[], integration_context_path, recent_results[], recent_retrospectives[]}`. objective.md 없으면 graceful skip → 2.2.1로 진행.

2. 패키지를 Read한 뒤 PM이 3축으로 정합성을 판정한다:
   - **A. DoD-변경 매핑 충실도**: 상당수 변경이 어떤 DoD에도 매핑되지 않으면 `drift_warning` 후보
   - **B. DoD 현실 가능성**: DoD가 현재 코드 상태에서 "관찰 가능"하게 구현되고 있는가? 없으면 `drift_warning` 후보
   - **C. 기획 노후화**: DoD/제약/우선순위가 현재 코드 현실과 모순되는가? 그렇다면 `objective_stale` 후보

3. 판정 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/alignment-check.md`에 기록한다 (헤더: `판정`, `A. DoD-변경 매핑 충실도`, `B. DoD 현실 가능성`, `C. 기획 노후화`).

4. 분기:
   - `aligned` → 2.2.1로 진행
   - `drift_warning` → `drift_count += 1`, 경고 출력 + 2.2.1 진행. `drift_count >= agile.drift_count_trigger`이면 비상 스티어링 진입
   - `objective_stale` → **비상 스티어링 강제 진입**(Step 3), 진행 보고서에 `alignment: objective_stale` 마커 포함

5. `AUTO_MODE=true`에서는 PM이 3축 판정과 분기를 자율 수행하고 근거를 `alignment-check.md`에 기록한다.

##### 2.2.1 프로젝트 건강 점검 (Sprint 시작 시 MANDATORY)

Sprint 시작 즉시 `in_progress` 결과를 기록(`python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {CURRENT_SPRINT} --status in_progress --summary "프로젝트 건강 점검 중" --json`)한 뒤 건강 점검을 수행한다.

점검 항목:
1. 테스트 실행 (`npm test` 등 프로젝트 표준 명령) + 빌드/타입체크 확인
2. known issues 조회: `python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues list {AGI_ID} --status open --json`
3. 직전 Sprint 회고 `Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md)` — 미해결 항목(`failed`, `limitations`) 확인, `lessons_learned`를 `PREVIOUS_LESSONS` 변수에 저장 (2.2.3 plan 컨텍스트 및 result 기록 시 사용)

판정: 실패 테스트/빌드, open known issues, 미해결 회고 항목 중 하나라도 있으면 `HEALTH_ISSUE_FOUND=true` → 수정 작업을 DoD 진행보다 우선. 모두 정상이면 `HEALTH_ISSUE_FOUND=false` → 2.2.2로 진행.

##### 2.2.2 DoD 항목 선택 (MoSCoW + 의존성 기반)

`HEALTH_ISSUE_FOUND=false`일 때만 DoD 선택을 수행한다.

선택 규칙: `objective-check --json`으로 미완료 항목 조회 → MoSCoW `must` > `should` > `could` 우선 → `deps`가 모두 `done`인 항목만 후보 → 직전 회고 `direction` 반영하여 미세 조정.

결정: 건강 이슈 있으면 `SELECTED_WORK_ITEM={FIX_TARGET}`, 없으면 `SELECTED_WORK_ITEM={SELECTED_DOD}`. 의존성 미충족 시 의존성 해소 작업 자동 생성 후 `SELECTED_WORK_ITEM={FIX_TARGET}`으로 전환.

##### 2.2.3 plan -a 호출 (N계층 컨텍스트)

`mst:plan -a` 호출 시 아래 컨텍스트를 반드시 전달한다.

컨텍스트 계층 (모두 전달 필수):
- `[의도층]`: MANDATORY Read — objective.md (JTBD 원문) + `details/{DOMAIN_SLUG}.md` + `objective.ids.json`(존재 시). plan.md 필수 기록: `충족 JTBD 조항`, `도메인 참조 ID`, `## Objective Trace` 또는 PAC 매핑의 objective anchor coverage evidence.
- `[고정층]`: objective.md 전체 (JTBD + 프로젝트 DoD + 제약 + 설계 결정 + NFR + 리스크)
- `[활성층]`: 현재 선택된 미완료 DoD 항목 | `[변화층]`: 직전 Sprint 결과 | `[회고층]`: 직전 retrospective
- `[이슈층]`: open known issues
- `[누적층]`: 2.2.0.7 생성 `integration-context.md` (MANDATORY Read — 이번 Sprint가 어디에 쌓을지 결정)
- `[제약층]`: 프로젝트 DoD + 성공 지표

```text
Skill(skill: "mst:plan", args: "-a {SELECTED_WORK_ITEM}
[의도층] MANDATORY Read (반드시 두 파일 모두 Read한 뒤 plan 작성):
  1. objective 원본: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
  2. 선택된 DoD 소속 도메인 상세: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/details/{DOMAIN_SLUG}.md
  3. objective anchor manifest: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json (존재 시)
  plan.md에 반드시 기록: (1) 충족 JTBD 조항 (2) 도메인 참조 ID (domain-slug + AD-NNN 목록) (3) objective trace / anchor coverage evidence: 선택 DoD/domain의 MUST objective anchor ID가 plan PAC 또는 `## Objective Trace`에 100% 매핑됐는지와 누락 ID 목록
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 현재 대상: {SELECTED_WORK_ITEM} | 소속 도메인: {DOMAIN_SLUG} | 미완료 DoD: {INCOMPLETE_DOD_LIST}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md
[회고층] 직전 회고: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md | 직전 교훈: {PREVIOUS_LESSONS}
[이슈층] open known issues: {OPEN_ISSUE_LIST}
[누적층] 통합 컨텍스트 파일(MANDATORY Read): {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/integration-context.md — 직전 K Sprint 분류(modify/wire/new-island), entrypoint 상태, wire 파일별 통합 지점, user_observable_change 요약을 확인하고 이번 Sprint가 어디에 쌓을지 결정한다
[제약층] 프로젝트 DoD: {PROJECT_DOD_LIST_LITERAL} | 성공 지표: {SUCCESS_METRICS_LITERAL}")
```

##### 2.2.3.a Dispatch 활성화 분기 (`config.agile.dispatch.enabled`)

Step 2.2.3은 `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.dispatch.enabled agile.dispatch.provider --json)` 값을 기준으로 분기한다. `agile.dispatch.provider` 미설정 시 `codex`로 간주한다.

- `enabled == true`: `2.2.3.D dispatch 실행 경로` 수행
- `enabled == false` 또는 키 미설정: inline 경로 수행 (기본값 `false`)
  - 위 `Skill(skill: "mst:plan", args: "-a ...")` 호출을 그대로 실행
  - **추가: inline 경로 경량 추적 마커 (MANDATORY)**: Sprint 시작 시 `{PROJECT_ROOT}/.gran-maestro/run/{AGI_ID}-S{NN}.json`에 아래 페이로드를 Write:
    ```json
    {"task_id": "{AGI_ID}-S{NN}", "phase": "running", "provider": "{resolved_provider}", "model": "{resolved_model}", "started_at": "{ISO8601}", "last_heartbeat": "{ISO8601}", "inline": true}
    ```
  - Sprint 종료 시 동일 파일을 `phase: "done"` (성공) 또는 `phase: "failed"` (실패)와 `terminated_at`, `exit_code`, `last_heartbeat` 필드로 업데이트.
  - inline 경로는 `dispatch-result.json`을 **생성하지 않는다** (ADR-007 하위 호환 유지).

##### 2.2.3.D Dispatch 실행 경로 (provider-neutral, MANDATORY)

0. Sprint prompt에는 아래 path-first context transfer contract를 반드시 포함한다. `templates/sprint-dispatch-prompt.md`를 조립할 때 이 블록을 그대로 채우고, path가 없으면 `N/A`로 숨기지 말고 명시적 상태값을 사용한다.
   ```text
   [CONTEXT_FILES]
   - objective: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
   - objective_ids: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json or NO_OBJECTIVE_IDS
   - plan: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.md or NO_SOURCE_PLAN
   - plan_json: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.json or NO_PLAN_JSON
   - plan_ids: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.ids.json or NO_PLAN_IDS
   - spec: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md or NO_ACTIVE_SPEC
   - spec_context_manifest: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md#§0-Context-Manifest or NO_SPEC_CONTEXT_MANIFEST
   - sprint_context: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/integration-context.md or NO_SPRINT_CONTEXT
   - previous_feedback: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/retrospective.md or NO_PREVIOUS_FEEDBACK
   [/CONTEXT_FILES]

   [WORK_CONTRACT]
   - read_requirements: 구현 전 위 context file과 spec §0 Context Manifest 파일을 직접 Read/inspection한다.
   - output_contract: agile/agile-plan/prompt-template 변경 파일, dispatch result contract, completion report를 보고한다.
   - verification_contract: verify_cmd, expected_signal, integration_smoke_id를 보고한다.
   - failure_contract: timeout, empty result, blocked, missing_context 상태를 구조화해 남긴다.
   [/WORK_CONTRACT]
   ```
   - completion report에는 최소 `changed files`, `simplifications made`, `remaining risks`, `Read/inspection evidence`, `verification evidence`를 포함한다.
   - objective/spec/plan 원문 대량 삽입 금지. path-first contract를 전달하고 child가 직접 Read/inspection하게 한다.
1. Sprint prompt 조립: `templates/sprint-dispatch-prompt.md` 기반으로 `sprint-prompt.md`를 생성하고, inline 경로와 동일한 N계층 컨텍스트를 채운다.
2. worktree 생성: `{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/`
3. provider별 native-first delegation dispatch 실행:
   - provider resolve: `PROVIDER=$(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.dispatch.provider 2>/dev/null || echo "codex")`
   - shared routing protocol로 host context와 route를 먼저 확정한다. Same-host `native_candidate`이면 host native agent에 `sprint-prompt.md + DELEGATION BOUNDARY`를 전달하고 native lifecycle을 기록한다.
   - 아래 model/CLI resolve와 호출 예시는 `route=external`에만 적용한다.
   - 모델 resolve: `MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model "$PROVIDER" default 2>/dev/null)`
   - `PROVIDER=codex`, external lane call:
     ```bash
     MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
     MST_CONTEXT_JSON="$(
       MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
       python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
     )" \
     python3 {PLUGIN_ROOT}/scripts/mst.py run \
       --task-id "{AGI_ID}-S{NN}" \
       --provider codex \
       --model "$MODEL" \
       --log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/" \
       --trace {AGI_ID}/S{NN}/dispatch \
       --require-worktree \
       --worktree-dir "{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/" \
       -- codex exec --approve-for-me -m "$MODEL" -C "{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/" "$(cat sprint-prompt.md)"
     ```
   - `PROVIDER=agy`, external lane call:
     ```bash
     MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
     MST_CONTEXT_JSON="$(
       MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
       python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
     )" \
     python3 {PLUGIN_ROOT}/scripts/mst.py run \
       --task-id "{AGI_ID}-S{NN}" \
       --provider agy \
       --model "$MODEL" \
       --log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/" \
       --trace {AGI_ID}/S{NN}/dispatch \
       --require-worktree \
       --worktree-dir "{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/" \
       -- agy --print "$(cat sprint-prompt.md)" --dangerously-skip-permissions --add-dir "{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/"
     ```
   - `PROVIDER=claude`, external lane call:
     ```text
     Skill(skill: "mst:claude", args: "--prompt-file sprint-prompt.md --dir {PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/ --trace {AGI_ID}/S{NN}/dispatch")
     ```
   - sprint dispatch lifecycle tuple: `sprint-prompt.md`, sprint worktree path, trace label, `{AGI_ID}-S{NN}`, sprint log dir는 같은 dispatch attempt에 속한다. Native는 delegation lifecycle과 host result를, external은 managed wrapper가 stdout/stderr/exit code를 수집한다.
   - external route의 provider는 `python3 {PLUGIN_ROOT}/scripts/mst.py run` lifecycle wrapper를 통해 다음 계약을 유지해야 한다:
     - `--task-id "{AGI_ID}-S{NN}"`
     - `--provider "$PROVIDER"`
     - `--model "$MODEL"`
     - `--log-dir "{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/"`
     - `--require-worktree`
     - `--worktree-dir "{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/"`
     - prompt source: `sprint-prompt.md`
     - cwd/worktree: `{PROJECT_ROOT}/.gran-maestro/worktrees/{AGI_ID}/sprint-{CURRENT_SPRINT}/`
   - lifecycle boundary mapping:
     - running log path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/running.log`
     - trace path: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{NN}/traces/{provider}-*.md`
     - wrapper register/heartbeat state: `${baseDir}/run/{AGI_ID}-S{NN}.json`
   - external wrapper가 위 artifact와 `running log tee / trace path / session metadata / output-failure contract / exit code propagation`을 기록한다. Native lane은 동일 task/worktree/prompt/output을 `delegation` evidence에 기록하고 가짜 exit code를 만들지 않는다.
4. 종료 신호 수신: native는 host completion signal과 result artifact를 확인하고, external은 provider exit code를 확인한 뒤 `dispatch-result.json` 존재 여부를 확인한다.
5. 실패 처리: 아래 `실패 처리 (MANDATORY)` 블록을 따른다.

###### Pre-dispatch HEAD 가드 (MANDATORY)

Dispatch 시작 전 primary worktree가 base 브랜치에 있는지 확인한다. 이 가드는 Sprint worktree dispatch가 primary worktree의 hijack 상태에서 출발하는 것을 막기 위한 필수 절차다.

절차:
1. `git -C {PROJECT_ROOT} rev-parse --abbrev-ref HEAD`로 현재 HEAD를 확인한다.
2. base 브랜치는 `config.worktree.base_branch`를 우선 사용하고, 값이 비어 있으면 `master`로 fallback 한다.
3. `HEAD == base`이면 dispatch를 계속 진행한다.
4. `HEAD != base`이면 dispatch를 중단하고 known issue를 자동 등록한다. 이 가드는 primary worktree를 자동 checkout하지 않는다.

```bash
CURRENT_HEAD=$(git -C {PROJECT_ROOT} rev-parse --abbrev-ref HEAD)
BASE_BRANCH=$(python3 {PLUGIN_ROOT}/scripts/mst.py config get worktree.base_branch 2>/dev/null || true)
BASE_BRANCH=${BASE_BRANCH:-master}

if [ "$CURRENT_HEAD" != "$BASE_BRANCH" ]; then
  UNCOMMITTED=$(git -C {PROJECT_ROOT} status --porcelain)
  echo "[Sprint Dispatch 차단] primary worktree HEAD=${CURRENT_HEAD}, base=${BASE_BRANCH}. 원본 checkout 변경 없이 중단합니다."
  MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues add {AGI_ID} \
    --description "primary worktree hijack: HEAD=${CURRENT_HEAD}, base=${BASE_BRANCH}, dirty=${UNCOMMITTED:+true}" \
    --severity MAJOR \
    --sprint {CURRENT_SPRINT}
  exit 1
fi
```

###### 1회 안내 메시지 (MANDATORY)

Step 2.2.3.D 경로의 **세션 첫 실행 시 1회만** 아래 문구를 출력한다:
`[Sprint Dispatch 모드] Sprint 실행을 별도 세션으로 격리합니다. 비활성화: config.agile.dispatch.enabled = false`

1회 출력 판정: 세션 메모리 플래그 `dispatch_notice_shown_{AGI_ID}` 또는 파일 플래그 `{PROJECT_ROOT}/.gran-maestro/tmp/dispatch-notice-shown-{AGI_ID}` 존재 여부 확인. 플래그 없으면 메시지 출력 후 즉시 플래그 기록(동일 세션 재출력 금지).

###### 실패 처리 (MANDATORY)

- native 실패 조건: native completion signal이 success가 아니거나 결과 artifact가 없고 reconcile 대상이 아닌 경우.
- external 실패 조건: `exit_code != 0` 또는 `dispatch-result.json` 미생성.
- 실패 시 반드시 아래 명령으로 실패 결과를 기록한다:
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} --status failed --summary "{failure_reason}"`
- `failure_reason`은 구체 원인 기재 (예: `"dispatch chain exited with code 137"`)
- 다음 Sprint의 Step `2.2.1 프로젝트 건강 점검`에서 이전 실패 Sprint를 감지하면 재시도 경로로 진입한다.
- inline fallback 수행 금지 (ADR-007): dispatch 실패 후 parent 세션에서 `plan/request/approve/accept`를 즉시 대체 실행하지 않는다.

규칙:
- `plan -a` 입력에 완료 시점/잔여 횟수 예측 문구를 포함하지 않는다.
- 스프린트 목표는 작업 항목 명사가 아니라 **관찰 가능한 결과/동작**으로 작성한다.
- 컨텍스트가 비어 있으면 `"N/A"`로 숨기지 말고 `missing_context`, `NO_OBJECTIVE_IDS`, `NO_PLAN_JSON`, `NO_PLAN_IDS`, `NO_ACTIVE_SPEC`, `NO_SPEC_CONTEXT_MANIFEST`, `NO_PREVIOUS_FEEDBACK` 같은 명시적 상태값을 남긴다.

##### 2.2.3.b MANDATORY Read 누락 자동 재지시 루프

Step 2.2.3 이후 plan-a 완료 직후 parent(Sprint 진행자)는 아래 검증/복구 루프를 수행한다.

1. `Read({PROJECT_ROOT}/.gran-maestro/plans/{PLN_ID}/plan.md)`로 산출물 확인.
2. `plan.md`에 `충족 JTBD 조항`, `도메인 참조 ID` 두 필드가 모두 존재하는지 검사한다.
3. `objective.ids.json`이 존재하거나 selected DoD/domain이 objective anchor metadata를 가진 경우, `plan.md`/`plan.ids.json`의 PAC 또는 `## Objective Trace`에서 선택 범위의 MUST anchor coverage를 검사한다. 필드 존재만으로 통과시키지 않는다.
4. 누락 시 자동 재지시 + 동일 N계층 컨텍스트로 plan-a 재호출. 최대 `agile.intent_redirect_max_retries` 회(기본 3)까지 반복.
5. 한도 도달 후에도 누락이면 현재 Sprint의 known issue에 `agi_id`, `dod_id`, 누락 필드/anchor ID 목록, 재시도 횟수, 마지막 plan 경로를 포함하여 자동 등록.

##### [추가 섹션] Sprint 중 디자인 수정 경로 (Step 번호 유지 전용)

아래 경로는 기존 Step `2.2.1~2.2.6`를 대체하지 않고, sprint 진행 중 필요한 경우에만 추가로 적용한다.

**경로 1: AI 자율 판단 (AUTO_MODE)** — `2.2.3` plan -a 실행 중 디자인 불일치 감지 시: `mst:plan` UI 감지 흐름으로 필요성 확정 → `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {plan 주제}")` 재호출 → 결과를 sprint plan 컨텍스트에 반영 후 계속.

**경로 2: 사용자 명시 요청** — sprint 중 사용자가 디자인 변경 요청 시: plan 스킬 UI 감지 흐름으로 전달하거나 즉시 `Skill(skill: "mst:stitch", args: "{요청 맥락}")` 호출 → 결과를 기준선에 반영 후 필요 시 `2.2.3` 재실행.

**경로 3: review 발견** — 구현 후 review에서 디자인과 구현 괴리 감지 시: 디자인 수정 필요 시 `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {보정 주제}")` 호출. 구현 수정만 필요 시 기존 sprint 수정 루프로 처리하고 디자인 baseline 유지.

###### objective.md 디자인 컨텍스트 baseline 업데이트 규칙 (MANDATORY)

디자인이 실제로 수정된 경우(경로 1~3) 아래를 반드시 적용한다.
1. objective.md `## 디자인 컨텍스트`의 `상태`를 `updated`로 변경한다.
2. `### 변경 이력`에 변경 시점(Sprint N/날짜), 변경 내용, 변경 사유를 기록한다.
3. DES-NNN이 새로 생성/교체되었으면 화면 목록과 텍스트 와이어프레임을 최신 기준으로 갱신한다.
4. objective 갱신 시 direct edit 금지 규칙을 유지하고, 기존 `mst.py` 기반 objective 갱신 절차를 따른다.

##### 2.2.4 Sprint 결과 기록 + Sprint 종류 자기선언 + DoD 갱신 제안

Sprint 실행 결과를 기록하고, 이번 Sprint에서 완료 근거가 확보된 DoD에 대해 갱신 제안을 남긴다.

**Sprint 종류 자기선언 (MANDATORY — 재프레이밍 핵심)**:

이 Sprint는 시작 시점 또는 결과 기록 시점에 **반드시 종류를 자기선언**한다:

- `user_observable` (기본값): 사용자가 이 Sprint 전에는 할 수 없었던 것을 이제는 할/볼 수 있게 됨. 진입점(CLI 명령, SKILL 호출, UI 클릭 경로, 생성된 산출물 등) 중 최소 1개가 추가/변경되어 관찰 가능. `--user-observable-change` 필드로 기록한다.
- `foundational` (예외): 사용자 관찰이 불가능한 기반 작업(테스트 인프라, 빌드 파이프라인, 내부 스키마 정의, 타입 선언 등). `--foundational-reason` 필드로 "왜 사용자 관찰 불가한지 + 어느 후속 Sprint에서 관찰 가능해질 예정인지"를 기록한다.

**연속 한도 (MANDATORY)**: `foundational` Sprint는 `config.agile.foundational_streak_max`(기본 2) 이상 연속 선언할 수 없다. 한도 도달 후 다음 Sprint가 또 `foundational`을 시도하면 비상 스티어링(Step 3) 강제 진입. Sprint 0은 이 카운트에 포함하지 않는다.

**지연 승격 (MANDATORY)**: `foundational` Sprint에 포함된 DoD는 `proposed_done` 상태로만 기록한다(=아직 `done` 승격 불가). 첫 번째 후속 `user_observable` Sprint 완료 시 `agile objective-transition --deferred-promote --sprint {N}` 호출로 누적된 `proposed_done` DoD를 **일괄 `done`으로 승격**한다.

1. Sprint 결과 기록:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{SELECTED_WORK_ITEM}" \
  --completed "{COMPLETED_ITEM_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --sprint-kind {user_observable|foundational} \
  --user-observable-change "{사용자가 이제 할/볼 수 있는 것}" \
  --foundational-reason "{foundational 사유 + 후속 계획}" \
  --sprint-goals '{SPRINT_GOALS_JSON_IF_AVAILABLE}' \
  --previous-lessons "{PREVIOUS_LESSONS}" \
  --json
```
  - `--sprint-kind` 생략 시 기본값 `user_observable`.
  - `--sprint-kind user_observable` → `--user-observable-change` 필수 (비어 있으면 경보 출력).
  - `--sprint-kind foundational` → `--foundational-reason` 필수.
  - 두 종류는 상호 배타 (한 필드만 지정).

1.5. `user_observable` Sprint 완료 시 지연 승격 호출:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} \
  --story {SELECTED_DOD_OR_PLACEHOLDER} \
  --status done \
  --deferred-promote \
  --sprint {CURRENT_SPRINT} \
  --json
```
  - 이 호출은 이번 Sprint가 기여한 DoD를 `done`으로 승격하면서, 이전 foundational Sprint 체인의 모든 `proposed_done` DoD를 역추적하여 일괄 `done`으로 승격한다.
  - 직전 `foundational` Sprint가 없으면 단일 DoD 전이와 동일하게 동작한다 (graceful).
  - `--sprint-goals`는 **optional** (수집 가능한 데이터만 채움): `[{"goal": "...", "status": "achieved|not_achieved|partial", "change_summary": "...", "evidence": {"screenshots": [...], "test_results": {...}, "diff": {...}}}]`

2. 회고 기록:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile retrospective {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --succeeded "{SUCCEEDED_ITEMS}" \
  --failed '{"item":"{ITEM_ID}","cause":"{CAUSE}","attempt":"{ATTEMPT}"}' \
  --velocity-planned {VELOCITY_PLANNED} \
  --velocity-completed {VELOCITY_COMPLETED} \
  --limitations "{LIMITATIONS}" \
  --lessons "{LESSONS_LEARNED}" \
  --direction "{NEXT_DIRECTION}" \
  --json
```
3. known issue 자동 해소 체크:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues list {AGI_ID} --status open --json
python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues resolve {AGI_ID} --issue-id {KI_ID} --json
```
4. DoD 갱신 제안 생성: `{dod_id, suggested_status, evidence_ref, reason}` 형태로 구성. `evidence_ref`는 `result.md`, 테스트/빌드 로그, `source-verify.md` 경로를 포함한다. authoritative 상태 확정(`done`)은 Step 3 승인 절차(3.3)에서만 수행한다.

##### 2.2.4.5 Sprint 종료 정리 (MANDATORY)

Sprint 결과와 회고 기록이 끝나면 브랜치·워크트리 정리를 반드시 수행한다. 이 단계는 Sprint 산출물 기록 이후, Sprint Review Gate 진입 전에 실행한다.

기본 호출:
```bash
CLOSE_JSON=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile sprint-close {AGI_ID} --sprint {CURRENT_SPRINT} --json)
CLOSE_EXIT=$?
CLOSE_STATUS=$(echo "$CLOSE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "parse_error")
```

판정:
- `CLOSE_EXIT == 0`이고 `CLOSE_STATUS`가 `closed` 또는 `already_closed`이면 성공으로 간주한다. `[Sprint Close 완료] status=${CLOSE_STATUS}` 메시지를 출력하고 다음 단계로 진행한다.
- `CLOSE_EXIT != 0`, `CLOSE_STATUS == aborted_tree_mismatch`, `CLOSE_STATUS == partial`, 또는 위 성공 조건 외의 모든 값은 실패로 간주한다.

실패 처리:
```bash
if [ "$CLOSE_EXIT" -eq 0 ] && { [ "$CLOSE_STATUS" = "closed" ] || [ "$CLOSE_STATUS" = "already_closed" ]; }; then
  echo "[Sprint Close 완료] status=${CLOSE_STATUS}"
else
  echo "[Sprint Close 실패] status=${CLOSE_STATUS}. 다음 Sprint의 Step 2.2.1 health check에서 재시도한다."
  MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues add {AGI_ID} \
    --description "sprint-close 실패 (status=${CLOSE_STATUS})" \
    --severity MAJOR \
    --sprint {CURRENT_SPRINT}
fi
```

규칙:
- `agile sprint-close` 호출은 생략할 수 없다. 호출 누락은 Sprint Exit Gate 실패로 본다.
- 실패 시 `|| true`로 숨기지 않는다. known issue 등록 후 다음 Sprint의 Step `2.2.1 프로젝트 건강 점검`에서 재시도 안내를 확인한다.
- 정리 성공 여부는 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprint-log.json`의 현재 Sprint 레코드로 검증한다.

##### Step 2.2.5 Sprint Review Gate (Step 2.2.4 직후 MANDATORY)

Sprint 결과/회고 기록 직후, objective details evidence를 스프린트 게이트로 검증한다.

기본 호출:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile evidence-check \
  --agi-id {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --json
```

판정 규칙 (3-tier):
- `PASS`: evidence 충족, 위반 0건. 즉시 Step 2.2.6으로 진행.
- `WARN`: 차단하지 않음. 경고를 Sprint 메모에 남기고 Step 2.2.6으로 진행.
- `FAIL`: 스프린트 진행 차단. 위반(artifact 미존재, `required_globs` 미충족 등)을 수정한 뒤 `evidence-check`를 재실행한다.

Objective Surface Coverage drift-check (MANDATORY):
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile drift-check \
  --agi-id {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --json
```

drift-check 판정:
- `PASS`: coverage가 threshold 이상. Step 2.2.6으로 진행.
- `WARN`: coverage 미만. 스프린트 메모에 `covered_surface`/`uncovered_surface` 기록 후 계속 진행.
- `ESCALATE`: WARN이 `warn_streak_limit` 이상 연속되면 비상 스티어링 트리거로 간주, Step 3 진입 또는 recall 정책 실행.

drift-check config: `config.agile.drift.enabled=false`면 skip WARN. `config.agile.drift.threshold` 기본값 `0.7`. `config.agile.drift.warn_streak_limit` 기본값 `2`.

recall 트리거 조건 (Level 2 patch만):
- `evidence-check == FAIL`: `python3 {PLUGIN_ROOT}/scripts/mst.py agile recall --agi-id {AGI_ID} --level 2 --reason fail --trigger evidence --json`
- `drift-check ESCALATE`: `python3 {PLUGIN_ROOT}/scripts/mst.py agile recall --agi-id {AGI_ID} --level 2 --reason drift --trigger drift-warn-streak --json`
- `config.agile.recall.enabled=false`면 recall skip + warn, 기존 워크플로우 유지.
- cooldown bypass는 evidence hard fail에서만 허용 (`--bypass-cooldown --fingerprint <hard-fail-id>`). drift 트리거에는 bypass 금지.

`required_globs` 규칙:
- 프로젝트 타입별 `required_globs`는 `config.agile.evidence_gate.required_globs`에서 읽는다.
- 어떤 패턴이든 매치가 0건이면 **hard fail**로 처리한다 (slide-craft 패턴 차단).
- 기본 fallback은 플러그인 타입의 `skills/*/SKILL.md`다.

예외 bypass (긴급 시에만):
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile evidence-check \
  --agi-id {AGI_ID} --sprint {CURRENT_SPRINT} --accept-evidence-gap "{REASON}" --json
```
- `REASON`은 필수다. bypass 사용 시 `.gran-maestro/agile/sprint-log.json`에 사유가 영구 기록된다.

##### 2.2.6 외부 에이전트 소스 검증 (Sprint 완료 후 MANDATORY)

Sprint 완료 직후 `explore`(또는 동등한 코드베이스 탐색)를 실행해 소스를 검증한다.

기본 호출:
```text
Skill(skill: "mst:explore", args: "-a [Source Verification]
AGI: {AGI_ID} / Sprint: {CURRENT_SPRINT}
검증 대상:
1) 이번 Sprint 변경 파일 + 영향 범위
2) 변경 내용이 SELECTED_WORK_ITEM과 일치하는지
3) 테스트/빌드 결과와 코드 변경 정합성
4) 누락된 회귀 위험/사이드이펙트
출력 형식:
- findings: [{severity: CRITICAL|MAJOR|MINOR, title, evidence_ref, fix_hint}]
- verdict: pass|fail")
```

fallback: `mst:explore` 사용 불가 시 `mst:codex` 또는 `mst:claude`를 동일 템플릿으로 호출한다.

검증 루프:
1. 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/source-verify.md`에 기록한다.
2. `verdict=fail` 또는 `CRITICAL|MAJOR` 발견 시: 자동 수정 태스크 생성 → 보완 → 테스트/빌드 재실행 → 소스 검증 재수행.
3. 최대 재시도 **3회**. 초과 시: `AUTO_MODE=true` → `[자동 중단]` 전환. `AUTO_MODE=false` → `AskUserQuestion` 에스컬레이션.
4. `pass` 또는 `MINOR`만 남으면:
```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```
5. `CONTINUATION GUARD`:
  - 위 update 호출 직후 `CURRENT_SPRINT = CURRENT_SPRINT + 1`로 갱신한다.
  - `[CRITICAL][STEERING-CHECK-ON-INCREMENTED-SPRINT]` 증가된 `CURRENT_SPRINT` 기준으로 스티어링 해당 여부를 **반드시 즉시 판정**한다.
  - `STEERING_DISABLED=true` 또는 `STEERING_EVERY == 0`이면 정기 스티어링 skip → Step 2.2.1로 즉시 진행.
  - `STEERING_EVERY > 0`이고 `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0`이면 `[MANDATORY][STEERING-DUE]` Step 3 실행 후 루프 상단으로 복귀.
  - 위 조건 해당 없으면 `[CRITICAL][NO-AD-HOC-PAUSE]` 확인 질문 없이 Step 2.2.1로 즉시 진행.
  - `[CRITICAL][NO-SELF-MOTIVATED-PAUSE]` 스티어링/비상 스티어링 트리거 해당 없는 한 어떤 사유로든 스프린트 간 정지를 절대 금지하고 Step 2.2.1로 즉시 진행한다.

---

#### 2.3 루프 종료 및 최종 보고서

**종료 조건**: `mst.py agile objective-check {AGI_ID} --json` 결과에서 `all_done: true` 반환.

최종 보고서를 출력한다:

```text
========================================
[완료] AGI-{AGI_ID} 자율 스프린트 루프 종료
========================================

총 스프린트 수: {TOTAL_SPRINTS}
완료된 DoD 수: {DONE_DOD} / {TOTAL_DOD}
생성된 PLN 목록: {PLN_IDS}
생성된 REQ 목록: {REQ_IDS}

스프린트 결과 요약:
- 성공: {SUCCESS_COUNT}회
- 실패: {FAIL_COUNT}회

결과 디렉토리: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/
목표 달성 여부: {JTBD_SUCCESS_SUMMARY}
========================================
```

##### 2.3.0 Finalization Gate (MANDATORY)

> 이 Gate가 통과되기 전에는 아래 2.3.1의 state clear를 실행하지 않는다. Gate 실패 시 [비상 스티어링] 진입.

1. Finalization CLI를 단일 호출한다:
   ```bash
   MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile finalize {AGI_ID} --json
   ```
2. exit code 분기:
   - `0`: Finalization Gate 통과. 즉시 2.3.1로 진행한다.
   - `2`: stdout JSON의 `pending_accept_reqs` 각 항목에 대해 `Skill(skill: "mst:accept", args: "-a {REQ_ID}")`를 호출한 뒤, 위 finalize CLI를 재실행한다.
   - 기타 non-zero: 즉시 Step 3(비상 스티어링)으로 진입하고, 2.3 이후 단계를 중단한다.
3. legacy inline 흐름(REQ 상태 확인, worktree cleanup, orphan cleanup, boundary check)은 finalize CLI가 결정론적으로 수행한다.

##### 2.3.1 완료 마킹 및 state clear

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status completed --json
```

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active false \
  --active false \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```

Finalization Gate 통과 및 worktree 정리 완료 확인 후 종료.

---

### Step 3: 스티어링 체크포인트

`[MST skill=agile step=3/4 return_to=null]`

**목표**: 정기 또는 비상 트리거 시 현재 진행 상황과 DoD 제안을 사용자에게 보고하고, approve/reject 및 objective 변경 여부를 반영한 뒤 루프를 계속 진행한다.
**AUTO_MODE=true에서는 이 보고가 사용자 검토를 요청하는 handoff가 아니라 진행 로그 산출물이며, 출력 직후 Step 2.2.1로 즉시 복귀하여 다음 Sprint를 시작한다.** AUTO_MODE=false 경로의 사용자 검토 흐름은 그대로 유지한다.

#### 3.1 트리거 조건

| 유형 | 조건 |
|------|------|
| **정기** | `STEERING_DISABLED != true` AND `STEERING_EVERY > 0` AND `CURRENT_SPRINT > 0` AND `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0` |
| **비상** | 안전장치 섹션의 비상 스티어링 트리거 조건 충족 시 즉시 진입 |

`steering_every` 값은 session.json에서 로드하며 기본값은 3이다. `STEERING_EVERY == 0` 또는 `STEERING_DISABLED == true`이면 정기 스티어링은 비활성화 상태로 간주한다.

#### 3.2 진행 보고서 출력

아래 형식으로 **진행 보고서**를 출력한다:

```text
========================================
[스티어링 체크포인트] AGI-{AGI_ID} — Sprint {CURRENT_SPRINT}
========================================

목표 진행률
- metric 달성률: {METRICS_PROGRESS} (성공 지표 기준)
- 프로젝트 DoD 진행률: {DOD_DONE}/{DOD_TOTAL} 완료

최근 {STEERING_EVERY} 스프린트 요약
| 스프린트 | 계획 | 완료 | 미완료 | 블로커 |
|----------|------|------|--------|--------|
| S{N}     | ...  | ...  | ...    | ...    |

회고 요약 (최근 {STEERING_EVERY} 스프린트)
- lessons learned: {RETRO_LESSONS_SUMMARY}
- limitations 추이: {RETRO_LIMITATIONS_TREND}
- known issues: open {KNOWN_ISSUES_OPEN_COUNT} / resolved {KNOWN_ISSUES_RESOLVED_COUNT}

소스 검증 요약
- pass: {VERIFY_PASS_COUNT}
- fail: {VERIFY_FAIL_COUNT}
- 주요 이슈: {VERIFY_TOP_FINDINGS}

통합 건강 (integration-review + alignment-check)
- 직전 {STEERING_EVERY} Sprint 분류: modify {MODIFY_COUNT} / wire {WIRE_COUNT} / new-island {NEW_ISLAND_COUNT}
- 누적 new-island 비율: {NEW_ISLAND_RATIO:.2%} (임계: {NEW_ISLAND_THRESHOLD:.2%})
- 연속 user_observable Sprint: {USER_OBSERVABLE_STREAK} / 연속 foundational: {FOUNDATIONAL_STREAK} (한도 {FOUNDATIONAL_STREAK_MAX})
- proposed_done 대기 DoD: {DEFERRED_DOD_COUNT}건 (다음 user_observable Sprint 완료 시 일괄 승격 예정)
- alignment 판정: aligned {ALIGNED_COUNT} / drift_warning {DRIFT_WARNING_COUNT} / objective_stale {OBJECTIVE_STALE_COUNT}
- Escape Hatch override: {ESCAPE_OVERRIDE_COUNT}건 {ESCAPE_REASONS}

DoD 체크 갱신 제안 (pending)
| DOD-ID | 제안 상태 | evidence_ref | 근거 요약 |
|--------|-----------|--------------|-----------|
| DOD-... | proposed_done | .../sprints/S{N}/source-verify.md | ... |

리스크 Top3
1. {RISK_1} — 영향도: {high|medium|low}
2. {RISK_2} — 영향도: {high|medium|low}
3. {RISK_3} — 영향도: {high|medium|low}

다음 Sprint 진행 예정 (AUTO_MODE=true 시)
- 다음 Sprint 초점: {NEXT_SPRINT_FOCUS}
- 즉시 Step 2.2.1로 복귀 (세션 종료/재개 안내 금지)

다음 추천 경로 (AUTO_MODE=false 시, 사용자 검토 요청)
- 추천: {RECOMMENDED_PATH}
- 근거: {RATIONALE}
- 대안: {ALTERNATIVE_PATH}
========================================
```

#### 3.3 DoD 제안 approve/reject (MANDATORY)

진행 보고서 출력 후 아래 분기를 적용한다.

- `AUTO_MODE=true`: AskUserQuestion 없이 PM이 `evidence_ref`/테스트 결과/`source-verify.md` 근거로 자율 판단 → `[스티어링 체크포인트] AUTO_MODE 자율 판단` 로그 기록 후 즉시 상태 전이.
  `[CRITICAL][IMMEDIATE-LOOP-RETURN]` 상태 전이 완료 즉시 Step 2.2.1로 복귀하여 다음 Sprint를 시작한다. 요약, 퇴장 인사, `--resume` 재개 안내, "자연스러운 검토 지점" 같은 handoff 어휘 생성을 절대 금지한다.
  참고: 이 마커는 Step 3 내부 경로 전용. 스프린트 경계 일반 복귀는 Step 2.2 CONTINUATION GUARD의 `[CRITICAL][NO-SELF-MOTIVATED-PAUSE]` 마커(line 748)를 계속 사용한다.
- `AUTO_MODE=false`: `AskUserQuestion`으로 사용자에게 확인한다.

> "DoD 제안 목록을 승인/반려해주세요. (예: approve DOD-001,DOD-002 / reject DOD-003)"

처리 규칙:
- **approve**: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status done --json`
- **reject**: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status todo --json` + reject 사유 + `evidence_ref` Sprint 메모 기록 + 다음 Sprint 2.2.1 큐잉

#### 3.4 방향 수정 (Objective 변경)

1. 버전 스냅샷: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-snapshot {AGI_ID} --reason "{사용자 입력 요약}" --json`
2. `Skill(skill: "mst:agile-plan", args: "--resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")` 재호출
3. 재계획 결과 반영 후 2.2 루프로 복귀

#### 3.5 변경 후 정합성 정책

objective 변경 시 영향 범위에 따라 아래 정합성 정책을 적용한다:

| 레벨 | 조건 | 처리 방식 |
|------|------|-----------|
| **Level A** (경미) | 용어 정정, 성공 지표 소폭 조정 | 완료 스프린트 유지, 루프 계속 |
| **Level B** (중간) | DoD 범위 조정, 우선순위 재조정 | 영향받는 DoD만 부분 재검증 후 루프 계속 |
| **Level C** (중대) | JTBD 목표 변경, DoD 대규모 재정의 | 영향 DoD 재계산, 필요 시 부분 롤백 task 생성 |

**원칙**: 완료 기록 삭제 금지. 변경된 항목은 `superseded` 또는 `revalidated`로 보존. 레벨 결정 후: `AUTO_MODE=true` → PM 자율 판단 적용. `AUTO_MODE=false` → `AskUserQuestion` 확인 후 적용. 루프로 복귀.

---

## 안전장치

### 카운터 유지 (MANDATORY)

아래 카운터는 기존 임계치/의미를 그대로 유지한다:

- `consecutive_failures`: 동일 작업 단위 연속 실패 횟수
- `drift_count`: 목표와 무관한 변경 누적 횟수
- `no_diff_count`: 실행 후 diff 없음 누적 횟수

### 4단계 복구 전략

작업 실패 발생 시 아래 레벨 순서로 복구를 시도한다. Level N 실패 시 Level N+1로 에스컬레이션.

| 레벨 | 이름 | 조건 | 처리 |
|------|------|------|------|
| **Level 0** | 자동 재시도 | transient failure (네트워크, 타임아웃 등 일시적 오류) | 동일 작업 1회 자동 재시도 |
| **Level 1** | 작업 분해 | scope 과대 (DoD 작업 범위가 너무 큼) | plan -a에 더 작은 단위로 분해 요청 후 재시도 |
| **Level 2** | 스킵 + blocked | 외부 의존성 미해소 | 현재 작업 단위를 `blocked` 상태로 마킹하고 다음 단위로 이동 |
| **Level 3** | 비상 스티어링 | Level 0~2로 해결 불가 또는 자동 중단 트리거 발동 | 사용자 개입 요청 → Step 3 강제 진입 |

복구 절차: 실패 감지 → 유형 분류 (transient/scope/external/unknown) → 해당 Level 복구 시도 → 성공 시 루프 재진입, 실패 시 다음 Level 에스컬레이션.

### Drift 감지

**정의**: 스프린트 결과물이 objective.md의 활성 DoD 항목과 **관련성**이 없는 경우.

**감지 시점**: 매 스프린트 완료(2.2.6 소스 검증 통과 직후) 수행.

> **Agile config fallback (MANDATORY)**: drift_threshold, drift_count_trigger, no_diff_count_trigger는 `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.drift_threshold agile.drift_count_trigger agile.no_diff_count_trigger)` 결과를 우선 사용하고, 없으면 기본값(80, 2, 2)을 사용한다.

**감지 절차**:

1. 변경된 파일 목록 추출 (`git diff --name-only`)
2. 활성 DoD와 변경 파일의 관련성 확인. 관련 없는 변경이 80% 이상인 경우: **drift 경고**
3. **형태 정합성 검증** (관련성 체크 직후, MANDATORY): DoD 항목에서 `DELIVERABLE_SHAPE_EXPECTED`를 추출하여 `DELIVERABLE_SHAPE_OBSERVED`와 LLM 판단으로 비교. 미부합 시 `[형태 불일치]` 태그 추가. DoD/산출물 정보 없으면 skip (graceful fallback).
4. drift 감지 시 아래 메시지 출력:
```text
[drift 감지] Sprint {N}
- 변경 파일: {파일 목록}
- 목표 단위: {WORK_ITEM_ID} — {WORK_ITEM_TITLE}
- 관련성: 관련|무관
- 형태 정합성: 부합|미부합|정보부족
- 태그: [형태 불일치]|(없음)
- 판정: 정상|경고|비상
```
5. **연속 2회 이상** drift 경고 발생 시: 비상 스티어링 트리거 → Step 3 즉시 진입

### 자동 중단 트리거

아래 조건 중 하나 이상 충족 시 루프를 즉시 중단하고 비상 스티어링을 실행한다:

| 조건 | 기준 |
|------|------|
| **연속 실패** | 동일 작업 단위에 대해 **연속 2회 실패** (`consecutive_failures`) |
| **누적 실패율** | 전체 스프린트 중 실패율 **50%** 이상 (최소 4 스프린트 이후 적용) |
| **무의미 루프** | **diff 없음** **2회 연속** (plan 실행 후 변경 파일 없음, `no_diff_count`) |
| **비용 cap** | 누적 **비용**/토큰 사용량이 session.json의 `cost_cap` 값 초과 |

자동 중단 발생 시:

```text
[자동 중단] AGI-{AGI_ID} — 중단 조건 충족: {REASON}
현재까지 결과: {DONE_ITEMS}/{TOTAL_ITEMS} 항목 완료
재개하려면: /mst:agile --resume {AGI_ID}
```

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active false \
  --active false \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```

`python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status paused --json` 실행 후 종료.

### 비상 스티어링 트리거

정기 체크포인트 외에 아래 조건에서 **Step 3을 즉시 강제 트리거**한다:
- `EMERGENCY_STEERING_ENABLED == false`이면 본 섹션 전체를 skip하고 비상 스티어링 강제 진입을 수행하지 않는다.

| 트리거 조건 | 설명 |
|-------------|------|
| 연속 실패 2회 (자동 중단 이전) | 자동 중단 직전 사용자 개입 기회 제공 (`consecutive_failures`) |
| blocked DoD 누적 50% 이상 | 절반 이상의 DoD가 blocked 상태 |
| drift 감지 연속 2회 | 변경 파일과 objective 관련성 80% 미달 연속 (`drift_count`) |
| Level 3 복구 에스컬레이션 도달 | 4단계 복구 최상위 레벨 도달 |

비상 스티어링 진입 시:
1. `[비상 스티어링] 조건: {TRIGGER_REASON}` 출력 후 Step 3으로 진입
2. Step 3.2 진행 보고서 즉시 출력
3. 사용자 개입 분기:
```text
[비상 스티어링] 자동 진행이 중단되었습니다. 트리거: {TRIGGER_REASON}

선택:
1) 계속 진행 (해당 DoD blocked 처리 후 다음 DoD)
2) objective 수정 (Step 3.4 방향 전환)
3) 완전 중단
```
   - `AUTO_MODE=true`: AskUserQuestion을 skip하고 PM이 위 1~3 중 하나를 자율 판단해 즉시 실행한다.
   - `AUTO_MODE=false`: `AskUserQuestion`으로 사용자 개입을 요청한다.
4. 사용자 응답에 따라 분기: **계속 진행** → DoD `blocked` 처리 후 다음 DoD. **objective 수정** → Step 3.4 후 루프 재진입. **완전 중단** → session `paused` 저장 후 종료.

---

## 상태 전이 규칙 (CRITICAL)

### 유효 상태 전이

| 엔티티 | 유효 전이 |
|--------|----------|
| DoD | `todo → proposed_done → done`, `proposed_done → todo`(reject), `todo → blocked → todo|proposed_done` |
| Session | `active → paused → completed`, `active → completed` |

**LLM은 objective.md를 절대 직접 편집하지 않습니다.**

모든 상태 변경은 아래 mst.py 스크립트 명령어로만 수행합니다:

| 작업 | 명령어 |
|------|--------|
| DoD 상태 변경 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status {todo\|proposed_done\|in_progress\|done\|blocked}` |
| 완료 여부 전체 확인 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json` |
| 세션 상태 업데이트 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status {active\|paused\|completed}` |
| 스프린트 결과 기록 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} ...` |

**이유**: LLM YAML/Markdown 파싱 오류 누적 방지 및 상태 파일 무결성 보장. (DSC-044 critic 합의)

---

## Anti-Rationalization Checklist

- 합리화 패턴: "간단한 목표니 Step 1 절차를 생략해도 된다." | 확인 증거: Step 1에서 `Skill(skill: "mst:agile-plan", ...)` 호출 로그와 반환 마커가 존재.
- 합리화 패턴: "objective.md가 이미 있으니 직접 편집해도 된다." | 확인 증거: 상태 변경 시 항상 `mst.py agile objective-transition` 실행 로그 존재.
- 합리화 패턴: "Step 0 없이 바로 생성으로 진행해도 된다." | 확인 증거: `mst.py agile status`(resume) 또는 `mst:agile-plan`(신규) 실행 로그가 Step 0~1 흐름에 존재.
- 합리화 패턴: "대략 N 스프린트면 되니 계획/보고에 넣어도 된다." | 확인 증거: objective.md, plan 입력, 중간/스티어링 보고 산출물 전체에서 스프린트 횟수 예측 문구 0건.
- 합리화 패턴: "횟수가 아니라 규모/기간 추정이므로 허용된다." | 확인 증거: 캘린더 변환/반복 횟수 암시 표현이 산출물 전체에서 0건.
- 합리화 패턴: "이번 스프린트는 바쁘니 스티어링 해당이어도 Step 3을 건너뛰자." | 확인 증거: 스티어링 해당 시점마다 `[MANDATORY][STEERING-DUE]` 로그와 Step 3 실행 기록이 존재.
- 합리화 패턴: "스티어링 미해당이지만 한 번 더 계속 여부를 묻자." | 확인 증거: 미해당 스프린트 로그에서 `"계속할까요?"`, `"멈출까요?"` 질문이 0건이고 Step 2.2.1로 즉시 진행한다.
- 합리화 패턴: "컨텍스트 한계에 도달했으니 체인을 건너뛰고 직접 codex로 끝내자." | 확인 증거: 체인 우회가 필요한 경우 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 사용 로그가 `auto-decisions.md` 또는 `retrospective.md`에 남아있어야 한다.
- 합리화 패턴: "컨텍스트가 길어졌으니/자연스러운 단락이니 여기서 끊자." | 확인 증거: `mst-stop-hook.sh`가 해당 턴을 block으로 판정해야 하며, LLM은 block 수신 시 즉시 다음 tool call을 emit한다(정지·요약·확인 질문 금지).
- 합리화 패턴: "Sprint 경계에서 WIP/stash/squash 부담을 이유로 agile update --status paused를 호출해 루프를 종료한다." | 확인 증거: `MST_AGILE_PAUSE_AUTHORIZED=1` 또는 `--user-requested` 플래그 없이 active→paused 전이를 시도하면 mst.py가 exit≠0으로 차단한다. 해당 호출 0건 또는 차단 로그 존재.
- 합리화 패턴: "Sprint 간 '자연스러운 단락'이라며 paused 상태 전이 명령으로 정지를 달성한다." | 확인 증거: stop-hook이 `[CRITICAL][SELF-PAUSE-DETECTED]` 마커로 block을 재-emit하고, LLM은 block 수신 즉시 다음 tool call을 emit한다 (상태 전이 명령 재호출 금지).
- 합리화 패턴: "Step 3 스티어링 보고를 출력했으니 이 지점은 사용자 검토에 자연스러운 단락이다. 다음 Sprint는 `--resume`으로 새 세션에서 재개하도록 안내하자." | 확인 증거: `contains_self_pause_rationalization`이 'handoff framing' 정규식으로 해당 문장을 block으로 재-emit하고, LLM은 block 수신 즉시 Step 2.2.1로 복귀하는 tool call을 emit한다.
- 합리화 패턴: "Sprint 진입 시점을 모델이 자체 페이싱(ScheduleWakeup 호출)으로 결정한다." | 확인 증거: PreToolUse hook이 ScheduleWakeup을 block한 audit 로그 기록 또는 차단 마커 존재.
- 합리화 패턴: "Sprint 종료 시 cleanup을 '시간 절약'을 이유로 생략한다." | 확인 증거: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprint-log.json`에 현재 Sprint 레코드 존재.
