---
name: "on"
description: "사용자가 $mst:on 또는 /mst:on을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 on 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: ""
---

# maestro:on

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

<!-- mst-session-class: identity-required; root-source: active persisted root or new CAP capture -->
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

Gran Maestro 모드를 활성화합니다. Maestro 오케스트레이션 스킬이 활성화됩니다.

## 모드 전환 규칙

### 활성화 시 차단되는 스킬
- `/autopilot`, `/ralph`, `/ultrawork`, `/team`, `/pipeline`, `/ultrapilot`, `/swarm`, `/ecomode`
  (구 오토파일럿/루프 계열 슬래시 스킬 차단 목적. `/ralph`는 과거 이름으로 유지하며, 현재 mst-loop 재진입은 `/mst:resume` + `scripts/mst-loop.sh`로 대체되었습니다.)

### Maestro 모드에서 사용 가능한 스킬
- Maestro 오케스트레이션: `/mst:request`, `/mst:list`, `/mst:inspect`, `/mst:approve`, `/mst:accept`, `/mst:feedback`, `/mst:cancel`, `/mst:dashboard`, `/mst:priority`, `/mst:history`, `/mst:settings`
- CLI 직접 호출: `/mst:codex`, `/mst:agy` (모드 무관)
- 단발 분석/리뷰: `/analyze`, `/deepsearch`, `/code-review`, `/security-review` (모드 무관)
- 유틸리티: `/note`, `/plan`, `/trace`, `/doctor` (모드 무관)

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

### Runtime Host Detection (MANDATORY)

스킬 실행 시작 시 아래 명령으로 현재 host를 확인하고 `MST_HOST_CONTEXT` / `MST_HOST`를 보관한다.

```bash
MST_HOST_CONTEXT="$(python3 {PLUGIN_ROOT}/scripts/mst.py host context --json 2>/dev/null || printf '{}')"
MST_HOST="$(printf '%s' "$MST_HOST_CONTEXT" | python3 -c 'import json,sys; p=json.load(sys.stdin); print(p.get("host") or "headless")' 2>/dev/null || printf 'headless')"
```

- `MST_HOST="codex"`이면 Codex plugin runtime이다. Claude Code hook 등록/정리, `~/.claude` 전역 설정 변경, `${CLAUDE_PLUGIN_ROOT}` 기반 설명은 실행하지 않는다.
- `MST_HOST="claude"`이면 기존 Claude Code plugin runtime 계약을 유지한다.
- `MST_HOST="headless"`이면 프로젝트 파일 초기화는 계속하되, Claude Code 사용자 전역 설정 변경은 명시적으로 필요한 경우에만 수행한다.

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

<!-- paused-resume:start -->
### Paused Snapshot Resume 안내 (MANDATORY)

모드 활성화 시작 시, Step 1 전에 현재 세션의 paused snapshot을 확인한다. 이 단계에서는 사용자에게 질문하지 않고 안내만 출력한다.

```bash
SESSION_ID="${MST_SESSION_ID:?MST_SESSION_ID is required for paused snapshot resume}"
PAUSED_COUNT="$(MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 {PLUGIN_ROOT}/scripts/mst.py state paused-count --session-id "$SESSION_ID" 2>/dev/null || printf '0')"
case "$PAUSED_COUNT" in ''|*[!0-9]*) PAUSED_COUNT=0 ;; esac
if [ "$PAUSED_COUNT" -gt 0 ]; then
  echo "paused 체인 ${PAUSED_COUNT}건 발견. /mst:resume 또는 다음 mst skill 호출로 재개됩니다."
  if [ "${AUTO_MODE:-false}" = "true" ]; then
    python3 {PLUGIN_ROOT}/scripts/mst.py state resume-paused --session-id "$SESSION_ID" >/dev/null 2>&1 || true
    echo "AUTO_MODE=true: paused 체인 ${PAUSED_COUNT}건 자동 resume 처리 완료"
  fi
fi
```

`AUTO_MODE=false`에서는 추가 확인 없이 안내만 출력한다. 다음 skill 호출 시 기존 continuation/resume 경로가 자연스럽게 이어진다. Paused snapshot state commands inherit the canonical `MST_SESSION_ID` structured context.
<!-- paused-resume:end -->


