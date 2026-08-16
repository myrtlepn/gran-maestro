---
name: approve
description: "사용자가 $mst:approve 또는 /mst:approve을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 approve 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[-a|--auto] [REQ-ID...] [--stop-on-fail | --continue] [--parallel] [--priority <level>]"
---

# maestro:approve

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

<!-- mst-session-class: identity-required; root-source: existing REQ argument -->
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

PM이 작성한 구현 스펙을 승인하고 Phase 2 실행을 시작합니다. 단건/배치 승인 모두 지원. Phase 3 PASS 후 최종 수락은 `workflow.auto_accept_result` 설정에 따라 자동 실행되지만, request child accept는 session branch까지만 반영되며 original base merge는 session-level accept 또는 `terminal_success` evidence gate에 남겨둡니다.

## Gate

### Entry

- 승인 대상 REQ와 의존성 검증 결과를 확정한 뒤에만 단건/배치 실행 루프로 진입한다.
- Phase 2 이후 단계는 NON-STOP 규칙(중간 멈춤 금지)을 적용 대상으로 잠근다.

### Exit

- Phase 3 결과 처리와 최종 수락(또는 수동 수락 안내)까지 완료되어야 approve를 종료할 수 있다.
- DAG 자동 연쇄가 활성화된 경우, 실행 가능한 후속 REQ가 더 이상 없거나 사용자 명시적 취소가 있을 때만 연쇄 루프를 종료한다.

### 금지 패턴

- "컨텍스트가 길어졌다", "대화가 길어졌다", "토큰을 많이 썼다"를 이유로 approve 실행을 임의 중단한다.
- 서브스킬 반환 메시지(`[TRACE_SAVED]` 등)를 종료 신호로 오해해 다음 Step 호출 없이 멈춘다.
- DAG 연쇄 중 실행 가능한 다음 REQ가 존재하는데도 임의 판단으로 체인을 종료한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "컨텍스트가 길어졌으므로 멈춘다." | 확인 증거: 컨텍스트 길이/대화 길이/토큰 소비량과 무관하게 `NEXT_ACTION` 출력 직후 다음 Step 도구 호출을 실행한다.
- 합리화 패턴: "대화가 길어졌으니 다음 REQ는 다음 턴에 하자." | 확인 증거: 실행 가능한 다음 REQ가 있으면 같은 실행 흐름에서 `mst:request --resume ... -a`를 즉시 호출한다.
- 합리화 패턴: "토큰 절약을 위해 DAG 자동 연쇄를 여기서 끝내자." | 확인 증거: 연쇄 루프는 사용자 명시적 취소 또는 실행 가능한 후보 부재 시에만 종료한다.
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

State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

Parent session inheritance contract: child invocation, subprocess, and hook execution inherit parent `MST_SESSION_ID`; children must not issue arbitrary `mst_session_id`. Hook payload `mst_session_id` is allowed only when it matches the inherited parent `MST_SESSION_ID`.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

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

### REQ ID 결정 (인자 파싱)

`$ARGUMENTS`를 파싱하여 승인 대상 REQ 리스트를 결정합니다. 아래 규칙을 순서대로 적용합니다.

#### 1. 명시적 단건 인자

`$ARGUMENTS`가 단일 REQ 패턴(`REQ-NNN`)이면 **단건 승인 프로토콜**을 직접 실행합니다.

#### 2. 명시적 다건 인자

공백 구분 REQ 패턴이 2개 이상이면 **토글 UI 없이** 직접 배치 실행합니다.

#### 3. 콤마 구분 및 범위 지정

콤마(`,`)나 범위(`..`) 포함 인자를 파싱합니다. 예시:

```
/mst:approve REQ-001,REQ-003,REQ-005     → [REQ-001, REQ-003, REQ-005]
/mst:approve REQ-001..005                 → [REQ-001, REQ-002, REQ-003, REQ-004, REQ-005]
```

범위 지정 시 **승인 가능 상태인 REQ만** 결과 리스트에 포함.

#### 4. `--priority` 필터링

`--priority <level>` 플래그가 있으면 해당 우선순위의 승인 가능 REQ만 필터링합니다. `request.json`의 `priority` 필드 기준. 필드 없는 REQ는 `normal`로 취급. REQ 패턴/범위와 조합 가능.

#### 5. 인자 없이 호출 — 조건부 분기

`$ARGUMENTS`에 REQ 패턴이 없고 플래그만 있거나 완전히 비어 있는 경우:

**스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request filter --phase 1 --format json` 실행 후 `status`가 `phase1_analysis` 또는 `pending_dependency`가 아닌 것 필터링. 실패 시 fallback.

**Fallback:**
1. `{PROJECT_ROOT}/.gran-maestro/requests/` 디렉토리의 모든 `request.json` 스캔
2. 승인 가능 상태 필터링: `current_phase == 1` 이고 `status`가 `phase1_analysis` 또는 `pending_dependency`가 아닌 것, 또는 `status`가 `phase2_spec_review`인 것
3. `--priority` 필터 있으면 추가 적용, REQ 번호 오름차순 정렬
4. 결과에 따라 분기:

| 승인 대기 REQ 수 | 환경 | 동작 |
|-----------------|------|------|
| 0개 | — | "승인 대기 중인 요청이 없습니다" 메시지 후 종료 |
| 1개 | — | **기존 단건 동작 그대로** (스펙 요약 → 승인 → Phase 2) |
| 2개+ | 대화형 (TTY) | **토글 선택 UI 진입** (아래 참조) |
| 2개+ | 비대화형 | **기존 동작 유지** (첫 번째 REQ 자동 선택, 단건 실행) |

#### 토글 선택 UI

승인 대기 REQ가 2개 이상이고 대화형(TTY) 환경일 때:

**배지 생성 규칙**: `dependencies.blockedBy` → `[←REQ-MMM]`, `dependencies.blocks` → `[→REQ-PPP]`, 복합 `[←MMM →PPP]`. 없으면 생략.

##### 2~4개인 경우 (multiSelect UI)

`AskUserQuestion`의 `multiSelect` 옵션 사용:
- `label: "A. REQ-NNN {title 앞 18자}  [←REQ-MMM →REQ-PPP]"` (배지 있을 때)
- `description: "[장점] 선택한 요청을 배치 실행에 포함합니다. [단점] 의존성이 있는 경우 선행 실패의 영향을 받습니다. [적합] Phase 1 완료, 태스크 N개 | 선행: REQ-MMM | 후행: REQ-PPP"` (의존성 있을 때)
- **기본값: 전체 선택**. 선택 후 확인 → 배치 실행. 0개 선택 시 "선택된 요청이 없습니다" 후 종료.

##### 5개 이상인 경우 (전체선택 / 직접 입력 UI)

1. **목록 텍스트 출력**: `REQ-NNN — {title}  [배지]  [태스크 M개]` 형식
2. **1차 AskUserQuestion**: `"A. 전체 선택"` 또는 `"B. ID 직접 입력"`
3. **`"A. 전체 선택"`**: 전체 대기 REQ 배치 실행.
4. **`"B. ID 직접 입력"`**: 2차 AskUserQuestion에서 REQ ID 자유 입력 → "콤마 구분 및 범위 지정" 파싱 로직으로 처리 → 배치 실행. 빈 입력/0건 → "선택된 요청이 없습니다" 후 종료.

---

### 단건 승인 프로토콜

**AUTO_MODE 초기화** (단건 프로토콜 진입 즉시):
1. args에 `--auto` 또는 `-a`가 있으면 `AUTO_MODE=true` (최우선)
2. args가 없으면 `{PLUGIN_ROOT}/scripts` 경유로 `read_workflow_state_auto_mode("mst:approve", "{REQ-ID}")` 호출
   - 반환값이 bool이면 `AUTO_MODE`에 채택
3. state fallback이 `None`이면 `request.json.auto_approve == true` 여부를 확인
4. 그래도 미결정이면 `config.auto_mode.approve` 확인
5. 모두 해당 없으면 `AUTO_MODE=false`

우선순위: `args > state(guarded, expected_source_id=REQ_ID) > request.json.auto_approve > config > false`
이후 모든 Step에서 이 변수를 사용한다.

`AUTO_MODE=true`이면 단건 프로토콜 진입 직후 workflow state를 기록한다 (non-blocking):

```bash
# RESOLVED(PLN-509): agile_loop_active 보존 — plan/agile 맥락은 Step 4b 브리프 변수(PLAN_JSON_META/PAC_LIST/OBJECTIVE_SECTION)로 주입됨 (PLN-469 → PLN-509)
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:approve \
  --req "{REQ-ID}" \
  --next-skill mst:accept \
  --next-source "{REQ-ID}" \
  --source-skill mst:approve \
  --auto true \
|| echo "[mst:approve] warning: failed to update workflow state" >&2
```

`AUTO_MODE=false`에서는 이 호출을 실행하지 않는다.

**세션 중 자율 모드 전환**: `AskUserQuestion` 대기 중 사용자가 "auto로 해줘", "자율 모드로", "-a로", "지금부터 자동으로" 등을 입력하면 즉시 `AUTO_MODE=true`로 전환합니다. 전환 즉시 `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력 후 현재 Step부터 AUTO_MODE=true 적용하여 재개.

REQ 리스트가 1건이거나 명시적 단건 인자 호출 시 이 프로토콜을 실행합니다.

1. `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/` 하위 spec.md 확인
   - **spec.md 없으면**: Phase 1 미완료. 사용자에게 알리고 PM Conductor 분석 재실행
