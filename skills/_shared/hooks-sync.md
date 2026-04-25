### Hooks 자동 동기화

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py hooks sync --silent || true
```

플러그인 버전이 `.claude/hooks/.mst-hook-version`과 다르면 hook 파일을 자동 동기화합니다. 동일 버전이면 no-op(수 ms). 실패해도 워크플로우를 차단하지 않습니다.
