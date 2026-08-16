---
name: accept
description: "사용자가 $mst:accept 또는 /mst:accept을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 accept 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[REQ-ID]"
---

# maestro:accept

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

Bootstrap 직전에 root source를 아래 두 변수 중 정확히 하나로 확정합니다.

- 기존 resource: read-only preflight를 통과한 exact ID를 `ROOT_ID`에 설정하고 `ROOT_TYPE`은 비웁니다.
- 신규 workflow: concrete namespace를 `ROOT_TYPE`에 설정하고 `ROOT_ID`는 비웁니다.

둘 다 있거나 둘 다 없으면 mutation 없이 거부합니다. 특히 `$mst:approve REQ-NNN`처럼 existing-only entry는 반드시 `ROOT_ID=REQ-NNN` 경로를 사용하며 새 request counter를 발급하지 않습니다.

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
elif [ -n "${ROOT_ID:-}" ] && [ -z "${ROOT_TYPE:-}" ]; then
  SESSION_IDENTITY_JSON=$(
    python3 "{PLUGIN_ROOT}/scripts/mst.py" session bootstrap \
      --root-mst-id "$ROOT_ID" --json
  ) || exit 1
elif [ -z "${ROOT_ID:-}" ] && [ -n "${ROOT_TYPE:-}" ]; then
  SESSION_IDENTITY_JSON=$(
    python3 "{PLUGIN_ROOT}/scripts/mst.py" session bootstrap \
      --root-type "$ROOT_TYPE" --json
  ) || exit 1
else
  echo "exactly one of ROOT_ID or ROOT_TYPE is required" >&2
  exit 1
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

Phase 3 리뷰를 통과한 결과물을 최종 수락합니다. request child accept는 감지된 session base branch에만 merge하고 정리하며, session-level accept 또는 `terminal_success` transition에서만 original base merge를 검토합니다.

## 호출 방식

- **자동**: `auto_accept_result=true`(기본) 시 `/mst:approve`에서 Phase 3 PASS 후 자동 실행
- **수동**: `auto_accept_result=false` 시 `/mst:approve`가 Phase 3 PASS 후 멈추고 사용자가 명시적 호출

## Gate

### Entry

- 대상 REQ를 확정하고 Phase 3 리뷰 PASS 상태를 먼저 검증한다.
- 머지/정리 대상 브랜치와 worktree 식별이 완료된 상태에서만 수락 절차를 시작한다.
- `source_plan` 존재 여부를 확인해 Step 6 동기화 대상(plan.json)을 결정한다.

### Exit

- squash-merge 커밋 생성, 선택된 target branch 반영 evidence, 브랜치/워크트리 정리, Phase 5 완료 처리가 모두 끝나야 종료한다.
- cleanup은 commit/merge/ref reflection 단계가 아니다. 선택된 target branch 반영 evidence가 성공한 뒤에만 worktree 제거, prune, meta 정리를 수행한다.
- `request.json`이 `done` 상태로 갱신되고 후속 의존 REQ 처리(해당 시)가 반영되어야 한다.
- `source_plan`이 있으면 Plan 상태 동기화 시도 결과(완료/스킵)를 남긴다.

### 금지 패턴

- 리뷰 PASS 확인 없이 머지/정리 단계부터 실행한다.
- target branch reflection evidence 없이 cleanup 또는 Phase 5 완료 처리를 진행한다.
- squash-merge 후 `git branch -d`만 사용해 정리 실패를 방치한다.
- `source_plan`이 있는데도 Step 6 동기화 확인을 생략하고 완료 처리한다.

## DOD-005 Merge Scope Contract

- accept scope truth table vocabulary는 `child_to_session`, `session_to_original`, `forbidden_caller`, `request_child_accept`, `session_level_accept`, `terminal_success`로 고정한다.
- `request_child_accept`는 항상 `child_to_session=true`, `session_to_original=false`다. target은 parent session branch이며 original base branch로 merge할 권한이 없다.
- `request child accept`와 `session-level manual accept`는 서로 다른 scope다. child accept는 parent session branch까지만 반영하고, final original merge evidence는 session scope에서만 소비한다.
- `request.json.detected_base`와 session branch는 child/session merge target 판정에 사용한다. `original_base_branch`와 `original_base_sha`는 final original merge evidence/reference로만 사용하며 `detected_base`와 혼용하지 않는다.
- `session_level_accept`와 `terminal_success`만 `session_to_original=true` 후보가 되며 `original_base_branch`와 `original_base_sha`는 reference/evidence로만 사용한다.
- `assistant_turn_end`, `stop_hook_continuation`, `tool_exit`, `subskill_return`, `review_pass_only`는 forbidden caller다.
- `Stop hook continuation`, `subskill return`, review PASS-only completion은 final original merge trigger가 아니다.
- forbidden caller는 session→original merge를 실행하지 않는다. continuation 안내, diagnostic 반환, parent workflow control return만 수행한다.
- accept scope는 child와 session으로 분리한다.
- terminal success는 상태머신 전이로만 인정한다.
- DOD-005는 DOD-013 full truth table과 DOD-014 multi-child ordering/idempotency를 범위 밖으로 유지한다.
- DOD-013과 DOD-014는 terminal success 확장과 multi-child ordering을 다루며, 이 단계에서는 final original merge authorization을 확장하지 않는다.

## DOD-006 Child-First / Session-Last Cleanup Contract