2. 스펙 요약을 사용자에게 표시
2.3. **체인 자동 실행 제안** (조건: `dependencies.blocks` 비어있지 않음 AND `workflow.auto_approve_on_unblock == false`):
  - 조건 미충족 시 이 단계 skip, Step 2.5로 진행
  - `AUTO_MODE=true` 또는 `request.json.auto_approve=true`이면 AskUserQuestion 없이 기본값("아니오, 각 단계마다 수동 approve") 적용 후 즉시 Step 2.5로 진행
  - 조건 충족 시 blocks 체인 시각화:
    ```
    이 REQ가 완료되면 아래 REQ들이 순서대로 실행 가능해집니다:
      REQ-NNN — {title} (대기 중)
      REQ-MMM — {title} (대기 중)  ← REQ-NNN 완료 후
    ```
    (blocks 배열의 직접 후속 REQ만 표시; 재귀 조회는 1단계만)
  - AskUserQuestion:
    - "예, 자동으로 연결 실행" → `config.json`의 `workflow.auto_approve_on_unblock`을 `true`로 업데이트
      알림: "✓ 이후 모든 체인에서 의존성 해소 시 자동 approve가 실행됩니다. (`/mst:settings workflow.auto_approve_on_unblock false`로 되돌릴 수 있습니다)"
    - "아니오, 각 단계마다 수동 approve" → 현재 요청만 진행, 설정 변경 없음
2.7. **Pre-Impl Preflight 검사 (구현 착수 전 필수)**

구현을 시작하기 전 아래 검사를 수행한다:

1. spec.md Read — 실패 시 "spec.md 읽기 실패 (경로: {spec_path}) — 워크트리 구조 확인 필요" 오류 반환 후 착수 차단.
2. spec.md 내 `"Test Scenarios (Pre-Impl)"` 문자열 **포함 검사(contains)** — `"## Test Scenarios (Pre-Impl)"` (번호 없음) 또는 `"## N.N Test Scenarios (Pre-Impl)"` (번호 있음) 모두 허용.
3. 각 automatable AC에 대해 `Test:` 항목(실행 명령 또는 확인 방법) 기입 여부 확인

**통과 조건**: 섹션 존재 + 모든 automatable AC에 Test 항목 기입
**실패 시**: 구현 착수 중단 → "Pre-Impl Test Scenarios 미작성" 오류 반환
  - failure_class: ac_unclear
  - PM에 반환: spec.md의 Test Scenarios 섹션 보완 요청

**예외**: manual AC만 있는 spec은 Test Scenarios 섹션이 비어있어도 통과 허용

preflight 검사가 통과된 경우에만 아래 base 감지/protected 검사를 실행하고, 이 검사가 통과된 경우에만 Step 3(worktree 생성 및 구현 착수)로 진행.

**Session parent base resolve + protected original guard (차단 검사, preflight 통과 이후 실행)**:
- `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py worktree resolve-base --req {REQ-ID} --json)`를 실행한다.
  - `MST_SESSION_ID`와 active/reused session metadata가 있는 정상 경로에서 stdout JSON의 `base`를 `SESSION_BASE_BRANCH`로 사용한다.
  - 성공 시 `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/request.json`의 `detected_base` 필드는 `session_branch`와 같은 값으로 저장되어야 한다.
  - 성공 JSON에는 `parent_mst_session_id`, `parent_session_branch`, `parent_session_worktree_path`, `original_base_branch`, `original_base_sha`가 포함되어야 한다.
- missing/invalid legacy-only identity, blocked session worktree, metadata mismatch는 original checkout/current HEAD fallback 없이 structured non-success diagnostic으로 approve를 차단한다.
- original base branch는 `original_base_branch`/`original_base_sha` reference로만 보존하며, final original merge trigger/scope는 DOD-005/DOD-013 범위로 남긴다.
- 이 단계에서는 REQ 브랜치나 태스크 worktree를 생성하지 않는다. `worktree.base_branch`는 하위 호환 설정으로만 남기며 approve의 신규 child base 결정에는 사용하지 않는다.

3. 승인 실행:
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 2 phase2_execution`; 실패 시 fallback으로 `request.json`의 `current_phase`=2, `status`=`phase2_execution` 직접 업데이트
   - `strategy.worktree_policy == "skip"`이면 worktree 생성을 스킵하고 `{PROJECT_ROOT}`에서 직접 작업, 그렇지 않으면 각 태스크에 대해 git worktree 생성
   - **Phase 2 (외주 실행) 프로토콜** 실행

---

### 실행 전 의존성 검증

REQ 리스트가 2건 이상일 때, 배치 실행 루프 진입 전 선택된 REQ 집합의 의존성 위반을 검사합니다.

```pseudo
violations = []
for req_id in selected:
  req = read_request_json(req_id)
  for dep in req.dependencies.blockedBy:
    if dep not in selected:
      violations.append({ req: req_id, missing_prereq: dep })

if violations:
  출력: "⚠️ 의존성 위반 감지:"
  for v in violations:
    출력: "  - {v.req}은 {v.missing_prereq}이 먼저 완료되어야 하나 선택 목록에 없음"

  AskUserQuestion:
    - "누락된 선행 REQ 추가하여 전체 체인 실행"  → 누락 REQ를 selected에 추가 후 재진행
    - "후행 REQ 제외하고 선택된 것만 실행"      → violations의 후행 REQ를 selected에서 제거 후 재진행
    - "취소"                                   → 종료
```

위반이 없거나 사용자 선택 후 재진행 시, 아래 배치 실행 루프로 진입합니다.

---

### 배치 실행 루프

REQ 리스트가 2건 이상일 때 실행합니다.

#### 실행 모드 결정

| 플래그 | 동작 |
|--------|------|
| (기본, 플래그 없음) | **순차 실행** — 각 REQ의 전체 라이프사이클(Phase 2 → 3 → 5) 완료 후 다음 REQ |
| `--parallel` | **병렬 실행** — `concurrency.batch_max_parallel_reqs`만큼 REQ를 동시 실행 |

#### 순차 모드

의존성 토폴로지 정렬을 수행하여 Wave 단위로 실행합니다. 의존성이 없는 REQ는 단일 Wave로 묶입니다.

**topological_sort_into_waves 알고리즘:**
```pseudo
def topological_sort_into_waves(req_ids):
  in_degree = {r: 0 for r in req_ids}
  for r in req_ids:
    for dep in read_request_json(r).dependencies.blockedBy:
      if dep in req_ids:
        in_degree[r] += 1

  waves = []
  remaining = set(req_ids)
  while remaining:
    wave = [r for r in remaining if in_degree[r] == 0]
    if not wave:               # 사이클 감지
      경고: "의존성 사이클 감지, 남은 REQ는 독립 실행"
      wave = list(remaining)
    waves.append(sorted(wave))
    for r in wave:
      remaining.remove(r)
      for s in remaining:
        if r in read_request_json(s).dependencies.blockedBy:
          in_degree[s] -= 1
  return waves
```

**Wave 캐스케이드 실행:**
```pseudo
waves = topological_sort_into_waves(req_list)

출력: "실행 계획:"
for i, wave in enumerate(waves):
  출력: "  Wave {i+1}: {wave} (순차 실행)"

all_results = []
outer: for wave_num, wave in enumerate(waves):
  출력: "── Wave {wave_num+1}/{len(waves)} 시작 ──"
  wave_results = []
  for req_id in wave:
    result = 단건 승인 프로토콜 실행(req_id, AUTO_MODE=현재 AUTO_MODE 값)
    wave_results.append(result)
    if result == FAILED:
      오류 처리 규칙 적용 (§ 배치 오류 처리)
      if 중단 결정:
        남은 REQ (현재 Wave 미실행 + 이후 Wave 전체) → skipped
        break outer
  all_results.extend(wave_results)

  failed_in_wave = [r.req_id for r in wave_results if r.status == FAILED]
  if failed_in_wave:
    이후 Wave에서 failed REQ를 blockedBy로 가진 REQ들 → 자동 Skip 마킹
    출력: "의존 REQ N개를 Skip합니다" 알림

최종 요약 출력(all_results)
```

#### 병렬 모드 (`--parallel`)

`--parallel` 플래그 사용 시에도 Wave 경계는 준수합니다. Wave 내 REQ들은 병렬 실행하고, Wave 간에는 순차 유지.

`config.concurrency.batch_max_parallel_reqs` 값으로 동시 실행 REQ 수를 결정합니다.

```pseudo
max_concurrent = config.concurrency.batch_max_parallel_reqs  # 기본 1

queue = req_list.copy()
running = {}
results = []

while queue 또는 running:
  while len(running) < max_concurrent and queue:
    req_id = queue.pop(0)
    if has_failed_dependency(req_id, results):
      results.append({req_id, status: "skipped", reason: "의존 REQ 실패"})
      continue
    출력: "[진행] {req_id} — 승인 시작..."
    task = 비동기로 단건 승인 프로토콜 실행(req_id)  # run_in_background
    running[req_id] = task

  for req_id, task in running:
    if task.completed:
      results.append(task.result)
      running.remove(req_id)
      출력: "[완료] {req_id} — {status}"

  sleep(backoff)

