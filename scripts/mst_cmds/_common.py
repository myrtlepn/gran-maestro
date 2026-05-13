"""Compatibility facade for sharded Gran Maestro runtime code."""
# Compatibility anchors: legacy_session_diagnostics, MST_STATE_PPID remain diagnostic-only.
from __future__ import annotations

from pathlib import Path

_MST_SHARD_DIR = Path(__file__).with_name('_common_shards')

def _mst_load_shards() -> None:
    for shard_path in sorted(_MST_SHARD_DIR.glob("part_*.py")):
        source = shard_path.read_text(encoding="utf-8")
        exec(compile(source, str(shard_path), "exec"), globals(), globals())

_mst_load_shards()
