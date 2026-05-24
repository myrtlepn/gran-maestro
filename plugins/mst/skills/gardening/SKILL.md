---
name: gardening
description: ".gran-maestro/의 stale plan/request/intent 리포트를 출력합니다. /mst:gardening 호출 시 mst.py gardening scan을 실행해 결과를 그대로 중계합니다."
user-invocable: true
argument-hint: "[--json]"
---

# maestro:gardening

가드닝 리포트 계산은 `scripts/mst.py`에 위임합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

1. `PROJECT_ROOT=$(pwd)`를 설정합니다.
2. `PLUGIN_ROOT`를 `{PROJECT_ROOT}`로 간주하고 아래 명령을 실행합니다.
   - 기본: `python3 {PLUGIN_ROOT}/scripts/mst.py gardening scan`
   - JSON: `python3 {PLUGIN_ROOT}/scripts/mst.py gardening scan --json`
3. 명령의 stdout을 그대로 출력합니다.
4. 명령 실패 시 stderr/exit code를 그대로 전달합니다. 별도 fallback은 수행하지 않습니다.

## 예시

```bash
/mst:gardening
/mst:gardening --json
```
