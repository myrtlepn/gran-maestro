from __future__ import annotations

import subprocess

from scripts import bump


def test_generate_after_bump(monkeypatch) -> None:
    real_run = bump.subprocess.run

    def _run(args, **kwargs):
        if args[:2] == ["git", "add"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return real_run(args, **kwargs)

    monkeypatch.setattr(bump.subprocess, "run", _run)

    bump.run_state_schema_generate()

    assert bump.FILE_STATE_SCHEMA_PY.exists()
    assert bump.FILE_STATE_SCHEMA_JSON.exists()

    py_text = bump.FILE_STATE_SCHEMA_PY.read_text(encoding="utf-8")
    for key in ("TASK_STATUSES", "TERMINAL", "TRANSITIONS", "RECOVERY_ACTIONS"):
        assert key in py_text
