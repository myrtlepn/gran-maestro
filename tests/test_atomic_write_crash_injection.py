"""DOD-004 T6: _skill_state._atomic_write_json crash-injection regression tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._skill_state import _atomic_write_json  # noqa: E402


def _tmp_paths_for(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_replace_failure_preserves_original(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"x": 1}, ensure_ascii=False), encoding="utf-8")

    import pytest

    with patch("scripts._skill_state.os.replace", side_effect=OSError("simulated crash")):
        with pytest.raises(OSError):
            _atomic_write_json(path, {"x": 2})

    preserved = json.loads(path.read_text(encoding="utf-8"))
    assert preserved == {"x": 1}
    assert _tmp_paths_for(path) == []


def test_write_sequence_fsync_before_replace(tmp_path):
    path = tmp_path / "snapshot.json"
    call_order: list[str] = []

    real_fsync = os.fsync
    real_replace = os.replace

    def wrapped_fsync(fd):
        call_order.append("fsync")
        return real_fsync(fd)

    def wrapped_replace(src, dst):
        call_order.append("replace")
        return real_replace(src, dst)

    with patch("scripts._skill_state.os.fsync", side_effect=wrapped_fsync), \
         patch("scripts._skill_state.os.replace", side_effect=wrapped_replace):
        _atomic_write_json(path, {"x": 1})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}

    # 최소 시퀀스: fsync(file) → replace. O_DIRECTORY 플랫폼이면 뒤에 fsync(dir) 추가.
    assert call_order[0] == "fsync"
    assert call_order[1] == "replace"
    if hasattr(os, "O_DIRECTORY"):
        assert call_order[2] == "fsync"
        assert len(call_order) == 3
    else:
        assert len(call_order) == 2


def test_fsync_failure_during_write_no_partial(tmp_path):
    path = tmp_path / "snapshot.json"
    assert not path.exists()

    import pytest

    with patch("scripts._skill_state.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            _atomic_write_json(path, {"x": 1})

    # 원본 미존재 상태를 보존 (replace 미도달)
    assert not path.exists()
    # tmp 파일도 cleanup
    assert _tmp_paths_for(path) == []
