from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backup_state_file(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup_path = path.with_name(f"{path.stem}.backup-{timestamp}{path.suffix}")
    source = path.read_bytes()
    backup_path.write_bytes(source)
    if _sha256_bytes(source) != _sha256_bytes(backup_path.read_bytes()):
        raise RuntimeError(f"Backup checksum mismatch for {path}")
    return backup_path
