---
name: setup-extension
description: "Chrome Extension(UI Picker)을 안정 경로에 복사하고 Load Unpacked 방식으로 설치하도록 안내합니다. Extension 안정 경로 복사, chrome://extensions 페이지 오픈, 절대 경로 표시, 클립보드 복사, Dashboard 서버 연결 확인을 순서대로 실행합니다. 사용자가 'Extension 설치', '크롬 확장 설정', '/mst:setup-extension'를 호출할 때 사용."
user-invocable: true
argument-hint: "[--skip-open]"
---

# maestro:setup-extension

`/mst:setup-extension`은 Gran Maestro Chrome Extension(UI Picker)을 Load Unpacked 방식으로 설치하도록 안내합니다.
Extension 경로 확인, Chrome 확장 프로그램 페이지 오픈, 설치 안내 및 클립보드 복사, Dashboard 서버 연결 확인의 4단계를 순서대로 실행합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

### Step 1: Extension 경로 확인

- `{PLUGIN_ROOT}/extension/` 디렉토리 존재 여부를 Bash `ls`로 확인
- 디렉토리가 없으면: 아래 메시지를 출력하고 중단

  ```
  Extension 파일을 찾을 수 없습니다.
  REQ-260 (Chrome Extension 구현)이 아직 완료되지 않았을 수 있습니다.
  플러그인을 최신 버전으로 업데이트한 후 다시 시도해주세요.
  ```

- 디렉토리가 있으면: `python3 {PLUGIN_ROOT}/scripts/mst.py extension ensure-copy`를 Bash로 실행하고 stdout 마지막 줄(결과 토큰)을 확인
  - **명령 실패(exit code != 0) 시**: 아래 경고를 출력하고 기존 동작으로 fallback — `EXT_PATH`를 `{PLUGIN_ROOT}/extension/`(절대 경로)로 설정하여 스킬을 계속 진행 (차단하지 않음)
    ```
    [경고] extension ensure-copy 실행에 실패했습니다. 기존 경로를 사용합니다.
    ```
  - **결과 토큰이 `skipped`** (프로젝트 설치): `EXT_PATH`를 `{PLUGIN_ROOT}/extension/`(절대 경로)로 설정
  - **결과 토큰이 `created`/`updated`/`unchanged`** (플러그인 설치): `EXT_PATH`를 `~/.gran-maestro/chrome-extension/`(절대 경로로 확장)로 설정
  - **결과 토큰이 `updated`일 때 추가 안내**: 아래 메시지를 출력
    ```
    Extension이 새 버전으로 업데이트되었습니다.
    chrome://extensions 페이지에서 확장 프로그램 새로고침 아이콘(🔄)을 클릭하여 변경사항을 반영해주세요.
    ```

### Step 2: Chrome 확장 프로그램 페이지 오픈

- `--skip-open` 옵션이 없으면 OS에 따라 아래 명령을 Bash로 실행:
  - macOS: `open "chrome://extensions"`
  - Linux: `xdg-open "chrome://extensions"`
  - Windows: `start chrome://extensions`
- 명령 실행 실패(exit code ≠ 0) 또는 `--skip-open` 옵션이 있으면:
  ```
  Chrome 주소창에 chrome://extensions 을 직접 입력해주세요.
  ```

### Step 3: 설치 안내 + 클립보드 복사

먼저 클립보드 복사를 Bash로 실행한다:

- macOS: `printf '%s' "{EXT_PATH}" | pbcopy`
- Linux: `printf '%s' "{EXT_PATH}" | xclip -selection clipboard`
  - 실패 시 fallback: `printf '%s' "{EXT_PATH}" | wl-copy`
- Windows: `printf '%s' "{EXT_PATH}" | clip`
- 모두 실패 시: "(클립보드 복사 실패 — 위 경로를 수동으로 복사해주세요)" 안내

그 후 아래 안내 메시지를 출력한다:

- **`--skip-open` 미사용 시:**

  ```
  [Gran Maestro Extension 설치 안내]

  1. Chrome 확장 프로그램 페이지가 열렸습니다 (열리지 않았다면 chrome://extensions 입력)
  2. 우측 상단 "개발자 모드"를 활성화하세요
  3. "압축해제된 확장 프로그램을 로드합니다" 클릭
  4. 아래 경로를 붙여넣으세요

  {EXT_PATH} (클립보드에 복사됨)

  💡 팁:
  - macOS: 파일 선택 창에서 Cmd+Shift+G → 경로 입력창
  - Linux: 파일 관리자 주소 입력창에 직접 붙여넣기
  - Windows: 탐색기 주소창에 직접 붙여넣기
  ```

