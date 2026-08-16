---
name: hud-uninstall
description: "사용자가 $mst:hud-uninstall 또는 /mst:hud-uninstall을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 hud-uninstall 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: ""
---

# maestro:hud-uninstall

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

MST HUD 래퍼를 해제하고 원래 Claude HUD status line 명령을 복원합니다.

## 실행 프로토콜

1. 경로 준비
   - `SETTINGS_PATH=~/.claude/settings.json`
   - `BACKUP_PATH=~/.claude/mst-statusline-backup.json`

2. 백업 확인
   - `BACKUP_PATH`가 없으면 아래 메시지를 출력하고 종료:
     - `백업 파일이 없어 원래 statusLine.command를 복원할 수 없습니다. (~/.claude/mst-statusline-backup.json)`

3. 백업에서 원래 `statusLine.command` 복원
   - `backup.statusLine.command` 문자열을 읽는다.
   - `~/.claude/settings.json`의 `statusLine`을 아래로 교체:
     - `type: "command"`
     - `command: {backup.statusLine.command}`
   - 기존 다른 필드는 모두 보존한다.
   - JSON 쓰기는 임시파일 + rename 방식으로 원자적 저장한다.

4. 완료 메시지 출력
   - `MST HUD 제거 완료`
   - `statusLine.command가 백업값으로 복원되었습니다`

## 예시 구현 명령 (Bash + Python)

```bash
python3 - <<'PY'
import json
import os
import sys

settings_path = os.path.expanduser("~/.claude/settings.json")
backup_path = os.path.expanduser("~/.claude/mst-statusline-backup.json")

if not os.path.exists(backup_path):
    print("백업 파일이 없어 원래 statusLine.command를 복원할 수 없습니다. (~/.claude/mst-statusline-backup.json)")
    sys.exit(0)

try:
    with open(backup_path, "r", encoding="utf-8") as f:
        backup = json.load(f)
except Exception:
    print("백업 파일 파싱 실패: ~/.claude/mst-statusline-backup.json")
    sys.exit(1)

status_line_backup = backup.get("statusLine") if isinstance(backup, dict) else None
command = status_line_backup.get("command") if isinstance(status_line_backup, dict) else None
if not isinstance(command, str) or not command.strip():
    print("백업 파일에 statusLine.command가 없습니다.")
    sys.exit(1)

try:
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}
if not isinstance(settings, dict):
    settings = {}

settings["statusLine"] = {"type": "command", "command": command}
tmp_settings = settings_path + ".tmp"
with open(tmp_settings, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp_settings, settings_path)

print("MST HUD 제거 완료")
print("statusLine.command가 백업값으로 복원되었습니다")
PY
```
