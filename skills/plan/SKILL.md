---
name: plan
description: "사용자가 $mst:plan 또는 /mst:plan을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 plan 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "{플래닝 주제 또는 해결하고 싶은 질문/문제}"
---

# maestro:plan

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

<!-- mst-session-class: identity-required; root-source: existing PLN argument or new pln allocation -->

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

**목적**: 어떤 질문이나 문제를 다루든, *그 해결책을 어떻게 접근할 것인지*에 대한 계획을 수립합니다.
사용자와 Q&A 대화를 통해 모호성을 제거하고, 합의된 결정사항을 `templates/plan.md` 형식의 plan.md로 저장합니다.

핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.md`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/auto-decisions.md`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/ambiguity-log.md`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/clarification-questions.md`
- `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` (status/consumed_at/linked_plan 업데이트용)

**그 외 모든 경로에 대한 Write/Edit 사용은 절대 금지입니다.**

- Stitch 관련 작업은 반드시 `Skill(skill: "mst:stitch", args: "...")`를 통해 실행한다.
- 허용 경로 외 수정 요청 시: 즉시 중단 → "plan.md에 기록합니다" 알림 → 의도를 plan.md 요구사항 섹션에 흡수

## Gate

### Entry

- `/mst:plan` 호출 시 주제 성격과 무관하게 Step 0.1~4 전체 프로토콜을 실행 대상으로 잠근다.
- 시작 전에 Write/Edit 허용 경로가 `PLN-*` 산출물 및 `CAP-*` 상태 갱신 경로인지 확인한다.
- `AUTO_MODE=false`이면 최소 1회 Q&A 또는 `AskUserQuestion` 기반 분기 근거를 확보한다.

### Exit

- `plan.md`와 `plan.json`이 생성되고 저장 경로/ID(PLN-NNN)가 확정되어야 종료할 수 있다.
- `저장하고 /mst:request 실행` 경로는 `plan.md` 디스크 저장 확인 후 1회만 호출한다.
- 어떤 종료 경로든 사용자에게 보이는 마지막 마무리는 반드시 `다음 단계 실행 명령:` 블록으로 끝난다.
  - `저장만 하기`: `/mst:request --plan PLN-NNN` 및 `/mst:request --plan PLN-NNN -a`
  - `mst:request`까지 실행 완료: 생성된 REQ가 있으면 `/mst:approve REQ-NNN`, REQ를 특정하지 못하면 `/mst:list`
  - 계획 후보 미선택/후보 없음 등 plan 산출물 없이 종료: `/mst:plan "{계획 주제}"`
  - 마지막 줄 뒤에 추가 설명, 인사, 요약을 붙이지 않는다.
- 범위 밖 수정 요청은 plan 요구사항으로 흡수 기록하고 코드/설정 파일은 수정하지 않는다.

### 금지 패턴

- "단순하니 plan 생략/축약"을 이유로 Step 0.1~4를 건너뛴다.
- `plan.md` 저장 전에 `mst:request` 호출 또는 직접 구현(코드 수정)으로 전환한다.
- `mcp__stitch__*`를 직접 호출해 스킬 경유 규칙을 우회한다.
- "컨텍스트 압박"을 이유로 sub-plan chain을 우회하여 직접 `codex exec` + master 커밋으로 전환한다. 격리 실행이 필요하면 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 경로를 사용한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "요구사항이 명확해 보이니 Cynefin 분류를 생략해도 된다." | 확인 증거: PM이 분류한 Cynefin 도메인과 적용 전략을 한 줄 통지로 출력한다.
- 합리화 패턴: "질문 없이도 충분하니 Q&A를 건너뛰자." | 확인 증거: `AskUserQuestion` 실행 로그 또는 `auto-decisions.md`의 대응 결정 항목을 남긴다.
- 합리화 패턴: "파일 저장 확인은 생략하고 다음 스킬로 넘어가자." | 확인 증거: `plan.md` 저장 경로와 실행 분기(`저장만/요청 실행`)를 명시한다.
- 합리화 패턴: "WebSearch 결과를 표로 정리했으니 REF 저장은 생략해도 된다." | 확인 증거: WebSearch 실행 횟수와 동일한 횟수의 `Bash(mst.py reference add ...)` 호출 로그가 존재한다.
- 합리화 패턴: "컨텍스트 한계에 도달했으니 체인을 건너뛰고 직접 codex로 끝내자." | 확인 증거: 체인 우회가 필요한 경우 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 사용 로그가 `auto-decisions.md` 또는 `retrospective.md`에 남아있어야 한다.
- 합리화 패턴: "컨텍스트가 길어졌으니/토큰 효율을 위해/변경 추적 품질을 위해 다음 단계를 새 세션에서 진행하는 게 낫다." | 확인 증거: 자동 연쇄 진입 컨텍스트 블록의 수치(context_pct, auto_approve_on_unblock)를 인용하여 chain 지속이 정상 경로임을 명시한 뒤 다음 스킬을 자동 호출한다.

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

<!-- @include _shared/user-input-boundary.md -->
### User Input Boundary (MANDATORY)

사용자 입력이 필요한 지점에서는 host별 질문 도구를 직접 판단하지 말고 `question prepare`를 먼저 호출한다. 이 규칙은 기존 `AskUserQuestion` 직접 호출 지시보다 우선한다.

