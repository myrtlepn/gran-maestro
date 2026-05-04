from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tests" / "hooks" / "test_sync_plugin_cache.sh"


def _run_sync_plugin_cache() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_sync_plugin_cache_integration() -> None:
    result = _run_sync_plugin_cache()
    assert result.returncode == 0, result.stdout + result.stderr


def main() -> int:
    result = _run_sync_plugin_cache()
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode != 0:
        return result.returncode
    print("PASS test_sync_plugin_cache_integration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