최종 요약 출력(results)
```

> **슬롯 관리**: 전역 동시 태스크 수는 `min(batch_max_parallel_reqs × max_tasks_per_req, worktree.max_active)`로 제한.

#### 진행 피드백 형식

순차: `[1/3] REQ-013 "JWT 미들웨어" — 승인 중... → 실행 중... → 완료`

병렬: `[병렬 2/3] REQ-013 시작 | REQ-014 시작`

최종 요약:
```
═══ 배치 승인 완료 ═══
성공: 2  |  실패: 1  |  건너뜀: 0
REQ-015: Phase 2 사전검증 실패 (tsc error) → /mst:approve REQ-015 로 재시도
```

---

### 배치 오류 처리

| 환경 | 기본 동작 | 세부 |
|------|-----------|------|
| **대화형 (TTY)** | **Prompt** | Continue / Skip / Retry / Abort 4지선다 제시. 기본 커서 위치: Continue |
| **비대화형 (CI)** | **Continue** | 실패 REQ는 `failed` 마킹 후 나머지 계속 진행. 최종 exit code: 실패 1건 이상이면 non-zero |

**의존성 기반 예외**: `dependencies.blockedBy` 관계에서 선행 REQ 실패 시 후속 REQ **자동 Skip** (환경 불문). `blockedBy` 미기재 시 독립 REQ로 취급.

**행동 수정자**: `--stop-on-fail` — 첫 실패 시 즉시 중단. `--continue` — 실패 무시 후 계속. (의존성 Skip은 양쪽 모두 유지)

실패한 REQ의 `status`를 `failed`로 마킹. 재진입: `/mst:approve REQ-NNN` 단건 호출 또는 다음 배치 시 토글 UI 재선택.

---

### Phase 2 외주 실행 프로토콜

#### OMX 플래그 취득 (Phase 2 진입 시 1회)

OMX_AUTOPILOT = (config.omx.enabled == true && config.omx.autopilot == true)
               → config.omx 키 미존재 시 false로 처리 (fallback)

이 값을 Step 4c / Fix / Escalation에서 참조한다.

Phase 2에서 Claude(PM)는 **절대 코드를 직접 작성하지 않습니다**. 모든 구현은 `/mst:codex` 또는 `/mst:agy`로 외주합니다.

#### 실행 전략 결정 (Phase 2 진입 시 1회, MANDATORY)

`request.json.source_plan -> plan.json.type -> type-strategies.json` 체인으로 실행 전략을 결정한다.

```pseudo
source_plan = request.json.source_plan
plan_type = "code"
if source_plan exists:
  plan = Read({PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json)
  plan_type = plan.type if plan.type exists else "code"

type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)
strategy = type_strategies[plan_type] || type_strategies["code"]

if Read/parse/key lookup failed:
  strategy = {
    "template": "templates/impl-request.md",
    "worktree_policy": "required",
    "review_mode": "code",
    "accept_mode": "squash-merge"
  }  # 하위 호환
```

- plan.json Read 실패, type 누락, type-strategies Read 실패/키 누락은 모두 code 전략 fallback으로 처리.
- `strategy.worktree_policy == "skip"`이면 DocExecutor 전략(문서 초안 생성 → 구조 검증 → 팩트체크)을 사용한다.

#### Step 1: 전체 태스크 스펙 일괄 검증 (외주 전 필수)

#### Step 2.7: Preflight — spec.md Read 검증

각 태스크의 spec.md를 Read하기 전 경로 유효성을 확인합니다:
- spec.md Read 실패 시: `"spec.md 읽기 실패 (경로: {spec_path}) — 워크트리 구조 확인 필요"` 오류를 반환하고 해당 태스크의 구현 착수를 차단합니다.
- Read 성공 후 아래 일괄 검증을 진행합니다.

모든 태스크의 spec.md를 일괄 검증합니다. 다음 항목이 명확한지 확인, 부족하면 보완:
- **수락 조건** (§3): AC가 pass/fail로 측정 가능한지
- **테스트 계획** (§5): 실행 명령어와 항목이 구체적인지
- **변경 범위** (§2): 수정 파일 목록 명시 여부

**Ideation 자동 트리거 (LLM 판단)**: 아래 상황 감지 시 `/mst:ideation` 호출하여 스펙 보완:
- 접근 방식 타당성 불확실 또는 대안이 더 나을 가능성
- 수락 조건 모호로 외주 에이전트 구현이 어려운 경우
- 아키텍처/보안/성능 설계 근거 부족
명백한 구현은 스킵.

#### Step 2: 의존성 분석 및 실행 계획 수립

1. 각 태스크의 `spec.md §7`에서 `blockedBy` 배열 읽기
2. 태스크 분류:
   - **독립 태스크**: `blockedBy` 비어있음 → 즉시 실행
   - **의존 태스크**: `blockedBy` 있음 → 선행 완료 후 실행
   - **단일 태스크**: 1개뿐 → 기존 순차 실행
3. 실행 계획 사용자 표시:
   ```
   Wave 1: {독립 태스크 목록} (병렬 실행)
   Wave 2: {Wave 1 완료 후 실행 가능한 태스크} (병렬 실행)
   ```

#### Step 3: 실행 에이전트 결정

spec.md 헤더의 `Assigned Agent` 필드를 읽어 에이전트를 결정합니다.

| 태스크 유형 | 에이전트 | capabilities |
|------------|---------|-------------|
| 백엔드, 리팩토링, 테스트 | `codex-dev` → `/mst:codex` | code, refactor, test |
| 신규 `.ts` 파일 생성, 단순 리팩토링·보일러플레이트, 독립 테스트 작성, 소규모 `.ts` 인라인 수정 | `codex-dev` → `/mst:codex` | code, refactor, test |
| 프론트엔드, 문서, 대용량 컨텍스트 | `agy-dev` → `/mst:agy` | frontend, docs, large-context |
| `.md` 문서, `.json`/`.env` config, `*.config.ts`, 기존 `.ts` 인라인 수정(신규 `.ts` 생성 없음) | Codex-primary: `codex-dev` → `/mst:codex`; legacy Claude preset: `claude-dev` → `/mst:claude` | code, docs, config, small-inline |

> **경계 케이스 기본값**: 태스크 유형이 모호한 경우 → `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get workflow.default_agent)` 값 사용 (`claude-dev` 하드코딩 금지).
> **Route guard**: shared routing protocol의 `host context`와 `delegation route`를 먼저 실행한다. Same-host `native_candidate`는 Codex collaboration 또는 Claude Task/Agent를 사용하며 provider CLI 설치 여부를 요구하지 않는다. CLI preflight와 `mst.py run`/`dispatch build`는 `route=external`일 때만 수행한다.

`claude`와 `claude-dev`는 동일하게 처리됩니다 (하위 호환).

`Assigned Agent` 필드 읽기: (1) `최종:` 패턴이 있으면 `최종:` 이후 값을 에이전트명으로 사용. (2) `최종:` 패턴이 없으면 필드 값 전체를 사용. (3) 필드가 없거나 비어있으면 `workflow.default_agent`를 fallback으로 사용.

**`Assigned Agent: claude`/`claude-dev`인 경우**: Step 4에서 Claude provider를 선택하고 shared routing protocol로 위임한다. Same-host는 Task/Agent, external route만 `/mst:claude` managed wrapper를 사용한다. PM은 직접 구현하지 않습니다.

#### Step 4: 병렬 디스패치 실행

**REQ 브랜치 생성 (태스크 수와 무관한 공통 선행 단계)**:

```bash
SESSION_BASE_BRANCH="{Step 2.7에서 저장한 request.json.detected_base}"
REQ_BRANCH=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree branch-name --req REQ-NNN --base "$SESSION_BASE_BRANCH" --role integration --agi "${AGI_ID:-}")
INTEGRATION_WORKTREE=$(python3 {PLUGIN_ROOT}/scripts/mst.py worktree path --req REQ-NNN --role integration --agi "${AGI_ID:-}")
python3 {PLUGIN_ROOT}/scripts/mst.py worktree create --path "$INTEGRATION_WORKTREE" --branch "$REQ_BRANCH" --base "$SESSION_BASE_BRANCH"
```

REQ 브랜치명은 AGI_ID가 있으면 `gran-maestro/{base_slug}/{AGI_ID}/REQ-NNN`, 없으면 legacy fallback으로 `gran-maestro/{base_slug}/REQ-NNN` 형식이다. `base_slug`는 session branch base의 `/`만 `-`로 치환한다.
REQ 브랜치 checkout과 태스크 통합은 원본 `PROJECT_ROOT` 또는 original checkout이 아니라 `INTEGRATION_WORKTREE`에서만 수행한다.
accept 단계는 후속 수락 정책에서 `request.json.detected_base`와 original base reference를 구분해야 하며, final original branch merge trigger/scope는 DOD-005/DOD-013 범위로 남긴다.
단일 태스크 REQ에서도 반드시 integration worktree를 생성해야 accept의 3단계 플로우가 정상 작동한다.

**태스크가 1개인 경우**: 기존 순차 실행과 동일 처리.

**실행 타입 분기 (if 1개, MANDATORY)**:
- `if strategy.worktree_policy == "skip"`:
  - 4a worktree 생성 단계는 스킵하고 `{PROJECT_ROOT}`에서 직접 작업한다.
  - 4b 브리프는 `templates/doc-request.md` 템플릿을 사용한다.
  - 4c 외주 지시는 코드 구현 대신 문서 작성 흐름(문서 초안 생성 → 구조 검증 → 팩트체크)으로 작성한다.
- `else` (`strategy.worktree_policy != "skip"`):
  - 아래 4a~4c 기존 절차를 그대로 수행한다. (변경 금지)

**태스크가 2개 이상이고 독립 태스크가 존재하는 경우 (`strategy.worktree_policy != "skip"`)**:

##### 4a. Worktree 일괄 생성

독립 태스크들의 git worktree를 미리 생성합니다. 태스크 worktree는 integration worktree에서 준비된 REQ 브랜치를 기준으로 생성:

```bash
TASK_BRANCH=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree branch-name --req REQ-NNN --task T01 --base "$SESSION_BASE_BRANCH" --agi "${AGI_ID:-}")
python3 {PLUGIN_ROOT}/scripts/mst.py worktree create --path {worktree_path} --branch "$TASK_BRANCH" --base "$REQ_BRANCH"
```

##### 4b. Outsource Brief 파일 작성

독립 태스크들의 브리프 파일을 **하나의 메시지에서 동시에 Write** 호출합니다.

```
Write -> {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-impl.md
```

브리프는 `templates/impl-request.md` 템플릿 사용. (`strategy.worktree_policy != "skip"` 경로)
- 브리프는 DOD-003 path-first contract를 유지해야 하며, 렌더링 결과에 `[CONTEXT_FILES]`와 `[WORK_CONTRACT]` block이 모두 포함되어야 한다.
- `[CONTEXT_FILES]` 필수 항목: `objective`, `objective_ids`, `plan`, `plan_json`, `plan_ids`, `spec`, `spec_context_manifest`, `previous_feedback`
- `[WORK_CONTRACT]` 필수 항목: `read_requirements`, `output_contract`, `verification_contract`, `failure_contract`
- 완료 보고 필수 항목: 변경 파일 목록, 생성/수정한 테스트, `completion report`, `Read/inspection evidence`, `verify_cmd`, `expected_signal`
- `{{IMPL_CONTEXT}}`: PM 작성 — 3~5줄 자유 형식 (무엇을, 왜, 어떻게 + 주의사항)
  - Step 4b 시작 시 `Reference Lookup Protocol`을 먼저 실행하고, 생성된 `[REFERENCE_CONTEXT]` 블록을 `{{IMPL_CONTEXT}}` 끝에 주입한다.
  - `reference.auto_search != true`이면 자동 WebSearch 없이 기존 REF 캐시 조회 결과만 주입한다.
  - `request.json`에 `linked_designs`가 존재하고 비어있지 않으면, `{{IMPL_CONTEXT}}` 끝에 `"spec.md §10의 Stitch HTML 파일을 참조하되 기술 스택에 맞게 구현하세요."` 자동 추가.
- `{{SPEC_PATH}}`, `{{WORKTREE_PATH}}`, `{{REQ_ID}}`, `{{TASK_ID}}`: 자동 주입
- `{{PLAN_PATH}}`: `request.json.source_plan` 존재 시 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`, 미존재 시 `NO_SOURCE_PLAN`
- `{{PREV_FEEDBACK_PATH}}`: 첫 실행 시 "N/A", 재실행 시 feedback 파일 경로
- `{{PLAN_JSON_META}}`: resolve 순서 `request.json` → `plan.json` → `plan.ids.json` → `objective.md`. `request.json.source_plan`이 존재하면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`을 Read하여 `cynefin_domain`, `linked_objective`, `linked_intent`, `linked_captures` 필드와 원본 경로를 3~5줄 요약으로 주입한다. `linked_intent`가 있으면 `python3 {PLUGIN_ROOT}/scripts/mst.py intent get {INTENT_ID} --json`으로 원본 intent를 조회하고, 반환된 원본 경로 또는 `{PROJECT_ROOT}/.gran-maestro/intent/{INTENT_ID}*.md` 조회 패턴과 확인 결과를 함께 주입한다. 미존재 시 warn 로그 + `NO_PLAN_JSON`, `NO_LINKED_INTENT`, `missing_context`, 또는 명시적 skip reason으로 치환한다.
- `{{PAC_LIST}}`: `source_plan`이 존재하면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json`을 Read하여 경로와 각 항목의 `id`, `grade`, `tags`, `text` 필드를 목록으로 주입한다. 미존재 시 warn 로그 + `NO_PLAN_IDS`, `missing_context`, 또는 명시적 skip reason으로 치환한다.
- `{{OBJECTIVE_SECTION}}`: `plan.json.linked_objective`가 존재하면 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI-NNN}/objective/objective.md`와 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI-NNN}/objective/objective.ids.json`(존재 시)을 Read하여 원본 경로, JTBD 요약, 프로젝트 DoD 항목, 성공 지표, objective anchor coverage evidence를 3~5줄 요약으로 주입한다. legacy plan에서 linked_objective/linked_intent/plan.ids.json 각각 미존재 시 warn 로그 + `NO_LINKED_OBJECTIVE`, `NO_OBJECTIVE_IDS`, `NO_LINKED_INTENT`, `NO_PLAN_IDS`, `missing_context`, 또는 명시적 skip reason으로 치환한다. agile-origin objective anchor metadata가 있는데 anchor manifest나 coverage evidence가 없으면 "N/A"로 숨기지 말고 brief에 누락 evidence를 남기고 review/accept가 확인할 수 있게 전달한다.
- `spec_context_manifest`는 항상 `{{SPEC_PATH}}#§0-Context-Manifest`로 전달하고, spec에 해당 섹션이 없으면 `NO_CONTEXT_MANIFEST` 또는 `missing_context`를 남긴다.
- `previous_feedback`는 첫 실행에만 `N/A` 허용, 그 외 재실행 경로에서는 feedback 파일 경로나 명시적 skip reason을 남긴다.
- source_plan이 있는 브리프는 PM 작성 요약만 신뢰하지 말고 `plan.md`, `plan.json`, `plan.ids.json`, linked objective/intent 원본, spec `§0 Context Manifest` 원본 파일을 구현 전 직접 Read/inspection하라는 지시와 완료 보고의 `Read/inspection evidence` 기록 요구를 반드시 포함한다. source_plan이 없는 legacy 요청은 이 요구를 hard fail로 적용하지 않고 `NO_SOURCE_PLAN` 또는 동등한 structured skip reason을 남긴다.
- required context slot 규칙: `plan:`은 path-first required slot이므로 `N/A`로 렌더링하지 않는다. `{{PLAN_PATH}}`는 실제 `plan.md` 절대경로이거나 `NO_SOURCE_PLAN`이어야 하며, `previous_feedback`만 첫 실행에서 `N/A`를 유지할 수 있다.

