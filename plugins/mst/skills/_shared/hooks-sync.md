### Hooks sync legacy repair

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py hooks sync --silent || true
```

`hooks sync`는 plugin core canonical runtime의 automatic canonical setup이 아니라, project legacy / source-dev helper 사본을 명시적으로 repair하는 source-dev 보조 명령입니다. 일반 프로젝트의 canonical runtime은 plugin manifest `hooks/hooks.json`과 `${CLAUDE_PLUGIN_ROOT}/hooks/...` command이며, `.claude/hooks/.mst-hook-version` 기반 동기화는 not canonical legacy/source-dev repair 경로로만 다룹니다. 동일 버전이면 no-op(수 ms). 실패해도 워크플로우를 차단하지 않습니다.
