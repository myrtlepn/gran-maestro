"""DOD-012: dashboard localhost-only binding + sensitive-info README note regression."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_TS = PROJECT_ROOT / "src" / "config.ts"
SERVER_TS = PROJECT_ROOT / "src" / "server.ts"
README = PROJECT_ROOT / "README.md"


def test_host_constant_is_localhost():
    text = CONFIG_TS.read_text(encoding="utf-8")
    assert 'export const HOST = "127.0.0.1";' in text, (
        "src/config.ts must export HOST=\"127.0.0.1\" to guarantee localhost-only binding."
    )
    # Negative regression: no accidental 0.0.0.0 or :: bind constant.
    assert not re.search(r'export\s+const\s+HOST\s*=\s*"0\.0\.0\.0"', text)
    assert not re.search(r'export\s+const\s+HOST\s*=\s*"::"', text)


def test_server_uses_host_constant():
    text = SERVER_TS.read_text(encoding="utf-8")
    assert re.search(r"hostname\s*:\s*HOST", text), (
        "src/server.ts must bind via `hostname: HOST` using the HOST constant."
    )


def test_readme_has_sensitive_info_note():
    text = README.read_text(encoding="utf-8")
    assert "flow-detail.ndjson" in text, "README.md must mention flow-detail.ndjson in the sensitive-info note."
    assert ("민감" in text) or ("sensitive" in text.lower()), (
        "README.md must contain sensitive-info keyword (민감 or sensitive)."
    )
    assert ("localhost-only" in text) or ("127.0.0.1" in text), (
        "README.md must mention localhost-only binding or 127.0.0.1."
    )