- child-first/session-last cleanup lifecycle vocabulary는 `freeze` → `child inspection` (`inspect_child_worktrees`) → `child merge/block` (`child_merge_or_block`) → `child removal` (`child_remove`) → `session inspection` (`inspect_session`) → `final merge/cancel policy` (`final_merge_or_block`) → `session removal` (`session_remove`) → `branch/archive` (`branch_or_archive`) 순서로 고정한다.
- `request child accept`는 child/session merge와 child cleanup evidence까지만 담당한다. session final cleanup/removal, `session inspection`, `final merge/cancel policy`, `session removal`, `branch/archive`, original base cleanup authority는 주장하지 않는다.
- child freeze snapshot에 없는 late-arriving child, dirty child, conflicted child, orphaned child는 child inspection 단계에서 barrier로 분류하고 session-last cleanup으로 넘어가지 않는다.
- session-level accept 또는 `terminal_success`만 session inspection 이후 final merge/cancel policy를 결정할 수 있다. session removal과 branch/archive는 final policy가 `merged` 또는 `cancelled`로 확정된 뒤에만 진행한다.
- worktree removal은 child removal과 session removal에서만 수행한다. branch/archive는 항상 worktree removal 이후의 마지막 정리 단계다.

## Anti-Rationalization Checklist

- 합리화 패턴: "테스트가 통과했으니 리뷰/상태 확인 없이 바로 머지해도 된다." | 확인 증거: 실행 로그에 리뷰 PASS 확인 결과와 대상 REQ-ID를 먼저 출력한다.
- 합리화 패턴: "일부 정리 실패는 무시하고 완료로 닫아도 된다." | 확인 증거: worktree/브랜치 정리 실행 결과를 항목별로 기록하고 실패 시 경고를 남긴다.
- 합리화 패턴: "수락만 끝나면 plan 동기화는 선택사항이다." | 확인 증거: Step 6에서 `source_plan` 조회 및 sync 실행(또는 skip 사유)을 명시한다.

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

State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

DOD-007 recovery judgement contract: `scripts.mst_cmds.cleanup.resolve_recovery_judgement_state` output은 diagnostic payload/action vocabulary contract only다. Primary action vocabulary는 `resume_session`, `cleanup_child`, `manual_conflict_resolution`, `blocked_destructive`, `diagnostic_only`로 고정하며 alternate destructive/success action name은 추가하지 않는다.

DOD-007 dashboard scope boundary: recovery judgement는 dashboard graph 후보 입력으로만 취급한다. Dashboard graph UI/API schema(노드/엣지/타임라인 계약)는 이 스킬 범위가 아니며 후속 작업으로 defer한다.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy/process/session owner metadata(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement, recovery authority, ownership proof, repair source, merge source가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

Request child accept recovery scope: request child accept는 child-to-session recovery 판단 범위만 가진다. `request_child_accept` caller는 session cleanup authority, original-base merge repair authority, automatic final merge retry authority를 주장하거나 실행하지 않고 `diagnostic_only` 판단만 반환할 수 있다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

### Step 0.1: 자율 모드 감지

1. args 전체 토큰에서 `-a` 또는 `--auto` 존재 여부 검사:
   - 감지 시 `AUTO_MODE=true` (args 어느 위치든 허용)
2. args에 없으면 `read_workflow_state_auto_mode("mst:accept", REQ_ID)` 호출 (helper는 T01에서 추가됨)
   - 반환 bool → `AUTO_MODE`에 채택
   - `None` → 3번 단계로 진행
3. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get auto_mode.accept)`로 `config.auto_mode.accept` 확인
   - true이면 `AUTO_MODE=true`
4. 미설정 또는 false이면 `AUTO_MODE=false` (기본)
5. `AUTO_MODE=true`이면 수락 AskUserQuestion을 전부 생략하고 최종 머지 단계까지 무정지 진행한다.

### AUTO_MODE와 DAG 연쇄 정책 분리 (MANDATORY)

AUTO_MODE는 "이 accept 호출의 무정지 실행"만 제어합니다. `dependencies.blocks`를 기반으로 한 DAG 연쇄 재기동 여부는 기존 정책 플래그만 참조합니다:
- `workflow.auto_approve_on_unblock` (config)
- `request.json.auto_approve` (해당 REQ 속성)

따라서 `/mst:accept -a REQ-N`이 `workflow.auto_approve_on_unblock=false` 환경에서 호출되어도 후속 REQ로의 자동 연쇄는 **발생하지 않습니다**. AUTO_MODE와 DAG 연쇄를 같은 신호로 취급하지 마십시오.
또한 approve의 auto-accept guard 차단은 AUTO_MODE와 별개이며, 차단된 건은 approve 단계에서 연쇄 호출이 멈춘 뒤 수동 `/mst:accept`로만 진입합니다.

### 세션 중 자율 모드 전환

사용자가 대기 중 "auto로", "자율 모드로", "-a로", "지금부터 자동으로" 등 입력 시 즉시 `AUTO_MODE=true`로 전환하고 `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력 후 현재 Step부터 재개합니다.

### REQ ID 결정 (인자 없이 호출 시)

`requests/`의 모든 `request.json` 스캔 → `current_phase==3` + `phase3_review`/PASS 상태 필터링 → REQ 번호 오름차순 첫 번째 선택 (없으면 "대기 중 요청 없음" 알림)

### 최종 수락 실행 (Phase 3 → Phase 5)