1. 질문 payload를 JSON 파일로 작성한다. 구조는 `templates/question-payload.schema.json`을 따른다.
2. 아래 CLI를 호출한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py question prepare \
     --skill {CURRENT_SKILL} \
     --step "{CURRENT_STEP}" \
     --resume-skill {CURRENT_SKILL} \
     --resume-args "{RESUME_ARGS}" \
     --payload-file {QUESTION_PAYLOAD_JSON} \
     --json
   ```
3. 반환값에 따라 분기한다.
   - `mode=claude_tool`: 반환된 `payload`로 `AskUserQuestion`을 호출한다.
   - `mode=pending_artifact`: 반환된 `user_message`를 사용자에게 보여주고 종료한다. 이 상태는 정상적인 사용자 입력 대기이며 임의 중단이 아니다.
   - `mode=auto_decision`: `AUTO_MODE=true` 경로로 질문 없이 계속하거나 blocker를 기록한다.
4. Codex/headless host에서는 `AskUserQuestion`을 직접 호출하지 않는다. pending question은 `.gran-maestro/questions/Q-*.json`에 저장되고 `/mst:resume --answer Q-...`로 재개한다.
5. workflow 중 임의 확인 질문이나 self-pause는 계속 금지한다. 정상 질문은 `question prepare`가 기록한 `awaiting_user_input` 상태와 payload hash가 일치할 때만 허용된다.
<!-- @end-include -->

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (User Input Boundary 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 User Input Boundary 질문 payload와 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->

<!-- @include _shared/reference-lookup.md -->
### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인한다. `true`일 때만 자동 WebSearch를 허용한다. 설정 미존재 시 기본값은 `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**: 현재 단계 입력에서 외부 의존성 키워드를 감지한다. `reference.llm_auto_trigger == true`이면 PM이 최신 정보가 필요하다고 판단할 때도 WebSearch를 트리거한다. `false`이면 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**: (a) `.gran-maestro/references/` 캐시를 `reference search --keyword "{keyword}" --json`으로 확인, (b) `searched_at + cache_ttl_days` 기준 `fresh/stale` 판정, (c) 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired` 판정.
3. **WebSearch 트리거**: 캐시 없음 또는 `stale/expired`일 때만 검색한다. `reference.auto_search == true`일 때만 실행하고 Step당 `max_searches_per_step`을 넘지 않는다. `reference.auto_fact_check == true`이면 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**: WebSearch를 1건이라도 실행했으면 결과마다 `Bash`로 `mst.py reference add`를 호출한다. 표/텍스트 결론 요약만으로는 저장 완료가 아니며 `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 예시 A (인용): `> 인용: "{원문 핵심 문장}" (출처: {URL}, 날짜: {YYYY-MM-DD})`
   - 예시 B (표): `| 열 | 값 |` 형태의 raw markdown table과 출처 URL을 보존한다.
   - 예시 C (코드 스니펫): fenced code block(```text)으로 raw 코드와 문서 URL/버전을 남긴다.
   - 신규 REF 품질 체크리스트 (저장 전 점검): Findings: 결론 1~3줄. Quotes: 짧은 원문 인용+URL. Data: 표/버전/날짜/수치. Context: 현재 plan 판단에 필요한 이유.
   - PM lazy-Read 트리거 (`content.md Read` 필수): summary만으로 부족하거나 표/코드/원문 뉘앙스가 결론에 영향을 주면 반드시 `content.md`를 Read한다.
5. **프롬프트 주입**: 이후 단계 프롬프트에 `[REFERENCE_CONTEXT]`를 주입한다. 형식: `current_date`, `model_cutoff`, `references: REF-001 (fresh|stale|expired) {topic} | {url}`. 참조가 없으면 `references: none`으로 명시한다.
<!-- @end-include -->

#### Plan-specific Reference Guidance

1. **키워드 감지 보강**: plan 텍스트(요청, 주제, 미결 항목, ideation 입력)에서 `library/framework/api/sdk/protocol/version/dependency` 및 한국어 동의어를 감지. 감지 키워드가 없고 `reference.llm_auto_trigger == false`이면 검색 생략.
2. **3단계 신선도 체크 보강**: 키워드별 반복 수행. (a) `mst.py reference search --keyword "{keyword}" --json`으로 조회. (b) `cache_ttl_days` 이내: `fresh`, 초과: `stale`. (c) `cutoff_threshold_months` 초과 시 `expired` 승격.
3. **WebSearch 트리거 보강**: `stale/expired` 항목만 검색 대상. `auto_search == true`일 때만 실행, `max_searches_per_step` 초과 금지.
4. **REF 저장 확장**: WebSearch N건 → `mst.py reference add` 최소 N회 (1:1 대응). `summary`는 한 줄 인덱스, `content.md`는 원문 근거.
5. **프롬프트 주입 보강**: 이후 의사결정 프롬프트(질문 생성, ideation/discussion 호출 인자)에 `[REFERENCE_CONTEXT]`를 주입. `model_cutoff`는 현재 모델 cutoff 문자열(미확인 시 `unknown`).

### Step 0.5: 디버그 의도 감지 & 자동 실행

이 단계는 문서 최상단의 bootstrap/resolve가 성공한 뒤에만 `mst:debug`를 호출합니다. parent full SID와 shell-safe context를 child invocation에 그대로 바인딩하며 debug child가 별도 identity를 발급하게 두지 않습니다.

**`--from-debug DBG-NNN` 직접 진입:** `debug/DBG-NNN/debug-report.md` Read (미존재 시 경고 후 Step 1) → `debug_context` 활성화(`linked_debug_id`, `root_cause`, `fix_suggestions`, `affected_files`) → Step 1로 진행

**키워드 기반 감지 (`--from-debug` 없는 경우):** 버그/에러/오류/안됨/고쳐/crash/타임아웃 등 감지 시:
1. "디버그 의도 감지, /mst:debug 먼저 실행" 통지
2. `Skill(skill: "mst:debug", args: "{이슈}")` 즉시 실행 (`--focus` 있으면 envelope 앞에 전달). Debug child는 이 exact parent binding을 resolve한 뒤에만 진행한다.
3. `debug-report.md` 완료 대기 후 Read → `debug_context` 보관 (DBG ID/근본 원인/수정 제안 P0~P2/영향 파일)
4. Step 1~2로 진행 시 `debug_context` 활성 상태 유지

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

**미감지 시:** Step 1로 진행.

**`--from-picks` 감지 (--from-debug 처리 후 실행):**

`--from-picks [CAP-001] [CAP-003] "요청 텍스트"` 형태 파싱:
1. `--from-picks` 뒤의 `[CAP-NNN]` 패턴을 모두 추출 → `capture_ids` 배열 보관
2. 각 `capture_ids`에 대해 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json` Read. 미존재 시 경고 후 건너뜀, 이미 `consumed` 상태이면 경고 표시 후 재사용 허용.
3. 성공적으로 Read한 캡처 데이터를 `capture_context` 배열에 보관 (ID, url, selector, memo, screenshot 등)
4. `--from-debug`와 동시 입력 시: `--from-debug` 우선 처리(debug_context) → `capture_context`는 보조 컨텍스트로 유지
5. `--from-picks` 미사용 시: `capture_context`는 빈 배열 (하위 호환)

### Step 0.75: [CAP-NNN] 자동 감지 (Step 0.5 직후)

Step 0.5 처리 완료 후, 사용자 입력 텍스트 전체에서 `/\[?CAP-\d{3,}\]?/gi` 패턴 매칭:
1. Step 0.5에서 이미 `capture_context`에 보관된 ID는 중복 Read 하지 않음
2. 신규 매칭 ID만 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json` Read. 미존재 시 경고 후 건너뜀, `consumed` 상태이면 경고 후 재사용 허용.
3. `capture_context`에 합집합 처리 (ID 기준 중복 제거)
4. 캡처가 5개 초과 시 요약 모드: ID + memo + screenshot_path만 보관 (html_snapshot 생략)
5. 매칭 결과 없으면 `capture_context`는 Step 0.5 상태 유지

### 세션 중 자율 모드 전환 (공통)

**어느 Step이든** 사용자 응답에서 다음 패턴 감지 시 즉시 `AUTO_MODE=true`로 전환:
- 자연어 예시: "auto로 해줘", "자율 모드로", "-a로 해줘", "지금부터 자동으로", "이제 auto로"
- 전환 즉시: `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력
- `AskUserQuestion` 대기 중이었다면: 대기를 종료하고 현재 단계부터 `AUTO_MODE=true` 적용하여 재개
- `AUTO_DECISION_TOTAL`, `AUTO_PM_COUNT` 등 카운터가 미초기화 상태이면 `0`으로 즉시 초기화

### Step 0.1: 자율 모드 감지

1. args 전체 토큰에서 `-a` 또는 `--auto` 존재 여부 검사. 하나라도 있으면 `AUTO_MODE=true`, 없으면 `AUTO_MODE=false`.
2. `AUTO_MODE=false`인 경우 state guarded fallback 시도: `read_workflow_state_auto_mode("mst:plan")` 호출. 반환값이 bool이면 채택, `None`이면 Step 3(config fallback)으로 진행.
3. config preload: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get auto_mode.plan auto_mode.confidence_threshold --json)` 결과를 `plan_auto_mode_config`로 보관한다. 키가 없으면 `Read(templates/defaults/config.json)` fallback.
4. `plan_auto_mode_config`의 `auto_mode.plan == true`면 `AUTO_MODE=true`. `auto_mode.confidence_threshold`를 읽어 `CONFIDENCE_THRESHOLD`에 저장하고, 미설정 시 기본값 `0.7`을 사용한다. CLI 플래그가 config보다 우선.

### Step 0.8: Args intent 판별 (MANDATORY)

> 목적: `/mst:plan` 호출 자체가 계획 의도 신호이지만, args 본문이 항상 계획 주제인 것은 아니다. 메타/질문/모호한 args를 계획 주제로 오해하지 않도록 PM이 자율 판별한다. Step 0.5(디버그)·0.75(CAP) 이후에 실행한다.

1. PM이 args 본문을 읽고 아래 둘 중 하나로 자율 분류한다.
   - **topic**: 계획 주제로 해석 가능한 경우 (예: "로그인 흐름 개선", "결제 모듈 리팩터링")
   - **meta**: 스킬·코드·사용자 질문이거나 주제가 모호한 경우 (예: "plan 스킬 이렇게 바꾸면?", "이 코드 설명해줘", "plan이 뭐야?")

   `debug_context` 또는 `capture_context`가 활성이면 이미 주제가 성립한 것으로 보고 `topic`으로 간주한다. 판별 기준은 규정하지 않고 PM 자율 판단에 맡긴다.

2. **topic 판정**: args 본문을 plan 주제로 삼아 Step 1로 진행한다.

3. **meta 판정**:
   1. 사용자가 실제로 요청한 동작(답변·설명·소규모 조사·코드 리뷰 등)을 먼저 수행한다.
   2. 수행 결과를 바탕으로 **파생 가능한 계획 후보 1~3개**를 선제시한다.
      - 형식: `[계획 후보] 1) {후보1 주제} 2) {후보2 주제} 3) {후보3 주제}`
      - 후보가 도출되지 않으면 "계획 가능한 후속 작업이 도출되지 않았습니다"만 출력하고 종료한다.
   3. `AUTO_MODE=false`: `AskUserQuestion`으로 후보 중 선택받거나 UI 자동 Other로 직접 주제 입력받아 Step 1로 진입한다. 명시 선택지에는 `"A. 후보 주제"`, `"B. 계획 없이 종료"`처럼 의미 있는 label을 사용한다.
   4. `AUTO_MODE=true`: PM이 최유력 후보 1건을 자율 선택하여 Step 1로 진입한다. 선택 근거를 Step 1에서 초기화되는 `auto-decisions.md`에 함께 기록한다. 후보 도출 불가 시 종료한다.
5. `workflow.high_pass_guard`를 읽어 `HIGH_PASS_GUARD`에 저장 (미설정 시 기본값: `enabled=true`, `confidence_supporting_only=true`, `require_external_execution_evidence=true`, `require_independent_judgement=true`, `block_self_report_only_pass=true`, `plan_bypass_requires_explicit_rationale=true`).
6. 우선순위: `args > state(guarded) > config > default(false)`.
7. `AUTO_MODE=true`이면 아래 초기값을 메모리에 보관:
   - `AUTO_DECISION_TOTAL=0`, `AUTO_PM_COUNT=0`, `AUTO_DISCUSSION_COUNT=0`, `AUTO_EXPLORE_DISCUSSION_COUNT=0`
   - `[자율 모드 활성화] confidence threshold: {CONFIDENCE_THRESHOLD}` 출력

### Step 1: 초기화

State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

Parent session inheritance contract: child invocation, subprocess, and hook execution inherit parent `MST_SESSION_ID`; children must not issue arbitrary `mst_session_id`. Hook payload `mst_session_id` is allowed only when it matches the inherited parent `MST_SESSION_ID`.

1. 문서 최상단의 canonical bootstrap/resolve와 shell-safe context 캡처가 성공했는지 확인합니다. 미완료이면 중단합니다.
2. canonical root가 `PLN-NNN`이면 bootstrap 결과의 `CANONICAL_ROOT_MST_ID`를 PLN 번호로 그대로 사용합니다. 상속된 parent root가 다른 namespace일 때만 `MST_BOUND_SUBPROCESS`의 `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type pln`으로 child PLN 번호를 한 번 예약합니다.
3. `{PROJECT_ROOT}/.gran-maestro/plans/`와 `PLN-NNN/` 디렉토리를 생성합니다.
4. bootstrap이 먼저 만든 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.json`을 Read하고 Canonical Root Metadata Merge 계약으로 아래 workflow 필드를 병합합니다:

   > ⏱️ **타임스탬프 취득 (MANDATORY)**:
   > `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
   > 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
   > 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

   ```json
   {
     "id": "PLN-NNN",
     "title": "플랜 주제",
     "status": "active",
     "created_at": "{TS — mst.py timestamp now 출력값}",
     "linked_requests": []
   }
   ```

4.5. `AUTO_MODE=true`이면 워크플로우 state를 즉시 기록한다 (non-blocking). 이 호출은 방금 작성한 `plan.json`에 canonical session metadata를 병합한다:

   ```bash
   MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
   MST_CONTEXT_JSON="$(
     MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
     python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
   )" \
   python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
     --active true --skill mst:plan --req "" --next-skill mst:request \
     --next-source PLN-NNN --source-skill mst:plan --auto true \
     --root-mst-id PLN-NNN \
   || echo "[mst:plan] warning: failed to update workflow state" >&2
   ```

5. `AUTO_MODE=true`이면 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/auto-decisions.md`를 즉시 초기화:

   ```markdown
   # 자율 결정 로그 — PLN-NNN

   > 자율 모드(-a)로 실행됨. 아래 항목들이 PM에 의해 자율 결정되었습니다.

   | 항목 | 결정값 | Confidence | 판단 방식 | 강제 여부 |
   |------|--------|-----------|-----------|-----------|
   ```

   `강제 여부` 값은 `강제(L1)` 또는 `자율`만 사용한다.

### Step 1.2: Cynefin 도메인 분류 & 전략 제안 (MANDATORY)

PM이 요청을 아래 기준으로 4개 도메인 중 하나로 분류한다.

| 도메인 | 신호 | plan 전략 |
|--------|------|-----------|
| Simple | 기존 패턴 직접 적용 가능, 범위 명확, 유사 구현 전례 다수 | 모호성 루프 간소화 가능 (plan 자체 스킵 금지) |
| Complicated | 전문가 분석 필요, 접근법 2~3가지 후보, 트레이드오프 있음 | Step 2.5(ideation/discussion) 적극 권장 |
| Complex | 정답 불명확, 실험 필요, 탐색적 성격, 범위 유동적 | REQ 분리(Step 3.5) 강력 권장, 단계적 탐색 제안 |
| Chaotic | 버그/장애/긴급 상황, 즉각 대응 필요 | /mst:debug 먼저 실행 후 plan 재개 안내 |

**AUTO_MODE 공통**: PM이 자율 분류하고 결과+전략을 한 줄 통지로 출력한 뒤 다음 Step 진행. AskUserQuestion으로 도메인 선택 묻지 않음. 사용자 이의 시 자연어 응답으로 재분류.

통지 포맷: `[Cynefin: {도메인}] {적용 전략 요약}`

Cynefin 자동 분류 보조 규칙: 트레이드오프 신호(대안 비교/장단점 균형/우선순위 충돌) · 외부 의존성 신호 · 비결정적 표현 신호 중 1개라도 감지되면 `Complicated` 이상으로 자동 플래그. `Simple`로 분류했더라도 자동 플래그 존재 시 Step 2.5의 `discussion` 실행 권장하고 근거를 auto-decisions.md에 기록.

`plan.json` 저장: `"cynefin_domain": "simple" | "complicated" | "complex" | "chaotic"` 필드 추가.

**AUTO_MODE=true 추가 동작**: auto-decisions.md에 분류 근거 기록.

### Step 1.5: 유사 Plan 참조 (선택적)

1. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json` 목록 조회 → 각 `title`과 현재 요청 주제 비교 (LLM 의미 유사도) → 유사도 상위 3개 후보 식별 (없으면 silent skip)
2. AUTO_MODE=false: AskUserQuestion으로 후보 목록(PLN-NNN/제목/생성일) 제시 + 재사용 여부 확인. 선택 시 해당 plan.md Read → 결정사항·제약·범위를 현재 세션 컨텍스트에 보관.
3. AUTO_MODE=true: 유사도 높다고 판단되면 자동 참조 + auto-decisions.md 기록.
4. 참조 대상으로 확정된 각 plan의 `plan.json`에서 `linked_intent` 확인 → 존재하면 `python3 {PLUGIN_ROOT}/scripts/mst.py intent get {INTENT_ID} --json`으로 intent 본문 Read하여 `referenced_intent`로 보관. 없거나 실패 시 graceful skip (워크플로우 차단 금지).

### Step 2: 초기 분석 & 첫 미결 항목 처리

#### MANDATORY Read: plan-context.md (선호 패턴 컨텍스트)

1. `{PROJECT_ROOT}/.gran-maestro/plan-context.md`를 반드시 Read한다. 파일이 없으면 아래 초기 템플릿으로 생성 후 즉시 Read한다 (비차단):
   ```markdown
   # Plan Q&A 선호 패턴
   _마지막 갱신: 없음 (초기 상태)_ / _세션 수: 0_ / _schema_version: 1_
   > 아직 선호 패턴이 기록되지 않았습니다.
   ## 선호 패턴 (Preference Table)
   | id | domain | type | statement | weight | freq | last_seen | tags |
   |----|--------|------|-----------|--------|------|-----------|------|
   ## Prompt Hints
   (패턴 축적 후 자동 생성됩니다)
   ```
2. `## 선호 패턴 (Preference Table)`에서 현재 주제와 관련된 패턴 최대 3개를 `preference_hints`로 추출한다.
3. Step 2~3의 모든 `AskUserQuestion`에서 과거 선호를 `description`에 명시적으로 인용한다 (권장 형식: `이전에 "{statement}"를 선호하셨습니다. 이번에도 동일하게 적용할까요?`). `freq` 숫자 직접 인용 금지.
4. 사용자가 인용 선호를 반박하면 해당 statement를 `disputed_preferences`에 수집하고 Step 4 저장 시 백그라운드 요약 입력으로 전달한다.

#### Step 2-R: Reference Lookup 실행 (Step 2 분석 직후, Step 2.5 이전, MANDATORY)

1. Step 2에서 정리된 요청 맥락(주제, 미결 항목, 제약, 우선순위 후보)을 입력으로 `Reference Lookup Protocol`을 실행한다.
2. `reference.auto_search != true`이면 자동 WebSearch는 금지하고, 기존 REF 캐시 조회 결과만 컨텍스트로 사용한다.
3. 생성된 `[REFERENCE_CONTEXT]` 블록을 Step 2.5/Step 3의 모든 판단 프롬프트(ideation/discussion/explore 포함)에 주입한다.
4. 본 단계는 구현 지시가 아닌 **판단 최신화 보조** 목적이다. plan 본문에 검색 결과를 복사하지 말고 REF-ID 중심으로 참조한다.

**`debug_context` 활성 시:** 근본 원인+수정 제안을 초기 컨텍스트로 선반영 → `[디버그 조사 결과 요약]` 블록 표시(근본 원인/수정 제안 P0~/영향 파일) → 구현 범위·우선순위·분리 실행 여부를 핵심 미결 항목으로 정리

**`capture_context` 활성 시:** 캡처 데이터를 초기 컨텍스트로 선반영 → `[캡처 참조 요약]` 블록 표시:
```
[캡처 참조 요약]
| ID | URL | Selector | Memo |
|----|-----|----------|------|
| CAP-001 | https://... | .btn-primary | 색상 변경 필요 |
> 스크린샷: `.gran-maestro/captures/CAP-001/screenshot.webp`
```
`debug_context`와 `capture_context` 모두 활성이면 둘 다 표시 (debug가 상위, capture가 보조).

**실행 분기:**

- `AUTO_MODE=false`:
  - PM이 요청을 분석하여 핵심 미결 항목(범위·우선순위·방향·접근법)을 파악한다.
  - **요청이 단순·명확해 보이더라도 반드시 최소 1회 `AskUserQuestion`으로 대화를 시작한다.** (Fast-track 금지)
    - 대부분 명확한 경우: PM이 현재 이해와 접근 방향 초안을 제시하고 "이 방향으로 진행할까요?" 형태의 확인 질문 포함
    - 미결 항목이 있는 경우: 가장 중요한 미결 항목 1~2개에 대한 질문 제시
  - `AskUserQuestion` 없이 Step 4로 직행하는 것은 **어떤 경우에도 허용하지 않는다.**
- `AUTO_MODE=true`: Step 2~3에서 `AskUserQuestion` 호출 금지. 우선순위가 가장 높은 미결 항목 1건을 먼저 처리한 뒤 Step 3 반복으로 이어간다. ideation/discussion 호출은 생략 대상이 아니라 결정 품질 확보 절차로 필요 시 즉시 수행한다.

#### [AUTO_MODE 판단 패턴] (Step 2~3, Step 3.8 공통)

프레이밍 원칙:
- `confidence`는 현재 근거의 충분도를 표현하는 작업 신호다. confidence는 보조 신호이며 high-pass 단독 근거로 사용하지 않는다.
- `discussion/ideation` 호출은 결정 품질과 반례 점검을 높이는 표준 절차다. 높은 confidence 자체를 discussion 생략의 정당화로 사용하지 않는다.

`AUTO_MODE=true`일 때 각 미결 항목 처리 순서:
1. PM이 해당 항목의 confidence score(0.0~1.0)를 자체 산정
2. `workflow.high_pass_guard` Hard Gate를 confidence 분기보다 먼저 평가:
   - reason token 키: `self_report_only_block`, `external_evidence_missing`, `independent_judgement_required`, `risk_signal_review_required`.
   - self-report만으로 pass를 확정하지 않는다.
   - 입력 증거가 LLM self-report(markdown/json)만 있고 외부 실행 증거가 없으면 confidence와 무관하게 discussion 경로로 강제한다.
   - 분리된 판정 단계(discussion/ideation/독립 리뷰)가 없으면 confidence와 무관하게 discussion 경로로 강제한다.
   - 영향 범위·다중 모듈·상태 전이·계약 변경 중 하나라도 감지되면 `risk_signal_review_required`로 기록하고 confidence 단독 high-pass를 금지한다.
   - Hard Gate 걸린 경우 auto-decisions.md에 즉시 행 추가: `| {항목명} | {결정값} | {confidence:.2f} | hard-gate ({reason_token}) | 강제(L1) |`
3. `confidence >= CONFIDENCE_THRESHOLD` AND Hard Gate 통과: PM 자율 결정. 대안 비교·영향 범위·이해관계자 정렬이 중요한 항목은 confidence가 높아도 discussion/ideation 호출로 결정 품질 보강 가능.
   - auto-decisions.md: discussion 미호출 시 `| {항목명} | {결정값} | {confidence:.2f} | PM 자율 판단 | 자율 |`, 호출 시 `| ... | 고신뢰+discussion 보강 | 자율 |`
   - 카운터: 미호출 시 `AUTO_DECISION_TOTAL++, AUTO_PM_COUNT++`, 호출 시 `AUTO_DECISION_TOTAL++, AUTO_DISCUSSION_COUNT++`
4. `CONFIDENCE_THRESHOLD > confidence >= 0.4`: `Skill(skill: "mst:discussion", args: "{미결 항목} --from-plan --auto")` → `consensus.md` 핵심 3~5개 추출 후 반영. auto-decisions.md: `| ... | discussion 결과 | 자율 |`. 카운터: `AUTO_DECISION_TOTAL++, AUTO_DISCUSSION_COUNT++`
5. `confidence < 0.4`: `WebSearch` 선행 후 confidence 재산정. 재산정 `>= 0.4`이면 discussion 실행, `< 0.4`이면 PM이 **가장 안전한 선택**으로 자율 결정. auto-decisions.md: `| ... | web-search→discussion 결과 | 자율 |`. 카운터: `AUTO_DECISION_TOTAL++, AUTO_EXPLORE_DISCUSSION_COUNT++`
6. 로그 기록은 plan.md 저장 시 일괄 처리하지 않고, **각 항목 결정 직후 Edit로 즉시 append**한다.

**공통:** Step 2 분석 후 자동 ideation/discussion 판단 필요 시 Step 2.5 실행 (confidence 수준과 무관하게 품질 보강이 필요하면 우선 적용 가능)

### Step 2.1: 모호성 해소 루프 (MANDATORY)

> ⚠️ AUTO_MODE=false일 때 모든 항목이 클리어될 때까지 이 루프를 반복한다.

#### 추론 가능 시 질문 생략 (MANDATORY, AUTO_MODE=false)

PM은 아래 체크리스트 항목 각각에 대해, 직전 대화 컨텍스트에서 답을 **추론 가능한지 먼저 판단**합니다. 추론 가능하면 `AskUserQuestion`을 **생략**하고 plan.md 초안에 `(PM 추론)` 표기로 기입합니다. 추론 불가한 항목만 기존 루프로 질문합니다.

**추론 가능 판정 기준**: 직전 대화 또는 툴호출 결과에 해당 값이 직접 명시되어 있거나, 문맥상 명백히 함의된 경우만 추론 가능로 본다. 애매하거나 복수 해석 가능하면 불가 처리. **배치 옵션**: 추론 불가 필드가 2개 이상 시 `AskUserQuestion`의 `questions[]` 배열로 1회에 묶을 수 있다.

AUTO_MODE=true 분기는 기존 `[AUTO_MODE 판단 패턴]` 그대로 동작하며, 이 규칙은 AUTO_MODE=false에서만 적용된다.

#### 체크리스트 항목

**5W1H**: (1) WHO: 사용자/수혜자 특정 (2) WHAT: 변경·추가·제거 대상 정의 (3) WHY: 비즈니스 근거/목적 명시 (4) WHEN: 완료 시점 또는 트리거 조건 (5) WHERE: 영향 받는 화면/시스템/모듈 특정 (6) HOW MUCH: 성공을 수치·관찰로 측정 가능한지 (7) HOW: 접근 방향 대략 정의 (기술 상세 아님 — 전략 방향)

**NFR**: (8) 성능 목표: 응답 시간, 처리량, 부하 명시 필요 여부 (9) 보안 요구사항: 인증·인가·데이터 보호 (10) 접근성/호환성: 특정 기기/OS/브라우저 요구 (11) 오류 처리: 실패 시 동작(롤백/알림/재시도) 정의 필요 여부

**직관적 추가 항목** (PM이 현재 요청을 읽고 자연스럽게 의문이 드는 것): PM이 자율 판단으로 0~3개 추가 작성. 너무 기술적이거나 구현 수준의 질문은 제외.

#### 루프 실행 절차

```
ROUND = 1
WHILE (미클리어 항목 존재):
  1. PM이 체크리스트 전체를 점검하여 미클리어 항목 목록 추출
  2. 미클리어 항목이 없으면 루프 종료 → Step 2.3으로 진행
  3. 미클리어 항목을 그룹화하여 AskUserQuestion 1회로 최대 4개 항목을 질문
  4. 사용자 답변을 각 항목에 반영
  5. ambiguity-log.md에 Round N 기록 (미클리어 항목 / 사용자 답변 / 해소 여부)
  6. ROUND++
```

**AUTO_MODE=true**: AskUserQuestion 없이 PM이 각 항목을 자율 판단으로 해소. 각 항목 해소 결과를 auto-decisions.md에 즉시 기록. 외부 정보 필요 시 WebSearch 실행.

#### Critical/Major Clarification Batch Rule (MANDATORY)

적용 범위: Step 2.1 모호성 루프, Step 3.8.5 적대적 검토, Step 3.9 D3에서 발견된 사용자 의도·범위·우선순위·허용치 관련 모호성.

