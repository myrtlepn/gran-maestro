import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_agile_session(workspace: Path, agi_id: str) -> None:
    session_dir = workspace / ".gran-maestro" / "agile" / agi_id
    (session_dir / "sprints").mkdir(parents=True, exist_ok=True)
    (session_dir / "index").mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"id": agi_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_dispatch_result_help(tmp_path):
    """--help가 exit 0으로 사용법을 표시한다."""
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    result = _run_mst(workspace, "agile", "dispatch-result", "--help")

    assert result.returncode == 0
    assert "dispatch-result" in (result.stdout + result.stderr)


def test_dispatch_result_creates_file(tmp_path):
    """dispatch-result 호출 시 파일 생성 및 필수 필드 11개 존재."""
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    agi_id = "AGI-101"
    _seed_agile_session(workspace, agi_id)

    result = _run_mst(
        workspace,
        "agile",
        "dispatch-result",
        agi_id,
        "--sprint",
        "1",
        "--status",
        "success",
        "--exit-code",
        "0",
        "--pln",
        "PLN-TEST",
        "--req",
        "REQ-TEST",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    output_path = workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / "S01" / "dispatch-result.json"
    assert output_path.exists()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    required = [
        "agi_id",
        "sprint",
        "status",
        "pln_id",
        "req_id",
        "commit_sha",
        "sprint_kind",
        "exit_code",
        "failure_reason",
        "result_recorded",
        "retrospective_recorded",
    ]
    for key in required:
        assert key in data, f"missing {key}"


def test_dispatch_result_rejects_invalid_status(tmp_path):
    """--status 허용값 이외 값이면 argparse가 거부한다."""
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    result = _run_mst(
        workspace,
        "agile",
        "dispatch-result",
        "AGI-101",
        "--sprint",
        "1",
        "--status",
        "bogus",
        "--exit-code",
        "0",
    )

    assert result.returncode != 0
