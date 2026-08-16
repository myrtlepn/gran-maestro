---
name: setup-omx
description: "사용자가 $mst:setup-omx 또는 /mst:setup-omx을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 setup-omx 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[--dir {프로젝트 경로}] [--skip-install]"
---

# maestro:setup-omx

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

<!-- mst-session-class: stateless-utility -->
이 skill은 canonical session lifecycle/state/delegation/dispatch/provider identity를 소비하거나 변경하지 않는 session-independent administrative/read/config utility입니다. 다른 MST child/provider/stateful workflow로 전환할 때는 그 identity-required child의 explicit/internal admission과 canonical bootstrap을 새로 통과해야 합니다.

`/mst:setup-omx`는 Codex CLI 프로젝트에 oh-my-codex(OMX)를 설치하고 초기화합니다.
설치, 초기화, gitignore 등록, AGENTS.md 주입의 4단계를 순서대로 자동 실행합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

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


### Step 1: OMX 전역 설치

- `--skip-install` 옵션이 없으면: `npm install -g oh-my-codex` 실행
- `--skip-install` 옵션이 있으면: 이 단계를 건너뛰고 Step 2로 이동

### Step 2: OMX 초기화

- `--dir {path}` 옵션이 있으면 해당 경로를 대상 디렉토리로 사용, 없으면 현재 디렉토리 사용
- 대상 디렉토리 존재 여부 확인, 없으면 에러 메시지 출력 후 중단
- `omx setup && omx doctor` 실행

### Step 3: gitignore 처리

- `{대상 디렉토리}/.gitignore` 파일 확인
- 파일이 없으면: `.omx` 한 줄을 포함한 새 `.gitignore` 파일 생성 (멱등성: 이미 있으면 스킵)
- 파일이 있으면:
  - `.omx` 항목이 이미 존재하면: 스킵 (중복 방지)
  - `.omx` 항목이 없으면: 파일 끝에 `.omx` 추가

### Step 4: AGENTS.md 주입

- `{PLUGIN_ROOT}/AGENTS.md` 파일 Read
  - 파일이 없으면: 에러 메시지 출력 후 중단
- `{대상 디렉토리}/AGENTS.md` 확인:
  - 있으면: "OMx 트리거 자동 분기 규칙" 구문 포함 여부 확인
    - 포함: 스킵 (중복 방지) — 사용자 확인 불필요, 즉시 완료 메시지 출력
    - 미포함: 사용자 확인 단계 진행 (아래)
  - 없으면: 사용자 확인 단계 진행 (아래)

#### 사용자 확인 단계

`AskUserQuestion`으로 다음 내용을 표시하고 동의 여부 확인:

- 질문: `"AGENTS.md 내용을 {대상 디렉토리}/AGENTS.md에 추가합니다. 계속하시겠습니까?"`
- 옵션 1 (기본): "추가" — `{PLUGIN_ROOT}/AGENTS.md` 내용을 append (파일 없으면 신규 생성)
- 옵션 2: "건너뛰기" — 이 단계 스킵, 완료 메시지 출력

사용자가 "건너뛰기" 선택 시: Step 4 종료, 전체 완료 메시지 출력

## 옵션

- `--dir {path}`: 대상 프로젝트 디렉토리 지정 (기본: 현재 디렉토리). 상대경로는 현재 작업 디렉토리 기준으로 해석
- `--skip-install`: OMX 전역 설치(Step 1)를 건너뜀. OMX가 이미 설치된 경우 사용

## 예시

```
# 현재 디렉토리에 OMX 설정
/mst:setup-omx

# 특정 프로젝트 경로에 OMX 설정
/mst:setup-omx --dir ./my-codex-project

# 설치 단계 건너뛰고 초기화만
/mst:setup-omx --skip-install

# 특정 경로에 설치 단계 건너뛰고 설정
/mst:setup-omx --dir /path/to/project --skip-install
```

## 주의사항

- **멱등성**: gitignore의 `.omx` 항목과 AGENTS.md 주입은 중복 방지 처리가 되어 있습니다. 스킬을 여러 번 실행해도 안전합니다.
- **AGENTS.md 소스**: `{PLUGIN_ROOT}/AGENTS.md` 파일에서 내용을 읽습니다. 이 파일이 존재하지 않으면 Step 4가 실패합니다.
- **oh-my-codex**: `npm install -g oh-my-codex` 설치를 위해 Node.js와 npm이 필요합니다.
- **omx 명령어**: Step 2 실행 전 OMX가 설치되어 있어야 합니다 (`omx --version`으로 확인).

## 문제 해결

- "omx: command not found" → `--skip-install` 없이 재실행 또는 `npm install -g oh-my-codex`
- "대상 디렉토리를 찾을 수 없음" → `--dir` 경로 확인 (상대경로는 cwd 기준)
- "AGENTS.md 소스 파일 없음" → `{PLUGIN_ROOT}/AGENTS.md` 확인; 플러그인 재설치
