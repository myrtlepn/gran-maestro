---
name: on
description: "Maestro 모드를 활성화합니다. 사용자가 '마에스트로 켜', '마에스트로 시작', '지휘자 모드'를 말하거나 /mst:on을 호출할 때 사용. 새 요청 시작은 /mst:request를 사용 (자동 부트스트래핑 포함)."
user-invocable: true
argument-hint: ""
---

# maestro:on

Gran Maestro 모드를 활성화합니다. Maestro 오케스트레이션 스킬이 활성화됩니다.

## 모드 전환 규칙

### 활성화 시 차단되는 스킬
- `/autopilot`, `/ralph`, `/ultrawork`, `/team`, `/pipeline`, `/ultrapilot`, `/swarm`, `/ecomode`
  (구 오토파일럿/루프 계열 슬래시 스킬 차단 목적. `/ralph`는 과거 이름으로 유지하며, 현재 mst-loop 재진입은 `/mst:resume` + `scripts/mst-loop.sh`로 대체되었습니다.)

### Maestro 모드에서 사용 가능한 스킬
- Maestro 오케스트레이션: `/mst:request`, `/mst:list`, `/mst:inspect`, `/mst:approve`, `/mst:accept`, `/mst:feedback`, `/mst:cancel`, `/mst:dashboard`, `/mst:priority`, `/mst:history`, `/mst:settings`
- CLI 직접 호출: `/mst:codex`, `/mst:gemini` (모드 무관)
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

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (AskUserQuestion 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 `AskUserQuestion`과 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->

<!-- paused-resume:start -->
### Paused Snapshot Resume 안내 (MANDATORY)

모드 활성화 시작 시, Step 1 전에 현재 세션의 paused snapshot을 확인한다. 이 단계에서는 사용자에게 질문하지 않고 안내만 출력한다.

```bash
SESSION_ID="${MST_SESSION_ID:?MST_SESSION_ID is required for paused snapshot resume}"
PAUSED_COUNT="$(python3 {PLUGIN_ROOT}/scripts/mst.py state paused-count --session-id "$SESSION_ID" 2>/dev/null || printf '0')"
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

   **6a. Hook 등록은 hooks.json 자체 등록으로 자동 처리됨**:
   - 플러그인 루트의 `hooks/hooks.json`이 SessionStart / PreToolUse(matcher="Skill") / Stop / UserPromptSubmit 4개 hook을 `${CLAUDE_PLUGIN_ROOT}/hooks/{스크립트명}` 형식으로 자체 등록합니다 (Claude Code 플러그인 표준 메커니즘, REQ-732 도입).
   - **/mst:on은 더 이상 hook 파일을 프로젝트로 복사하지 않으며**, `settings.local.json`의 `hooks` 블록도 변경하지 않습니다. 사용자 정의 hook(`env`, `permissions`, 사용자 hook 등록 등) 기존 항목은 그대로 보존됩니다.
   - 결과: 플러그인 캐시 한 곳을 갱신하면 모든 등록 프로젝트가 자동으로 최신 hook을 사용합니다 (stale 사본 발생 불가).
   - 기존 `.claude/hooks/` 사본이 남아있는 프로젝트는 자동으로 정리됩니다 — 본 단계는 `python3 {PLUGIN_ROOT}/scripts/mst.py on cleanup --silent || true`를 호출해 stale mst hook 사본·settings 항목을 안전하게 제거합니다 (사용자 정의 hook은 정규식 패턴 매칭으로 보존). 명시적 호출은 `python3 {PLUGIN_ROOT}/scripts/mst.py on cleanup`(또는 `--dry-run` 미리보기)으로 가능합니다.

   ```bash
   # mst hook 사본·settings 항목 자동 정리 (silent fail-open)
   python3 "{PLUGIN_ROOT}/scripts/mst.py" on cleanup --silent || true
   ```

   **6b. 버전 알림 스크립트 설치**:
   - `check-version.sh`를 `~/.claude/scripts/`에 복사; `settings.json`의 `hooks.UserPromptSubmit`에 아래 hook 추가(미존재 시):
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

역할 전환: Claude Code → PM (지휘자)
- 코드 작성: 금지 (Codex/Gemini에 위임)
- 분석/스펙/리뷰: 활성

Maestro 오케스트레이션 스킬이 활성화되었습니다.
/mst:request 로 새 요청을 시작하세요.
```

## 쉘에서 상태 확인

`maestro-status.sh` (macOS/Linux) 또는 `maestro-status.py` (Windows) 함께 설치:
```bash
~/.claude/scripts/maestro-status.sh           # "on (requests: 2)" 또는 "off"
~/.claude/scripts/maestro-status.sh --json    # JSON 전체 출력
~/.claude/scripts/maestro-status.sh -q        # exit code만 (스크립팅용)
~/.claude/scripts/maestro-status.sh --field active
```

## 문제 해결

- "이미 활성화됨" → `mode.json`의 `active: true` 확인; 추가 작업 불필요
- "config.json 생성 실패" → 쓰기 권한 및 git 저장소 루트 여부 확인
