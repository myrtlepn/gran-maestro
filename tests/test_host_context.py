from __future__ import annotations

from scripts.mst_cmds.host import build_host_context


def test_codex_thread_id_identifies_codex_host(monkeypatch) -> None:
    monkeypatch.delenv("MST_HOST", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-123")

    context = build_host_context()

    assert context["host"] == "codex"
    assert context["adapter"]["uses_queue_supervisor"] is True
    assert context["adapter"]["uses_claude_hooks"] is False
