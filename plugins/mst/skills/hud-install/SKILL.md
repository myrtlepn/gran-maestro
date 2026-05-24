---
name: hud-install
description: "MST HUD statusline 래퍼를 설치합니다. 기존 statusLine.command를 백업하고 MST 래퍼로 교체합니다. 사용자가 'HUD 설치', 'statusline 설치', '/mst:hud-install'을 호출할 때 사용."
user-invocable: true
argument-hint: ""
---

# maestro:hud-install

Claude Code status line을 MST HUD 래퍼(`scripts/mst-statusline.sh`)로 교체합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 절대경로입니다.

1. 경로 준비
   - `SETTINGS_PATH=~/.claude/settings.json`
   - `BACKUP_PATH=~/.claude/mst-statusline-backup.json`
   - `WRAPPER_PATH={PLUGIN_ROOT}/scripts/mst-statusline.sh`
   - `WRAPPER_COMMAND=bash "{WRAPPER_PATH}"`

2. `~/.claude/settings.json`의 현재 `statusLine.command`를 백업
   - 백업 포맷:
     ```json
     {
       "statusLine": {
         "type": "command",
         "command": "..."
       }
     }
     ```
   - 이미 `statusLine.command`가 MST 래퍼(`mst-statusline.sh`)이고 백업 파일이 존재하면 백업 갱신은 생략한다.

3. `~/.claude/settings.json` 업데이트
   - `statusLine.type = "command"`
   - `statusLine.command = WRAPPER_COMMAND`
   - 기존 다른 필드(`env`, `permissions`, `hooks`, `enabledPlugins` 등)는 모두 보존한다.
   - JSON 쓰기는 임시파일 + rename 방식으로 원자적 저장한다.

4. 완료 메시지 출력
   - `MST HUD 설치 완료`
   - `statusLine.command -> bash "{WRAPPER_PATH}"`
   - `backup -> ~/.claude/mst-statusline-backup.json`
   - 모델 정보가 있으면 MST 라인에 prefix가 표시됨 (예: `[Claude/Opus] MST idle`)

## 예시 구현 명령 (Bash + Python)

```bash
python3 - <<'PY'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
backup_path = os.path.expanduser("~/.claude/mst-statusline-backup.json")
plugin_root = "{PLUGIN_ROOT}"
wrapper_path = os.path.join(plugin_root, "scripts", "mst-statusline.sh")
wrapper_command = f'bash "{wrapper_path}"'
default_hud_command = (
    "bash -c 'plugin_dir=$(ls -d \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}\"/plugins/cache/claude-hud/claude-hud/*/ 2>/dev/null "
    "| sort -t/ -k$(echo \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache/claude-hud/claude-hud/\" | tr \"/\" \"\\n\" | wc -l)n | tail -1); "
    "exec \"/opt/homebrew/bin/node\" \"${plugin_dir}/dist/index.js\"'"
)

try:
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}
if not isinstance(settings, dict):
    settings = {}

status_line = settings.get("statusLine")
if not isinstance(status_line, dict):
    status_line = {}

current_command = status_line.get("command")
is_wrapper = isinstance(current_command, str) and "mst-statusline.sh" in current_command
backup_exists = os.path.exists(backup_path)
if not (is_wrapper and backup_exists):
    backup_command = current_command if isinstance(current_command, str) else ""
    if is_wrapper and not backup_exists:
        backup_command = default_hud_command
    backup = {
        "statusLine": {
            "type": status_line.get("type", "command"),
            "command": backup_command
        }
    }
    tmp_backup = backup_path + ".tmp"
    with open(tmp_backup, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_backup, backup_path)

settings["statusLine"] = {"type": "command", "command": wrapper_command}
tmp_settings = settings_path + ".tmp"
with open(tmp_settings, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp_settings, settings_path)

print("MST HUD 설치 완료")
print(f"statusLine.command -> {wrapper_command}")
print(f"backup -> {backup_path}")
PY
```