1. `{PROJECT_ROOT}/.gran-maestro/` 디렉토리 생성, `.gitignore`에 `.gran-maestro/` 등록 (미존재 시)
2. 플러그인 루트 경로 확인 (스킬 베이스 디렉토리 2단계 상위)
2.5. Extension 안정 경로 동기화 (비차단):
   - Bash로 `python3 {PLUGIN_ROOT}/scripts/mst.py extension ensure-copy` 실행 (Step 2에서 확인한 `PLUGIN_ROOT` 사용)
   - 이 명령은 **비차단(non-blocking)**으로 처리한다: 명령 실패(exit code ≠ 0) 시 경고 없이 무시하고 Step 3으로 진행
   - 결과 토큰별 분기:
     - `updated` → 안내 출력: `"Extension이 업데이트되었습니다. chrome://extensions 페이지에서 확장 프로그램 새로고침 아이콘을 클릭하세요"`
     - `created` → 안내 출력: `"Extension 안정 경로 복사 완료 (~/.gran-maestro/chrome-extension/)"`
     - `unchanged` / `skipped` → 추가 출력 없음 (silent)
     - 명령 실패 → 추가 출력 없음 (silent) — `{PLUGIN_ROOT}/extension/` 미존재 등 에러 종료 포함
3. `config.json` / `agents.json` 없으면 `templates/defaults/`에서 복사
3.5. **base_branch 설정 마법사**:
   - 현재 git 브랜치 감지:
     ```bash
     CURRENT_BRANCH=$(git -C "{PROJECT_ROOT}" branch --show-current 2>/dev/null)
     # git 저장소가 아니거나 빈 문자열이면 "main" 폴백
     [ -z "$CURRENT_BRANCH" ] && CURRENT_BRANCH="main"
     ```
   - 기존 base_branch 값 읽기:
     ```bash
     SAVED_BRANCH=$(python3 -c "
     import json
     try:
         d = json.load(open('{PROJECT_ROOT}/.gran-maestro/config.json'))
         v = d.get('worktree', {}).get('base_branch', '')
         print(v)
     except: print('')
     " 2>/dev/null || echo "")
     ```
   - **skip 조건**: `SAVED_BRANCH`가 비어있지 않고 `SAVED_BRANCH != "main"` 이면:
     → `"✓ base_branch: {SAVED_BRANCH} (기존 설정 유지)"` 출력 후 Step 3.55로 진행.

     > ℹ️ `"main"`은 templates/defaults/config.json의 기본값이므로 "미설정"과 동일하게 취급한다.
     > Step 3에서 config.json이 처음 복사된 경우에도 SAVED_BRANCH는 `"main"`이 되어 질문 조건에 진입한다.

   - **질문 조건** (`SAVED_BRANCH` 비어있거나 `SAVED_BRANCH == "main"` 인 경우):
     - 선택지 목록 구성:
       1. `CURRENT_BRANCH` 옵션 (권장): label = `"{CURRENT_BRANCH} (현재 브랜치, 권장)"`, value = `{CURRENT_BRANCH}`
       2. `"main"` — `CURRENT_BRANCH != "main"`인 경우에만 포함
       3. `"master"` — `CURRENT_BRANCH != "master"`인 경우에만 포함
       (Other 텍스트 입력 항상 허용)
     - AskUserQuestion 표시:
       - 질문: `"워크트리를 어느 브랜치에서 분기할까요? (감지된 현재 브랜치: {CURRENT_BRANCH})"`
     - 사용자가 선택한 **value**(브랜치명)를 `BASE_BRANCH_VALUE`로 저장:
       - 고정 선택지 선택 시: value 그대로 사용 (`{CURRENT_BRANCH}`, `"main"`, `"master"` 중 택일)
       - Other 텍스트 직접 입력 시: 입력 문자열을 trim() 후 사용
   - config.json에 반영 (임시파일 + rename 패턴으로 원자적 쓰기):
     ```bash
     python3 - << EOF
     import json, os, tempfile
     path = "{PROJECT_ROOT}/.gran-maestro/config.json"
     try:
         d = json.load(open(path))
     except:
         d = {}
     d.setdefault("worktree", {})["base_branch"] = "{BASE_BRANCH_VALUE}"
     tmp = path + ".tmp"
     with open(tmp, "w") as f:
         json.dump(d, f, indent=2, ensure_ascii=False)
     os.replace(tmp, path)
     EOF
     ```
   - 완료 메시지: `"✓ base_branch: {BASE_BRANCH_VALUE}"`
