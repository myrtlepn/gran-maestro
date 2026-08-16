---
name: ideation
description: "사용자가 $mst:ideation 또는 /mst:ideation을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 ideation 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "{주제} [--focus {architecture|ux|performance|security|cost}]"
---

# maestro:ideation

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

<!-- mst-session-class: identity-required; root-source: existing IDN argument or new idn allocation -->

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

설정된 AI 팀원들의 의견을 병렬 수집하고 PM이 종합하여 인터랙티브 토론을 진행합니다. Maestro 모드 활성 여부에 관계없이 사용 가능. REQ 워크플로우와 독립적으로 실행됩니다.

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

### Step 1: 초기화

1. 문서 최상단의 canonical bootstrap/resolve와 shell-safe context 캡처가 성공했는지 확인합니다. 미완료이면 중단합니다.
2. canonical root가 `IDN-NNN`이면 bootstrap 결과의 `CANONICAL_ROOT_MST_ID`를 artifact ID로 그대로 사용합니다. 상속된 parent root가 다른 namespace일 때만 `MST_BOUND_SUBPROCESS`의 `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type idn`로 child IDN ID를 한 번 예약합니다.

3. `{PROJECT_ROOT}/.gran-maestro/ideation/`와 `IDN-NNN/` 디렉토리를 생성합니다 (NNN은 3자리 zero-padded).
4. bootstrap이 먼저 만든 `session.json`을 Read하고 Canonical Root Metadata Merge 계약으로 아래 workflow 필드를 병합합니다:

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "id": "IDN-NNN",
  "topic": "{사용자 주제}",
  "focus": "{focus 옵션 또는 null}",
  "status": "analyzing",
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "participants": [
    {
      "key": "architect(codex)",
      "role": "architect",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "codex",
      "started_at": null,
      "completed_at": null
    },
    {
      "key": "ux-strategist(agy)",
      "role": "ux-strategist",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "agy",
      "started_at": null,
      "completed_at": null
    },
    {
      "key": "risk-analyst(claude)",
      "role": "risk-analyst",
      "perspective": "",
      "type": "opinion",
      "status": "pending",
      "provider": "claude",
      "started_at": null,
      "completed_at": null
    }
  ],
  "critics": {
    "claude": { "status": "pending", "provider": "claude" }
  },
  "critic_count": 1,
  "participant_config": { "codex": 3, "agy": 2, "claude": 1 }
}
```

`participants`는 config의 `ideation.agents`를 읽어 생성합니다 (`discussion`과 독립 운영).
### participants 동적 생성 규칙
1. 각 provider(codex, agy, claude)의 count 읽기
2. count == 1 → key는 `{role}(provider)` 형식
3. count > 1 → 순서대로 role 생성, `{participant.key}` 형태로 key 구성
4. 각 항목에 `provider` 필드 기록
5. 합계 검증: 2~7명, 위반 시 에러 후 중단
6. count == 0 → 해당 provider 완전 skip

`participants` 키 없으면 기본값 `{ codex:1, agy:1, claude:1 }`.

예시 (`ideation.agents.codex=3`, `ideation.agents.agy=2`, `ideation.agents.claude=1`):
```json
{
  "participants": [
    { "key": "architect(codex)", "role": "architect", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "ux(codex)", "role": "ux", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "security(codex)", "role": "security", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "architecture(agy)", "role": "architecture", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "cost(agy)", "role": "cost", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "risk(claude)", "role": "risk", "perspective": "", "type": "opinion", "status": "pending", "provider": "claude", "started_at": null, "completed_at": null }
  ]
}
```

### Step 1.5: PM 역할 배정 (Role Assignment)

PM이 주제와 focus를 분석하여 `participants` 수만큼 관점을 배정합니다.
- 주제 분석: 도메인, 복잡도, 기술적 깊이 파악
- 프로바이더 매칭: Codex(코드/구현/아키텍처), AGY(전략/디자인/트렌드), Claude(추론/리스크/평가)
- Critic 수: 기본 1, 복잡 주제 2
- Critic 배정: Claude ≥ 1 → Claude 우선, Claude = 0 → Codex → AGY. critic_count=2 → 2명 배정
- `session.json` 업데이트: `participants[].perspective`, `critics` 키, `participant_config`, `critic_count`, `status: "collecting"`

### AUTO-CONTINUE 원칙 (CRITICAL)

> **이 스킬의 Step 1~3은 사용자 입력 없이 자율적으로 진행합니다.**
> - 백그라운드 작업(Codex/AGY/Claude)이 완료될 때, 사용자에게 "계속할까요?" "진행할까요?" 등을 **절대 묻지 마세요**.
> - 개별 백그라운드 작업 완료 알림에는 간단히 확인만 하고 **모든 작업이 완료될 때까지 대기**하세요.
> - 모든 작업이 완료되면 **즉시 다음 Step**으로 진행하세요 (Step 2 (participants + critics 동시 dispatch) → 2.5 (완료 대기 + 진행 상황 출력) → 2.7 (critic 완료 확인) → 3 → 사용자 보고).
> - 사용자 상호작용은 Step 4(인터랙티브 토론)에서만 발생합니다.
> - 이 원칙은 mst-loop/ultrawork 모드가 아니어도 항상 적용됩니다.

### 프롬프트 파일 생성 원칙 (CRITICAL)

`context.md`는 단독 Write, 프롬프트 파일은 **단일 combined 파일 Write → 스크립트 split** 패턴을 사용합니다:
- `session.json` 업데이트, `context.md` 작성은 기존대로 단일 응답 내 Write 처리
- 프롬프트 파일(N+M개)은 `prompts/combined-prompts.txt` **1개**에 `===SPLIT: {filename}===` 구분기호로 모두 포함
- combined-prompts.txt Write 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts` 실행
- provider dispatch는 participant별 route를 먼저 결정하고, 선택된 native background agent 또는 external background process 호출을 가능한 한 단일 응답에 포함합니다.