##### 4c. 독립 태스크 동시 실행

각 태스크에 shared routing protocol을 독립 적용한다. Same-host native fan-out은 host native background agent를 사용하고, `run_in_background: true` 기반 Bash/managed wrapper 예시는 해당 태스크의 `route=external`일 때만 사용한다.

{task_dir} = {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/

## DOD-004 agy-dev Direct Bash Exception Contract

- `agy-dev` direct Bash exception은 병렬 dispatch(parallel dispatch)에서 `Skill(mst:agy)` 직렬 호출로 전환할 수 없는 경우에만 허용한다.
- direct Bash exception은 protected `/mst:agy` identity를 대체하지 않으며, prompt-file path와 context file path inspection 결과를 브리프와 completion report에 남겨야 한다.
- lifecycle evidence는 `running.log`, worktree path, trace label 또는 trace-equivalent id, final exit evidence, evidence path, evidence id를 포함한다.
- failure_kind는 `rate_limit`, `timeout`, `empty_result`, `nonzero_exit`로 구분하고, 429/rate-limit/quota 신호는 `rate_limit`으로 기록한다.
- Codex fallback은 `agy-dev → codex fallback` 정책에 따라 structured failure_kind와 lifecycle evidence가 존재할 때만 실행 또는 갭 태스크로 기록한다.

> ⚠️ **agy-dev Bash 강제 (MANDATORY)**: agy-dev는 단건/병렬 무관하게 **항상** `Bash(run_in_background: true)`로 실행한다.
> `Skill(mst:agy)` 전환 불가. trace는 `running.log`로 대체된다.

```bash
# route=external + codex-dev인 경우에만 (OMX_AUTOPILOT=true 시 \$autopilot 프리픽스 삽입)
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex");
  command: 'MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c '"'"'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'"'"')" python3 {PLUGIN_ROOT}/scripts/mst.py run --task-id {REQ-ID}-T{TASK-NUM} --provider codex --model "$MODEL" --log-dir {task_dir} --trace {REQ-ID}/{TASK-NUM}/phase2-impl --require-worktree --worktree-dir {worktree_path} -- codex exec --approve-for-me -m "$MODEL" -C {worktree_path} "\$autopilot $(cat {prompt_file})" < /dev/null',   # OMX_AUTOPILOT=true
  # 또는:
  command: 'MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c '"'"'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'"'"')" python3 {PLUGIN_ROOT}/scripts/mst.py run --task-id {REQ-ID}-T{TASK-NUM} --provider codex --model "$MODEL" --log-dir {task_dir} --trace {REQ-ID}/{TASK-NUM}/phase2-impl --require-worktree --worktree-dir {worktree_path} -- codex exec --approve-for-me -m "$MODEL" -C {worktree_path} "$(cat {prompt_file})" < /dev/null',              # OMX_AUTOPILOT=false
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)

# agy-dev인 경우
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model agy default 2>/dev/null);
  command: 'MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c '"'"'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'"'"')" python3 {PLUGIN_ROOT}/scripts/mst.py run --task-id {REQ-ID}-T{TASK-NUM} --provider agy --model "$MODEL" --log-dir {task_dir} --trace {REQ-ID}/{TASK-NUM}/phase2-impl --require-worktree --worktree-dir {worktree_path} -- agy --print "$(cat {prompt_file})" --dangerously-skip-permissions --add-dir "{worktree_path}" < /dev/null',
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)

# claude-dev (또는 claude)인 경우
if (route == "native_candidate" and host == "claude"):
  Task(subagent_type: "general-purpose", prompt: {prompt_file 내용 + DELEGATION BOUNDARY}, run_in_background: true)
elif (route == "external"):
  # route=external; external lane only
  Skill(skill: "mst:claude", args: "--prompt-file {prompt_file} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-impl")
```

`claude-dev` external 단건 실행은 bare `--trace`만 넘기지 않는다. Native lane은 shared lifecycle sequence를 사용하고, external Phase 2 dispatch는 다음 항목을 함께 묶는다:
- dispatch 입력: `--prompt-file {prompt_file}`, `--dir {worktree_path}`, `--trace {REQ-ID}/{TASK-NUM}/phase2-impl`
- wrapper-owned 파생/전달: `python3 {PLUGIN_ROOT}/scripts/mst.py run`, `--task-id {REQ-ID}-T{TASK-NUM}`, `--provider claude`, `--model "$MODEL"`, `--log-dir {task_dir}`
- lifecycle evidence: `{task_dir}/running.log`, trace path, session metadata, output/failure contract, exit-code propagation

각 실행에서 background `task_id`를 받은 직후, 아래 실제 CLI를 즉시 호출해 dispatch attempt metadata를 `request.json`에 영구 저장:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py request record-phase2-dispatch-attempt {REQ_ID} \
  --task-num {TASK_NUM} \
  --task-id {bg_task_id} \
  --attempt-id {attempt_id} \
  --dispatched-at {UTC ISO8601} \
  --agent {agent_slug} \
  --worktree-path {worktree_path} \
  --log-path {task_dir}/running.log \
  --expected-task-status-before {dispatch 직전 task.status} \
  --json
```

이 CLI는 내부적으로 `record_phase2_dispatch_attempt(req_id, **kwargs)` writer를 호출하며, 저장 결과는 아래 구조를 따라야 한다:

```json
{
  "background_task_ids": [
    {
      "task_id": "{bg_task_id}",
      "task_num": "01",
      "attempt_id": "{attempt_id}",
      "dispatched_at": "{UTC ISO8601}",
      "agent": "codex-dev",
      "worktree_path": "{worktree_path}",
      "log_path": "{task_dir}/running.log",
      "expected_task_status_before": "{dispatch 직전 task.status}",
      "status": "running"
    }
  ],
  "tasks": [
    {
      "id": "T01",
      "attempts": [
        {
          "attempt_id": "{attempt_id}",
          "task_id": "{bg_task_id}",
          "task_num": "01",
          "dispatched_at": "{UTC ISO8601}",
          "agent": "codex-dev",
          "worktree_path": "{worktree_path}",
          "log_path": "{task_dir}/running.log",
          "expected_task_status_before": "{dispatch 직전 task.status}",
          "status": "running"
        }
      ]
    }
  ]
}
```

`background_task_ids`는 계속 배열 계약을 유지하고 additive metadata만 보강한다. `tasks[].attempts[]`는 같은 attempt를 task 관점에서 다시 관찰하는 용도이며, 같은 REQ 내 기존 `attempt_id`와 충돌하면 dispatch를 즉시 실패시켜야 한다.

> **세션 간 추적**: `task_id`와 `attempt_id`를 기록하여 세션 전환, 재외주, append 로그 혼재 후에도 같은 시도를 식별한다. 필요 시 `TaskStop(task_id)`로 취소.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제). approve는 Phase 5 완료 시에만 종료.

##### 4d. 완료 감지 루프

모든 병렬 태스크가 완료될 때까지 폴링합니다.

```pseudo
backoff = 2초
max_backoff = 30초

while (실행 중인 태스크가 있음):
  for task_id in running_tasks:
    result = TaskOutput(task_id, block: false, timeout: 5000)
    if result.status == 'completed':
      remove task_id from running_tasks
      if result.exit_code == 0:
        Step 5로 이동(사전 검증)
      else:
        mark task status = failed
        Step 4e 실패 전파 규칙 적용
        Fallback 규칙 적용(필요 시 재실행)
      해당 태스크가 선행인 후속태스크가 있으면 4e로 이동

  if running_tasks 남아있음:
    sleep(backoff)
    backoff = min(backoff * 2, max_backoff)
```

##### 4e. 의존 태스크 디스패치 (선형 의존 체인)

선행 태스크 완료 시 blockedBy 해소:
1. 후속 태스크의 `blockedBy`에서 완료 태스크 제거
2. `blockedBy` 비면 4c에 추가해 병렬 실행
3. 실패 전파: 선행 `failed`이면 후속 태스크를 `cancelled`로 전이, 즉시 사용자 알림

#### Step 5: 사전 검증 (각 완료된 태스크별)

> ⚠️ **NON-STOP EXECUTION RULE (CRITICAL)**:
> Step 5 ~ Step 6 ~ Phase 3 ~ 최종 수락까지 **중간 멈춤 없이 연속 실행**한다.
> 텍스트를 출력했으면 **반드시 해당 단계의 도구 호출(Bash/Edit/Skill 등)을 즉시 실행**한다.
> **서브스킬 반환 직후 강제 패턴**: 서브스킬(mst:claude, mst:codex, mst:agy, mst:review 등)이 반환되면 반환 텍스트와 무관하게 **즉시** `NEXT_ACTION: <다음 Step 설명>` 패턴을 출력하고 해당 Step의 도구 호출을 실행한다. 서브스킬 반환은 종료가 아니라 **다음 단계 전환 신호**다.
> 컨텍스트 길이/대화 길이/토큰 소비량을 이유로 한 자발적 중단을 금지한다. Claude Code는 자동 대화 압축으로 실제 한계를 관리하므로, LLM이 이를 근거로 중단 여부를 직접 판단하지 않는다.
> 이 규칙은 이 approve 스킬의 모든 후속 Step에 적용된다.

각 태스크 완료 즉시 사전 검증 실행:
1. spec §5의 테스트 명령어 실행 (`test_output` 캡처 + exit code 확보)
2. spec §5의 타입 체크 명령어 실행 (`tsc_output` 캡처 + exit code 확보)
3. PASS/FAIL 분기 전에 `self_check` 객체를 생성하고 `request.json`의 현재 태스크에 기록
   ```pseudo
   self_check = {
     tsc: (tsc_exit_code == 0 ? "PASS" : "FAIL"),
     test: (test_exit_code == 0 ? "PASS" : "FAIL"),
     ran_at: now_in_iso8601_utc(),
     tsc_output: tsc_output,
     test_output: test_output,
     retry_round: (request_json.pre_check_retries or 0)
   }

   try:
     req = Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/request.json)
     task = find(req.tasks, id == {TASK_ID})
     if task exists:
       task.self_check = self_check
       Write(request.json, req)
     else:
       warn("[non-blocking] self_check 저장 대상 task를 찾지 못함: {TASK_ID}")
   except err:
     warn("[non-blocking] self_check 저장 실패: {err}")
   ```
   저장 실패는 **non-blocking**: 경고만 출력하고 다음 분기로 진행.
4. 결과 분기:
   - **PASS**: `status` → `review` → **즉시 Step 5.5 실행** (PM 커밋)
   - **FAIL**: `status` → `pre_check_failed` → **즉시 Step 5b 실행** (재외주)

#### Step 5.5: PM 커밋 (사전검증 PASS 시)

Step 5 PASS 후 PM이 직접 커밋합니다 (외주 에이전트의 `index.lock` 문제 방지).

0. 이중 커밋 방지: `git -C {worktree_path} status --porcelain` → 출력 없으면 이미 clean. 이 경우에도 현재 branch/HEAD evidence를 저장한 뒤 `status` → `committed` 전환 후 Step 5.7 진행.
   ```bash
   if [ -z "$(git -C {worktree_path} status --porcelain)" ]; then
     COMMIT_HASH=$(git -C {worktree_path} rev-parse --verify HEAD)
     COMMIT_MSG=$(git -C {worktree_path} log -1 --format="%s")
     TASK_BRANCH=$(git -C {worktree_path} symbolic-ref --quiet --short HEAD)
     MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py task set-commit {REQ_ID}-T{TASK_ID_PAD} "$COMMIT_HASH" "$COMMIT_MSG" \
       --branch "$TASK_BRANCH" \
       --worktree-path "{worktree_path}"
   fi
   ```

1. 전체 변경 스테이징: `git -C {worktree_path} add -A`

2. `frontend/` 변경 자동 감지 후 빌드:
   ```bash
   FRONTEND_CHANGED=$(git -C {worktree_path} diff --cached --name-only | grep "^frontend/" | head -1)
   if [ -n "$FRONTEND_CHANGED" ]; then
     cd {worktree_path}/frontend && npm install --prefer-offline && npm run build
     git -C {worktree_path} add dist/
   fi
   ```

3. PM이 커밋:
   ```bash
   git -C {worktree_path} commit -m "[{REQ_ID}/{TASK_ID}] {spec §1 요약}

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
   ```

4. 커밋 hash/message 저장 (실패 시 경고 후 계속):
   ```bash
   COMMIT_HASH=$(git -C {worktree_path} log -1 --format="%H")
   COMMIT_MSG=$(git -C {worktree_path} log -1 --format="%s")
   TASK_BRANCH=$(git -C {worktree_path} symbolic-ref --quiet --short HEAD)
   MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py task set-commit {REQ_ID}-T{TASK_ID_PAD} "$COMMIT_HASH" "$COMMIT_MSG" \
     --branch "$TASK_BRANCH" \
     --worktree-path "{worktree_path}"
   ```

5. 태스크 `status` → `committed`, `background_task_ids` status → `"completed"` 업데이트 → Step 5.7 진행. Step 6의 readiness gate는 각 완료 task의 `commit_hash`와 `branch`/`worktree_path`가 현재 task branch HEAD와 일치하는지 검증하므로 status만 갱신해서는 Phase 3으로 전환되지 않는다.

#### Step 5.7: 설계 의도 검증 루프 (PM 커밋 이후, Phase 3 이전)

> 이 Step은 Step 5 ~ Step 6 사이의 **NON-STOP EXECUTION RULE 적용 범위 내부**다.
> 검증 에이전트 반환 후 즉시 판정/보완/재검증 또는 Step 6 전환을 수행한다.

##### 5.7-0. 진입 게이트 (source_plan Guard + 하위호환)

1. `Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/request.json)`로 `source_plan`을 확인한다.
2. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get intent_verification review.auto_review workflow.auto_accept_result --json)`를 실행하고, stdout JSON 배열을 `phase3_config_items`로 보관한다. 같은 preload에서 `intent_verification`, `review.auto_review`, `workflow.auto_accept_result`를 함께 추출한다. 파싱 실패, 빈 값, 누락 항목은 graceful fallback 처리한다.
   - `intent_cfg`: `phase3_config_items`에서 `key == "intent_verification"`인 항목의 `value`. 파싱 실패 또는 빈 값이면 `{}`로 취급한다.
   - `intent_enabled`: `intent_cfg.enabled`가 boolean이면 그 값을 사용하고, 아니면 `true`.
   - `max_iterations`: `intent_cfg.max_iterations`가 양의 정수이면 그 값을 사용하고, 아니면 `5`.
   - `review.auto_review`, `workflow.auto_accept_result`도 같은 preload에서 함께 확보해 Step 6 Phase 3 리뷰 루프에서 재사용한다.
   - REQ-866 경계: readiness read-only 확인은 `request phase2-status`로 수행하고, 전환 실행은 기존 `advance-phase2-if-ready --json` 경로에만 남긴다. 상태 전이를 수행하는 `workflow gate-summary`류 bundle 명령은 사용하지 않는다.
3. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py request phase2-status {REQ_ID} --json)`를 실행하고, stdout JSON의 `ready` 값을 확인한다.
   - `ready != true`이면 아직 모든 Phase 2 태스크가 완료 상태가 아니므로 Step 6으로 이동해 전환 명령이 `incomplete_tasks`를 보고하게 한다.
4. `source_plan`이 없으면 `[Step 5.7 skip] source_plan 없음 (--plan 없는 REQ) → Step 6 진행`을 출력하고 Step 6으로 이동한다.
5. `intent_enabled == false`이면 `[Step 5.7 skip] intent_verification.enabled=false → Step 6 진행`을 출력하고 Step 6으로 이동한다.

##### 5.7-1. 비교 대상 초기화 (AD/PAC/구조 명세)

1. plan 파일 Read: `plan.md`(AD 및 구조 명세 섹션 추출), `plan.ids.json`(PAC 목록 추출)
2. 검증 결과 저장 디렉토리 준비: `intent-verification/`

##### 5.7-2. 반복 루프 (iteration = 1..max_iterations, 기본 5)

각 iteration마다 아래 (a)~(d)를 순서대로 실행한다.

###### (a) 검증 에이전트 디스패치

1. 템플릿 Read: `{PROJECT_ROOT}/templates/intent-verification.md`
2. 변수 치환(문자열 치환, MANDATORY): `{REQ_ID}`, `{PLN_ID}`, `{ITERATION}`, `{WORKTREE_PATH}`, `{AD_LIST}`, `{PAC_LIST}`, `{STRUCTURE_SPEC}`
3. 치환된 프롬프트 저장: `intent-verification/prompt-iteration-{iteration}.md`
4. Step 5b 재외주 패턴과 동일한 전략/재시도 정책으로 검증 에이전트를 디스패치한다.

###### (b) 리포트 저장 + PM 판정

1. 리포트를 즉시 저장한다 (MANDATORY): `intent-verification/iteration-{iteration}.md`
2. 판정 집계: 반영됨 / 부분반영 / 미반영
3. `부분반영 + 미반영 == 0`이면 수렴으로 간주하고 루프 종료: `"[Step 5.7 converged] 미반영 항목 0건 → Step 6 진행"`

###### (c) 보완 태스크 디스패치 (미반영 항목 존재 시)

1. `보완 필요 항목` 목록을 기반으로 단일 보완 태스크를 생성한다.
2. 기존 구현 태스크와 동일한 에이전트 배정/외주 브리프 패턴을 재사용한다.
3. 모드 분기:
   - `AUTO_MODE=true`: PM 자율 판단으로 즉시 보완 디스패치
   - `AUTO_MODE=false`: AskUserQuestion으로 미반영 목록 제시 → "보완하고 재검증" 또는 "남은 항목 무시하고 진행"
4. 보완 완료 후 PM 커밋은 **Step 5.5와 동일한 절차**(add/build-if-needed/commit/hash 저장)로 수행한다.

###### (d) 재검증 재진입

보완 커밋 완료 즉시 `iteration += 1` 후 Step 5.7-2 (a)로 재진입한다. `iteration > max_iterations`이면 루프 종료.

##### 5.7-3. 종료 조건

- 수렴: `부분반영 + 미반영 == 0` → 즉시 Step 6 진행
- 한도 도달: `iteration > max_iterations` → 잔여 미반영이 있어도 Step 6 진행
- 에이전트 실행 실패: 기존 outsource 재시도 패턴(`retry.max_cli_retries`) 적용

##### 5.7-4. 최종 요약 저장 (권장)

루프 종료 시 `intent-verification/summary.md`에 저장. 포함 항목: 총 iteration 수, 수렴 여부, 잔여 미반영 항목 목록.

##### 5.7-5. Step 6 연결

Step 5.7 종료 직후 **즉시** `Step 6: Phase 3 전환`으로 진행한다.

#### Step 5b: 사전검증 실패 재외주 (Pre-check Failure Re-outsourcing)

Step 5 FAIL 시, PM이 직접 코드를 수정하지 않고 외주 에이전트에게 에러 컨텍스트와 함께 재요청합니다. 최대 재시도 소진 후 PM 직접 개입.

**실행 타입 분기 (if 1개, MANDATORY)**:
- `if strategy.worktree_policy == "skip"`:
  - Step 5 FAIL을 문서 검증 실패로 해석하고, 아래 DocExecutor 재실행 루프를 우선 적용한다.
  - 최대 재시도는 고정 `2회`, 루프는 `팩트체크 실패 → 소스 재확인 프롬프트 생성 → 재작성` 순서.

##### 5b-doc-1. 팩트체크 실패 항목 수집

직전 문서 검증 결과에서 실패 claim 목록(`failed_claims`)과 근거 부족 항목(`unverified_claims`)을 추출. 각 항목에 대해 "현재 서술 / 실패 사유 / 필요한 근거(source)"를 정리한다.

##### 5b-doc-2. 소스 재확인 프롬프트 생성

`Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-doc-fix-R{N}.md`

포함 내용: spec.md §3 수락 조건, 실패/미검증 claim 목록 + 실패 사유, `§0 Context Manifest` 재확인 지시, "실패 claim 섹션만 재작성 후 구조 검증 + 팩트체크 다시 실행" 지시.

##### 5b-doc-3. DocExecutor 재실행 (동일 태스크 경로)

동일 에이전트로 재외주 실행. `request.json`에 `doc_factcheck_retries`(없으면 0)를 +1 저장. 재작성 완료 후 즉시 Step 5로 복귀.

##### 5b-doc-4. 재시도 한도 도달 시 PM 직접 개입

`doc_factcheck_retries >= 2`이면 루프 종료. PM이 소스 원문을 재확인해 문서를 직접 보정한 뒤 검증만 재실행한다.

- `else` (`strategy.worktree_policy != "skip"`):
  - 아래 `5b-1 ~ 5b-5` 기존 코드 경로를 **그대로** 수행한다. (변경 금지)

##### 5b-1. 에러 출력 캡처

- tsc 에러: 전체 stderr/stdout 캡처
- 테스트 실패: 실패 목록 + 에러 메시지 캡처
- 에러 출력 3000자 초과 시 앞 500자 + 뒤 2500자로 트리밍

##### 5b-2. 에러 출력 포맷터 적용 (Agent-Friendly)

5b-1의 트리밍된 에러 출력(`TRIMMED_ERROR_OUTPUT`)에 아래 포맷터 적용:
- `python3 {PLUGIN_ROOT}/scripts/format-precheck-errors.py`
- tsc 패턴: `파일경로(줄,열): error TSNNNN: 메시지` → `파일경로:줄 — TSNNNN — 메시지`
- 테스트 실패도 가능한 경우 동일 구조로 변환
- **Fail-safe**: 파싱 결과 0건이거나 예외 발생 시 `TRIMMED_ERROR_OUTPUT`을 그대로 사용 (passthrough). 최종 출력 변수명: `FORMATTED_ERROR_OUTPUT`

##### 5b-2.5. 재시도 카운터 확인

- `pre_check_retries` 필드 확인 (없으면 0)
- `config.retry.max_cli_retries` (기본 2) 미만 → 5b-3 (재외주)
- 이상 → 5b-5 (PM 직접 개입)

##### 5b-3. 에러 수정 프롬프트 생성

`Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-R{N}.md`

포함 내용: spec.md §3 수락 조건, **포맷된 에러 출력(`FORMATTED_ERROR_OUTPUT`)**, "에러 수정 후 검증 명령어 실행 확인" 지침, spec §5 테스트/타입체크 명령어. `<error_context>`의 `{ERROR_OUTPUT}`에 `FORMATTED_ERROR_OUTPUT` 바인딩.

##### 5b-4. 동일 worktree에서 재외주 실행

```pseudo
if OMX_AUTOPILOT:
  fix_content = Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-R{N}.md)
  fix_omx_path = {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-omx-R{N}.md
  Write(fix_omx_path, "$autopilot\n\n" + fix_content)
  Skill(skill: "mst:codex", args: "--prompt-file {fix_omx_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-fix-R{N}")
else:
  Skill(skill: "mst:codex", args: "--prompt-file {fix_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-fix-R{N}")
```

- `pre_check_retries` +1, `tasks[].retry_count` +1, `request.json` 저장
- `status` → `executing`. 재외주 완료 후 **즉시 Step 5 복귀**

##### 5b-4.5. Codex Fallback 추가 시도 (5b-5 이전)

`max_cli_retries` 소진 후, PM 직접 개입 전 Codex 에스컬레이션 1회 시도:

1. **에러 유형 분류**: 환경·의존성 이슈이면 → 즉시 5b-5로 이동
2. **`codex_fallback_retries` 확인**: `>= 1`이면 → 즉시 5b-5로 이동 (최대 1회 한도)
3. **stash 후 Codex 에스컬레이션**: `git -C {worktree_path} stash`, 에스컬레이션 프롬프트 준비 (`phase2-fix-R{N}.md` + `## 에스컬레이션 힌트` 섹션). Step 4c와 동일 패턴으로 실행 (`running-fallback.log` 출력).
4. **성공 시**: `codex_fallback_retries = 1` 업데이트 → Step 5 재진입. **실패 시**: stash pop → 5b-5 이동.

##### 5b-5. PM 직접 개입 (재외주 소진 시)

0. **실행 중 백그라운드 태스크 취소**: `background_task_ids`에서 `status: "running"` 항목을 `TaskStop(task_id)`로 취소 → `"cancelled"` 업데이트.
1. **worktree preflight**: 직접 수정 전 반드시 `python3 {PLUGIN_ROOT}/scripts/mst.py dispatch validate-worktree --worktree-dir {worktree_path} --json`를 실행한다. 실패하면 원본 checkout에서 수정하지 말고 `status="blocked"`, `reason="pm_direct_fix_worktree_guard_failed"`를 기록한다.
2. PM이 에러 출력 분석 후 `{worktree_path}` 내부에서만 직접 코드 수정
3. `request.json.tasks[].pm_direct_fix`에 `true`, `worktree_path`, `verification_command`, `expected_signal`, `changed_files`, `rollback_command`를 기록한다.
4. 사전검증(Step 5) 재실행
5. PASS → `status: review` / 여전히 FAIL → `git -C {worktree_path} checkout -- .` rollback 후 사용자 개입 요청

#### Step 6: Phase 3 전환

모든 Phase 2 태스크가 완료 상태(`committed`, `completed`, `done`, `accepted`)에 도달하면:

1. **Read-only readiness 확인**:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py request phase2-status {REQ_ID} --json)`를 실행한다.
   - Bash stdout JSON을 파싱해 `ready == true`이고 `advanced == false`인지 확인한다.
   - `ready == false`이면 stdout JSON의 `reason`과 `incomplete_tasks`를 근거로 아직 Phase 3에 진입하지 않고 대기/수정 분기로 이동한다.
2. **전환 실행**:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py request advance-phase2-if-ready {REQ_ID} --json)`를 실행한다.
   - Bash stdout JSON을 먼저 파싱한다. canonical read-only/MST_SESSION_ID guard가 막으면 command는 non-zero exit code를 반환할 수 있지만, stdout JSON은 `reason == "guard_blocked"`, `advanced == false`로 구조화되어야 한다.
   - exit code와 함께 stdout JSON을 확인해 `reason == "guard_blocked"`이면 takeover/manual recovery로 분기하고, readiness failure와 혼동하지 않는다.
   - guard 차단이 없을 때는 Bash stdout JSON을 파싱해 `ready == true`이고 `advanced == true`인지 확인한다.
   - 성공 시 request는 `current_phase=3`, `status=phase3_review`이며, `review_summary.status`는 기존 `passed`/`failed`가 아닌 경우 `pending_phase3_review`로 보장된다.