3.55. **protected_branches 설정 마법사**:
   - 기본값은 `["main", "master", "release/*"]`이다.
   - 현재 `worktree.protected_branches` 값 읽기 및 표시:
     ```bash
     CURRENT_PROTECTED_BRANCHES_JSON=$(python3 - << EOF
     import json
     default = ["main", "master", "release/*"]
     try:
         d = json.load(open('{PROJECT_ROOT}/.gran-maestro/config.json'))
         v = d.get("worktree", {}).get("protected_branches", default)
         if not (isinstance(v, list) and all(isinstance(item, str) for item in v)):
             v = default
     except Exception:
         v = default
     print(json.dumps(v, ensure_ascii=False))
     EOF
     )
     echo "현재 protected_branches: ${CURRENT_PROTECTED_BRANCHES_JSON}"
     ```
   - 사용자에게 현재 값을 그대로 유지하거나 편집할지 묻는다.
     - Enter 또는 기본값 유지 선택 시: `PROTECTED_BRANCHES_JSON=${CURRENT_PROTECTED_BRANCHES_JSON}`로 두고 `config.json`을 변경하지 않고 다음 단계로 진행한다.
     - 편집 입력은 쉼표 구분 문자열(`main,master,release/*`) 또는 JSON 배열 문자열(`["main", "master", "release/*"]`) 둘 다 허용한다.
     - 편집 성공 시 `PROTECTED_BRANCHES_JSON`은 파싱 결과를 `json.dumps(value, ensure_ascii=False)`로 직렬화한 JSON 배열 문자열이다.
   - 편집 입력 파싱 규칙:
     ```python
     import json

     default = ["main", "master", "release/*"]

     def parse_protected_branches(raw):
         raw = raw.strip()
         if not raw:
             return None
         if raw.startswith("["):
             parsed = json.loads(raw)
         else:
             parsed = [item.strip() for item in raw.split(",")]
         if not isinstance(parsed, list):
             raise ValueError("protected_branches must be a list")
         parsed = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
         if not parsed:
             raise ValueError("protected_branches must include at least one branch pattern")
         return parsed
     ```
     - 파싱 실패 시 사용자에게 재입력을 요청한다.
     - 파싱 실패가 3회 발생하면 `protected_branches_value = default`로 기본값 복구 후 저장한다.
   - 편집 또는 3회 실패 기본값 복구 시 `config.json`에 반영 (임시파일 + rename 패턴으로 원자적 쓰기):
     ```bash
     python3 - << EOF
     import json, os
     path = "{PROJECT_ROOT}/.gran-maestro/config.json"
     protected_branches_value = {PROTECTED_BRANCHES_JSON}
     try:
         d = json.load(open(path))
     except Exception:
         d = {}
     d.setdefault("worktree", {})["protected_branches"] = protected_branches_value
     tmp = path + ".tmp"
     with open(tmp, "w") as f:
         json.dump(d, f, indent=2, ensure_ascii=False)
     os.replace(tmp, path)
     EOF
     ```
   - 완료 메시지: `"✓ protected_branches: {PROTECTED_BRANCHES_JSON}"`
3.6. **MANDATORY (config 변경 후처리)**: Step 3/3.5/3.55에서 `config.json`이 생성/수정된 직후 아래 명령을 실행한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py config resolve || echo "[warning] config.resolved.json 갱신 실패. 수동으로 'python3 scripts/mst.py config resolve'를 실행하세요." >&2
   ```
4. `{PROJECT_ROOT}/.gran-maestro/mode.json` 작성 (always overwrite):

   > ⏱️ **타임스탬프 취득 (MANDATORY)**:
   > `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
   > 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
   > 출력값을 `activated_at` 필드에 기입한다. 날짜만 기입 금지.

   ```json
   {
     "active": true,
     "activated_at": "{TS — mst.py timestamp now 출력값}",
     "auto_deactivate": true,
   }
   ```
