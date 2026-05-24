#!/usr/bin/env python3
"""Compatibility facade for sharded Gran Maestro runtime code."""
# Compatibility anchors: MST_STATE_PPID, MST_SNAPSHOT_SESSION_ID, sessionId remain diagnostic-only; phase gate is enforced by hooks/lib/pre_tool_use_fast.py.
from __future__ import annotations

from pathlib import Path

_MST_SHARD_DIR = Path(__file__).with_name('pre_tool_use_fast_shards')

def _mst_load_shards() -> None:
    for shard_path in sorted(_MST_SHARD_DIR.glob("part_*.py")):
        source = shard_path.read_text(encoding="utf-8")
        exec(compile(source, str(shard_path), "exec"), globals(), globals())

_mst_load_shards()
