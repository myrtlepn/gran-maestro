---
name: picks
description: "사용자가 $mst:picks 또는 /mst:picks을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 picks 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[--list] [--all] [{자연어 선택/변경 요청}]"
---

# maestro:picks

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

<!-- mst-session-class: identity-required; root-source: selected existing CAP root -->
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

사용자가 캡처 큐에서 항목을 자연어로 선택하고, 변경 요청 감지 시 `/mst:plan --from-picks`로 자동 전환합니다.

## 실행 제약 (CRITICAL -- 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` (status 업데이트용)

**그 외 모든 경로에 대한 Write/Edit 사용은 절대 금지입니다.**

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

### Step 1: 캡처 목록 로드

1. `{PROJECT_ROOT}/.gran-maestro/captures/` 디렉토리 존재 확인
   - **미존재 시**: "캡처가 없습니다. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료
2. `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` 일괄 Read
3. 기본 필터: status가 `archived`, `done`, 또는 `consumed`인 항목 제외 (pending/selected 표시)
   - `--all` 옵션 시: archived/done/consumed 포함 전체 표시
4. `created_at` 기준 최신순 정렬, 기본 50개 제한
   - `--all` 사용 시 50개 제한 해제
5. **캡처가 0개일 때**: "표시할 캡처가 없습니다. `--all`로 consumed/done 포함 전체 확인 가능. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료

### Step 2: 목록 표시

#### 2-0: 대시보드 링크 정보 취득

목록 표시 전에 대시보드 URL 구성에 필요한 정보를 취득합니다:

1. **포트 취득**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get server.port)`로 `server.port` 값을 취득합니다. 키 미설정 또는 조회 실패 시 기본값 `3847`을 사용합니다.
2. **프로젝트 ID 취득**: 대시보드 API를 호출하여 현재 프로젝트의 ID를 취득합니다:
   ```bash
   curl -s "http://127.0.0.1:<port>/api/projects"
   ```
   응답 JSON 배열에서 `path`가 `{PROJECT_ROOT}/.gran-maestro`와 일치하는 항목의 `id`를 사용합니다.
   - API 호출 실패 또는 매칭 프로젝트 없음: 프로젝트 ID 없이 진행 (링크에서 `?project=` 파라미터 생략)

#### 2-1: 테이블 출력

캡처 목록을 요약 테이블로 표시합니다:

| ID | URL | Selector | Memo | Tags | Status | Age |
|----|-----|----------|------|------|--------|-----|

- **Age**: 상대 시간으로 표시 (예: "3일 전", "2h")
- **Status**: pending / selected / consumed / archived / done
- `ttl_warned_at`이 non-null인 항목: Status 옆에 `[⚠ 24h]` 표시 (TTL 경고)
- URL은 발췌 표시 (도메인 + 경로 앞부분)

#### 2-2: 대시보드 링크 표시

테이블 하단에 각 캡처의 대시보드 직접 링크를 표시합니다:

```
📎 Dashboard links:
  CAP-001 → http://localhost:<port>/picks/CAP-001?project=<project-id>
  CAP-002 → http://localhost:<port>/picks/CAP-002?project=<project-id>
  ...
```

- URL 형식: `http://localhost:<port>/picks/<CAP-ID>?project=<project-id>`
- 프로젝트 ID 취득 실패 시: `?project=<project-id>` 파라미터를 생략하여 `http://localhost:<port>/picks/<CAP-ID>` 형식으로 출력
- 대시보드 서버 미실행(2-0 API 호출 실패) 시에도 링크는 표시 (서버 시작 후 사용 가능)

**`--list` 옵션 시**: 목록만 표시 후 종료 (사용자 입력 대기 없음)

### Step 3: 사용자 입력 분석 (LLM)

사용자 입력을 LLM이 분석하여 아래 유형으로 분류합니다:

#### 3-A: 직접 ID 지정
- 예: "CAP-001, CAP-003"
- 지정된 ID에 해당하는 캡처를 선택 대상으로 확정
- 기본 필터에서 숨겨진 status(`consumed`/`done`/`archived`)도 ID 직접 지정 시 매칭 허용

#### 3-B: 자연어 필터
- 예: "헤더 관련", "버튼", "#ui 태그"
- LLM이 memo, tags, selector, url 등을 종합하여 매칭되는 캡처를 선택 대상으로 확정

#### 3-C: 변경 요청 감지
- 예: "이 버튼 색상 빨간색으로 바꿔", "수정해줘", "바꿔줘", "추가해줘"
- 변경 요청 키워드: 수정, 바꿔, 추가, 삭제, 변경, 고쳐, 업데이트, modify, change, fix, update, add, remove
- 선택 + 변경 요청이 동시에 포함된 것으로 처리 -> Step 4로 진행

#### 매칭 결과 처리

- **매칭 0건**: "일치하는 캡처가 없습니다. 다시 시도해주세요." 안내 -> 재입력 대기
- **재입력 최대 3회** 후에도 0건이면 종료
- **선택만 (변경 요청 없음)**: 선택된 캡처의 status를 `selected`로 업데이트 (capture.json Write) -> 목록 재표시 (갱신된 status 반영) -> 선택 완료 안내 + 클립보드 복사 제공 후 종료

클립보드 복사 내용:
```
/mst:plan --from-picks [CAP-003] [CAP-005] {요약}
```

### Step 4: 선택 확인 및 /mst:plan 전환

변경 요청이 감지된 경우 실행합니다.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

**실행 순서** (반드시 순차):

1. **status 업데이트 먼저**: 선택된 캡처의 status를 `selected`로 업데이트 (capture.json Write)
2. **`/mst:plan --from-picks` 호출**: 사용자 전체 입력에서 요청 텍스트를 추출하여 전달

```
Skill(skill: "mst:plan", args: "--from-picks [CAP-NNN] [CAP-NNN] {요청 텍스트}")
```

## 옵션 정리

| 옵션 | 설명 |
|------|------|
| `--list` | 캡처 목록만 표시 후 종료 (선택 대화 진입 안 함) |
| `--all` | archived/done/consumed 포함 전체 표시, 50개 제한 해제 |
| `--list --all` | 전체 캡처 목록 확인 (archived/done/consumed 포함, 제한 없음) |

## 에러 처리

- `captures/` 디렉토리 미존재: "캡처가 없습니다. Chrome Extension에서 캡처를 시작하세요." 안내 후 종료
- `capture.json` 파싱 실패: 해당 항목 건너뛰기 + 경고 표시
- TTL 경고 대상 캡처: `ttl_warned_at` non-null 시 `[⚠ 24h]` 표시