1. `severity=critical|major`이거나 finding의 `requires_user_answer=true`인 항목은 PM이 `(PM 추론)` 또는 자동 보완으로 닫을 수 없다.
2. PM은 각 항목에 대해 `질문`, `PM 추천 답변`, `추천 근거`, `틀렸을 때 영향`을 작성하고 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/clarification-questions.md`에 append한다.
3. 질문 횟수를 줄이기 위해 최대 5개 항목을 하나의 배치로 묶는다. 사용자에게는 아래 표를 먼저 보여준다.
   ```markdown
   | ID | 확인할 모호성 | PM 추천 답변 | 추천 근거 | 틀렸을 때 영향 |
   |----|---------------|--------------|-----------|----------------|
   | CQ-1 | ... | ... | ... | ... |
   ```
4. `AUTO_MODE=false`: 배치당 AskUserQuestion 1회만 실행한다. 선택지는 최대 4개로 고정한다.
   - `A. 추천안 모두 수락`: 표의 모든 PM 추천 답변을 사용자 승인 결정으로 반영
   - `B. 일부만 수정`: 사용자가 `CQ-1=...; CQ-3=...`처럼 수정할 수 있게 안내하고, 수정된 항목만 재반영
   - `C. 더 검토`: 현재 배치 전체를 `mst:discussion` 또는 `mst:ideation`으로 보강한 뒤 같은 배치를 재질문
   - `D. 범위 제외/보류`: 해당 항목을 No-go Scope 또는 리스크 레지스터에 기록
5. `AUTO_MODE=true`: critical/major 사용자 의존 모호성이 남아 있으면 자율로 진행하지 않는다. `auto-decisions.md`와 `clarification-questions.md`에 blocker를 기록하고 `/mst:request` 자동 호출을 중단한다.
6. 사용자가 `A. 추천안 모두 수락`을 선택한 경우에도 기록에는 `(PM 추천 — 사용자 일괄 승인)`으로 남긴다. PM 단독 결정으로 기록하지 않는다.

**`ambiguity-log.md` 형식**:
```markdown
# 모호성 해소 로그 — PLN-NNN
## Round 1 — {타임스탬프}
### 미클리어 항목
| 번호 | 항목 | 질문 내용 |
|------|------|-----------|
### 사용자 답변
- WHO: "..."
### 해소 결과
| 번호 | 항목 | 해소 여부 |
|------|------|-----------|
```

### Step 2.3: 제약사항 수집 (MANDATORY Q&A)

> ⚠️ AUTO_MODE=false일 때 추론 불가 항목이 1개 이상 남으면 AskUserQuestion을 반드시 실행한다. 모든 항목이 추론 가능으로 판정되어 `(PM 추론)` 표기로 기입되면 AskUserQuestion을 생략할 수 있다. 추론 판정 근거 없이 임의로 생략하는 것은 금지한다.

> **추론 가능 시 생략 (MANDATORY)**: PM은 Out-of-scope·기술적 제약·비즈니스 제약·MoSCoW 각 항목에 대해, 직전 대화 컨텍스트에서 값을 추론 가능한지 먼저 판정한다. 추론 가능한 항목은 `AskUserQuestion`을 생략하고 plan.md의 해당 섹션에 `(PM 추론)` 표기로 기입한다. 판정 기준은 Step 2.1의 "추론 가능 시 질문 생략" 블록과 동일.

아래 4가지를 하나의 AskUserQuestion으로 통합 질문한다 (질문 제목: "이 plan의 제약사항을 확인합니다."):

1. **하지 않을 것 (Out-of-scope)**: 이번 plan에서 명시적으로 제외할 기능/범위 (예: "모바일 대응 제외")
2. **기술적 제약**: 사용해야 하거나 사용하면 안 되는 기술 스택/버전/도구 (예: "Node 18 이상")
3. **비즈니스 제약**: 기간, 예산, 법규, 외부 의존성 (예: "2주 내 완료", "GDPR 준수")
4. **MoSCoW 우선순위**: Must have / Should have / Could have / Won't have. Cynefin이 Simple인 경우 Must / Won't만 확인하고 나머지 생략 가능.

각 항목에 "해당 없음" 선택지 포함. 답변은 plan.md `## 제약사항` 및 `## 우선순위 (MoSCoW)` 섹션에 반영.

**AUTO_MODE=true**: PM이 요청 맥락에서 제약사항과 MoSCoW를 자율 추론하고 auto-decisions.md에 기록한다.

### Step 2.4: 테스트 전략 의도 수집 (선택적 Q&A)

> Shared preload: Step 2.4와 Step 2.45는 시작 전에 `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get plan_qa_presets --json)`를 1회 실행해 `plan_qa_presets_config`로 보관하고, `plan_qa_presets.test_strategy`/`plan_qa_presets.loop_exit`를 모두 여기서 읽는다. preload 실패 시에만 `templates/defaults/config.json` fallback을 사용한다.

> ⚠️ **AUTO_MODE 가드 (CRITICAL — 최우선 평가)**: `AUTO_MODE=true`이면 AUTO_MODE=false 블록 전체를 건너뛰고 즉시 AUTO_MODE=true 블록을 실행한다.

**AUTO_MODE=true** (최우선 분기): PM이 요청 맥락에서 테스트 방법론 적용 여부와 목표 커버리지를 자율 판단. `plan_qa_presets.test_strategy` 값이 `"ask"` 이외이면 해당 preset을 기본값으로 채택. 판단 근거와 결정을 auto-decisions.md에 기록. plan.md `## 테스트 전략` 섹션에 반영. **AskUserQuestion 호출 절대 금지.**

**AUTO_MODE=false**: `plan_qa_presets_config`의 `plan_qa_presets.test_strategy` 값을 먼저 확인한다 (없으면 `templates/defaults/config.json` fallback).
- `"ask"` 이외의 preset이면 AskUserQuestion 생략하고 자동 적용: `"apply-80"` → 적용/80%, `"apply-90"` → 적용/90%, `"apply-no-coverage"` → 적용/미설정, `"skip"` → 적용 안 함
- `"ask"`이면 AskUserQuestion 1회 수행. 핵심 선택지 4개: `"A. 적용 80%"`, `"B. 적용 90%"`, `"C. 적용 미설정"`, `"D. 적용 안 함"`. ⚠️ 이 질문은 보조 선택지 규칙 적용 제외.

### Step 2.45: Loop 종료 조건 수집 (선택적 Q&A)

> ⚠️ **AUTO_MODE 가드 (CRITICAL — 최우선 평가)**: `AUTO_MODE=true`이면 AUTO_MODE=false 블록 전체를 건너뛰고 즉시 AUTO_MODE=true 블록을 실행한다. AskUserQuestion 호출 절대 금지.

**AUTO_MODE=true** (최우선 분기): PM이 기본 프리셋 `"기존 검증 통과(기본값)"`을 자율 선택. `plan_qa_presets.loop_exit`가 `"ask"` 이외면 해당 preset 채택. 판단 근거와 결정을 auto-decisions.md에 기록. plan.md `## Loop 종료 조건` 섹션에 반영.

**AUTO_MODE=false**: `plan_qa_presets_config`의 `plan_qa_presets.loop_exit` 값을 확인한다 (없으면 fallback).
- `"ask"` 이외이면 자동 적용: `"default_pass"` → 기존 종료 조건(AC 통과 + max_iterations), `"convergence"` → 연속 무변경 수렴, `"fixed_n"` → 고정 N회 반복
- `"ask"`이면 AskUserQuestion 수행. 핵심 선택지 3개: `"A. 기존 검증 통과"`, `"B. 무변경 수렴"`, `"C. 고정 횟수 반복"`. ⚠️ 이 질문은 보조 선택지 규칙 적용 제외.
- `"C. 고정 횟수 반복"` 선택 시 후속 AskUserQuestion으로 N값(자연수) 수집.
- `"B. 무변경 수렴"` 또는 `"C. 고정 횟수 반복"` 또는 UI 자동 Other 입력 시 복수 조건 AND 조합 여부 확인. `"A. 조건 추가"` 선택 시 동일 선택지 반복, `"B. 이대로 진행"` 시 종료.

### Step 2.6: 의존성 확인 (MANDATORY)

> ⚠️ AUTO_MODE=false일 때 추론 불가 항목이 1개 이상 남으면 반드시 AskUserQuestion으로 확인한다. 추론 가능으로 판정되면 `(PM 추론)` 표기로 기입하고 AskUserQuestion을 생략할 수 있다 (Step 2.1 규칙과 동일).

질문: "이 plan이 의존하거나 연관된 다른 작업이 있나요?"
- 선행 필요 (blockedBy): 이 plan 시작 전 완료되어야 하는 PLN/REQ
- 연관 (relatedTo): 영향을 주고받는 PLN/REQ
- "없음" 선택지 포함

수집된 의존성은 plan.md `## 의존성` 섹션에 기록. **AUTO_MODE=true**: PM이 자율 판단 후 auto-decisions.md에 기록.

### Step 2.5: PM 자동 판단 (해석 B)

> ⚠️ **기술 스택·아키텍처·코드 수준 접근법 결정은 plan 단계에서 수행하지 않습니다.** 코드베이스 탐색이 필요한 기술적 결정은 /mst:request 단계에서 수행됩니다. plan에서 다루는 결정은 **비즈니스 방향·사용자 경험·범위·우선순위** 수준에 한정합니다.

아래 조건 해당 시 첫 질문 전에 PM이 먼저 실행:
- **ideation**: 접근법 2개 이상+트레이드오프 모호, 사용자 경험/비즈니스 방향 결정, PM 확신 낮음
- **discussion**: 복잡한 트레이드오프+팀 합의 필요, 비즈니스 리스크 큰 결정

트리거 시: "[이유]로 [ideation/discussion] 먼저 실행" 통지 → `Skill(skill: "mst:ideation/discussion", args: "{주제}")` → 핵심 3~5개 요약 → 후속 결정 문맥으로 선반영 (`AUTO_MODE=false`면 질문, `AUTO_MODE=true`면 자율 판단 패턴)

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

동일 세션/주제/타입 완료 이력 있으면 새 세션 생성 없이 기존 결과 재사용.

> **[전역 규칙] AskUserQuestion 선택지 구성 (API 제약: 최대 4개 옵션)**
> `AUTO_MODE=false`에서 콘텐츠 결정 관련 모든 `AskUserQuestion` 호출 시:
> - **핵심 선택지**: 최대 3개 (실제 답변 옵션)
> - **보조 선택지**: 반드시 1개 — ideation · discussion · explore 중 현재 맥락에 가장 적합한 것을 택 1
> - **Other**: UI가 자동 추가하므로 사용자 자유 입력용 `Other`, `기타`, `직접 입력`, `자유 입력`, `사용자 지정`, `Custom` explicit option을 수동으로 넣지 않는다.
> - Step 4 저장 액션 AskUserQuestion은 보조 선택지 규칙 제외.
>
> **[전역 규칙] 선택지 표기 형식 (MANDATORY)**
> - content-decision explicit option label은 bare `A`, `B`, `C`, `D`, `1`, `2`, `3`, `4`가 아니라 `A. {의미 요약}`~`D. {의미 요약}` 또는 `1. {의미 요약}`~`4. {의미 요약}` 형식으로 쓴다.
> - 사용자가 왼쪽 label만 보고도 선택지 의미를 구분할 수 있어야 한다. 예: `A. 최소 변경`, `B. 전면 정렬`, `1. 우선순위 유지`.
> - 금지 예시: `A`, `B`, `1`, `α`, `β`, `γ`, `i`, `ii`, `iii`, `I`, `II`, `III`, 이모지·기호만으로 된 prefix.
> - 후보/분기/안건을 본문에 나열할 때도 visible structural prefix는 `A.`, `B.`, `C.`, `D.`, `1.`, `2.`, `3.`, `4.`만 사용한다.