### Step 2: 병렬 의견 수집 (Direct File Write)

**단일 응답에서 아래를 동시 Write한 뒤, route가 허용한 모든 native/external background 호출을 단일 응답 내에서 동시 발송합니다.**

1. **Dispatch 프롬프트 조립 — feature flag 분기**

   config 확인:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py config get prompt_builder.enabled prompt_builder.fallback_on_error
   ```

   #### (a) prompt_builder.enabled=true (하이브리드 JSON 경로, 권장)
   1. `context.md` 본문을 `.gran-maestro/tmp/ctx-{session_id}.md`로 Write (기존 context.md와 동일 내용, tmp 복사본)
   2. `dispatch-input.json`을 아래 스키마로 Write:
      ```json
      {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
          "topic": "{IDN-NNN 주제}",
          "constraints": ["..."],
          "reference_context_file": ".gran-maestro/tmp/ctx-{session_id}.md"
        },
        "tasks": [
          {"role": "{participant.key}", "angle": "{perspective}", "ask": "핵심 질문 1~3개 ≤200자"},
          {"role": "{participant.key}", "angle": "{perspective}", "ask_file": ".gran-maestro/tmp/task-{role}-ask.md"}
        ]
      }
      ```
      - `format: "mst.dispatch"`, `schema_version: 1`
      - `common`: `topic`, `constraints[]`, `reference_context_file: ".gran-maestro/tmp/ctx-{session_id}.md"`
      - `tasks[]`: 각 participant/critic마다 `{role: "{participant.key}", angle: "{perspective}", ask: "...≤200자"}` 또는 `ask_file: "..."}`
      - 200자 초과 질문은 `.gran-maestro/tmp/task-{role}-ask.md`로 Write 후 `ask_file` 경로 참조
   3. CLI 호출:
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py prompt build \
        --input {absolute_path}/dispatch-input.json \
        --out-dir {absolute_path}/prompts \
        --sid {session_id}
      ```
      (metrics는 자동 기본 경로로 적재됨)
   4. 성공 시 생성된 `prompts/combined-prompts.txt`를 기존대로 `session split-prompts`로 분할 (기존 3단계 스크립트 호출 유지):
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts
      ```
   5. 실패 시 (exit != 0) → (b) fallback 경로로 자동 전환

   #### (b) prompt_builder.enabled=false 또는 CLI fallback (기존 직접 조립 경로)
   - `context.md` — 공통 배경 컨텍스트 (주제 상세, 코드베이스 현황, 핵심 제약)
   - `prompts/combined-prompts.txt` — N+M개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함
     (participant N개 + critic M개, 아래 포맷 그대로 적용)

   combined-prompts.txt Write 완료 직후:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts
   ```
   → `prompts/{participant.key}-prompt.md` × N, `prompts/critique-{criticKey}-prompt.md` × M 자동 생성

   #### fallback 규약 (MANDATORY)
   (a) 경로 실행 중 `mst.py prompt build`가 exit 2/3 등 실패 반환 시:
   - stderr 로그와 구조화 errors JSON을 Read
   - PM이 지적된 오류를 기반으로 JSON을 1회 수정 후 재시도 (repair 1회)
   - 재시도 실패 시 즉시 (b) 기존 직접 조립 경로로 전환 (workflow 차단 금지)
   - `config.prompt_builder.fallback_on_error=false`이면 repair 실패 시 워크플로우를 중단하고 사용자 에스컬레이션

   참고: `mst.py prompt build`는 오류 반환만 담당하며, repair 1회/fallback 전환은 본 스킬(ideation)의 책임이다.

   이후 2번(participant Task 발송)부터는 기존 내용 그대로 진행.