### Phase 3 리뷰 루프 (auto_review 활성화 시)

모든 Phase 2 태스크가 완료 상태에 도달하고 `current_phase`가 3으로 전환된 후:

1. `review.auto_review` / `workflow.auto_accept_result` 설정 확인:
   - 가능하면 Step 5.7-0의 `phase3_config_items` preload를 재사용한다.
   - Step 5.7을 건너뛴 경로라 preload가 없으면 `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get intent_verification review.auto_review workflow.auto_accept_result --json)`를 1회 실행해 `phase3_config_items`를 복구한다.
   - `AUTO_MODE`는 단건 프로토콜 진입 시 단일 초기화된 값을 그대로 사용한다 (이중 판단 금지).
   - `false` (기본): 아래 태스크 상태 검증 후 최종 수락 실행 (mst:review 미호출):
     1. `request.json.tasks` 전체 확인: 모든 Phase 2 태스크가 완료 상태(`committed`, `completed`, `done`, `accepted`)인지 검증
        - 미완료 태스크 존재 시: "태스크 {TASK_ID}가 아직 Phase 2 완료 상태가 아닙니다" 경고 후 대기
     2. 검증 통과 시 같은 `phase3_config_items` preload의 `workflow.auto_accept_result` 설정에 따라 즉시 실행:
        - **`true` (기본)**: `Skill(skill: "mst:accept", args: "{REQ_ID}")` 호출 → accept 완료 후 DAG 연쇄 실행 판단
        - **`false`**: Phase 3 리뷰 PASS로 간주하고 멈추고, 사용자에게 `/mst:accept {REQ_ID}` 수동 호출 안내
   - `true` 또는 `AUTO_MODE=true`이면 mst:review 호출 진행

