"""Pytest harness compatibility for plugin-cache guarded hooks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _run_guarded_hooks_from_plugin_cache(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Rewrite test-only `bash <mst-hook>` calls to a plugin cache shaped path.

    T01 added a production guard that intentionally fail-opens when hooks are run
    outside Claude's plugin cache/marketplace directories. Many older regression
    tests still execute hook scripts from the source tree or from temporary
    project `hooks/` directories. This wrapper keeps those tests exercising the
    hook body without weakening the production guard.
    """
    wrapper_dir = tmp_path_factory.mktemp("hook-bash-wrapper")
    cache_root = tmp_path_factory.mktemp("hook-plugin-cache")
    wrapper_path = wrapper_dir / "bash"
    wrapper_path.write_text(
        f"""#!/bin/bash
set -euo pipefail

real_bash="/bin/bash"
cache_root={str(cache_root)!r}

if [ "$#" -gt 0 ]; then
  script="$1"
  base="$(basename "$script" 2>/dev/null || true)"
  case "$base" in
    mst-session-init.sh|mst-pre-tool-use.sh|mst-stop-hook.sh|mst-auto-chain-context.sh)
      script_dir="$(cd "$(dirname "$script")" && pwd)"
      case "$script_dir" in
        */.claude/plugins/cache/*/hooks|*/.claude/plugins/marketplaces/*/hooks)
          ;;
        *)
          # T09 relaxed guard 호환: lib/sha256.bash + parent .git/.gran-maestro 마커가 있으면
          # 정상 hooks 디렉토리이므로 redirection 없이 그대로 실행 (relaxed guard가 통과시킴).
          parent_dir="$(dirname "$script_dir")"
          if [ -f "$script_dir/lib/sha256.bash" ] \
             && {{ [ -e "$parent_dir/.git" ] || [ -d "$parent_dir/.gran-maestro" ]; }}; then
            : # passthrough; T09 relaxed guard accepts this path
          else
            safe_id="$(printf '%s' "$script_dir" | shasum -a 256 | awk '{{print $1}}')"
            target_root="$cache_root/$safe_id/.claude/plugins/cache/gran-maestro/mst/TEST"
            target_hooks="$target_root/hooks"
            mkdir -p "$target_hooks"
            cp "$script" "$target_hooks/$base"
            chmod +x "$target_hooks/$base"

            # T09: hooks/lib 동시 복사 — fast path python script 로드 보장
            if [ -d "$script_dir/lib" ]; then
              rm -rf "$target_hooks/lib"
              cp -R "$script_dir/lib" "$target_hooks/lib"
            fi

            source_scripts="$(cd "$script_dir/.." && pwd)/scripts"
            rm -rf "$target_root/scripts"
            if [ -d "$source_scripts" ]; then
              ln -s "$source_scripts" "$target_root/scripts"
            else
              mkdir -p "$target_root/scripts"
            fi

            shift
            exec "$real_bash" "$target_hooks/$base" "$@"
          fi
          ;;
      esac
      ;;
  esac
fi

exec "$real_bash" "$@"
""",
        encoding="utf-8",
    )
    wrapper_path.chmod(0o755)
    os.environ["PATH"] = f"{wrapper_dir}{os.pathsep}{os.environ.get('PATH', '')}"
