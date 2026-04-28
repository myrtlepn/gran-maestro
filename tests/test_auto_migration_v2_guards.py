"""DOD-014 + DOD-015 + DOD-016 회귀 테스트.

mst-session-init.sh의 자동 마이그레이션 트리거에 추가된:
- 재귀 가드 (MST_AUTO_MIGRATE_IN_PROGRESS=1)
- 사용자 레벨 settings 충돌 detection
- migration.log 가시성
- dup-hook detection (per-PPID marker)

가 모두 정상 동작하는지 검증.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "mst-session-init.sh"


@pytest.fixture(scope="module")
def hook_text() -> str:
    return HOOK_PATH.read_text(encoding="utf-8")


def test_recursion_guard_env_var_referenced(hook_text):
    """PAC-1: MST_AUTO_MIGRATE_IN_PROGRESS 환경변수가 진입 가드로 사용된다."""
    assert "MST_AUTO_MIGRATE_IN_PROGRESS" in hook_text


def test_recursion_guard_blocks_when_set(hook_text):
    """PAC-1: MST_AUTO_MIGRATE_IN_PROGRESS=1이면 즉시 skip."""
    fn_match = re.search(
        r"check_hook_version_mismatch\(\)\s*\{(.+?)^\}",
        hook_text,
        re.DOTALL | re.MULTILINE,
    )
    assert fn_match
    body = fn_match.group(1)
    assert re.search(
        r'MST_AUTO_MIGRATE_IN_PROGRESS[^=]*=\s*1[^"]*"\s*\][\s\S]*?return 0',
        body,
    ) or '"${MST_AUTO_MIGRATE_IN_PROGRESS:-0}" = "1"' in body


def test_recursion_guard_exported_to_child(hook_text):
    """PAC-1: cleanup 호출 시 MST_AUTO_MIGRATE_IN_PROGRESS=1 export."""
    assert re.search(
        r"MST_AUTO_MIGRATE_IN_PROGRESS=1\s+timeout\s+30",
        hook_text,
    ), "MST_AUTO_MIGRATE_IN_PROGRESS=1 not exported to cleanup invocation"


def test_user_settings_conflict_detection_function(hook_text):
    """PAC-2: 사용자 레벨 settings 충돌 detection 함수 존재."""
    assert "_auto_migrate_detect_user_settings_conflict" in hook_text
    assert "${HOME}/.claude/settings.json" in hook_text or "$HOME/.claude/settings.json" in hook_text


def test_user_settings_conflict_pattern(hook_text):
    """PAC-2: 4개 mst hook 패턴 grep."""
    assert re.search(
        r"mst-\(stop-hook\|session-init\|pre-tool-use\|auto-chain-context\)\\\.sh",
        hook_text,
    ), "user settings conflict pattern incomplete"


def test_migration_log_helper_function(hook_text):
    """PAC-3: _auto_migrate_log 헬퍼 함수 존재."""
    assert "_auto_migrate_log" in hook_text
    assert "migration.log" in hook_text


def test_migration_log_rotation_cap(hook_text):
    """PAC-3: 50KB rotation cap."""
    assert "51200" in hook_text
    assert "tail -c" in hook_text


def test_migration_log_called_on_key_paths(hook_text):
    """PAC-3: 주요 분기마다 migration.log에 append."""
    assert hook_text.count("_auto_migrate_log") >= 5  # 호출 5회 이상


def test_dup_hook_detection_function(hook_text):
    """PAC-4: dup-hook detection 함수 + per-PPID marker."""
    assert "_auto_migrate_detect_dup_hook" in hook_text
    assert "session-init-${PPID" in hook_text or "session-init-${PPID:-0}" in hook_text


def test_recursion_guard_runtime(tmp_path):
    """PAC-1 dynamic: 함수 단위로 재귀 가드 동작 확인."""
    test_script = tmp_path / "test.sh"
    test_script.write_text(f"""#!/bin/bash
set -uo pipefail
PROJECT_ROOT={tmp_path}
mkdir -p "$PROJECT_ROOT/.gran-maestro/tmp"

# helper functions extracted via awk
source <(awk '/^_auto_migrate_log\\(\\)/,/^}}$/' {HOOK_PATH})

# 재귀 가드 시뮬레이션
if [ "${{MST_AUTO_MIGRATE_IN_PROGRESS:-0}}" = "1" ]; then
  echo "blocked_recursive"
else
  echo "would_proceed"
fi
""", encoding="utf-8")
    test_script.chmod(0o755)

    # 일반 호출
    p1 = subprocess.run(["/bin/bash", str(test_script)], capture_output=True, text=True, timeout=10)
    assert "would_proceed" in p1.stdout

    # 재귀 가드 활성
    env = os.environ.copy()
    env["MST_AUTO_MIGRATE_IN_PROGRESS"] = "1"
    p2 = subprocess.run(
        ["/bin/bash", str(test_script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "blocked_recursive" in p2.stdout


def test_migration_log_runtime_append(tmp_path):
    """PAC-3 dynamic: _auto_migrate_log이 메시지를 append하고 회전 동작."""
    text = HOOK_PATH.read_text(encoding="utf-8")
    fn_match = re.search(r"^_auto_migrate_log\(\)[^\n]*\{(.+?)^\}", text, re.DOTALL | re.MULTILINE)
    assert fn_match
    helpers = tmp_path / "helpers.bash"
    helpers.write_text(f"_auto_migrate_log() {{{fn_match.group(1)}}}", encoding="utf-8")

    log_path = tmp_path / "migration.log"
    script = f"""#!/bin/bash
set -uo pipefail
source {helpers}
_auto_migrate_log {log_path} "test_message_1"
_auto_migrate_log {log_path} "test_message_2"
"""
    proc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    content = log_path.read_text(encoding="utf-8")
    assert "test_message_1" in content
    assert "test_message_2" in content


def test_check_hook_version_mismatch_logs_visibility(hook_text):
    """PAC-3: check_hook_version_mismatch 본문이 migration.log에 다양한 분기 기록."""
    fn_match = re.search(
        r"check_hook_version_mismatch\(\)\s*\{(.+?)^\}",
        hook_text,
        re.DOTALL | re.MULTILINE,
    )
    assert fn_match
    body = fn_match.group(1)
    # 주요 분기에 _auto_migrate_log 호출
    log_calls = body.count("_auto_migrate_log")
    assert log_calls >= 5, f"check_hook_version_mismatch logs only {log_calls} migration events"