#### Step 6.3: 이전 Iteration 결정 로그 복구 (iteration 2+)

`iteration_num >= 2`인 경우: `iteration-decisions/iteration-{iteration_num - 1}.md` Read → 컨텍스트 보관. 파일 없으면 skip.

2. mst:review 호출:
   ```
   AUTO_MODE=true  -> Skill(skill: "mst:review", args: "{REQ_ID} --auto")
   AUTO_MODE=false -> Skill(skill: "mst:review", args: "{REQ_ID}")
   ```
   (`AUTO_MODE=true`에서는 `review.auto_review=false`이더라도 항상 호출)
   > ⚠️ **반환 후 즉시 3번으로 진행** — `[TRACE_SAVED]` 텍스트 포함 여부 무관. approve는 Phase 5(mst:accept) 완료 시에만 종료.

#### Step 6.5: PM Iteration 결정 로그 저장 (Compaction 대비)

mst:review 반환 후, review 결과 처리(3번) 진입 전에 실행. `iteration-decisions/` 디렉토리 생성 후 `iteration-{iteration_num}.md` Write:

   ```markdown
   # Iteration {iteration_num} 결정 로그

   ## AC 상태
   {각 AC에 대해: AC-NNN: PASS/FAIL + 판단 근거 1줄}

   ## 핵심 판단
   {리뷰에서 발견된 주요 이슈에 대한 PM의 severity 동의/이의 + 결정 이유}

   ## 다음 iteration 방향
   {다음 iteration에서 집중할 AC 목록 + 추가 태스크 방향}
   ```

Write 실패 시 warn만 출력하고 워크플로우를 차단하지 않는다 (graceful).

