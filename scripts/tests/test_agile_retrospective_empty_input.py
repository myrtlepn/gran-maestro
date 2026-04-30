from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.mst_cmds.agile import _parse_agile_failed_items


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-999"


def _run_mst(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _retrospective_path(cwd: Path, sprint: int = 0) -> Path:
    return cwd / ".gran-maestro" / "agile" / AGI_ID / "sprints" / f"S{sprint:02d}" / "retrospective.json"


def _retrospective_args(*, failed: str = "[]") -> list[str]:
    return [
        "agile",
        "retrospective",
        AGI_ID,
        "--sprint",
        "0",
        "--status",
        "done",
        "--succeeded",
        "ok",
        "--failed",
        failed,
        "--velocity-planned",
        "0",
        "--velocity-completed",
        "0",
        "--limitations",
        "lim",
        "--lessons",
        "lesson",
        "--direction",
        "direction",
        "--json",
    ]


def _without_arg(args: list[str], option: str) -> list[str]:
    index = args.index(option)
    return args[:index] + args[index + 2 :]


@pytest.fixture
def agi_session(tmp_path: Path) -> Path:
    agi_dir = tmp_path / ".gran-maestro" / "agile" / AGI_ID
    agi_dir.mkdir(parents=True)
    (agi_dir / "session.json").write_text(
        json.dumps({"id": AGI_ID, "agi_id": AGI_ID, "status": "active"}),
        encoding="utf-8",
    )
    return tmp_path


def test_parse_failed_items_legacy_paths() -> None:
    failed_item = {"tried_approach": "x", "failure_reason": "y"}

    assert _parse_agile_failed_items(json.dumps([failed_item])) == [failed_item]
    assert _parse_agile_failed_items(json.dumps(failed_item)) == [failed_item]
    assert _parse_agile_failed_items("[]") == []
    assert _parse_agile_failed_items(None) == []
    assert _parse_agile_failed_items([]) == []


def test_retrospective_cli_legacy_failed_inputs(agi_session: Path) -> None:
    cases = [
        ("[]", []),
        (
            '[{"tried_approach":"x","failure_reason":"y"}]',
            [{"tried_approach": "x", "failure_reason": "y"}],
        ),
        (
            '{"tried_approach":"x","failure_reason":"y"}',
            [{"tried_approach": "x", "failure_reason": "y"}],
        ),
    ]

    for failed_arg, expected_failed in cases:
        result = _run_mst(agi_session, *_retrospective_args(failed=failed_arg))

        assert result.returncode == 0, result.stderr
        payload = json.loads(_retrospective_path(agi_session).read_text(encoding="utf-8"))
        assert payload["failed"] == expected_failed


def test_retrospective_cli_required_args_kept(agi_session: Path) -> None:
    required_options = [
        "--lessons",
        "--direction",
        "--status",
        "--velocity-planned",
        "--velocity-completed",
    ]

    for option in required_options:
        result = _run_mst(agi_session, *_without_arg(_retrospective_args(), option))

        assert result.returncode == 2
        assert "required" in result.stderr


def test_parse_failed_items_empty_inputs() -> None:
    assert _parse_agile_failed_items("") == []
    assert _parse_agile_failed_items([""]) == []
    assert _parse_agile_failed_items([" "]) == []
    assert _parse_agile_failed_items([None]) == []
    assert _parse_agile_failed_items(None) == []
    assert _parse_agile_failed_items([]) == []


def test_retrospective_cli_empty_and_omitted(agi_session: Path) -> None:
    empty_args = _retrospective_args(failed="")
    empty_args[empty_args.index("--succeeded") + 1] = ""
    empty_args[empty_args.index("--limitations") + 1] = ""

    omitted_args = _retrospective_args()
    for option in ("--failed", "--limitations", "--succeeded"):
        omitted_args = _without_arg(omitted_args, option)

    for args in (empty_args, omitted_args):
        result = _run_mst(agi_session, *args)

        assert result.returncode == 0, result.stderr
        payload = json.loads(_retrospective_path(agi_session).read_text(encoding="utf-8"))
        assert payload["failed"] == []
        assert payload["succeeded"] == []
        assert payload["known_limitations"] == ""


def test_retrospective_md_known_limitations_fallback(agi_session: Path) -> None:
    args = _retrospective_args(failed="")
    args[args.index("--succeeded") + 1] = ""
    args[args.index("--limitations") + 1] = ""

    result = _run_mst(agi_session, *args)

    assert result.returncode == 0, result.stderr
    retrospective_md_path = _retrospective_path(agi_session).with_suffix(".md")
    retrospective_md = retrospective_md_path.read_text(encoding="utf-8")
    assert "- known_limitations: 없음" in retrospective_md


def test_retrospective_cli_whitespace_limitations(agi_session: Path) -> None:
    args = _retrospective_args()
    args[args.index("--limitations") + 1] = "   "

    result = _run_mst(agi_session, *args)

    assert result.returncode == 0, result.stderr
    payload = json.loads(_retrospective_path(agi_session).read_text(encoding="utf-8"))
    assert payload["known_limitations"] == ""

    retrospective_md_path = _retrospective_path(agi_session).with_suffix(".md")
    retrospective_md = retrospective_md_path.read_text(encoding="utf-8")
    assert "- known_limitations: 없음" in retrospective_md


def test_parse_failed_items_non_string_raises_value_error() -> None:
    for raw_values in ([1], [{"x": 1}], [[1, 2]]):
        with pytest.raises(ValueError):
            _parse_agile_failed_items(raw_values)
