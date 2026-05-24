---
name: hud-uninstall
description: "MST HUD statusline 래퍼를 제거하고 백업된 원래 statusLine.command를 복원합니다. 사용자가 'HUD 제거', 'statusline 복원', '/mst:hud-uninstall'을 호출할 때 사용."
user-invocable: true
argument-hint: ""
---

# maestro:hud-uninstall

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
