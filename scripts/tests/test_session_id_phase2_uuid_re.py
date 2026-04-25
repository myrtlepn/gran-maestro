from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
for candidate in (PROJECT_ROOT, SCRIPTS_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from scripts._snapshot_probe import UUID_RE  # noqa: E402


HOOK = PROJECT_ROOT / "hooks" / "mst-stop-hook.sh"


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("aa11bb22-cc33-4dd4-8eee-ffff00001111", True),
        ("AA11BB22-CC33-4DD4-8EEE-FFFF00001111", False),
        ("aa11bb22-cc33-1dd4-8eee-ffff00001111", False),
        ("aa11bb22-cc33-3dd4-8eee-ffff00001111", False),
        ("aa11bb22-cc33-5dd4-8eee-ffff00001111", False),
        ("aa11bb22-cc33-4dd4-cccc-ffff00001111", False),
    ],
)
def test_snapshot_probe_uuid_re_strict_v4(session_id: str, expected: bool) -> None:
    assert bool(UUID_RE.match(session_id)) is expected


def test_hook_uuid_re_matches_snapshot_probe() -> None:
    hook_text = HOOK.read_text(encoding="utf-8")
    match = re.search(
        r"UUID_RE = re\.compile\(\n\s+r\"(?P<pattern>[^\"]+)\"\n\)",
        hook_text,
    )

    assert match is not None
    assert match.group("pattern") == UUID_RE.pattern