개별 프롬프트 포맷:
```markdown
# {Role} 관점 의견 요청

## 공유 컨텍스트
{absolute_path}/context.md 파일을 Read하세요.

## 당신의 역할
{perspective} 관점에서 분석합니다.

## 질문
{역할별 핵심 질문 1~3개}

## 출력 요구사항
- {absolute_path}/opinion-{participant.key}.md에 저장
- {opinion_char_limit}자 이내
```

Critic 프롬프트 템플릿:
```markdown
# Critic 평가 요청 — {session_id}

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/opinion-{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

**도구 사용 원칙 (CRITICAL)**
> - participant/critic별 shared route를 먼저 결정한다. Same-host Codex는 collaboration, same-host Claude는 `Task(run_in_background: true)`, external route는 managed provider process로 병렬 실행한다.
> - 각 응답은 파일로 직접 쓰기, 프롬프트도 파일로 저장 후 `--prompt-file` 사용
> - agent는 프롬프트 파일 실행 전 반드시 공유 컨텍스트 파일을 Read해야 합니다

> **모델 결정**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get ideation.agents.claude.tier models.providers.claude.default_tier)`로 tier를 구한 뒤 `models.providers.claude[{tier}]`로 resolve (opus / sonnet)

2. **participant provider dispatch** (`participants` 동적 순회):

각 participant에 대해 shared routing protocol과 native lifecycle을 적용한다. 아래 Bash는 `route=external` 전용이다. Same-host Codex `native_candidate`는 collaboration agent에 prompt file과 `DELEGATION BOUNDARY`를 전달한다.

- `provider: "codex"`, external lane only:
  ```
  Bash(
    run_in_background: true,
    command: "MST_SESSION_ID=\"{CANONICAL_MST_SESSION_ID}\" MST_CONTEXT_JSON=\"$(MST_CONTEXT_B64=\"{CANONICAL_MST_CONTEXT_B64}\" python3 -c 'import base64,os,sys;s=os.environ[\"MST_CONTEXT_B64\"];MAX_CONTEXT_BYTES=262144;sys.exit(\"encoded MST context exceeds limit\") if len(s)>349528 else None;raw=base64.b64decode(s.encode(\"ascii\"),altchars=b\"-_\",validate=True);sys.exit(\"decoded MST context is oversized or non-canonical\") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode(\"ascii\")!=s else None;sys.stdout.buffer.write(raw)')\" codex exec --approve-for-me -m \"{model}\" -C $(pwd) \"$(cat {absolute_path}/prompts/{participant.key}-prompt.md)\" > {absolute_path}/opinion-{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/opinion-{participant.key}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "MST_SESSION_ID=\"{CANONICAL_MST_SESSION_ID}\" MST_CONTEXT_JSON=\"$(MST_CONTEXT_B64=\"{CANONICAL_MST_CONTEXT_B64}\" python3 -c 'import base64,os,sys;s=os.environ[\"MST_CONTEXT_B64\"];MAX_CONTEXT_BYTES=262144;sys.exit(\"encoded MST context exceeds limit\") if len(s)>349528 else None;raw=base64.b64decode(s.encode(\"ascii\"),altchars=b\"-_\",validate=True);sys.exit(\"decoded MST context is oversized or non-canonical\") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode(\"ascii\")!=s else None;sys.stdout.buffer.write(raw)')\" agy --print \"$(cat {absolute_path}/prompts/{participant.key}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/opinion-{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/opinion-{participant.key}.md; exit $EC"
  )
  ```