> **[전역 규칙] 선택지 장단점·추천 필수 — 모든 다중 선택지 AskUserQuestion 공통**
> 선택지가 2개 이상인 모든 `AskUserQuestion`에서 각 선택지에 **장점·단점·추천하는 상황**을 `description` 또는 `preview` 필드에 **반드시 포함**한다.
> - 내용 없이 라벨만 있는 빈 선택지는 **절대 금지**한다.
> - 적용 제외: 순수한 예/아니오 확인 질문, 계속/종료 확인, 정보 수집형 자유 텍스트 질문.
> - 구체적인 표현 형식은 아래 "선택지 장단점 표현: 3가지 유형"을 따른다.

### Step 3: 반복 정제

- `AUTO_MODE=false`: 사용자 답변 반영해 PM이 추가 질문 필요성 자율 판단, 핵심 결정 사항이 명확해질 때까지 반복
- `AUTO_MODE=true`: 사용자 질문 없이 PM이 미결 항목을 순차 처리하고, 각 항목마다 `[AUTO_MODE 판단 패턴]`을 적용해 결정/로그 기록을 완료할 때까지 반복
- `AUTO_MODE=false`에서만 모든 질문은 `AskUserQuestion`으로 **동시 1개만**; **총 옵션 최대 4개** (API 하드 제한: 핵심 3개 + 보조 1개, Other는 자동 추가)
- **보조 선택지 (`AUTO_MODE=false`, 반드시 1개 포함 — 생략 불가)**:
  PM이 현재 질문 맥락에 가장 적합한 것을 **3가지 중 1개만** 선택:
  - `"다각도 의견 모으기 (ideation)"` — 접근법이 2개 이상이고 트레이드오프가 불명확할 때
  - `"팀 토론으로 합의 찾기 (discussion)"` — 복잡한 비즈니스 결정으로 합의가 필요할 때
  - `"코드베이스 탐색 + 웹검색 (explore)"` — 관련 파일·현재 구현·패턴 파악 및 외부 사례 검색이 필요할 때

#### Step 3.2: 사용자 선택 기반 재질문 흐름 (`AUTO_MODE=false`)

고정 선택지 선택 **또는 사용자가 텍스트로 직접 ideation/discussion/explore 요청** 시 현재 주제로 해당 스킬 실행:

> ⚠️ **직접 요청 감지**: "discussion 해줘", "ideation 돌려줘", "explore 해줘", "코드 찾아줘", "웹 검색해줘" 등 텍스트로 직접 요청한 경우에도 동일하게 이 흐름을 따른다. 스킬 실행 후 반드시 Step 3으로 복귀해야 한다.
>
> `AUTO_MODE=true`에서는 `[AUTO_MODE 판단 패턴]`을 사용한다.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

- **ideation/discussion 선택 시**: `Skill(skill: "mst:ideation/discussion", args: "{주제} --focus {관련 분야}")` → 동일 이력 있으면 재사용 → `synthesis.md`/`consensus.md` Read → 핵심 3~5개를 `[AI 팀 의견 요약]`으로 표시 → **즉시 같은 턴에서** Step 3으로 복귀하여 원 질문 동일 포맷으로 `AskUserQuestion` 재실행
- **웹 검색 선택 시**: `WebSearch(query: "{주제 관련 업계 표준/유사 사례/대안}")` (필요 시 복수) → 결과 핵심을 `[외부 리서치 결과]`로 요약 → **즉시 같은 턴에서** Step 3으로 복귀하여 `AskUserQuestion` 재실행
- **explore 선택 시**: `Skill(skill: "mst:explore", args: "{주제} --focus {관련 파일/기능}")` + `WebSearch("{주제} 사례 구현 패턴")` → `explore-report.md` Read → `[코드베이스 탐색 결과]` 및 `[웹 검색 결과]` 각각 요약 → **즉시 같은 턴에서** Step 3으로 복귀하여 `AskUserQuestion` 재실행

#### 시각적 미리보기 활용 (UI/레이아웃 선택 시)

UI 레이아웃/컴포넌트 구조/화면 흐름/정보 밀도 비교가 필요한 단일 선택(`multiSelect: false`) 시 각 옵션에 텍스트 와이어프레임을 첨부한다.
- **`description`**: 짧은 텍스트 설명. preview가 표시되지 않아도 의미를 잃지 않도록 핵심 차이를 담는다.
- **`preview`**: 우측 미리보기 패널에 표시되는 ASCII 도식. 화면명이나 컴포넌트명을 포함해 구조 차이를 바로 볼 수 있게 한다.

```
┌─────────────┐   ← 박스로 영역 구분
│  컴포넌트    │
└─────────────┘
[버튼A] [버튼B]   ← 인라인 요소
─────────────────  ← 구분선
```

> ⚠️ `multiSelect: true` 질문에서는 preview 패널이 비활성화되므로 시각 비교가 필요한 결정은 단일 선택 질문 여러 개로 분리한다. 분리할 수 없는 multiSelect는 `description`에 `[장점]`, `[단점]`, `[적합]`을 모두 포함한다.

#### 선택지 장단점 표현: 3가지 유형

선택지가 2개 이상인 모든 `AskUserQuestion`에서 아래 **3가지 유형 중 하나**를 반드시 적용한다. 적용 제외: 순수한 예/아니오 확인, 계속/종료 확인, 정보 수집형 자유 텍스트 질문.

**유형 1: non-visual single-select content-decision**

`multiSelect: false`이고 UI 구조 비교가 아닌 결정 질문은 각 option label과 preview를 아래처럼 구성한다.

```
label: "A. 타입 안전성 우선"
description: "초기 설정 비용은 있지만 장기 유지보수 안정성을 높이는 선택"
preview: |
  ## 장점
  - 타입 추론과 IDE 지원이 강해 후속 구현 실수를 줄입니다.
  - 변경 영향이 컴파일 단계에서 빨리 드러납니다.

  ## 단점
  - 초기 설정과 타입 정의 시간이 더 필요합니다.
  - 간단한 문서 변경에는 과한 절차가 될 수 있습니다.

  ## PM 추천 의견
  여러 스킬과 에이전트 지침이 함께 바뀌는 경우처럼 회귀 위험이 있는 변경에 추천합니다.
```

**유형 2: visual-comparison single-select**

UI/레이아웃/컴포넌트 배치/정보 배치/화면 흐름을 비교하는 질문은 각 option preview에 텍스트 와이어프레임을 포함한다.

```
label: "B. 좌측 탐색 유지"
description: "정보 구조가 안정적이지만 모바일 전환 시 공간이 줄어드는 배치"
preview: |
  ## 화면 구조
  ┌────────────── 대시보드 ──────────────┐
  │ Nav │ Header                         │
  │     │ ┌──── 카드 ────┐ ┌──── 카드 ─┐ │
  │     │ └──────────────┘ └───────────┘ │
  └──────────────────────────────────────┘

  ## 장점
  - 주요 메뉴가 항상 보여 탐색 비용이 낮습니다.

  ## 단점
  - 좁은 화면에서는 콘텐츠 폭이 줄어듭니다.

  ## PM 추천 의견
  관리자 화면처럼 반복 탐색이 많은 경우에 추천합니다.
```

**유형 3: multiSelect content-decision**

`multiSelect: true`에서는 preview가 표시되지 않으므로 각 option.description에 `[장점]`, `[단점]`, `[적합]` 태그와 충분한 설명을 넣는다.

```
label: "C. 회귀 테스트 포함"
description: "[장점] 기존 흐름 파손을 빠르게 확인합니다. [단점] 실행 시간이 늘어납니다. [적합] 사용자 영향이 큰 공통 규칙 변경에 적합합니다."
```

이모티콘 사용 금지 — 반드시 `[장점]`, `[단점]`, `[적합]` 대괄호 텍스트 태그를 사용한다.

### Step 3.3: INVEST Gate

Q&A 반복 종료 판단 직후, DoR-Discovery(Step 3.4) 진입 전에 INVEST 6개 기준을 PM이 내부 점검한다. **미충족 기준만** 사용자에게 질문하고, 충족 기준은 Q&A 없이 자동 통과한다.

| 기준 | 전체명 | PM 내부 판단 질문 |
|------|--------|-------------------|
| I | Independent | 다른 플랜/REQ 완료 없이 독립적으로 실행 가능한가? |
| N | Negotiable | 세부 구현 방식이 협상·조정 가능한 상태인가? |
| V | Valuable | 사용자 또는 비즈니스에 명확한 가치가 있는가? |
| E | Estimable | 작업 크기(복잡도/범위)를 대략적으로 추정할 수 있는가? |
| S | Small | 단일 REQ에서 완결 가능한 범위인가? |
| T | Testable | 완료 여부를 검증할 수 있는 기준(AC)이 정의 가능한가? |

**`AUTO_MODE=false` 처리**: 충족 기준은 Q&A 없이 통과. 미충족 기준: `AskUserQuestion`으로 질문 헤더 `[INVEST 검증 — {기준약어}: {기준 전체명}]` 사용. S 미충족: 분리 동의 시 Step 3.5 연계; 유지 시 예외 통과 후 근거 기록. T 미충족: Step 4에서 AC 초안 섹션 작성 유도. I/N/V/E 미충족: 답변을 plan 결정사항에 반영.

**`AUTO_MODE=true` 처리**: 모든 기준을 `[AUTO_MODE 판단 패턴]`으로 처리. 각 기준 판단 결과를 auto-decisions.md에 즉시 기록: `| INVEST-{기준약어} | {충족/미충족 — 조치 내용} | {confidence:.2f} | PM 자율 판단 | 자율 |`. S 미충족: 범위 축소 또는 분리 방향 결정 후 Step 3.5 연계. T 미충족: PM이 AC 초안 직접 작성.

**전체 충족 시**: 별도 Q&A 없이 Step 3.4 (DoR-Discovery Gate)로 진행

### Step 3.4: DoR-Discovery Gate

Q&A 종료 판단 직후, plan 초안 진행 전 5개 항목을 PM이 내부 점검한다. 모든 항목 충족 시 Step 3.5로 진행, 하나라도 미충족 시 분기한다.

**체크리스트**: (1) 문제 정의: 무엇이 없거나 잘못되었는지 명확한가? (2) 대상 사용자/시스템: 수혜자/영향 범위가 특정되었는가? (3) 성공 지표 초안: 완료됐음을 측정할 수 있는 결과가 정의되었는가? (4) 제외 범위 초안: 이번에 다루지 않을 항목이 식별되었는가? (5) 핵심 리스크 Top3: 구현 실패 또는 범위 이탈의 주요 위험이 파악되었는가?

**미충족 처리**:
- `AUTO_MODE=false`:
  ```
  WHILE (미충족 항목 존재):
    1. 미충족 항목 목록 출력
    2. AskUserQuestion으로 각 항목 보완 정보 질문 (항목당 1회)
    3. 답변 반영 후 체크리스트 재점검
    4. 모든 항목 충족될 때까지 반복
  ```
- `AUTO_MODE=true`: PM이 미충족 항목을 자율 결정하고 `auto-decisions.md`에 기록 후 진행

### Step 3.5: REQ 책임 분리 (PM 필수 검토)

#### REQ 분리 원칙

아래 중 하나라도 해당 시 분리 실행 제안 후 사용자 동의 요청:
- 레이어 혼재(백엔드+프론트), 도메인 혼재, 독립 완결 가능, 타임라인 차이, 영역 충돌 위험, 리스크 성격 차이