3. review 결과 처리:

   **review_issues_summary 로드**: 최신 `reviews/RV-NNN/review.json`을 Read → `review_issues_summary` 파싱 (critical/major/minor 카운트 + auto_fixed/skipped 배열)
   - `auto_accept_guard` 메타 파싱:
     - `skipped_minor_count` = `review_issues_summary.auto_accept_guard.skipped_minor_count` (없으면 `0`)
     - `protection_flags_count` = `review_issues_summary.auto_accept_guard.protection_flags_count` (없으면 `0`)
     - `guard_blocked` = `review_issues_summary.auto_accept_guard.blocked == true OR skipped_minor_count > 0 OR protection_flags_count > 0`
     - `auto_accept_guard.blocked_reasons`가 있으면 차단 사유로 그대로 보고한다.

	   - **`status: "passed"`**: `review_summary.status → "passed"` 이후 아래 규칙으로 분기한다:
	     - `workflow.auto_accept_result == true AND guard_blocked == false`:
	       - accept 스킬을 명시적으로 호출:
	         ```
	         AUTO_MODE=true  -> Skill(skill: "mst:accept", args: "-a {REQ_ID}")
	         AUTO_MODE=false -> Skill(skill: "mst:accept", args: "{REQ_ID}")
	         ```
	       - ⚠️ **MANDATORY**: in-context 실행 시 Plan 상태 동기화가 생략되는 것을 방지하기 위해 반드시 Skill 도구를 통해 mst:accept를 호출한다.
	       - accept 완료 후 아래 **DAG 자동 연쇄 실행**을 즉시 판단한다.
	     - `workflow.auto_accept_result == true AND guard_blocked == true`:
	       - 즉시 auto accept를 호출하지 않는다.
	       - `auto_accept_guard.blocked_reasons`와 함께 보호 차단 상태를 보고하고, 사용자에게 `/mst:accept {REQ_ID}` 수동 호출 경로를 안내한다.
	     - `workflow.auto_accept_result == false`:
	       - Phase 3 리뷰 PASS 후 멈추고, 사용자에게 `/mst:accept {REQ_ID}`를 수동으로 호출하라고 안내한다. 설정 변경: `/mst:settings workflow.auto_accept_result false`

     **DAG 자동 연쇄 실행** (accept 완료 직후, `auto_accept_result == true`인 경우에만 실행):

     아래 조건을 모두 충족하면 같은 plan의 후속 REQ를 자동 연쇄 실행한다.
     (`auto_accept_result == false`인 경우의 DAG 연쇄 규칙은 `mst:accept`(Step 5.6)에서 실행)

     **실행 조건**:
     1. 현재 REQ의 `request.json`에서 `source_plan`이 `"PLN-NNN"` 형태로 존재
     2. 현재 REQ의 `request.json`에서 `dag_auto_chain == true`
     3. 현재 REQ 상태가 `done` 또는 `completed` 또는 `accepted`

     하나라도 불충족이면 DAG 연쇄 실행 단계는 skip.

     **다음 REQ 탐색 규칙**:
     1. 매 반복마다 `plan.json` Read 후 `linked_requests` 전체를 plan 정의 순서대로 재평가
     2. 후보 필터: 현재·완료·종료 상태 REQ 제외. 실행 가능 상태(`pending_dependency`, `phase1_analysis`, `spec_ready`)만 후보.
     3. `blockedBy` 해소 판정: 모든 선행 REQ가 `done`/`completed`/`accepted`이면 "실행 가능"으로 판단
     4. 실행 가능한 첫 번째 후보를 "다음 REQ"로 선택

     **자동 연쇄 실행 루프**:
     > **컨텍스트 길이 기반 중단 금지 (MANDATORY)**:
     > 아래 루프는 컨텍스트 길이/대화 길이/토큰 소비량을 이유로 중단하지 않는다.
     > **유일한 예외는 사용자의 명시적 취소 지시**다.

     ```pseudo
     chain_results = [{ req_id: CURRENT_REQ_ID, status: "completed" }]

     while true:
       plan = Read({PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json)
       next_req = first runnable req from plan.linked_requests (full scan each loop)
       if not next_req:
         break

       출력: "[DAG 연쇄] 다음 실행: {next_req.id} ({next_req.title})"
       Skill(skill: "mst:request", args: "--plan {source_plan} --resume {next_req.id} -a")

       refreshed = Read({PROJECT_ROOT}/.gran-maestro/requests/{next_req.id}/request.json)
       if refreshed.status in ["done", "completed", "accepted"]:
         chain_results.append({ req_id: next_req.id, status: "completed" })
         continue

       pending_tail = remaining non-terminal req ids in same plan
       출력: "[DAG 연쇄 중단] {next_req.id} 실패. 후속 REQ: {pending_tail.join(', ')}"
       종료

     if all linked_requests are done/completed/accepted:
       출력: "[DAG 연쇄 완료] {source_plan}의 모든 REQ가 완료되었습니다. ..."
     else:
       출력: "[DAG 연쇄 종료] 실행 가능한 다음 REQ가 없어 종료했습니다."
     ```

   - **`status: "gap_found"`**:
     **a. CRITICAL 이슈 존재 시**: CRITICAL은 PM 직접 수정 불가, 항상 재외주.

     **a-2. MINOR 이슈**: `review_issues_summary.skipped`에 기록된 대로 스킵, 재외주 대상에 포함하지 않음.

     **b. MAJOR 이슈 — PM 직접 수정 분기**:

     > **CRITICAL은 PM 직접 수정 불가, 항상 재외주**

     MAJOR 이슈 중 아래 **모든 조건**을 충족하면 PM이 worktree에서 직접 수정:
     1. MAJOR만 (CRITICAL이 동시 존재하면 해당 CRITICAL은 반드시 재외주)
     2. `config.review.severity_auto_fix.pm_direct_fix_enabled == true`
     3. 변경 대상 파일 수 <= `pm_direct_fix_max_files`
     4. 예상 diff 줄 수 <= `pm_direct_fix_max_diff_lines`
     5. 고위험 패턴 배제: API 스펙, DB 스키마/마이그레이션, 권한/보안 코드, 공통 유틸

     **PM 직접 수정 조건 미충족 시** → 재외주 경로(아래 c.)로 전환.

     **PM 직접 수정 절차**: MAJOR 이슈 중 조건 충족 이슈만 PM이 직접 수정하고 나머지는 재외주.
     1. `python3 {PLUGIN_ROOT}/scripts/mst.py dispatch validate-worktree --worktree-dir {worktree_path} --json`를 실행해 `{worktree_path}`가 등록된 linked worktree이고 primary checkout이 아님을 확인한다. 실패하면 직접 수정 분기를 중단하고 재외주 경로(c.)로 전환한다.
     2. PM이 해당 worktree에서만 직접 코드 수정
     3. **검증 게이트**: spec §5 테스트 + 타입 체크 → PASS 필수. PASS 시 Step 5.5와 동일한 커밋 절차. FAIL 시 롤백(`git -C {worktree_path} checkout -- .`) → 해당 MAJOR 이슈 태스크를 `request.json.tasks`에 신규 생성(`generated_by: "review"`, `status: "pending"`) → c. 경로로 진입.
     4. `review-report.md`에 `pm_direct_fix: true`, `worktree_path`, 수정 파일 목록, 수정 내용 요약, 검증 명령, expected signal, commit 또는 rollback evidence를 기록.

     **c. MAJOR 조건 미충족 또는 재외주 경로**:
     > ⚠️ **AUTO_MODE=true일 때 재외주는 무정지 실행**: AskUserQuestion 없이 즉시 아래 절차를 실행한다.
     1. `request.json.tasks`에서 `generated_by: "review"` + `status: "pending"` 태스크만 선별
     2. **Step 4a 포함** 재실행: 신규 태스크 worktree 생성 후 4b~4e 실행
     3. 재실행 완료 후 `current_phase → 3` 재전환 → 이 루프 반복

   - **`status: "pass_a_failed"`**:
     > ⚠️ CRITICAL: `pass-a-result.md` 스키마 필수 필드가 하나라도 누락되면 재외주 선별을 즉시 중단하고 review 재실행을 요구한다.

     | 조건 | 동작 | 다음 단계 |
     |---|---|---|
     | `pass-a-result.md` 스키마 검증 실패 (필수 필드 누락) | `"스키마 불일치"` 출력 + review 재실행 안내 | 재외주 선별 중단 |
     | 스키마 통과 + `covers_ac` 비어있지 않은 태스크 있음 | `failed_ac_ids ∩ covers_ac` 교집합 기준 선별 | 선별 태스크로 재외주 |
     | 스키마 통과 + 모든 `committed` 태스크의 `covers_ac`가 없거나 빈 배열 | 하위 호환 fallback — 전체 `committed` 태스크 선별 | 재외주 진행 |
     | 스키마 통과 + `covers_ac` 있으나 교집합 없음 | fallback 없이 빈 선별 유지 | 재외주 대상 없음 |
     | 스키마 통과 + 일부 태스크만 `covers_ac` 존재 | 교집합 기준 선별 + 나머지 fallback 포함 | 선별 태스크로 재외주 |

     재외주 태스크 선별:
     1. `reviews/RV-NNN/pass-a-result.md` Read → `failed_ac_ids` 파싱
     2. 스키마 검증: 필수 필드(`pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`) 하나라도 누락 시 중단
     3. `committed` 태스크 중 `covers_ac` 비어있지 않은 태스크: `failed_ac_ids ∩ covers_ac` 교집합 >= 1인 태스크 선정
     4. fallback: `covers_ac` 없거나 빈 배열인 `committed` 태스크는 fallback으로 포함

     재외주 절차:
     > ⚠️ **AUTO_MODE=true일 때 재외주는 무정지 실행**.
     1. 선별 태스크에 신규 태스크 항목 생성 (`generated_by: "review"`, `status: "pending"`)
     2. **Step 4a 포함** 재실행: 신규 태스크 worktree 생성 후 4b~4e 실행
     3. 재외주 완료 후 → `current_phase` 3 재전환 → `mst:review` 재호출

   - **`status: "limit_reached"`**:
     - 일반 모드: AskUserQuestion → [추가 반복 허용 (+1회)] / [현재 상태로 수락] / [중단]
     - `--auto` 모드: `review_summary.status = "limit_reached"` 기록 후 `workflow.auto_accept_result` 설정에 따라 즉시 실행

단, `--auto` 플래그 맥락: approve가 `--auto`로 실행된 경우 review 호출 시 컨텍스트로 전달됨.

#### Fallback 규칙

- 최대 깊이: 1단계 (codex → agy, agy → codex)
- 동일 에이전트 재시도: 최대 2회
- fallback 에이전트 재시도: 최대 2회
- 모두 실패 시: 사용자 개입 요청

## 문제 해결

- "승인할 스펙이 없음" → 해당 요청이 Phase 1(PM 분석) 완료 상태인지 확인. `/mst:inspect {REQ-ID}`로 상태 조회
- "이미 승인됨" → 해당 요청이 이미 Phase 2 이후에 있음. `/mst:inspect {REQ-ID}`로 현재 Phase 확인
- 최종 수락이 필요한 경우 → Phase 3 리뷰 PASS 후 `/mst:accept` 수동 호출하거나, `workflow.auto_accept_result`를 `true`로 설정
- 배치 실패 재시도 → `/mst:approve REQ-NNN`으로 실패한 REQ만 단건 재승인
