---
name: hud-install
description: "사용자가 $mst:hud-install 또는 /mst:hud-install을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 hud-install 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: ""
---

# maestro:hud-install

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