1. **리뷰 PASS 확인**: PASS 아니면 사용자 알림 후 중단 (먼저 `/mst:feedback` 완료 필요)
2. **요약 리포트 생성**: 모든 태스크 완료 결과 → `summary.md` 작성
2.5. **Evidence Verification Gate (PAC 증거 검증)**:
   - 목적: `source_plan` 기반 PAC 검증 증거가 최신 review 산출물에 모두 첨부되었는지 확인한다.
   - 이 gate는 PAC/objective/evidence-ledger 검증 전용이며, 아래 PO 의도 검증 gate와 서로 대체 관계가 아니다.
   - 실행 순서:
     1. `request.json.source_plan` 확인.
        - 미존재 시: `"[INFO] Evidence gate skip (source_plan 없음)"` 및 `"[INFO] PO intent validation gate skip: reason=NO_SOURCE_PLAN"` 출력 후 다음 단계 진행 (하위 호환).
     2. `source_plan`이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json` Read.
        - 파일 미존재 시: `"[INFO] Evidence gate skip (plan.ids.json 없음)"` 출력 후 다음 단계 진행 (하위 호환).
     3. `plan.ids.json`에서 PAC ID 목록(`PAC-N`)을 로드한다.
     3.5. **PAC 범위 필터링 (분리 실행 플랜 대응)**:
        - `request.json`의 모든 태스크에서 `covers_ac` 배열을 수집한다.
        - 해당 태스크의 `spec.md`의 `## 3.3 PAC Mapping`에서 `Coverage == "COVERED"`인 PAC ID만 추출하여 `in_scope_pacs`로 설정한다.
        - `in_scope_pacs`가 비어있으면 (하위 호환: PAC Mapping 미존재) `plan.ids.json`의 전체 PAC를 대상으로 한다.
        - `in_scope_pacs`가 있으면 해당 PAC만 검증 대상으로 한정한다 (OTHER_REQ PAC 제외).
     4. 최신 review iteration(`request.json.review_iterations`의 최신 `rv_id`)을 식별하고
        `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/evidence-ledger.md`를 Read한다.
        - 파일 미존재 시: `"[INFO] Evidence gate skip (evidence-ledger.md 없음 — 레거시 review)"` 출력 후 다음 단계 진행 (하위 호환).
     5. PAC별 증거 존재 여부를 확인한다 (`in_scope_pacs` 범위 내에서만).
        - 기준: `evidence-ledger.md`에 해당 PAC ID 레코드가 존재해야 한다.
        - 누락 PAC가 1개 이상이면 accept를 **즉시 블로킹**하고 아래 메시지를 출력한 뒤 중단한다.
          - `증거 미첨부 PAC: {PAC-ID 목록}`
     6. agile-origin objective anchor metadata가 있으면 `objective.ids.json`, spec `## 3.4 Epic DoD Mapping`, 최신 `evidence-ledger.md`의 Objective Anchor 검증 증거를 확인한다.
        - MUST objective anchor가 `N/A`로만 사라졌거나 매핑 증거가 없으면 accept를 블로킹한다.
        - 누락 anchor가 1개 이상이면 `증거 미첨부 objective anchor: {anchor ID 목록}`을 출력하고 중단한다.
        - 누락이 없으면 다음 단계 진행.
     7. **PO 의도 검증 hard gate (source_plan 기반 추가 gate)**:
        - 실행 조건: `request.json.source_plan`이 존재하는 현재 REQ에만 적용한다. `source_plan`이 없으면 위 1번의 `reason=NO_SOURCE_PLAN` skip만 남기고 PO gate로 실패시키지 않는다.
        - 이 gate는 기존 PAC/objective/evidence-ledger 검증을 약화하거나 대체하지 않는다. 위 5번 또는 6번에서 이미 블로킹된 실패는 `po_intent_validation.verdict == PASS`로 상쇄할 수 없다.
        - 최신 review 선택 기준:
          1. `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/request.json`의 `review_iterations` 배열만 사용한다.
          2. `status == "completed"`인 항목만 후보로 인정한다.
          3. 배열 순서상 가장 뒤의 completed 항목을 현재 request의 최신 completed review artifact로 선택하고, 해당 `rv_id`의 `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/review.json`만 Read한다.
          4. 이전 completed iteration의 PASS, `in_progress`/`failed`/`limit_reached` iteration, 다른 REQ의 review artifact, 파일명만 유사한 외부 산출물은 PASS 근거로 인정하지 않는다.
        - 판정 규칙:
          1. 최신 completed review artifact가 없거나 `review.json`을 Read할 수 없으면 accept를 즉시 블로킹하고 `PO 의도 검증 산출물 없음: 최신 completed review artifact 없음`을 출력한다.
          2. `review.json.po_intent_validation` 객체가 없으면 accept를 즉시 블로킹하고 `PO 의도 검증 산출물 없음: po_intent_validation 없음`을 출력한다.
          3. `po_intent_validation.verdict != "PASS"`이면 accept를 즉시 블로킹하고 `PO 의도 검증 verdict 불일치: expected=PASS actual={verdict}`를 출력한다. `FAIL`, `SKIP`, 빈 값, 알 수 없는 값은 모두 불일치다.
          4. `po_intent_validation.compared_sources`가 없거나 빈 배열/빈 문자열이면 accept를 즉시 블로킹하고 `PO 의도 검증 원본 문서 비교 누락: compared_sources 비어 있음`을 출력한다.
          5. `po_intent_validation.compared_changes`가 없거나 빈 배열/빈 문자열이면 accept를 즉시 블로킹하고 `PO 의도 검증 변경 내용 비교 누락: compared_changes 비어 있음`을 출력한다.
          6. `po_intent_validation.rationale` 필드는 존재해야 하며, 누락 시 `PO 의도 검증 산출물 없음: rationale 누락`으로 블로킹한다.
          7. `po_intent_validation.missing_or_mismatched_intent` 필드는 존재해야 한다. PASS일 때 빈 배열/빈 문자열은 허용하지만, 필드 자체가 없으면 `PO 의도 검증 산출물 없음: missing_or_mismatched_intent 누락`으로 블로킹한다.
        - 통과 조건: 현재 REQ의 최신 completed review artifact에 `po_intent_validation.verdict == PASS`가 있고, `compared_sources`와 `compared_changes`가 비어 있지 않으며, `rationale`과 `missing_or_mismatched_intent` 필드가 존재할 때만 다음 단계로 진행한다.
