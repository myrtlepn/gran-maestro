"""Compatibility facade for sharded Gran Maestro runtime code."""
# Compatibility anchors: _collect_migration_targets handles legacy PPID state directories; state migrate: PPID -> session_id migration entry point.
from __future__ import annotations

from pathlib import Path

_MST_SHARD_DIR = Path(__file__).with_name('state_shards')

def _mst_load_shards() -> None:
    for shard_path in sorted(_MST_SHARD_DIR.glob("part_*.py")):
        source = shard_path.read_text(encoding="utf-8")
        exec(compile(source, str(shard_path), "exec"), globals(), globals())

_mst_load_shards()
