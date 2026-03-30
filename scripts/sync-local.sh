#!/usr/bin/env bash
set -euo pipefail

INSTALLED_JSON="$HOME/.claude/plugins/installed_plugins.json"

CACHE=$(python3 - "$INSTALLED_JSON" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
entries = d.get("plugins", {}).get("mst@gran-maestro") or []
path = (entries[0] if entries else {}).get("installPath", "")
if not path:
    raise SystemExit("installPath를 찾을 수 없습니다")
print(path.rstrip("/"))
PY
)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# hooks/ 원본 → .claude/hooks/ 프로젝트 복사본 동기화
if [ -d "$REPO_ROOT/hooks" ]; then
  mkdir -p "$REPO_ROOT/.claude/hooks"
  for f in "$REPO_ROOT"/hooks/mst-*.sh; do
    [ -f "$f" ] && cp "$f" "$REPO_ROOT/.claude/hooks/" && chmod +x "$REPO_ROOT/.claude/hooks/$(basename "$f")"
  done
  echo "✓ hooks/ → .claude/hooks/ 동기화 완료"
fi

RSYNC_OPTS=(
  -a --delete
  --exclude='.git'
  --exclude='node_modules'
  --exclude='.gran-maestro'
)

rsync "${RSYNC_OPTS[@]}" "$REPO_ROOT/" "$CACHE/"
echo "✓ Synced → $CACHE"

# 마켓플레이스 경로 동기화 (Claude가 세션 시작 시 스킬을 로드하는 경로)
MARKETPLACE="$HOME/.claude/plugins/marketplaces/gran-maestro"
if [ -d "$MARKETPLACE" ]; then
  rsync "${RSYNC_OPTS[@]}" "$REPO_ROOT/" "$MARKETPLACE/"
  echo "✓ Synced → $MARKETPLACE"
else
  echo "⚠ 마켓플레이스 경로 없음 (skip): $MARKETPLACE"
fi

echo "  Claude 세션을 재시작해야 변경사항이 반영됩니다."
