"""4개 hook 스크립트가 plugin cache 경로 외부에서 실행되면 silent fail-open되는지 검증.

T01 spec AC-003 검증.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_NAMES = [
    "mst-session-init.sh",
    "mst-pre-tool-use.sh",
    "mst-stop-hook.sh",
    "mst-auto-chain-context.sh",
]


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_fail_open_outside_plugin_cache(hook_name):
    """hook을 임시 디렉토리(/tmp/...)로 복사해 실행 시 silent fail-open 보장."""
    src = REPO_ROOT / "hooks" / hook_name
    assert src.exists(), f"source hook missing: {src}"

    with tempfile.TemporaryDirectory() as td:
        # plugin cache가 아닌 임시 디렉토리/hooks/{name} 형태로 복사
        target_dir = Path(td) / "hooks"
        target_dir.mkdir()
        target = target_dir / hook_name
        shutil.copy2(src, target)
        os.chmod(target, 0o755)

        # stdin은 빈 상태로 실행 (auto-chain-context는 stdin 필요)
        proc = subprocess.run(
            ["/bin/bash", str(target)],
            input="",
            capture_output=True,
            text=True,
            timeout=15,
        )

        # fail-open: exit 0
        assert proc.returncode == 0, (
            f"{hook_name} did not fail-open outside plugin cache. "
            f"exit={proc.returncode}, stderr={proc.stderr[:500]}"
        )
        # stderr 경고 1줄 이상
        assert "[mst-hook] warning" in proc.stderr, (
            f"{hook_name} did not emit fail-open warning. stderr={proc.stderr[:500]}"
        )


def test_hooks_json_manifest_uses_plugin_root_variable():
    """T01 AC-001 회귀 검증: hooks/hooks.json이 4개 이벤트를 ${CLAUDE_PLUGIN_ROOT}로 등록."""
    manifest_path = REPO_ROOT / "hooks" / "hooks.json"
    assert manifest_path.exists(), f"hooks.json missing: {manifest_path}"
    data = json.loads(manifest_path.read_text())
    expected_events = {"SessionStart", "PreToolUse", "Stop", "UserPromptSubmit"}
    assert set(data["hooks"].keys()) == expected_events
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "Skill"
    for event_entries in data["hooks"].values():
        for entry in event_entries:
            for hook in entry["hooks"]:
                assert hook["type"] == "command"
                assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
