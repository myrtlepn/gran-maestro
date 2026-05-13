"""Compatibility facade for sharded Gran Maestro runtime code."""
from __future__ import annotations

from pathlib import Path

_MST_SHARD_DIR = Path(__file__).with_name('test_mst_on_cleanup_shards')

def _mst_load_shards() -> None:
    for shard_path in sorted(_MST_SHARD_DIR.glob("shard_*.py")):
        source = shard_path.read_text(encoding="utf-8")
        exec(compile(source, str(shard_path), "exec"), globals(), globals())

_mst_load_shards()
