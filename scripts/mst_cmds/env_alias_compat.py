from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

CANONICAL_SESSION_ENV = "MST_SESSION_ID"
LEGACY_STATE_PPID_ENV = "MST_STATE_PPID"
LEGACY_SNAPSHOT_SESSION_ENV = "MST_SNAPSHOT_SESSION_ID"
LEGACY_SESSION_ALIASES = (LEGACY_SNAPSHOT_SESSION_ENV, LEGACY_STATE_PPID_ENV)

_WARNED_ALIASES_IN_PROCESS: set[str] = set()


def _project_base_dir() -> Optional[Path]:
    env_base = os.environ.get("MST_BASE_DIR", "").strip()
    if env_base:
        candidate = Path(env_base)
        return candidate if candidate.name == ".gran-maestro" else candidate / ".gran-maestro"

    current = Path.cwd().resolve()
    while True:
        candidate = current / ".gran-maestro"
        if candidate.is_dir():
            return candidate
        if current.name == ".gran-maestro" and current.is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _warn_marker_path(alias: str) -> Optional[Path]:
    base_dir = _project_base_dir()
    if base_dir is None:
        return None
    safe_alias = "".join(ch for ch in alias if ch.isalnum() or ch == "_")
    return base_dir / "tmp" / "legacy-env-alias-warnings" / f"{date.today().isoformat()}-{safe_alias}.warned"


def warn_legacy_alias_once(alias: str) -> None:
    """Warn once per process and once per project+alias+date for 0.60.x env aliases.

    TODO(0.61.0): remove legacy alias warning/marker support with the alias fallback paths.
    """
    if alias in _WARNED_ALIASES_IN_PROCESS:
        return
    _WARNED_ALIASES_IN_PROCESS.add(alias)

    marker = _warn_marker_path(alias)
    if marker is not None:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("warned\n")
        except FileExistsError:
            return
        except OSError:
            pass

    print(
        f"[legacy-env-alias] {alias} is deprecated; migration: set {CANONICAL_SESSION_ENV} instead.",
        file=sys.stderr,
    )


def canonical_session_id_from_env(env: Mapping[str, str] | None = None) -> str | None:
    source = env if env is not None else os.environ
    value = str(source.get(CANONICAL_SESSION_ENV, "")).strip()
    return value or None


def legacy_session_id_from_env(
    env: Mapping[str, str] | None = None,
    *,
    warn: bool = True,
    aliases: tuple[str, ...] = LEGACY_SESSION_ALIASES,
) -> tuple[str | None, str | None]:
    source = env if env is not None else os.environ
    for alias in aliases:
        value = str(source.get(alias, "")).strip()
        if value:
            if warn:
                warn_legacy_alias_once(alias)
            return value, alias
    return None, None


def resolve_session_id_from_env(env: Mapping[str, str] | None = None, *, warn_legacy: bool = True) -> tuple[str | None, str | None]:
    canonical = canonical_session_id_from_env(env)
    if canonical:
        return canonical, CANONICAL_SESSION_ENV
    return legacy_session_id_from_env(env, warn=warn_legacy)
