from __future__ import annotations

import os


LLM_ENV_PREFIXES = ("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_")


def require_user_tty() -> None:
    if not os.isatty(0) or any(key.startswith(LLM_ENV_PREFIXES) for key in os.environ):
        raise SystemExit("TTY provenance required")