- `provider: "claude"`, same-host native candidate:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[ideation.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. DELEGATION BOUNDARY를 준수하고 결과를 opinion-{participant.key}.md에 Write. 완료 후 '완료'"
  )
  ```
  `route=external`이면 이 Task 대신 `/mst:claude` managed wrapper를 사용한다.

3. **critic provider 동시 발송** (`critics` 동적 순회, participant와 동일 응답):

Critic에도 별도 route/lifecycle을 적용한다. 아래 Bash는 `route=external` 전용이며 same-host Codex는 collaboration agent를 사용한다.

- `provider: "codex"`, external lane only:
  ```
  Bash(
    run_in_background: true,
    command: "MST_SESSION_ID=\"{CANONICAL_MST_SESSION_ID}\" MST_CONTEXT_JSON=\"$(MST_CONTEXT_B64=\"{CANONICAL_MST_CONTEXT_B64}\" python3 -c 'import base64,os,sys;s=os.environ[\"MST_CONTEXT_B64\"];MAX_CONTEXT_BYTES=262144;sys.exit(\"encoded MST context exceeds limit\") if len(s)>349528 else None;raw=base64.b64decode(s.encode(\"ascii\"),altchars=b\"-_\",validate=True);sys.exit(\"decoded MST context is oversized or non-canonical\") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode(\"ascii\")!=s else None;sys.stdout.buffer.write(raw)')\" codex exec --approve-for-me -m \"{model}\" -C $(pwd) \"$(cat {absolute_path}/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "MST_SESSION_ID=\"{CANONICAL_MST_SESSION_ID}\" MST_CONTEXT_JSON=\"$(MST_CONTEXT_B64=\"{CANONICAL_MST_CONTEXT_B64}\" python3 -c 'import base64,os,sys;s=os.environ[\"MST_CONTEXT_B64\"];MAX_CONTEXT_BYTES=262144;sys.exit(\"encoded MST context exceeds limit\") if len(s)>349528 else None;raw=base64.b64decode(s.encode(\"ascii\"),altchars=b\"-_\",validate=True);sys.exit(\"decoded MST context is oversized or non-canonical\") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode(\"ascii\")!=s else None;sys.stdout.buffer.write(raw)')\" agy --print \"$(cat {absolute_path}/prompts/critique-{criticKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "claude"`, same-host native candidate:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[ideation.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판 관점에서 분석. DELEGATION BOUNDARY를 준수하고 결과를 critique-{criticKey}.md에 Write. 완료 후 '완료'"
  )
  ```
  `route=external`이면 이 Task 대신 `/mst:claude` managed wrapper를 사용한다.

4. **진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
의견 수집 중  ({session_id})
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- participants가 없으면 상단 섹션만 출력
- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

결과 확인: `participants` 순회 → `opinion-{participant.key}.md` 존재 여부로 성공/실패 판단.

### Step 2.5: 완료 확인 및 상태 업데이트

각 백그라운드 태스크 완료 알림 도착 시 아래 형식으로 출력:
```
  [✓] {role} ({provider})  완료  [{n}/{participants_total + critics_total}]
```

모든 participants + critics가 완료되면:
```
의견 수집 완료  (참여자 {P}/{P}, 비평 {C}/{C})
→ synthesis 시작...
```

`participants` 순회 → 파일 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`. 세션 상태 일괄 업데이트 후 다음 Step 진행.

### Step 2.7: Critic 완료 확인

`critics` 키 순회 → `critique-{criticKey}.md` 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`.
실패 시 에러 처리는 기존 에러 처리 섹션 준수.

### Step 3: PM 종합 (Delegated Synthesis)

의견 파일 목록은 `participants` 항목 순회로 동적 생성:
- `opinion-{participant.key}.md` + 관점: `{participant.perspective}`
- `critique-{criticKey}.md` 순회

Synthesis prompt는 템플릿 `templates/ideation-synthesis.md` 사용.
세션 정보 또한 고정 인원 표기가 아닌 `participants` 동적 나열 형식으로 구성.

### Step 4: 인터랙티브 토론

**Step 4 진입 시 컨텍스트 판별 (최우선):**
`/mst:request`가 ideation을 서브 호출할 때는 호출 인자에 `--from-start` 플래그가 포함됨.
이 플래그 존재 여부로 분기한다.

- **[경로 A] `/mst:request` 서브 호출 (`--from-start` 포함):**
  1. `synthesis.md`를 호출자(/mst:request)에게 반환
  2. `session.json`의 `status`를 즉시 `"completed"`로 갱신

- **[경로 B] 독립 실행 (flags 없음):**
  1. `synthesis.md` 표시
  2. 사용자 질의 반영 토론 진행
  3. 내용 append: `discussion.md`
  4. `session.json`의 `status`를 `"discussing"` → 완료 시 `"completed"`로 갱신

## 에러 처리

참여자 수 대비 처리:
- 과반 이상 성공: 실패/누락 항목을 제외하고 합성 진행
- 과반 미만 성공: PM 자체 분석으로 보완 후 진행
- 전원 실패: 에러 메시지 + 재시도 안내
- CLI 미설치: 해당 AI 스킵, 사용 가능한 AI로만 진행

## 옵션

- `--focus {architecture|ux|performance|security|cost}`: 분석 범위를 특정 분야로 제한

## 세션 파일 구조

```
.gran-maestro/ideation/IDN-NNN/
├── session.json
├── context.md                          # 공통 배경 컨텍스트 (Step 2 병렬 Write)
├── prompts/
│   ├── {participant.key}-prompt.md     # 경량 프롬프트 (context.md Read 지시 포함)
│   ├── critique-{criticKey}-prompt.md
│   └── synthesis-prompt.md
├── opinion-{participant.key}.md
├── critique-{criticKey}.md
└── synthesis.md
```

## 예시

```
/mst:ideation "마이크로서비스 vs 모놀리식 아키텍처"
```
