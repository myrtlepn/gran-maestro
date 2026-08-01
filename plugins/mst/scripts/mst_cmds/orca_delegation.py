from __future__ import annotations

"""Local Orca CLI launch-surface support for protected MST delegation.

This module owns only Orca executable selection and JSON terminal/worktree
commands. Provider execution and lifecycle evidence stay in
``native_delegation``.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ORCA_COMMAND_TIMEOUT_SECONDS = 15
ORCA_CREATE_TIMEOUT_SECONDS = 30


class OrcaCommandError(RuntimeError):
    """A side-effect-free Orca CLI command failed or returned invalid data."""


class OrcaPreflightError(OrcaCommandError):
    """The selected local Orca runtime/worktree is not ready."""


class OrcaCreateUncertain(OrcaCommandError):
    """Terminal creation was invoked but its outcome is not authoritative."""


def _inside_orca(env: Mapping[str, str]) -> bool:
    return any(
        str(env.get(key) or "").strip()
        for key in (
            "ORCA_WORKTREE_ID",
            "ORCA_WORKTREE_PATH",
            "ORCA_MANAGED_TERMINAL",
            "ORCA_SESSION_ID",
        )
    )


def resolve_orca_cli(
    *,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    """Select one Orca executable command without fallback after selection."""

    source = os.environ if env is None else env
    explicit = str(source.get("ORCA_CLI_COMMAND") or "").strip()
    if explicit:
        try:
            selected = shlex.split(explicit)
        except ValueError as exc:
            raise OrcaCommandError(f"invalid ORCA_CLI_COMMAND: {exc}") from exc
        if not selected:
            raise OrcaCommandError("ORCA_CLI_COMMAND did not select an executable")
    elif str(source.get("ORCA_DEV_REPO_ROOT") or "").strip():
        selected = ["orca-dev"]
    elif str(platform_name or sys.platform).lower().startswith("linux") and not _inside_orca(source):
        selected = ["orca-ide"]
    else:
        selected = ["orca"]

    executable = selected[0]
    if os.path.sep in executable or (os.path.altsep and os.path.altsep in executable):
        candidate = Path(executable).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise OrcaCommandError(f"selected Orca executable is unavailable: {executable}")
        resolved = str(candidate.resolve())
    else:
        resolved = which(executable) or ""
        if not resolved:
            raise OrcaCommandError(f"selected Orca executable is unavailable: {executable}")
    return (resolved, *(str(item) for item in selected[1:]))


def _nested_values(payload: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for current_key, value in payload.items():
            if str(current_key) == key:
                values.append(value)
            values.extend(_nested_values(value, key))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_nested_values(value, key))
    return values


def _status_ready(payload: dict[str, Any]) -> bool:
    for key in ("ready", "reachable", "connected", "running"):
        values = _nested_values(payload, key)
        if any(value is False for value in values):
            return False
    status_values = [
        str(value).strip().lower()
        for value in _nested_values(payload, "status")
        if isinstance(value, str) and value.strip()
    ]
    if any(value in {"offline", "stopped", "starting", "unready", "unreachable", "error"} for value in status_values):
        return False
    return True


def _status_local(payload: dict[str, Any]) -> bool:
    result = payload.get("result")
    if isinstance(result, dict):
        app = result.get("app")
        runtime = result.get("runtime")
        # Orca's remote status intentionally reports a reachable runtime while
        # app.running is false on the CLI caller's machine. Reject that shape
        # before the generic readiness check so V1 stays local-only.
        if (
            isinstance(app, dict)
            and app.get("running") is False
            and isinstance(runtime, dict)
            and runtime.get("reachable") is True
        ):
            return False
    if any(value is True for value in _nested_values(payload, "remote")):
        return False
    scope_values: list[str] = []
    for key in ("scope", "mode", "kind", "type", "runtimeScope", "runtime_scope"):
        scope_values.extend(
            str(value).strip().lower()
            for value in _nested_values(payload, key)
            if isinstance(value, str) and value.strip()
        )
    if any(value in {"remote", "federated", "cloud"} for value in scope_values):
        return False
    # The installed V1 CLI talks to its local desktop bridge. An explicit
    # remote/federated marker fails closed; its absence is the local contract.
    return True


def _extract_worktree_path(payload: Any) -> str | None:
    preferred = ("path", "worktreePath", "worktree_path", "rootPath", "root_path")
    for key in preferred:
        for value in _nested_values(payload, key):
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _unwrap_result(payload: Any) -> Any:
    if (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and isinstance(payload.get("result"), (dict, list))
    ):
        return payload["result"]
    return payload


def _extract_terminal_handle(payload: Any) -> str | None:
    payload = _unwrap_result(payload)
    if isinstance(payload, dict):
        terminal = payload.get("terminal")
        if isinstance(terminal, dict):
            for key in ("handle", "terminalHandle", "terminal_handle", "id"):
                value = terminal.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("handle", "terminalHandle", "terminal_handle"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _terminal_entries(payload: Any) -> list[dict[str, Any]]:
    payload = _unwrap_result(payload)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("terminals", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    terminal = payload.get("terminal")
    return [dict(terminal)] if isinstance(terminal, dict) else []


class OrcaClient:
    def __init__(
        self,
        command_argv: Sequence[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.command_argv = tuple(command_argv or resolve_orca_cli(env=env))
        if not self.command_argv:
            raise OrcaCommandError("Orca executable command is empty")
        self._env = dict(os.environ if env is None else env)
        self._runner = runner

    def _redact_wrapper_detail(self, detail: Any) -> str:
        redacted = str(detail or "")
        for argument in self.command_argv[1:]:
            value = str(argument or "")
            if value:
                variants = {
                    value,
                    repr(value)[1:-1],
                    json.dumps(value, ensure_ascii=False)[1:-1],
                    json.dumps(value, ensure_ascii=True)[1:-1],
                    shlex.quote(value),
                }
                for variant in sorted(variants, key=len, reverse=True):
                    if variant:
                        redacted = redacted.replace(
                            variant, "[REDACTED_ORCA_CLI_ARG]"
                        )
        return redacted

    def _run_json(
        self,
        arguments: Sequence[str],
        *,
        timeout: int = ORCA_COMMAND_TIMEOUT_SECONDS,
        create_invoked: bool = False,
    ) -> dict[str, Any] | list[Any]:
        argv = [*self.command_argv, *(str(item) for item in arguments)]
        try:
            result = self._runner(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type("Orca CLI invocation timed out") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type(
                f"Orca CLI invocation failed ({type(exc).__name__})"
            ) from exc
        if result.returncode != 0:
            tail = self._redact_wrapper_detail(
                (result.stderr or result.stdout or "").strip()
            )[-512:]
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type(
                f"Orca CLI exited {result.returncode}" + (f": {tail}" if tail else "")
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type("Orca CLI returned invalid JSON") from exc
        if not isinstance(payload, (dict, list)):
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type("Orca CLI JSON response must be an object or list")
        if isinstance(payload, dict) and (
            payload.get("ok") is False
            or payload.get("success") is False
            or str(payload.get("status") or "").strip().lower() == "error"
        ):
            detail = self._redact_wrapper_detail(
                payload.get("error") or payload.get("message") or "structured error"
            )
            error_type = OrcaCreateUncertain if create_invoked else OrcaCommandError
            raise error_type(f"Orca CLI returned an error: {detail}")
        return payload

    def preflight(self, worktree_dir: Path | str) -> dict[str, Any]:
        worktree = Path(worktree_dir).resolve(strict=False)
        if not worktree.is_dir():
            raise OrcaPreflightError(f"MST worktree does not exist: {worktree}")
        try:
            status = self._run_json(["status", "--json"])
        except OrcaCommandError as exc:
            raise OrcaPreflightError(str(exc)) from exc
        if not isinstance(status, dict):
            raise OrcaPreflightError("local Orca runtime is not ready")
        if not _status_local(status):
            raise OrcaPreflightError("remote or federated Orca runtimes are unsupported")
        if not _status_ready(status):
            raise OrcaPreflightError("local Orca runtime is not ready")

        selector = f"path:{worktree}"
        try:
            shown = self._run_json(
                ["worktree", "show", "--worktree", selector, "--json"]
            )
        except OrcaCommandError as exc:
            raise OrcaPreflightError(str(exc)) from exc
        shown_path = _extract_worktree_path(shown)
        if not shown_path or Path(shown_path).resolve(strict=False) != worktree:
            raise OrcaPreflightError("Orca worktree preflight did not resolve the exact MST worktree")
        return {
            "ok": True,
            "runtime_scope": "local",
            "worktree_dir": str(worktree),
            "worktree_selector": selector,
            # Persist/output only the executable identity. ORCA_CLI_COMMAND may
            # contain wrapper flags or credentials; those stay process-local
            # and are resolved afresh for later reconciliation/cleanup calls.
            "cli_argv": [self.command_argv[0]],
        }

    def create_terminal(self, *, selector: str, title: str, command: str) -> dict[str, Any]:
        payload = self._run_json(
            [
                "terminal",
                "create",
                "--worktree",
                selector,
                "--title",
                title,
                "--command",
                command,
                "--json",
            ],
            timeout=ORCA_CREATE_TIMEOUT_SECONDS,
            create_invoked=True,
        )
        if not isinstance(payload, dict):
            raise OrcaCreateUncertain("Orca terminal create returned an invalid response")
        handle = _extract_terminal_handle(payload)
        if not handle:
            raise OrcaCreateUncertain("Orca terminal create response omitted the terminal handle")
        return {**payload, "terminal_handle": handle}

    def list_terminals(self, *, selector: str) -> list[dict[str, Any]]:
        payload = self._run_json(
            ["terminal", "list", "--worktree", selector, "--json"]
        )
        return _terminal_entries(payload)

    def close_terminal(self, *, handle: str) -> dict[str, Any]:
        payload = self._run_json(
            ["terminal", "close", "--terminal", handle, "--tab", "--json"]
        )
        return payload if isinstance(payload, dict) else {"status": "closed"}


def terminal_handle(payload: Any) -> str | None:
    return _extract_terminal_handle(payload)


def terminal_title(payload: Any) -> str:
    payload = _unwrap_result(payload)
    if not isinstance(payload, dict):
        return ""
    for key in ("title", "name", "displayName", "display_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    terminal = payload.get("terminal")
    return terminal_title(terminal) if isinstance(terminal, dict) else ""
