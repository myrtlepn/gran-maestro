"""DOD-010 + DOD-011 + DOD-012 회귀 테스트 — 자동 마이그레이션 트리거 G1~G4 가드.

mst-session-init.sh의 check_hook_version_mismatch가 mismatch 감지 시 자동으로
mst.py on cleanup --silent를 실행하되 G1 lock + G2 fail-open + G3 anti-loop
+ G4 환경 detection으로 안전성을 보장하는지 검증한다.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "mst-session-init.sh"


@pytest.fixture(scope="module")
def hook_text() -> str:
    return HOOK_PATH.read_text(encoding="utf-8")


def test_check_hook_version_mismatch_invokes_cleanup(hook_text):
    """PAC-1: mismatch 감지 → mst.py on cleanup --silent 자동 실행."""
    assert "mst.py" in hook_text or "scripts/mst.py" in hook_text
    assert "on cleanup" in hook_text
    assert "--silent" in hook_text


def test_check_hook_version_mismatch_uses_timeout(hook_text):
    """PAC-1 + G2: timeout 30 으로 fail-open 보장."""
    assert re.search(r"timeout\s+30\b", hook_text), "timeout 30 wrapper missing"


def test_g1_lock_acquisition(hook_text):
    """PAC-2: migration.lock 파일 + acquire/release 패턴."""
    assert "migration.lock" in hook_text
    assert "_auto_migrate_acquire_lock" in hook_text
    assert "_auto_migrate_release_lock" in hook_text


def test_g1_stale_lock_invalidation(hook_text):
    """PAC-2: stale lock(>120s) 자동 무효화 로직 존재."""
    assert "stale_secs" in hook_text
    # 호출 측에서 120 또는 환경별 값을 stale 임계로 전달해야 한다
    assert re.search(r"_auto_migrate_acquire_lock\s+\"?\$?[a-z_]*lock[a-z_]*\"?\s+\d+", hook_text), \
        "lock acquire call missing stale_secs argument"


def test_g2_fail_open_returns_zero(hook_text):
    """PAC-3: 자동 트리거가 실패해도 hook 본문은 return 0 / exit 0 보장."""
    # check_hook_version_mismatch 함수 본문에 timeout 실패 분기에서 return 0 / exit 0 / continue 형태로 차단 없음 보장
    fn_match = re.search(
        r"check_hook_version_mismatch\(\)\s*\{(.+?)^\}",
        hook_text,
        re.DOTALL | re.MULTILINE,
    )
    assert fn_match, "check_hook_version_mismatch function not found"
    body = fn_match.group(1)
    # 실패 분기에 exit 1 또는 return 1 같은 차단 패턴이 없어야 한다
    assert "exit 1" not in body, "fail-open broken: exit 1 found in body"
    # 함수가 마지막에 return 0으로 끝나야 한다
    assert re.search(r"return 0\s*$", body.strip()), "function should end with return 0"


def test_g3_anti_loop_failed_marker(hook_text):
    """PAC-4: migration-failed marker + TTL 검사."""
    assert "migration-failed" in hook_text
    assert "_auto_migrate_failed_recently" in hook_text
    assert "_auto_migrate_mark_failed" in hook_text
    assert "_auto_migrate_clear_failed" in hook_text
    # TTL 600s 적용
    assert re.search(r"failed_recently[^\d]+\d+\s+600", hook_text) or "600" in hook_text


def test_g4_env_detection_claude_disable(hook_text):
    """PAC-5: MST_DISABLE_AUTO_MIGRATE=1 환경변수로 자동 트리거 skip."""
    assert "MST_DISABLE_AUTO_MIGRATE" in hook_text


def test_g4_env_detection_timeout_missing(hook_text):
    """PAC-5: timeout 명령 부재 시 skip."""
    assert re.search(r"command -v\s+timeout", hook_text), "timeout command-v guard missing"


def test_no_trigger_when_versions_match(tmp_path, hook_text):
    """버전이 일치하면 자동 트리거 자체가 발동하지 않아야 한다 (early return).

    static 검증: 함수 본문 시작에서 plugin_version=hook_version이면 return 0.
    """
    fn_match = re.search(
        r"check_hook_version_mismatch\(\)\s*\{(.+?)^\}",
        hook_text,
        re.DOTALL | re.MULTILINE,
    )
    assert fn_match
    body = fn_match.group(1)
    # plugin_version과 hook_version이 같으면 일찍 return 0
    assert re.search(r'\[\s*"\$plugin_version"\s*=\s*"\$hook_version"\s*\][\s\S]*?return 0', body) or \
           '"$plugin_version" = "$hook_version"' in body


def test_g3_marker_helpers_defined(hook_text):
    """PAC-4 보조: marker helper 함수 4개 모두 정의."""
    for fn in ["_auto_migrate_acquire_lock", "_auto_migrate_release_lock",
               "_auto_migrate_failed_recently", "_auto_migrate_mark_failed",
               "_auto_migrate_clear_failed"]:
        assert re.search(rf"^{fn}\(\)\s*\{{", hook_text, re.MULTILINE), \
            f"helper {fn} not defined"


def _extract_helpers_to_tempfile(hook_path: Path, tmp_path: Path) -> Path:
    """5개 _auto_migrate_* 헬퍼 함수만 추출하여 tempfile 작성 (source 가능)."""
    text = hook_path.read_text(encoding="utf-8")
    helpers: list = []
    for fn_name in [
        "_auto_migrate_acquire_lock",
        "_auto_migrate_release_lock",
        "_auto_migrate_failed_recently",
        "_auto_migrate_mark_failed",
        "_auto_migrate_clear_failed",
    ]:
        match = re.search(
            rf"^{fn_name}\(\)[^\n]*\{{(.+?)^\}}",
            text,
            re.DOTALL | re.MULTILINE,
        )
        assert match, f"{fn_name} not extractable"
        helpers.append(f"{fn_name}() {{{match.group(1)}}}")
    out = tmp_path / "helpers.bash"
    out.write_text("\n".join(helpers), encoding="utf-8")
    return out


def test_lock_acquisition_runtime(tmp_path):
    """G1 lock 동작을 함수 단위로 동적 검증."""
    import subprocess
    helpers = _extract_helpers_to_tempfile(HOOK_PATH, tmp_path)
    lock_path = tmp_path / "migration.lock"
    script = f"""
set -uo pipefail
source {helpers}
_auto_migrate_acquire_lock {lock_path} 120 && echo "acquired1"
_auto_migrate_acquire_lock {lock_path} 120 || echo "blocked2"
_auto_migrate_release_lock {lock_path}
_auto_migrate_acquire_lock {lock_path} 120 && echo "acquired3"
_auto_migrate_release_lock {lock_path}
"""
    proc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "acquired1" in proc.stdout
    assert "blocked2" in proc.stdout
    assert "acquired3" in proc.stdout


def test_marker_failed_recently_runtime(tmp_path):
    """G3 anti-loop marker TTL 동작 동적 검증."""
    import subprocess
    helpers = _extract_helpers_to_tempfile(HOOK_PATH, tmp_path)
    marker = tmp_path / "migration-failed"
    script = f"""
set -uo pipefail
source {helpers}
_auto_migrate_mark_failed {marker}
_auto_migrate_failed_recently {marker} 600 && echo "still_failed"
_auto_migrate_clear_failed {marker}
_auto_migrate_failed_recently {marker} 600 || echo "cleared"
"""
    proc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "still_failed" in proc.stdout
    assert "cleared" in proc.stdout