분리 확정 시: plan.md `## 분리 실행` 섹션에 각 책임 단위 기록.

규모가 클수록 REQ를 더 적극적으로 분리해야 합니다. 규모가 크다는 이유로 mst:request를 건너뛰고 직접 구현하는 것은 절대 금지합니다.

> **태스크 분해는 plan 범위 밖**: REQ 내부의 태스크 분해는 mst:request 단계에서 코드베이스 탐색 결과를 바탕으로 결정합니다.

### Step 3.8: Strategic Review Pass (선택적)

> ℹ️ 이 단계는 코드베이스 탐색이 아닌 **전략적 의사결정 지원**에 초점을 맞춥니다. 기술 구현 수준의 검토는 /mst:request 단계의 Spec Pre-review Pass에서 수행됩니다.

#### 3.8.0: config 읽기 및 enabled 확인

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get plan_review)` → plan_review 섹션 취득 (없으면 `templates/defaults/config.json` fallback). `enabled` 값을 메모리에 보관.
- **enabled == false**: 이 단계 전체 skip → Step 4로 진행
- **enabled == true**: 아래 3.8.1부터 실행

#### 3.8.1: PM 내부 초안 작성

3.8.1 시작 직후 `{PROJECT_ROOT}/.gran-maestro/plan-context.md`를 다시 Read하여 최신 선호 패턴을 전략 검토 입력으로 병합. `weight=HIGH` 패턴은 전략 선택의 우선 제약으로 반영. `[DISPUTED]` 태그 패턴은 기본 추천안에서 제외.

Q&A 대화 내용을 바탕으로 PM이 플랜 초안 텍스트를 작성한다 (디스크 미저장, 메모리 내). 이 초안은 Step 4에서 최종 제시될 내용의 초기 버전이다.

#### 3.8.2: 전략적 분석 수행

PM이 plan 초안을 바탕으로 아래 세 관점에서 직접 분석을 수행한다:

**관점 A — 의도 검증 (Intent Validation)**: 사용자가 요청한 것(what)과 실제로 필요한 것(why)의 갭 분석. "X를 원한다고 했지만, 진짜 문제는 Y일 수 있다" 패턴 탐지. **JTBD 근본 과업 확인**: "사용자/시스템이 이 plan을 통해 완수하려는 근본 과업(Job)은 무엇인가?"를 명시적으로 확인. 근본 과업이 plan 범위에서 해결되지 않으면 `MAJOR` 이슈로 분류.

**관점 B — 외부 리서치 (Industry Research)**: 필요하다고 판단되는 항목에 한해 `WebSearch` 실행 (전체 실행 강제 아님): 업계 표준·권장 패턴, 대안 솔루션, 흔한 함정.

**관점 C — 범위 위험 감지 (Scope Risk Detection)**: 범위 크립(scope creep) 징후 탐지. "이 범위로 가면 나중에 Y 문제가 생길 수 있다" 전략적 경고. plan 외부로 번지는 영향 범위 예측.

#### 3.8.3: 이슈 분류 및 처리

PM이 분석 결과를 이슈로 분류:
- `CRITICAL:` 방향이 근본적으로 잘못됨 (의도 오해, 심각한 범위/전략 문제)
- `MAJOR:` 중요한 대안·리스크가 고려되지 않음
- `MINOR:` 참고할 만한 외부 사례·패턴
- `NO_ISSUES`: 전략적 문제 없음

**오실레이션 탐지 (재정제 전 PM 판단 — `AUTO_MODE=false`)**: 이번 이슈 목록이 직전 라운드와 실질적으로 동일한가? 동일하면 에이전트 재dispatch 없이 반복 이슈를 하나로 합성하여 사용자에게 에스컬레이션. → "같은 이슈가 반복되고 있습니다. 방향을 결정해 주세요." (CRITICAL 수준). 이 판단은 PM의 질적 판단으로만 수행한다 (별도 에이전트 호출 금지).

**`AUTO_MODE=false`**: CRITICAL/MAJOR 이슈 존재 시: `AskUserQuestion`으로 이슈 제시 + 각 이슈를 해소하는 구체적 옵션 + **"반영 없이 진행"** + **보조 선택지 필수 1개 포함**. 사용자 답변 반영하여 PM 초안 재정제. MINOR 이슈만: PM이 자체 판단으로 plan 초안에 참고 메모로 반영 → Step 4. NO_ISSUES: 바로 Step 4.

**`AUTO_MODE=true`**: 모든 이슈를 `[AUTO_MODE 판단 패턴]`으로 처리. 각 결정은 즉시 `auto-decisions.md`에 기록하고 PM 초안에 반영.

**리스크 레지스터 자동 생성**: 이슈 분류 완료 후 리스크 레지스터 표로 변환. 매핑: CRITICAL → 가능성/영향 모두 "상", MAJOR → "중", MINOR → "하". NO_ISSUES: "식별된 리스크 없음" 한 줄만 기재.

```markdown
## 리스크 레지스터
| 리스크 | 가능성 | 영향 | 완화 방안 |
|--------|--------|------|-----------|
| {이슈 설명} | 상/중/하 | 상/중/하 | {PM 제안 완화 방안} |
```

Step 3.9 진입 시 초안은 전략적 검토가 반영된 정제 버전이다.

### Step 3.8.5 적대적 검토 게이트

> 목적: D3 Reverse Simulation Gate 진입 전, plan 초안의 완전성을 적대적으로 점검해 엣지케이스, 누락 흐름, persona/NFR gap, 통합 경계 gap을 AC/리스크/제약 보강 후보로 승격한다. 이 단계는 D3의 "명료도" 검증이 아니라 "완전성" 검증이다.

#### 3.8.5.0: config 읽기 및 enabled 확인

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.adversarial_review)`로 설정을 읽는다.
- `agile.adversarial_review.enabled != true`이면 graceful skip 후 Step 3.9로 진행한다.
- enabled perspective만 실행한다. 기본 enabled는 `edge`, `flow`, `integration`이며 `persona`, `nfr`은 설정이 true인 경우에만 실행한다.
- `max_rounds` 기본값은 3, `current_round` 초기값은 1이다.

#### 3.8.5.1: perspective별 context 조회

각 perspective마다 아래 CLI를 실행한다.

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py plan review --plan-path {path} --perspective {name} --json
```

CLI 반환값은 `context_files`, `output_schema`, `perspective`만 사용한다. plan 원문, Q&A 대화 맥락, DoD/JTBD 원문을 에이전트 프롬프트에 직접 포함하지 않는다.

#### 3.8.5.2: 독립 에이전트 dispatch

에이전트는 반드시 독립 컨텍스트로 호출한다. Perspective별 shared route를 실행해 same-host Codex는 collaboration, same-host Claude는 `Task`/`Agent`, external route만 managed provider skill/CLI를 사용한다. Native child에는 `DELEGATION BOUNDARY`를 포함한다.

프롬프트 예시는 아래 두 줄만 허용한다.

```text
역할: {perspective} 관점의 적대적 검토자.
Read로 context_files 경로를 로드하고 output_schema에 맞게 findings JSON을 반환하시오.
```

#### 3.8.5.3: findings 기록 및 수렴

findings는 round별 append 방식으로 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/adversarial-review-findings.md`에 기록한다. 각 append 블록에는 `round`, `perspective`, `severity`, `finding`, `suggested_dod`, `requires_user_answer`, `question`, `recommended_answer`, 반영 여부를 포함한다.

수렴 조건은 `findings 배열이 비어있음 OR current_round >= max_rounds`이다.
- findings가 비어 있으면 Step 3.9로 진행한다.
- findings가 있고 `current_round < max_rounds`이면 반영 대상 finding을 plan 초안의 AC, 제약, 리스크 레지스터, 제외 범위 중 적절한 위치에 보강한 뒤 `current_round += 1`로 재실행한다.
- `current_round >= max_rounds`이면 남은 finding을 파일에 기록하고 Step 3.9로 진행한다.

#### 3.8.5.4: AUTO_MODE 분기

`AUTO_MODE=true`:
- `parallel_in_auto_mode=true`이면 enabled perspective를 병렬 실행하고, false이면 순차 실행한다.
- `severity=critical|major` 또는 `requires_user_answer=true` finding은 Critical/Major Clarification Batch Rule로 보낸다. PM이 자동 반영하지 않는다.
- 그 외 finding만 자동 반영 가능하며 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/auto-decisions.md`에 근거와 반영 내용을 기록한다.

`AUTO_MODE=false`:
- 기본 실행은 `edge` + `flow` 2종을 순차 실행한다.
- `severity=critical|major` 또는 `requires_user_answer=true` finding은 Critical/Major Clarification Batch Rule로 묶어 사용자 confirm 후 plan 초안에 반영한다.
- minor finding은 요약으로 제시하되, 사용자가 반영을 선택한 경우에만 plan 초안에 반영한다.

### Step 3.9: D3 Reverse Simulation Gate (MANDATORY)

> 목적: request 단계 진입 전, plan AC(인수 기준 초안)의 해석 분기점과 모호성을 역방향으로 점검해 의도 전달 손실을 차단한다.

#### 3.9.0: D3/PAC Trace config 로드

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get d3 pac_trace)`로 `d3`, `pac_trace` 섹션 읽기 (없으면 `templates/defaults/config.json` fallback). 기본값:
- `d3.enabled=true`, `d3.light_mode=true`, `d3.ambiguity_threshold=0.2`, `d3.sprint_plan_threshold=0.15`, `d3.max_escalation_retries=3`, `pac_trace.enabled=true`
- `d3.agents`: `codex={count:2,tier:"premium"}`, `agy={count:0,tier:"premium"}`, `claude={count:0,tier:"economy"}`
- `d3.cynefin_skip=["simple","chaotic"]`

`d3.enabled != true`면 이 단계 전체 skip → Step 4. 현재 Cynefin 도메인이 `d3.cynefin_skip`에 포함되면 D3 skip → Step 4. `complicated` 또는 `complex`이면 D3 실행을 필수로 적용.

#### 3.9.1: AC 앵커 정규화 (PAC 임시 앵커)

plan 초안의 `## 인수 기준 초안` 불릿 목록을 정규화(순서/중복 제거)하여 D3 입력 리스트를 만든다. D3 실행 중에는 `PAC-1..N` 임시 앵커를 메모리에서 부여하고 D3 프롬프트 앞단에 고정 주입한다. Step 4 저장 시 동일 순서를 기준으로 `plan.ids.json`에 영구 PAC를 생성해 드리프트를 방지한다.

#### 3.9.2: light D3 기본 실행 (독립 에이전트)