5. `requests/`, `worktrees/` 디렉토리 생성
6. 워크플로우 Hook 등록 (자동, 사용자 작업 불필요):

   **Codex runtime branch (MANDATORY)**:
   - `MST_HOST="codex"`인 경우 아래 6a/6b의 Claude Code hook 등록·정리·전역 설정 설치 단계를 모두 skip한다.
   - Codex는 Claude Code Stop/PreToolUse/UserPromptSubmit hook이 아니라 `.gran-maestro/pending.ndjson` queue와 `/mst:resume`/headless drain contract를 사용한다.
   - 이 분기에서는 `~/.claude/scripts`, `~/.claude/settings.json`, `.claude-plugin/plugin.json`, `hooks/hooks.json`, `${CLAUDE_PLUGIN_ROOT}`를 생성/수정/등록하지 않는다.
   - 안내 출력: `"Codex runtime: Claude Code hooks skipped; queue supervisor is active."`

   **6a. MST core Hook 등록은 hooks.json 자체 등록으로 자동 처리됨**:
   - plugin core canonical runtime은 `.claude-plugin/plugin.json`의 `"hooks": "./hooks/hooks.json"`와 플러그인 루트의 `hooks/hooks.json`입니다. `hooks/hooks.json`이 SessionStart / PreToolUse(matcher="Skill", "ScheduleWakeup") / Stop / UserPromptSubmit hook을 `${CLAUDE_PLUGIN_ROOT}/hooks/{스크립트명}` 형식으로 자체 등록합니다 (Claude Code 플러그인 표준 메커니즘, REQ-732 도입).
   - **/mst:on은 일반 프로젝트에 `.claude/hooks/` 사본을 만들지 않으며**, `settings.local.json`의 `hooks` 블록도 MST core canonical runtime으로 변경하지 않습니다. 사용자 정의 hook(`env`, `permissions`, 사용자 hook 등록 등) 기존 항목은 그대로 보존됩니다.
   - project-local `.claude/hooks/mst-*.sh` 또는 `$CLAUDE_PROJECT_DIR/.claude/hooks/...` 등록은 일반 프로젝트 canonical runtime이 아니라 project legacy / source-dev helper / cleanup·diagnostic 대상입니다.
   - 결과: 플러그인 캐시 한 곳을 갱신하면 모든 등록 프로젝트가 `${CLAUDE_PLUGIN_ROOT}` 경유로 최신 MST core hook을 사용합니다 (stale 사본 발생 불가).
   - 기존 `.claude/hooks/` MST 사본이 남아있는 프로젝트는 canonical 주입 대상이 아니라 cleanup 대상입니다 — 본 단계는 `python3 {PLUGIN_ROOT}/scripts/mst.py on cleanup --silent || true`를 호출해 stale mst hook 사본·settings 항목을 안전하게 제거합니다 (사용자 정의 hook은 정규식 패턴 매칭으로 보존). 명시적 호출은 `python3 {PLUGIN_ROOT}/scripts/mst.py on cleanup`(또는 `--dry-run` 미리보기)으로 가능합니다.

   ```bash
   # legacy mst hook 사본·settings 항목 자동 정리 (silent fail-open)
   if [ "${MST_HOST:-headless}" = "claude" ]; then
     MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}" MST_CONTEXT_JSON="$(MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}" python3 -c 'import base64,os,sys;s=os.environ["MST_CONTEXT_B64"];MAX_CONTEXT_BYTES=262144;sys.exit("encoded MST context exceeds limit") if len(s)>349528 else None;raw=base64.b64decode(s.encode("ascii"),altchars=b"-_",validate=True);sys.exit("decoded MST context is oversized or non-canonical") if len(raw)>MAX_CONTEXT_BYTES or base64.urlsafe_b64encode(raw).decode("ascii")!=s else None;sys.stdout.buffer.write(raw)')" python3 "{PLUGIN_ROOT}/scripts/mst.py" on cleanup --silent || true
   else
     echo "Codex runtime: Claude Code hooks skipped; queue supervisor is active."
   fi
   ```

   **6b. User-global environment hook 설치**:
   - 이 단계는 `MST_HOST="claude"`에서만 실행한다. `MST_HOST="codex"`이면 반드시 skip한다.
   - `check-version.sh`는 MST core SessionStart/Stop hook이 아니라 user-global environment hook입니다. `check-version.sh`를 `~/.claude/scripts/`에 복사; `settings.json`의 `hooks.UserPromptSubmit`에 아래 hook 추가(미존재 시):
     ```json
     { "type": "command", "command": "~/.claude/scripts/check-version.sh" }
     ```
     동일 `command`가 이미 등록되어 있으면 건너뜁니다.
     `hooks.UserPromptSubmit` 배열은 기존 항목을 보존한 상태로 병합해야 합니다.
     설정 파일 파싱은 `python3` 또는 `jq`로 수행할 수 있으며, 동일 `command`가 이미 존재하면 추가하지 마세요.
7. 사용자에게 모드 전환 알림 출력

## 출력

```
Gran Maestro 모드 활성화

역할 전환: 현재 host → PM (지휘자)
- 코드 작성: 금지 (Codex/AGY에 위임)
- 분석/스펙/리뷰: 활성

Maestro 오케스트레이션 스킬이 활성화되었습니다.
/mst:request 로 새 요청을 시작하세요.
```

## 쉘에서 상태 확인

Claude Code host에서는 `maestro-status.sh` (macOS/Linux) 또는 `maestro-status.py` (Windows)를 함께 설치한다. Codex host에서는 이 전역 설치를 skip하고 `{PROJECT_ROOT}/.gran-maestro/mode.json`을 상태 기준으로 사용한다.
```bash
~/.claude/scripts/maestro-status.sh           # "on (requests: 2)" 또는 "off"
~/.claude/scripts/maestro-status.sh --json    # JSON 전체 출력
~/.claude/scripts/maestro-status.sh -q        # exit code만 (스크립팅용)
~/.claude/scripts/maestro-status.sh --field active
```

## 문제 해결

- "이미 활성화됨" → `mode.json`의 `active: true` 확인; 추가 작업 불필요
- "config.json 생성 실패" → 쓰기 권한 및 git 저장소 루트 여부 확인