2.6. **수락 전략 결정 (source_plan → plan.json.type → type-strategies.json 체인, MANDATORY)**:
   - `request.json.source_plan` 값이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`을 Read하고 `type` 필드를 확인한다.
   - `plan_type = plan.json.type` (`type` 누락 또는 Read 실패 시 `"code"` fallback)
   - `type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)` 시도
   - `strategy = type_strategies[plan_type] || type_strategies["code"]`
   - `type-strategies.json` Read 실패/파싱 실패/키 누락 시 `strategy = {"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`로 fallback해 기존 수락 경로를 유지한다.
3. **Worktree → REQ 브랜치 → session target squash-merge** (기본: `strategy.accept_mode != "file-placement"`)
   - `if strategy.accept_mode == "file-placement"`:
     - squash-merge를 실행하지 않고 문서 파일을 대상 경로로 배치(복사/이동)한다.
     - 배치 대상 경로는 각 태스크 spec/doc-spec에 정의된 문서 산출 경로를 따른다.
     - 아래 3-1~3-3 git merge 절차는 건너뛴다.
   - `else` (`strategy.accept_mode != "file-placement"`):
     - 아래 3-1~3-3 절차를 수행한다.
   - approve 단계(Step 4a)에서 생성된 다계층 REQ 브랜치를 사용합니다.
   - 단일 태스크 REQ도 동일한 플로우를 적용합니다.
   - **base/브랜치 변수 준비 (MANDATORY)**:
     - DOD-005 기준으로 child/request accept의 merge target은 `request.json.detected_base`가 가리키는 session branch 또는 session-derived integration branch다.
     - `request.json.detected_base`가 있으면 해당 값을 최우선 base로 사용한다.
     - `request.json.detected_base`가 없으면 legacy 호환을 위해 명시된 `config.worktree.base_branch`만 사용할 수 있다. 둘 다 없으면 사용자 기준 session branch evidence가 누락된 것으로 보고 중단한다.
     - `original_base_branch`와 `original_base_sha`는 final original merge evidence다. 이 Step 3에서는 reference로만 보존하며 child/request accept가 original base branch로 직접 merge하지 않는다.
     - branch name은 `worktree branch-name` helper로만 산출하며, AGI_ID가 있으면 `gran-maestro/{base_slug}/{AGI_ID}/...` 형식을 사용한다.
     - accept worktree 생성 실패 시 감지 base와 실제 git 상태가 불일치한 것으로 보고 명시적 오류를 출력한 뒤 중단한다.
     ```bash
     REQUEST_JSON="{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/request.json"
     DETECTED_BASE=$(python3 -c 'import json, sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(str(data.get("detected_base") or "").strip())' "$REQUEST_JSON")
     CONFIG_BASE_BRANCH=$(python3 {PLUGIN_ROOT}/scripts/mst.py config get worktree.base_branch 2>/dev/null || true)
     CONFIG_BASE_BRANCH=$(printf "%s" "$CONFIG_BASE_BRANCH" | head -n 1 | xargs)
     BASE_BRANCH="${DETECTED_BASE:-$CONFIG_BASE_BRANCH}"
     if [ -z "$BASE_BRANCH" ]; then
       echo "[accept] Error: request.json.detected_base가 없고 config.worktree.base_branch도 비어 있습니다. /mst:approve에서 사용자 기준 session branch를 다시 감지하세요." >&2
       exit 1
     fi
     REQ_BRANCH=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree branch-name --req REQ-NNN --base "$BASE_BRANCH" --role integration --agi "${AGI_ID:-}")
     TASK_BRANCH_PREFIX=$(python3 {PLUGIN_ROOT}/scripts/mst.py worktree branch-name --req REQ-NNN --base "$BASE_BRANCH" --task T --agi "${AGI_ID:-}")
     echo "[accept] squash base: ${BASE_BRANCH}"
     echo "[accept] request branch: ${REQ_BRANCH}"
     ```
   - **3-1. 각 태스크 worktree → REQ 브랜치 일반 머지 (태스크 커밋 이력 보존)**:
     - hard-coded `T01`/`T02` 순서로 merge하지 않는다. `request.json.tasks`에서 child 목록을 만들고 `worktree child-merge-queue`가 반환한 deterministic queue 순서만 따른다.
     - `merge_queue_state=="blocked"` 또는 `blockers`가 있으면 즉시 중단한다. blocked 상태에서는 squash merge, target branch reflection, cleanup, Phase 5 완료 처리를 수행하지 않는다.
     - `merge_required=false`인 `already_merged`/`duplicate_child` 항목은 merge를 재실행하지 않는다. idempotency 판단은 `idempotency_key` evidence로만 한다.
     ```bash
     # 각 태스크 브랜치를 dedicated integration worktree에서 REQ 브랜치에 머지한다.
     INTEGRATION_WORKTREE=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree path --req REQ-NNN --role integration --agi "${AGI_ID:-}")
     CHILDREN_QUEUE_FILE="{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/child-merge-children.json"
     python3 - "$REQUEST_JSON" "REQ-NNN" "$TASK_BRANCH_PREFIX" "$CHILDREN_QUEUE_FILE" <<'PY'
import json
import sys
from pathlib import Path

request_json = Path(sys.argv[1])
req_id = sys.argv[2]
task_branch_prefix = sys.argv[3]
out_path = Path(sys.argv[4])
payload = json.loads(request_json.read_text(encoding="utf-8"))

def task_suffix(raw):
    value = str(raw or "").strip()
    if not value:
        return ""
    token = value.rsplit("-", 1)[-1]
    if token.startswith("T") and token[1:].isdigit():
        return token[1:]
    return token

children = []
for index, task in enumerate(payload.get("tasks") or [], start=1):
    if not isinstance(task, dict):
        continue
    raw_task_id = str(task.get("id") or task.get("task_id") or f"T{index:02d}").strip()
    task_id = task_suffix(raw_task_id) or f"{index:02d}"
    commit = task.get("commit") if isinstance(task.get("commit"), dict) else {}
    attempts = [item for item in (task.get("attempts") or []) if isinstance(item, dict)]
    latest_attempt = attempts[-1] if attempts else {}
    child_branch = (
        task.get("child_branch")
        or task.get("branch")
        or task.get("task_branch")
        or commit.get("branch")
        or commit.get("task_branch")
        or latest_attempt.get("branch")
        or latest_attempt.get("task_branch")
        or f"{task_branch_prefix}{task_id}"
    )
    children.append(
        {
            "req_id": req_id,
            "task_id": task_id,
            "child_id": raw_task_id or f"{req_id}-T{task_id}",
            "child_branch": child_branch,
            "ready_at": task.get("completed_at") or task.get("committed_at") or task.get("updated_at") or "",
            "priority": task.get("accept_priority", task.get("priority", index)),
            "state": task.get("child_merge_state") or "ready",
        }
    )

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(children, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
     CHILD_MERGE_EVENTS_JSON="${CHILD_MERGE_EVENTS_JSON:-[]}"
     CHILD_MERGE_QUEUE=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree child-merge-queue \
       --mst-session-id "${MST_SESSION_ID:-request-child-accept}" \
       --session-branch "$REQ_BRANCH" \
       --children-json "@$CHILDREN_QUEUE_FILE" \
       --durable-events-json "$CHILD_MERGE_EVENTS_JSON" \
       --json)
     printf '%s\n' "$CHILD_MERGE_QUEUE"
     python3 - "$CHILD_MERGE_QUEUE" "$INTEGRATION_WORKTREE" <<'PY'
import json
import subprocess
import sys

payload = json.loads(sys.argv[1])
integration_worktree = sys.argv[2]
allowed_states = {"ready", "idempotent_replay", "empty"}

if not payload.get("ok") or payload.get("merge_queue_state") not in allowed_states:
    print(
        "[accept] Error: child merge queue blocked: "
        f"state={payload.get('merge_queue_state')} blockers={payload.get('blockers')}",
        file=sys.stderr,
    )
    sys.exit(1)
if payload.get("session_to_original") is not False:
    print("[accept] Error: child accept must not authorize session_to_original", file=sys.stderr)
    sys.exit(1)

target_branch = payload.get("target_branch")
queue = payload.get("queue") or []
merge_required = any(bool(entry.get("merge_required")) for entry in queue)
if payload.get("session_final_merge_blocked") is True and not merge_required:
    print("[accept] Error: session_final_merge_blocked evidence is inconsistent", file=sys.stderr)
    sys.exit(1)
for entry in queue:
    if entry.get("merge_target") != target_branch:
        print("[accept] Error: child merge target mismatch", file=sys.stderr)
        sys.exit(1)
    if entry.get("child_to_session") is not True or entry.get("session_to_original") is not False:
        print("[accept] Error: child merge scope mismatch", file=sys.stderr)
        sys.exit(1)
    if not entry.get("merge_required"):
        continue
    child_branch = str(entry.get("child_branch") or "").strip()
    if not child_branch:
        print("[accept] Error: child branch evidence missing", file=sys.stderr)
        sys.exit(1)
    message = (entry.get("commit_metadata") or {}).get("message") or f"Merge child {entry.get('child_id')} to session branch"
    subprocess.run(["git", "-C", integration_worktree, "merge", "--no-ff", child_branch, "-m", message], check=True)
    print(
        "[accept] child merge ok: "
        f"child_id={entry.get('child_id')} idempotency_key={entry.get('idempotency_key')}"
    )
PY
     ```
   - **3-2. REQ 브랜치 → base squash-merge (단일 커밋 생성)**:
     ```bash
     ACCEPT_WORKTREE=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree path --req REQ-NNN --role accept --agi "${AGI_ID:-}")
     ACCEPT_BRANCH=$(python3 {PLUGIN_ROOT}/scripts/mst.py worktree branch-name --req REQ-NNN --base "$BASE_BRANCH" --role accept --agi "${AGI_ID:-}")
     python3 {PLUGIN_ROOT}/scripts/mst.py worktree create --path "$ACCEPT_WORKTREE" --branch "$ACCEPT_BRANCH" --base "$BASE_BRANCH"
     TARGET_BEFORE=$(git -C "$ACCEPT_WORKTREE" rev-parse --verify "refs/heads/${BASE_BRANCH}")
     git -C "$ACCEPT_WORKTREE" merge --squash "${REQ_BRANCH}"
     ```
     실제 실행은 감지 base 변수를 사용하며, 원본 `PROJECT_ROOT`에서는 checkout/merge를 수행하지 않는다.
     이 단계의 squash target은 session scope다. final session→original merge는 여기서 수행하지 않으며 `session_level_accept` 또는 `terminal_success` evidence gate에서만 검토한다.
     예: `request.json.detected_base="feature/branch-rules"`, `AGI_ID="AGI-026"`이면 accept worktree가 `feature/branch-rules`에서 생성되고 그 내부에서 `gran-maestro/feature-branch-rules/AGI-026/REQ-NNN`를 squash merge한다.
     [커밋 양식 감지]
     1. `git -C {PROJECT_ROOT} log --pretty=format:"%s" -10`을 실행해 최근 10개 커밋 subject를 수집한다.
     2. 수집된 subject에서 `[REQ-`로 시작하는 항목을 우선 분석 대상으로 사용하고, 없으면 전체 10개를 분석 대상으로 사용한다.
     3. 분석 대상에서 가장 빈번한 패턴을 추출한다.
        - 접두사 패턴: `[REQ-NNN]` 형태와 뒤따르는 설명 구조를 식별한다.
        - 언어 패턴: 한국어/영어 중 우세한 언어를 식별한다.
        - 부록 패턴: `(...)` 형태의 파일목록/부록 유무를 식별한다.
     4. `git log` 실행 실패, 커밋 히스토리 부재, 또는 분석 대상에서 일관된 패턴을 추출할 수 없는 경우 subject 폴백은 `[REQ-NNN] {REQ 제목}`으로 고정한다.
     5. 감지 결과로 `{DETECTED_SUBJECT}`를 만들고, 예를 들어 `[REQ-NNN] 한국어 설명 (파일목록)`이 우세하면 동일한 접두사/언어/괄호 부록 구조를 유지한다.
     ```bash
     git -C "$ACCEPT_WORKTREE" commit -m "{DETECTED_SUBJECT}

     Base branch: ${BASE_BRANCH}

     태스크 요약:
     - T01: {태스크 1 제목}
     - T02: {태스크 2 제목}"
     ```
     squash commit 생성 직후에는 선택된 target branch(`BASE_BRANCH`)에 해당 commit을 반영하고 도달성 evidence를 확인한다.
     - target branch가 이미 checkout된 worktree가 있으면 그 worktree에서 `ff-only`로 반영한다.
     - checkout된 target worktree가 없으면 old SHA(`TARGET_BEFORE`)를 지정한 atomic ref update로 반영한다.
     - target drift, dirty target worktree, reachability evidence 누락은 blocker이며 cleanup/Phase 5로 진행하지 않는다.
     ```bash
     ACCEPT_COMMIT=$(git -C "$ACCEPT_WORKTREE" rev-parse --verify HEAD)
     ACCEPT_REFLECTION=$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py worktree reflect-accept \
       --accept-worktree "$ACCEPT_WORKTREE" \
       --target-branch "$BASE_BRANCH" \
       --accepted-commit "$ACCEPT_COMMIT" \
       --target-before "$TARGET_BEFORE" \
       --json)
     printf '%s\n' "$ACCEPT_REFLECTION"
     python3 - "$ACCEPT_REFLECTION" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
if not payload.get("ok"):
    print(
        "[accept] Error: target branch reflection failed: "
        f"{payload.get('reason')} action={payload.get('action')}",
        file=sys.stderr,
    )
    sys.exit(1)
if payload.get("merge_state") != "target_reflected_ff_only":
    print("[accept] Error: unexpected target reflection state", file=sys.stderr)
    sys.exit(1)
if payload.get("target_after") != payload.get("accepted_commit"):
    print("[accept] Error: accepted commit is not the target branch HEAD", file=sys.stderr)
    sys.exit(1)
reachability = payload.get("reachability") or {}
if reachability.get("accepted_commit_is_ancestor_of_target") is not True:
    print("[accept] Error: accepted commit reachability evidence missing", file=sys.stderr)
    sys.exit(1)
if payload.get("cleanup_performed") is True:
    print("[accept] Error: reflection helper must not perform cleanup", file=sys.stderr)
    sys.exit(1)
PY
     ACCEPT_REFLECTION_GATE_OK=true
     ```
   - **3-3. REQ 브랜치 삭제** (squash merge 후 `-D` 강제 삭제):
     ```bash
     # Step 4의 cleanup helper를 먼저 정의한 뒤 사용한다.
     # 실패 시 각 태스크 meta를 clean_failed로 기록하고 accept 흐름은 정리 단계로 계속 진행한다.
     delete_req_branch_safely "${REQ_BRANCH}" "T01" "T02"
     ```
3.5. **Implementation Decision 기록 (비차단)**:
   - `source_plan`이 존재하면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`의 `linked_intent` 필드를 읽어 INTENT_ID 취득
   - INTENT_ID가 존재하면 해당 Intent 파일(`{PROJECT_ROOT}/.gran-maestro/intents/{INTENT_ID}.md`)의 `## Implementation Decision` 섹션 끝에 아래 형식으로 직접 Edit(append):
     - Edit 방법: old_string에 섹션의 기존 마지막 줄(또는 빈 줄 포함)을 포함하고, new_string에 기존 내용 + 새 항목을 추가
     ```
     [YYYY-MM-DD] [REQ-NNN] {spec §1 요약}
     ```
   - `linked_intent` 미존재 시 skip (비차단); 파일 Edit 실패 시 warn만 출력, 워크플로우 차단 금지

4. **정리**: target branch reflection 성공 후 각 태스크의 worktree 및 임시 브랜치 정리
   - 이 단계는 commit, merge, target branch ref update를 수행하지 않는다.
   - `ACCEPT_REFLECTION_GATE_OK=true`가 아니면 정리를 시작하지 말고 Step 3-2의 blocker를 먼저 해결한다.
   > ⚠️ **squash merge 후 브랜치 삭제 규칙**: REQ 브랜치를 `{BASE_BRANCH}`에 squash merge하면 merge ancestor가
   > 생성되지 않으므로 `git branch -d`(soft delete)는 "not fully merged" 오류로 실패합니다.
   > 브랜치 삭제는 `git branch -D`를 사용하세요.
   > `\|\| true`로 정리 실패를 숨기지 않습니다. 각 호출은 exit code를 수집하고 실패 시
   > `.gran-maestro/worktrees/{REQ_ID}-{taskId}.meta.json`의 기존 필드를 보존하면서
   > `state="clean_failed"`와 `clean_failed.{command,exit_code,message,timestamp}`를 기록합니다.
   - `strategy.accept_mode == "file-placement"`이면 worktree가 없을 수 있으므로 worktree 제거 단계는 "없으면 skip"으로 처리한다 (graceful skip, 비차단).
   - 각 태스크를 **독립적으로** 실행 (`&&` 연결 금지 — 하나 실패 시 나머지 미실행됨)
   - 순서: worktree 제거 먼저, 브랜치 삭제 나중
   ```bash
record_clean_failed() {
  local task_id="$1"
  local exit_code="$2"
  local failed_command="$3"
  local error_message="$4"

  python3 - "$PROJECT_ROOT" "$REQ_ID" "$task_id" "$exit_code" "$failed_command" "$error_message" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1])
req_id = sys.argv[2]
task_id = sys.argv[3]
exit_code = int(sys.argv[4])
failed_command = sys.argv[5]
error_message = sys.argv[6].strip() or "cleanup command failed"
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
meta_path = project_root / ".gran-maestro" / "worktrees" / f"{req_id}-{task_id}.meta.json"

try:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

payload.setdefault("taskId", f"{req_id}-{task_id}")
payload["state"] = "clean_failed"
payload["last_activity_at"] = now
payload["clean_failed"] = {
    "command": failed_command,
    "exit_code": exit_code,
    "message": error_message,
    "timestamp": now,
}
payload["error_message"] = error_message
payload["exit_code"] = exit_code
payload["failed_command"] = failed_command
payload["failed_at"] = now

meta_path.parent.mkdir(parents=True, exist_ok=True)
tmp_path = Path(str(meta_path) + ".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp_path, meta_path)
PY
}

remove_worktree_safely() {
  local task_id="$1"
  local worktree_path="$2"
  local failed_command output status

  failed_command="python3 ${PLUGIN_ROOT}/scripts/mst.py worktree remove --path ${worktree_path} --force"
  set +e
  output=$(python3 "${PLUGIN_ROOT}/scripts/mst.py" worktree remove --path "$worktree_path" --force 2>&1)
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    echo "[mst:accept][WARN] worktree cleanup failed: task=${task_id} status=${status} path=${worktree_path}" >&2
    record_clean_failed "$task_id" "$status" "$failed_command" "$output"
  fi
  return 0
}

delete_task_branch_safely() {
  local task_id="$1"
  local branch="$2"
  local failed_command output status

  failed_command="git -C ${PROJECT_ROOT} branch -D ${branch}"
  set +e
  output=$(git -C "$PROJECT_ROOT" branch -D "$branch" 2>&1)
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    echo "[mst:accept][WARN] task branch cleanup failed: task=${task_id} status=${status} branch=${branch}" >&2
    record_clean_failed "$task_id" "$status" "$failed_command" "$output"
  fi
  return 0
}

delete_req_branch_safely() {
  local branch="$1"
  shift
  local failed_command output status task_id

  failed_command="git -C ${PROJECT_ROOT} branch -D ${branch}"
  set +e
  output=$(git -C "$PROJECT_ROOT" branch -D "$branch" 2>&1)
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    echo "[mst:accept][WARN] request branch cleanup failed: status=${status} branch=${branch}" >&2
    for task_id in "$@"; do
      record_clean_failed "$task_id" "$status" "$failed_command" "$output"
    done
  fi
  return 0
}

cleanup_task_safely() {
  local task_id="$1"
  local worktree_path="$2"
  local task_branch="$3"

  remove_worktree_safely "$task_id" "$worktree_path"
  delete_task_branch_safely "$task_id" "$task_branch"
}
```
   - 태스크별 실행 예시:
     ```bash
     cleanup_task_safely "T01" "{PROJECT_ROOT}/.gran-maestro/worktrees/REQ-NNN-T01" "${TASK_BRANCH_PREFIX}01"
     cleanup_task_safely "T02" "{PROJECT_ROOT}/.gran-maestro/worktrees/REQ-NNN-T02" "${TASK_BRANCH_PREFIX}02"
     delete_req_branch_safely "${REQ_BRANCH}" "T01" "T02"
     ```
4.5. **Pending Stitch 화면 재확인**:
   - `request.json`의 `stitch_screens` 배열에서 `status: "pending"` 항목 확인
   - 없으면 이 단계 스킵
   - 있으면: `mcp__stitch__list_screens(projectId)` 호출 (projectId는 `config.stitch.project_id`)
     - **`baseline_screen_ids` 있는 경우**:
       - 현재 screen IDs = `screens[].name`에서 마지막 `/` 이후 값 추출
       - 차집합 = 현재 screen IDs - pending 항목의 `baseline_screen_ids`
       - 차집합 비어있지 않으면: 첫 번째 ID로 `get_screen` 호출 → URL 확보 → 발견 처리
       - 차집합 비어있으면: 미발견 처리
     - **`baseline_screen_ids` 없는 경우** (구버전 pending 호환):
       - 타임스탬프 비교 불가 → 미발견 처리
     - **발견 시**: `get_screen`으로 URL 확보 →
       `stitch_screens`의 pending 항목을 아래 필드로 업데이트:
       `stitch_screen_id`, `url` (`https://stitch.withgoogle.com/projects/{project_id}`),
       `image_url` (`screenshot.downloadUrl` 또는 null), `status: "active"`
       → "[Stitch] 화면 확인 완료 — {screen title}" 출력
     - **미발견 시**: pending 유지 →
       "[Stitch] 화면 미확인 — /mst:stitch --list로 수동 확인 가능합니다." 출력

5. **Phase 5 완료 처리**: `ACCEPT_REFLECTION_GATE_OK=true` 및 `ACCEPT_REFLECTION.merge_state=="target_reflected_ff_only"` evidence를 확인한 뒤에만 `stitch_screens`의 `active` 항목 → `archived`로 변경; **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 5 done`; 실패 시 fallback으로 `current_phase`=5, `status`=`done` 직접 업데이트; 완료 알림
> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

5.1. **워크플로우 상태 정리 (MANDATORY)**: Phase 5 완료 처리 직후, `python3 {PLUGIN_ROOT}/scripts/mst.py state get --json` 결과의 `agile_loop_active`를 먼저 확인한 뒤 아래 분기로 실행한다.

- `agile_loop_active=true`이면, 워크플로우를 끄지 말고 agile 복귀 상태로 복원:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --req "{ACTIVE_REQ}" \
  --auto {AUTO_MODE} \
|| echo "[mst:accept] warning: failed to restore agile workflow state" >&2
```

- `--auto` 값은 현재 accept의 AUTO_MODE(= Step 0.1 판정 결과)를 그대로 전달하여
  retrospective → 새 sprint 진입 시 AUTO_MODE가 false로 덮이지 않도록 한다.
- 기존 `--auto false` 고정 호출(clear 경로, :186)은 변경하지 않는다
  (active=false로 state를 닫을 때는 auto_mode도 의미가 없으므로 false 유지).

- `agile_loop_active!=true`이면, 기존처럼 워크플로우 비활성:

```bash
MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" \
MST_CONTEXT_JSON="$(
  MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" \
  python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)'
)" \
python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active false \
  --auto false \
|| echo "[mst:accept] warning: failed to clear workflow state" >&2
```

- 이 호출은 workflow 종료용이며 `--auto false` 고정을 유지한다.

- 두 호출 모두 비차단(non-blocking)으로 처리한다: 실패 시 경고만 출력하고 워크플로우를 계속 진행한다.
- `approve`의 `state set-workflow --active true` 호출과 대칭을 이룬다.

5.5. **후속 REQ 활성화 (Dependency Unblock)**:
  - `request.json`의 `dependencies.blocks` 배열 확인
  - 배열이 비어있으면 이 단계 스킵
  - 비어있지 않으면 각 후속 REQ-ID에 대해:
    a. `{PROJECT_ROOT}/.gran-maestro/requests/{BLOCKED-REQ-ID}/request.json` Read
    b. `status`가 `pending_dependency`인지 확인 (아니면 스킵)
    c. `dependencies.blockedBy` 배열에서 현재 완료된 REQ-ID를 제거
    d. `blockedBy` 배열이 비어지면:
       - `request.json`의 `status`를 `"phase1_analysis"`로 변경
       - 사용자에게 알림: `[활성화] {BLOCKED-REQ-ID} 의존성 해소 — Phase 1 분석 시작`
       - PM Conductor로 해당 REQ의 Phase 1 분석 즉시 실행 (spec.md 자동 작성)
       - Phase 1 분석 완료 (`status == "spec_ready"`) 후:
         * `workflow.auto_approve_on_unblock == true`이면:
           - 알림: `[자동 실행] {BLOCKED-REQ-ID} 의존성 해소 완료 → approve 자동 실행 중...`
           - `Skill(skill: "mst:approve", args: "{BLOCKED-REQ-ID}")` 호출
         * `false`이면: 기존과 동일하게 `/mst:approve {BLOCKED-REQ-ID}` 안내
    e. `blockedBy`가 아직 남아있으면 현재 REQ-ID만 제거하고 `pending_dependency` 유지
5.6. **DAG 자동 연쇄 실행 게이트 (수동 수락 경로 지원)**:
  - 목적: `workflow.auto_accept_result=false`로 `/mst:accept`를 수동 호출한 경로에서도 DAG 연쇄를 동일하게 보장
  - 실행 조건 (모두 충족 시에만 실행):
    1. `workflow.auto_accept_result == false`
    2. 현재 REQ의 `request.json.source_plan`이 `"PLN-NNN"` 형태로 존재
    3. 현재 REQ의 `request.json.dag_auto_chain == true`
    4. 현재 REQ 상태가 `done` 또는 `completed` 또는 `accepted`
  - 탐색/실행 규칙:
    - 매 반복마다 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json` Read 후 `linked_requests` 전체를 재평가한다 (`after=current` 방식 금지)
    - 후보 상태는 `pending_dependency`, `phase1_analysis`, `spec_ready`를 모두 포함한다
    - 완료/종료 상태(`done`, `completed`, `accepted`, `cancelled`)는 제외한다
    - 후보 REQ의 `dependencies.blockedBy`가 모두 해소된 경우에만 실행한다
    - 실행 호출 계약:
      - `Skill(skill: "mst:request", args: "--plan {source_plan} --resume {next_req.id} -a")`
      - `mst:request`는 기존 REQ 재개 모드로 동작해야 하며 신규 REQ를 생성하면 안 된다
  - 실패/종료 처리:
    - 다음 REQ 실행 후 상태가 `done`/`completed`/`accepted`가 아니면 즉시 중단
    - 중단 보고: `[DAG 연쇄 중단] {REQ-ID} 실패. 후속 REQ: {REQ-ID 목록}`
    - `linked_requests` 전체가 `done`/`completed`/`accepted`면 완료 보고:
      `[DAG 연쇄 완료] PLN-NNN의 모든 REQ가 완료되었습니다. ...`
6. **Plan 상태 동기화**:
   - `source_plan`(예: `PLN-NNN`) 있으면: `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json` Read → `linked_requests` 내 모든 REQ 상태 확인
   - 전체 `done`/`completed`/아카이브 시: **스크립트 우선** `python3 {PLUGIN_ROOT}/scripts/mst.py plan sync {source_plan}`; 실패 시 fallback으로 `plan.json`의 `status="completed"` + `completed_at` 직접 업데이트
   - 미완료 REQ 존재 시: 스킵; `source_plan` 없으면 스킵

## 예시

```
/mst:accept              # 최종 수락 대기 중인 첫 번째 요청 자동 선택
/mst:accept REQ-001      # 명시적으로 REQ-001 최종 수락
```

## 설정

`workflow.auto_accept_result` (기본: `true`): `true` → 자동 수락; `false` → 수동 호출 필요
```
/mst:settings workflow.auto_accept_result false
```

## 문제 해결

- "수락 요청 없음" → `/mst:inspect {REQ-ID}`로 Phase 3 PASS 상태 확인
- "리뷰 PASS 아님" → `/mst:feedback`으로 피드백 루프 먼저 완료
- "머지 충돌" → worktree에서 수동 충돌 해결 후 재실행
- "이미 완료됨" → `/mst:inspect {REQ-ID}` 확인