- **`--skip-open` 사용 시** (1번 항목만 변경):

  ```
  [Gran Maestro Extension 설치 안내]

  1. Chrome 주소창에 chrome://extensions 을 입력하세요
  2. 우측 상단 "개발자 모드"를 활성화하세요
  3. "압축해제된 확장 프로그램을 로드합니다" 클릭
  4. 아래 경로를 붙여넣으세요

  {EXT_PATH} (클립보드에 복사됨)

  💡 팁:
  - macOS: 파일 선택 창에서 Cmd+Shift+G → 경로 입력창
  - Linux: 파일 관리자 주소 입력창에 직접 붙여넣기
  - Windows: 탐색기 주소창에 직접 붙여넣기
  ```

### Step 4: 연결 확인 (선택)

- `.gran-maestro/config.resolved.json` 파일 Read (프로젝트 루트 기준 상대 경로)
- `server.port` 값을 추출
- `curl -s --max-time 5 http://127.0.0.1:{port}/` 실행 (Bash)
  - curl 미설치 또는 명령 실패: "서버 확인을 건너뜁니다 (curl 미설치)" 안내 후 정상 종료
- HTTP 200 응답: "Dashboard 서버가 실행 중입니다. Extension 설치 후 연결이 자동으로 설정됩니다."
- 실패 또는 타임아웃: "Dashboard 서버가 실행 중이 아닙니다. 나중에 `/mst:dashboard`로 시작할 수 있습니다."
- 서버 상태와 무관하게 Extension 설치 안내(Step 3)는 이미 완료된 상태임

## 옵션

- `--skip-open`: chrome://extensions 페이지 자동 오픈(Step 2)을 건너뜀. Chrome이 이미 열려 있거나 자동 오픈이 불필요한 환경(예: WSL)에서 사용

## 예시

```
# Extension 설치 안내 (chrome://extensions 자동 오픈)
/mst:setup-extension

# 자동 오픈 없이 경로와 클립보드 복사만
/mst:setup-extension --skip-open
```

## 주의사항

- **멱등성**: 이 스킬은 `extension ensure-copy`를 통해 안정 경로에 Extension 파일을 복사하지만, 멱등하게 동작합니다 (버전이 같으면 `unchanged`, 다르면 `updated`). 클립보드 복사와 안내 메시지만 추가로 실행하므로 여러 번 실행해도 부작용이 없습니다.
- **Extension 소스**: 설치 형태에 따라 Extension 경로가 다릅니다.
  - **플러그인 설치** (`created`/`updated`/`unchanged`): `~/.gran-maestro/chrome-extension/` — 플러그인 업데이트와 독립적인 안정 경로에 복사본이 위치합니다.
  - **프로젝트 설치** (`skipped`): `{PLUGIN_ROOT}/extension/` — 개발 중인 소스 디렉토리를 직접 사용합니다.
  - `{PLUGIN_ROOT}/extension/` 디렉토리가 없으면 Step 1에서 중단됩니다 (REQ-260 완료 후 사용 가능).
- **Chrome 개발자 모드 경고**: Load Unpacked 방식의 본질적 특성으로, 설치 시 Chrome이 개발자 모드 경고를 표시할 수 있습니다. 정상 동작입니다.
- **이미 설치된 경우**: Extension이 이미 로드된 상태에서 재실행해도 동일한 안내만 표시됩니다 (Chrome API 제한으로 설치 여부를 자동 감지할 수 없음).

## 문제 해결

| 증상 | 원인 | 해결 방법 |
|------|------|-----------|
| "Extension 파일을 찾을 수 없습니다" | `{PLUGIN_ROOT}/extension/` 미존재 | 플러그인 최신 버전 확인; REQ-260 완료 여부 확인 |
| chrome://extensions 가 열리지 않음 | Chrome 미설치 또는 OS 제한 | `--skip-open`으로 재실행 후 수동으로 chrome://extensions 입력 |
| 클립보드 복사 실패 (Linux) | `xclip`/`wl-copy` 미설치 | `sudo apt install xclip` 또는 `sudo apt install wl-clipboard` 설치 후 재실행 |
| WSL 환경에서 오픈 실패 | `xdg-open` 동작 제한 | `--skip-open`으로 재실행; Windows Chrome에서 수동으로 경로 입력 |
| `extension ensure-copy` 실패 경고 | `mst.py` 스크립트 오류 또는 구버전 | 경고만 출력되며 스킬은 `{PLUGIN_ROOT}/extension/` 경로로 계속 진행됨; 플러그인을 최신 버전으로 업데이트하면 해결 |
| Dashboard 서버 연결 실패 | 서버 미실행 상태 | `/mst:dashboard`로 서버 시작 후 Extension 재연결 (설치 자체는 완료됨) |
