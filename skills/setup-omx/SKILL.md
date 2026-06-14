---
name: setup-omx
description: "Codex CLI 프로젝트에 oh-my-codex(OMX)를 설치·초기화·gitignore 등록·AGENTS.md 주입하는 4단계 자동화를 수행합니다. 사용자가 'OMX 설치', 'oh-my-codex 설정', '/mst:setup-omx'를 호출할 때 사용."
user-invocable: true
argument-hint: "[--dir {프로젝트 경로}] [--skip-install]"
---

# maestro:setup-omx

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
