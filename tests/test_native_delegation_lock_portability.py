from scripts.mst_cmds import native_delegation


def test_native_delegation_imports_without_posix_fcntl() -> None:
    """The native delegation module must be importable on Windows."""
    assert native_delegation._task_lock is not None