D3 실행 에이전트는 config의 `d3.agents`를 기준으로 결정 (`debug.agents`, `explore.agents`와 동일 패턴):
1. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get d3.agents)` 우선, 없으면 `templates/defaults/config.json` fallback, 둘 다 없으면 기본값 적용
2. provider별 `count > 0` 항목만 dispatch 대상, 각 `count`만큼 독립 실행 엔트리 생성
3. 모델 tier: `d3.agents.{provider}.tier` → 모델명: `config.models.providers.{provider}[tier || default_tier]`으로 resolve

D3는 반드시 **독립 컨텍스트**로 호출한다. 각 provider에 shared route를 적용해 native candidate는 host agent, external은 managed provider entrypoint를 사용한다. 입력 제한: AC 텍스트 + 용어집 + 제약 + `DELEGATION BOUNDARY`만 전달하며 plan 대화 맥락은 전달하지 않는다.

기본 실행은 `d3.light_mode=true` 기준 (저비용 모드). `complicated`/`complex` 도메인에서는 AC 형식/완결성 micro-screen 1회 선행.

AC별 출력 필수 항목:
- `interpretation_branches`: 구현자가 다르게 해석할 수 있는 분기점
- `ambiguity_type`: `AMBIGUOUS_SUBJECT | AMBIGUOUS_CONDITION | AMBIGUOUS_OUTCOME | MISSING_EDGE_CASE`
- `is_ambiguous`: `true | false`
- `severity`: `critical | major | minor`
- `requires_user_answer`: `true | false`
- `question`: 사용자 의도 확인이 필요할 때 물어볼 질문
- `recommended_answer`: PM 추천 답변
- `recommendation_rationale`: 추천 근거
- `confidence`: `0.0~1.0`

`is_ambiguous=true`로 판정된 AC만 full D3로 escalation. 동일 AC가 3회 연속 `confidence < 0.4`이면 아키텍트 리뷰 큐로 escalation path 전환.

#### 3.9.3: D3 blocking 게이트 판정

- `ambiguous_count` = `is_ambiguous=true`인 AC 개수
- `ambiguity_ratio = ambiguous_count / total_ac`
- 임계치: `agile_context_active=true`이면 `d3.sprint_plan_threshold` 사용 (기본 0.15), 그 외는 `d3.ambiguity_threshold` (기본 0.2)
- `ambiguity_ratio > threshold`이면 request 진입 차단:
  1. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/d3-findings.md` 생성
  2. 모호 AC 목록 + 유형 + 분기점 + 보완 제안 기록
  3. AC 수정 후 Step 3.9 재실행 (회귀)
- 임계치 이하이면 D3 통과 → Step 4 진행

#### 3.9.4: 자동 재지시 루프 (AD-RV-003)

임계치 초과 판정 시 사용자 에스컬레이션 대신 자동 재지시 루프를 수행한다. 단, `severity=critical|major` 또는 `requires_user_answer=true`인 사용자 의존 모호성은 자동 재지시 대상이 아니라 Critical/Major Clarification Batch Rule 대상으로 처리한다. `agile_context_active=true`일 때만 강제 적용되며, 일반 plan에서도 동일 로직을 재사용할 수 있다.

1. `d3-findings.md` 기록 후 재지시 메시지 생성: "모호 AC 목록과 보완 제안을 반영해 plan 초안을 수정한 뒤 Step 3.9를 재실행하세요."
2. 재지시 루프 카운터 `d3_redirect_retries`를 증가시키고 3.9.2를 재실행.
3. `d3_redirect_retries > d3.max_escalation_retries` (기본 3)가 되면 루프 종료:
   - warning 로그: `"[D3 재지시 소진] {max} 회 재시도 후에도 임계치 초과. 현재 plan으로 진행합니다."`
   - `agile_context_active=true`일 때만: `python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues add {AGI_ID} --title "D3 sprint-plan 재지시 소진" --detail "PLN-{NNN} — {max} 회 재시도 후 모호도 임계치 초과. 수동 검토 필요." --severity medium`
   - `d3_redirect_exhausted=true` 플래그를 plan.json에 기록
4. 사용자 에스컬레이션 금지 — 자동 복구 루프만 수행한다 (AD-RV-003, AD-INT-002와 일관).

### Step 4: plan.md 초안 제시, 저장, 요청 연계

> **`(PM 추론)` 수정 경로**: 초안에 `(PM 추론)` 표기로 기입된 항목에 대해 사용자가 "수정 필요"로 지시하면, PM은 같은 턴에서 해당 항목만 반영해 초안을 재제시하고 수정되지 않은 다른 항목에 대해서는 재질문하지 않는다.

#### UI 감지 (Step 4 진입 시)

plan 주제, 요청 텍스트, 결정사항 섹션을 대상으로 아래 두 가지 방식 중 하나라도 해당하면 UI로 판단한다:

**1. 키워드 매칭**: `화면`, `UI`, `페이지`, `대시보드`, `컴포넌트`, `레이아웃`, `프론트엔드`, `디자인`, `화면 설계`, `목업`, `시안`

**2. 의미 판단 (LLM)**: 키워드 없어도 새 화면/UI 흐름 생성이 필요하거나 기존 화면/UI가 크게 수정된다고 판단되는 경우 (예: "로그인 흐름 구성", "어드민 메뉴 신설", "결제 단계 추가", "온보딩 프로세스 설계", "기존 대시보드 레이아웃 재구성")

- **감지됨 + `AUTO_MODE=false`**:
  - Step 4 저장 액션 AskUserQuestion 전에 아래 질문을 **반드시 1회** 실행한다:
    - 질문: `review 단계에서 브라우저 UI 테스트도 같이 진행할까요?`
    - 선택지: **"A. 브라우저 UI 테스트 진행"** → `## 브라우저 테스트` 섹션 추가 (`enabled: true`) → **즉시 Step 4.1으로 진행** / **"B. 이번에는 생략"** → `enabled: false`
  - 저장 액션 AskUserQuestion 선택지에 4번째 옵션 "스티치로 디자인 시안 보기" 추가
- **감지됨 + `AUTO_MODE=true`**: AskUserQuestion 없이 PM이 `브라우저 UI 테스트 진행(enabled: true)`을 기본값으로 자율 결정하고 `auto-decisions.md`에 기록. **즉시 Step 4.1의 AUTO_MODE=true 분기를 실행**. PM이 `mst:stitch`를 자동 호출해 시안을 초안에 반영.
- **미감지** → Stitch 단계 없이 진행

#### Agile 컨텍스트 감지 (Step 4 진입 시, MANDATORY + graceful)

1. 현재 plan 입력 args 본문에 `[고정층]`, `[활성층]`, `[변화층]` 3개 태그가 모두 존재하는지 검사. 모두 있으면 `agile_context_active=true`, 없으면 `false`.
2. `agile_context_active=true`일 때: `[고정층] 목적 파일:` 라인에서 objective.md 경로 추출 → objective.md Read → JTBD 요약, 프로젝트 DoD 전체 항목, 성공 지표를 `objective_context`로 보관. 없거나 파싱 실패 시 `[미확인]`으로 표기 (워크플로우 차단 금지).
3. `agile_context_active=false`이면 `objective_context` 처리 전체를 skip한다 (하위 호환).

#### Step 4.1: 테스트 흐름 수집 (브라우저 테스트 "진행" 선택 시 MANDATORY)

> `enabled: false`(생략) 또는 UI 미감지 시 이 단계 전체를 skip한다 (하위 호환).

**PM 추론 절차** (AUTO_MODE 공통): plan 대화 맥락(인수 기준 초안, 결정사항, 범위 섹션)에서 신규 기능 (new) 및 기존 기능 회귀 (regression) 테스트 흐름을 추론한다. 각 흐름은 1줄 설명으로 작성.

**`AUTO_MODE=false`**: PM이 추론한 테스트 흐름을 아래 형식으로 텍스트 출력 후 AskUserQuestion으로 확인:
```
[예상 테스트 흐름]
신규 기능:
  1. {흐름 설명}
기존 기능 회귀:
  1. {흐름 설명}
```
AskUserQuestion 선택지: **"A. 위 흐름으로 확정"** / **"B. 흐름 수정 필요"** (수정 후 반복) / **"C. 코드베이스 탐색"**. 추가 흐름은 UI 자동 Other 입력으로 받고, 입력 시 목록에 추가한 뒤 "더 추가할 흐름이 있나요?" 후속 질문을 반복한다.

**`AUTO_MODE=true`**: PM이 자율 추론한 테스트 흐름을 AskUserQuestion 없이 바로 확정. auto-decisions.md에 기록: `| 테스트 흐름 수집 | {N}개 흐름 (신규 {X}개 + 회귀 {Y}개) | {confidence:.2f} | PM 자율 판단 | 자율 |`

**test_flows 반영**: 확정된 테스트 흐름을 `## 브라우저 테스트` 섹션에 포함:
```markdown
## 브라우저 테스트
- enabled: true
- execution_phase: review-pass-a
- tools: playwright | claude-in-chrome | auto
- test_flows:
  - [new] {신규 기능 흐름}
  - [regression] {기존 기능 회귀 흐름}
```

1. 대화 내용 반영한 plan 초안 텍스트 제시 (**파일은 아직 작성하지 않음**)
   - **`## 인수 기준 초안` 섹션을 반드시 포함한다 (MANDATORY)**: "이 plan이 완료됐다는 것은:" 프리픽스로 시작하는 불릿 리스트. 내용은 구현 방법이 아닌 **관찰 가능한 결과/동작** 중심으로 기술. 각 PAC 항목에 `[TIER-A]` 또는 `[TIER-B]` 위험도 태그를 반드시 포함 (미부여 시 기본값 `TIER-B`). 영향 예상 항목은 `[IMPACT]` 태그를 포함한 독립 불릿으로 추가 (기본 등급 `[SHOULD]`, PM 재량으로 `[MUST]` 가능). `[IMPACT]` 항목이 0개인 plan은 graceful skip.
     - 예시: `- [SHOULD] [IMPACT] [TIER-A] 기존 설정 화면의 입력 폼이 정상 렌더링되고 저장 기능이 동작한다`
   - **`## 범위 예산 (Appetite)` / `## 제외 범위 (No-go Scope)` 섹션을 반드시 포함한다** (빈 값 placeholder 허용)
   - `## 제약사항` (Step 2.3) / `## 우선순위 (MoSCoW)` (Step 2.3) / `## 의존성` (Step 2.6) / `## 리스크 레지스터` (Step 3.8.3) 섹션 포함
   - **`## Intent (JTBD)` 섹션** (권장 — 생략 시 intent 파일 미생성): When I / I want to / So I can
   - **`## Objective 컨텍스트` 섹션** (`agile_context_active=true`일 때만):
     ```markdown
     ## Objective 컨텍스트
     - objective.md: {objective_context_path}
     - objective.ids.json: {objective_anchor_manifest_path | N/A}
     - JTBD 요약: {objective_jtbd_summary}
     - 프로젝트 DoD: (항목 목록)
     - 성공 지표: (지표 목록)
     ```
   - **`## Objective Trace` 섹션** (`agile_context_active=true` + objective anchor manifest 존재 시 MANDATORY):
     - 선택된 DoD/domain의 MUST objective anchor ID를 plan PAC 또는 Objective Trace row에 매핑한다.
     - `anchor_total`, `anchor_mapped`, `anchor_missing_ids`를 기록한다. `anchor_missing_ids`가 비어있지 않으면 plan 완료로 판정하지 않는다.
     - request가 재파싱할 수 있도록 objective detail path와 anchor manifest path를 그대로 남긴다.
   - UI 감지 시 `## 브라우저 테스트` 섹션 추가 (Step 4.1에서 수집된 흐름 목록 포함)
   - `debug_context` 또는 `capture_context` 활성, 또는 `UI 감지됨 + {PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md 존재` 시 `## 연관 컨텍스트` 섹션 포함 — **파일 경로만 기록, 내용 복사 금지**:
     ```markdown
     ## 연관 컨텍스트
     > 상세 내용은 아래 파일을 직접 참조하세요. 내용을 이 파일에 복사하지 않습니다.
     | 유형 | ID | 파일 경로 |
     |------|----|-----------|
     | 디버그 조사 | DBG-NNN | `.gran-maestro/debug/DBG-NNN/debug-report.md` |
     | 캡처 | CAP-NNN | `.gran-maestro/captures/CAP-NNN/capture.json` |
     | 디자인 시스템 | DESIGN.md | .gran-maestro/designs/DESIGN.md |
     ```
