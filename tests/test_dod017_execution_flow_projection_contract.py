"""Compatibility facade for sharded Gran Maestro runtime code."""
# Compatibility anchor: tests/test_dod017_execution_flow_projection_contract.py remains the contract facade.
from __future__ import annotations

from pathlib import Path

_MST_SHARD_DIR = Path(__file__).with_name('test_dod017_execution_flow_projection_contract_shards')

def _mst_load_shards() -> None:
    for shard_path in sorted(_MST_SHARD_DIR.glob("shard_*.py")):
        source = shard_path.read_text(encoding="utf-8")
        exec(compile(source, str(shard_path), "exec"), globals(), globals())

_mst_load_shards()
