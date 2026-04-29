from __future__ import annotations

import pytest

from scripts.mst_cmds import _provenance


def _clear_llm_env(monkeypatch) -> None:
    for key in list(_provenance.os.environ):
        if key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_")):
            monkeypatch.delenv(key, raising=False)


def test_requires_tty(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(_provenance.os, "isatty", lambda fd: False)

    with pytest.raises(SystemExit, match="TTY provenance required"):
        _provenance.require_user_tty()


def test_rejects_claude_code_prefix(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(_provenance.os, "isatty", lambda fd: fd == 0)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "llm")

    with pytest.raises(SystemExit, match="TTY provenance required"):
        _provenance.require_user_tty()


def test_rejects_claudecode_prefix(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(_provenance.os, "isatty", lambda fd: fd == 0)
    monkeypatch.setenv("CLAUDECODE_SESSION_ID", "llm")

    with pytest.raises(SystemExit, match="TTY provenance required"):
        _provenance.require_user_tty()


def test_rejects_claude_api_prefix(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(_provenance.os, "isatty", lambda fd: fd == 0)
    monkeypatch.setenv("CLAUDE_API_TOKEN", "llm")

    with pytest.raises(SystemExit, match="TTY provenance required"):
        _provenance.require_user_tty()


def test_accepts_user_tty_without_llm_env(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(_provenance.os, "isatty", lambda fd: fd == 0)

    _provenance.require_user_tty()