2. 저장 전 Confidence Score Matrix 자가평가 수행

   | 축 | 질문 | 점수 |
   |----|------|------|
   | Clarity | 요구사항·제약에 모호성/중의적 표현이 없는가? | 0.0~1.0 |
   | Feasibility | 범위 내에서 기술적으로 실현 가능한가? | 0.0~1.0 |
   | Decoupling | REQ 단위가 결합도 낮게 분리되었는가? | 0.0~1.0 |
   | Completeness | 후속 Agent가 코드 작성하기에 정보가 충분한가? | 0.0~1.0 |

   점수는 4축 요약 표 형태로 출력. **0.5 미만 항목**에는 "수정 후 진행" 권고를 표시. `AUTO_MODE=true`에서는 0.5 미만 축을 자율 보완하고 근거를 `auto-decisions.md`에 기록한 뒤 진행.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

3. 저장 액션 결정:
   - `AUTO_MODE=false`: `AskUserQuestion`으로 선택지 제시
     - **"저장하고 /mst:request 실행"**: plan.md 저장 후 mst:request 호출 (직접 구현 아님 — REQ 생성+spec.md 작성으로 이동)
     - **"저장하고 /mst:request -a 실행 (자율 모드)"**: plan.md 저장 후 mst:request를 자율 모드(-a)로 호출
     - **"수정 후 진행"**: 수정 내용 입력 후 Step 4 반복
     - **"저장만 하기"**: plan.md만 저장, mst:request는 수동 실행
       → 저장 완료 후 출력: `{PLN-NNN}으로 저장됨. 다음 명령으로 구현 사양(spec.md)을 작성할 수 있습니다.\n  - 일반: /mst:request --plan {PLN-NNN}\n  - 자율 모드: /mst:request --plan {PLN-NNN} -a` (**절대 /mst:approve를 안내하지 않음**)
       → 즉시 이어서 `AskUserQuestion`: **"지금 /mst:request 실행할까요?"** (선택지: **"A. 바로 실행"** / **"B. 자율 모드 실행"** / **"C. 여기서 종료"**)
     - **"스티치로 디자인 시안 보기"** *(UI 키워드 감지 시에만 표시)*
   - `AUTO_MODE=true`: `AskUserQuestion` 없이 **"저장하고 /mst:request 실행"** 경로를 기본값으로 즉시 진행 (규모·복잡도와 무관하게 이 경로만 허용)
4. 저장 선택 시 `plans/PLN-NNN/plan.md` 작성; `debug_context` 활성 시 `plan.json`에 `"linked_debug"` 추가

   #### linked_objective 기록 (agile 컨텍스트 전용, MANDATORY)

   - `agile_context_active=true`일 때만 `plan.json`에 `"linked_objective"` 필드를 추가한다.
   - `objective_context_path`에서 `/agile/(AGI-\d+)/objective/objective.md` 패턴으로 AGI ID 추출. 성공 시 `"linked_objective": "AGI-NNN"`, 실패 시 `"linked_objective": null`.
   - `agile_context_active=false`이면 기록하지 않는다 (하위 호환).

   #### AUTO_MODE next_action 기록 (MANDATORY)

   - `AUTO_MODE=true`이고 저장 액션이 `"저장하고 /mst:request 실행"` 또는 `"저장하고 /mst:request -a 실행"` 경로인 경우, `plan.json`에 아래 `next_action` 필드를 **반드시 기록**한다:
     ```json
     {
       "next_action": {
         "expected_skill": "mst:request",
         "source_skill": "mst:plan",
         "source_id": "PLN-NNN",
         "auto_mode": true,
         "project_root": "{PROJECT_ROOT}",
         "created_at": "{TS}"
       }
     }
     ```
   - 같은 조건에서 `{PROJECT_ROOT}/.gran-maestro/tmp/mst-next-action-${PPID}.json`를 Bash로 즉시 생성한다 (plan.json 기록 직후):
     ```bash
     mkdir -p "{PROJECT_ROOT}/.gran-maestro/tmp"
     cat > "{PROJECT_ROOT}/.gran-maestro/tmp/mst-next-action-${PPID}.json" <<EOF
     {"expected_skill":"mst:request","source_skill":"mst:plan","source_id":"PLN-NNN","auto_mode":true,"project_root":"{PROJECT_ROOT}","created_at":"{TS}"}
     EOF
     ```
   - `AUTO_MODE=false` 또는 `"저장만 하기"` 경로에서는 `next_action` 필드를 기록하지 않고 `.gran-maestro/tmp/` 마커도 생성하지 않는다.
   - `.gran-maestro/tmp/` 마커와 `plan.json.next_action` 클리어는 `mst:request` push hook이 authoritative 하게 처리한다 (순차 best-effort).

   #### PAC-N ID 자동 부여 + plan.ids.json 생성 (MANDATORY)

   - 저장 직전 `## 인수 기준 초안`의 불릿 목록을 순서대로 정규화한다.
   - 각 항목에 `PAC-N` ID를 자동 부여한다 (`PAC-1`, `PAC-2`, ...).
   - 등급 결정: `[SHOULD]` 태그 있으면 `grade="SHOULD"`, 그 외는 `grade="MUST"`.
   - 태그 결정: `[IMPACT]` 태그 → tags에 `"IMPACT"` 추가. `[TIER-A]` → `"TIER-A"`, `[TIER-B]` → `"TIER-B"`. 둘 다 없으면 기본값 `"TIER-B"`. 기존 태그와 Tier 태그는 독립적으로 공존.
   - `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.ids.json` 파일을 반드시 생성/갱신한다:
     ```json
     [
       { "id": "PAC-1", "text": "...", "grade": "MUST", "tags": ["TIER-B"] },
       { "id": "PAC-2", "text": "...", "grade": "SHOULD", "tags": ["IMPACT", "TIER-A"] }
     ]
     ```
   - 하위호환: 기존 항목에 `tags` 필드가 없어도 오류로 처리하지 않고 `tags=[]`로 간주.
   - `pac_trace.enabled != true`여도 파일 생성은 유지한다 (하위 단계 호환 목적).

   #### Intent 파일 자동 생성 (비차단)

   plan.md 저장 직후, `## Intent (JTBD)` 섹션이 존재하고 비어있지 않으면:
   - `When I` → `--situation`, `I want to` → `--feature`, `So I can` → `--goal` 및 `--motivation` (동일 값)
   - `context_manifest_files`가 비어있지 않으면 각 파일 경로를 `--file "{파일경로}"` 형태로 전달, 비어있으면 `--file` 인자 없이 실행:
     ```bash
     MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py intent add \
       --plan PLN-NNN --feature "..." --situation "..." --motivation "..." --goal "..."
     ```
   - 반환된 INTENT_ID를 `plan.json`의 `"linked_intent": "INTENT-NNN"` 필드에 기록.
   - `## Intent (JTBD)` 섹션이 없거나 비어있으면 skip (비차단). 명령 실패 시 warn만 출력, 워크플로우 차단 금지.

   - `capture_context` 활성 시 **plan.md 저장 시점에 일괄 처리 (atomic)**:
     - 참조된 각 캡처의 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json`을 Edit: `status` → `"consumed"`, `consumed_at` → 현재 시각, `linked_plan` → `"PLN-NNN"`.
     - `plan.json`에 `"linked_captures": ["CAP-001", "CAP-003"]` 추가.

   #### Q&A 선호 요약 백그라운드 트리거 (MANDATORY, 비차단)

   plan.md 저장 직후 아래를 수행한다:
   - 입력 파일: `{PROJECT_ROOT}/.gran-maestro/qa-raw/PLN-NNN.jsonl`, `{PROJECT_ROOT}/.gran-maestro/plan-context.md`. 없으면 warn 후 skip.
   - 백그라운드 agent를 1회 호출해(`run_in_background: true`) `plan-context.md`를 갱신한다.
   - 갱신 규칙:
     1. Preference Table을 Source of Truth로 유지 (`id/domain/type/statement/weight/freq/last_seen/tags`)
     2. 강한 표현(절대/반드시/싫어/금지 등) 감지 시 `weight=HIGH` 부여
     3. Step 2에서 수집한 `disputed_preferences`에는 `[DISPUTED]` 태그 부여
     4. Prompt Hints는 Table 기반 파생으로 재생성, 빈도 숫자 직접 인용 금지
     5. 파일 길이가 200줄 초과 시 150줄로 압축 (제거 우선순위: `[DISPUTED]` → `NORMAL + freq=1 + 90일 미갱신` → 유사 statement 병합. `weight=HIGH` 항목은 압축 대상 제외)
   - 실패 시 warn만 출력하고 다음 단계로 진행.
5. **"저장하고 /mst:request 실행" / "저장하고 /mst:request -a 실행" 경로**: ⚠️ **plan.md 디스크 기록 확인 후에만** 단 1회 호출 (미저장 상태 호출 절대 금지)
   - `AUTO_MODE=true`: `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")`
   - `AUTO_MODE=false`, 일반 실행: `Skill(skill: "mst:request", args: "--plan PLN-NNN {주제}")`
   - `AUTO_MODE=false`, 자율 모드 선택 시: `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")`
   - `## 분리 실행` 섹션이 있으면 mst:request가 다중 REQ 자동 생성
   - ⚠️ **spec.md 작성 완료 전 plan 스킬 종료 금지**
   - request 결과에서 생성된 REQ ID를 수집하고, plan 스킬 최종 마무리의 마지막 블록에 다음 명령을 출력한다:
     ```text
     다음 단계 실행 명령:
       /mst:approve REQ-NNN
     ```
     REQ ID를 특정하지 못한 경우에는 fallback으로 `다음 단계 실행 명령:\n  /mst:list`를 출력한다.
6. Stitch 연계 (`AUTO_MODE=false`에서 선택했거나, `AUTO_MODE=true`에서 UI 감지된 경우):
   1. `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {plan 주제}")` 호출 (⚠️ `mcp__stitch__*` 도구 직접 호출 절대 금지)
   2. 호출 완료 후 Stitch 프로젝트/화면 정보를 plan 초안에 `## 디자인 시안` 섹션으로 추가: DES-NNN ID + 프로젝트 URL, 각 화면: 화면명 + Stitch URL + html_file 경로. html_file이 null이면 해당 행 생략.
   3. `AUTO_MODE=false`면 Step 4 재표시 (저장/수정 선택 가능), `AUTO_MODE=true`면 저장 경로로 계속 진행.
7. `AUTO_MODE=true`이고 plan.md 저장 완료 후 아래 요약을 반드시 출력:

   ```text
   [자율 실행 완료]
   PLN-NNN 플랜이 자율 모드로 완성되었습니다.
   - 총 자율 결정: {AUTO_DECISION_TOTAL}건
   - PM 자율 판단: {AUTO_PM_COUNT}건
   - discussion 사용: {AUTO_DISCUSSION_COUNT}건
   - web-search→discussion 사용: {AUTO_EXPLORE_DISCUSSION_COUNT}건

   자세한 결정 내역: .gran-maestro/plans/PLN-NNN/auto-decisions.md

   다음 단계 실행 명령:
     /mst:approve REQ-NNN
   ```
   생성된 REQ ID를 특정하지 못한 경우 마지막 명령은 `/mst:list`로 대체한다. 위 블록 뒤에 추가 설명을 붙이지 않는다.

## 출력 형식

`templates/plan.md`를 기본 템플릿으로 사용하여 plan.md를 작성합니다.
