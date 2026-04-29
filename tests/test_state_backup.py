from __future__ import annotations

import hashlib
import re
from pathlib import Path

from scripts._state_backup import backup_state_file


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_backup_preserves_content(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text('{"status":"done"}\n', encoding="utf-8")

    backup = backup_state_file(source)

    assert backup.exists()
    assert ".backup-" in backup.name
    assert _sha256(source) == _sha256(backup)


def test_backup_path_format(tmp_path: Path) -> None:
    source = tmp_path / "request.json"
    source.write_text('{"status":"pending"}\n', encoding="utf-8")

    backup = backup_state_file(source)

    pattern = re.compile(r"^request\.backup-\d{8}T\d{6}\.json$")
    assert pattern.match(backup.name)
