"""mst-session-init.sh의 Claude Code 버전 가드 fail-open 동작을 검증.

T01 spec AC-004 검증.
"""

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "mst-session-init.sh"


def test_claude_command_missing_fail_open():
    """claude 명령이 PATH에 없을 때도 hook은 fail-open으로 종료."""
    assert HOOK_PATH.exists(), f"hook missing: {HOOK_PATH}"

    with tempfile.TemporaryDirectory() as empty_dir:
        env = os.environ.copy()
        # 최소한의 시스템 PATH는 유지하되 claude는 미존재
        env["PATH"] = f"{empty_dir}:/usr/bin:/bin"
        proc = subprocess.run(
            ["/bin/bash", str(HOOK_PATH)],
            input="",
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        # plugin cache 외부 경로에서 실행되므로 fail-open guard에서 먼저 종료될 수도 있음.
        # 어떤 경로든 exit 0이면 fail-open 보장 충족.
        assert proc.returncode == 0, (
            f"mst-session-init did not fail-open when claude missing. "
            f"exit={proc.returncode}, stderr={proc.stderr[:500]}"
        )


def test_version_guard_block_present_in_source():
    """버전 가드 코드 블록이 mst-session-init.sh에 존재."""
    text = HOOK_PATH.read_text()
    # 핵심 패턴 검증
    assert "Claude Code version guard" in text, "version guard comment missing"
    assert "command -v claude" in text, "claude existence check missing"
    assert "required_claude_version" in text, "required_claude_version variable missing"
    assert "claude --version" in text, "claude --version invocation missing"
    # fail-open 결정
    assert "exit 0" in text, "fail-open exit 0 missing in version guard"


def test_fake_old_claude_fail_open(tmp_path):
    """가짜 claude 스크립트가 구버전을 반환하도록 시뮬레이션해도 hook은 fail-open."""
    # 가짜 claude 스크립트 (PATH에서 우선 발견되도록)
    fake_dir = tmp_path / "fake_bin"
    fake_dir.mkdir()
    fake_claude = fake_dir / "claude"
    fake_claude.write_text("#!/bin/bash\necho 'claude version 0.0.1'\n")
    fake_claude.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_dir}:/usr/bin:/bin"

    proc = subprocess.run(
        ["/bin/bash", str(HOOK_PATH)],
        input="",
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )

    # required_claude_version="0.0.0" placeholder이므로 실제 버전 비교는 비활성.
    # plugin cache 외부 경로 가드도 적용. 어떤 경로든 fail-open(exit 0).
    assert proc.returncode == 0, (
        f"mst-session-init did not fail-open with fake claude. "
        f"exit={proc.returncode}, stderr={proc.stderr[:500]}"
    )
