from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds._provenance import require_user_tty


ZERO_HASH = "0" * 64
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class LedgerDiagnosis:
    ok: bool
    reason: str
    mismatch_seq: int | None
    last_valid_seq: int
    last_valid_hash: str
    valid_lines: list[str]
    total_lines: int


def _project_root() -> Path:
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR.parent.resolve()
    return Path.cwd().resolve()


def _policy_home() -> Path:
    explicit = os.environ.get("MST_POLICY_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    claude_home = Path(os.environ.get("MST_CLAUDE_HOME", str(Path.home()))).expanduser()
    return claude_home / ".claude" / "gran-maestro-policy"


def _project_key(project_root: Path) -> str:
    return hashlib.sha256(os.path.realpath(project_root).encode()).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _sanitize_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or "/" in value or ".." in value or not SESSION_ID_RE.match(value):
        raise ValueError("invalid session_id")
    return value


def _history_paths(project_root: Path, policy_home: Path, session_id: str) -> tuple[Path, Path, Path, Path]:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = policy_home / "ledger-heads" / f"{session_id}.head"
    verify_state = session_dir / "history.verify"
    return history_file, local_head, mirror_head, verify_state


def _read_head(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _write_heads(local_head: Path, mirror_head: Path, head_hash: str) -> None:
    _atomic_write_text(local_head, head_hash + "\n")
    _atomic_write_text(mirror_head, head_hash + "\n")


def _write_verify_state(verify_state: Path, head_hash: str, history_file: Path, seq: int) -> None:
    _atomic_write_text(verify_state, f"{head_hash}\t{_file_fingerprint(history_file)}\t{seq}\n")


def _diagnose_ledger(history_file: Path, local_head: Path, mirror_head: Path) -> LedgerDiagnosis:
    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    valid_lines: list[str] = []

    lines = history_file.read_text(encoding="utf-8").splitlines() if history_file.is_file() else []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            return LedgerDiagnosis(False, f"invalid json line={line_no}: {exc}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if not isinstance(row, dict):
            return LedgerDiagnosis(False, f"row is not object line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if row.get("seq") != expected_seq:
            return LedgerDiagnosis(False, f"seq line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if row.get("prev_hash") != expected_prev:
            return LedgerDiagnosis(False, f"prev_hash line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        event = row.get("event")
        if not isinstance(event, dict):
            return LedgerDiagnosis(False, f"event line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        computed = _sha256_text(expected_prev + "\n" + _canonical_event(event))
        if row.get("event_hash") != computed:
            return LedgerDiagnosis(False, f"event_hash line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        valid_lines.append(line)
        expected_prev = computed
        last_hash = computed
        expected_seq += 1

    local_value = _read_head(local_head)
    mirror_value = _read_head(mirror_head)
    has_entries = expected_seq > 1
    if has_entries and local_value is None:
        return LedgerDiagnosis(False, "missing history.head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if has_entries and mirror_value is None:
        return LedgerDiagnosis(False, "missing home mirror head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if local_value is not None and local_value != last_hash:
        return LedgerDiagnosis(False, "history.head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if mirror_value is not None and mirror_value != last_hash:
        return LedgerDiagnosis(False, "home mirror head", None, expected_seq - 1, last_hash, valid_lines, len(lines))

    return LedgerDiagnosis(True, "ok", None, expected_seq - 1, last_hash, valid_lines, len(lines))


def _confirm_or_abort(args: argparse.Namespace, message: str) -> bool:
    if bool(getattr(args, "yes", False)):
        return True
    answer = input(f"{message} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _backup_history(history_file: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = history_file.with_name(f"{history_file.name}.bak.{timestamp}")
    suffix = 0
    while backup.exists():
        suffix += 1
        backup = history_file.with_name(f"{history_file.name}.bak.{timestamp}.{suffix}")
    shutil.copy2(history_file, backup)
    return backup


def _append_repair_event(project_root: Path, policy_home: Path, session_id: str, payload: dict) -> None:
    history_file, local_head, mirror_head, verify_state = _history_paths(project_root, policy_home, session_id)
    diagnosis = _diagnose_ledger(history_file, local_head, mirror_head)
    if not diagnosis.ok:
        raise RuntimeError(f"cannot append repair event to unhealthy ledger: {diagnosis.reason}")
    event = {
        "type": "repair_executed",
        "timestamp": _utc_now(),
        **payload,
    }
    event_hash = _sha256_text(diagnosis.last_valid_hash + "\n" + _canonical_event(event))
    row = {
        "event": event,
        "event_hash": event_hash,
        "prev_hash": diagnosis.last_valid_hash,
        "seq": diagnosis.last_valid_seq + 1,
        "timestamp": event["timestamp"],
    }
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    _write_heads(local_head, mirror_head, event_hash)
    _write_verify_state(verify_state, event_hash, history_file, diagnosis.last_valid_seq + 1)


def _repair_session(args: argparse.Namespace) -> int:
    project_root = _project_root()
    policy_home = _policy_home()
    session_id = _sanitize_session_id(args.session)
    history_file, local_head, mirror_head, verify_state = _history_paths(project_root, policy_home, session_id)

    diagnosis = _diagnose_ledger(history_file, local_head, mirror_head)
    if diagnosis.ok:
        print(f"복구 불필요: ledger integrity OK (session={session_id})")
        return 0

    mismatch = f"seq={diagnosis.mismatch_seq}" if diagnosis.mismatch_seq is not None else diagnosis.reason
    print(f"history ledger mismatch: {mismatch}", file=sys.stderr)
    print(f"recommended truncate seq: {diagnosis.last_valid_seq}", file=sys.stderr)
    print(f"rerun: mst hook repair --session {session_id} --truncate-to {diagnosis.last_valid_seq} --yes", file=sys.stderr)

    truncate_to = getattr(args, "truncate_to", None)
    if truncate_to is None:
        return 2
    if truncate_to < 0 or truncate_to > diagnosis.last_valid_seq:
        print(f"invalid --truncate-to {truncate_to}; maximum valid seq is {diagnosis.last_valid_seq}", file=sys.stderr)
        return 2
    if not history_file.is_file():
        print(f"history file not found: {history_file}", file=sys.stderr)
        return 2
    if not _confirm_or_abort(args, f"truncate {history_file} to seq {truncate_to}?"):
        print("repair aborted", file=sys.stderr)
        return 1

    backup = _backup_history(history_file)
    retained = diagnosis.valid_lines[:truncate_to]
    _atomic_write_text(history_file, ("\n".join(retained) + "\n") if retained else "")
    head_hash = ZERO_HASH if truncate_to == 0 else json.loads(retained[-1])["event_hash"]
    _write_heads(local_head, mirror_head, head_hash)
    _write_verify_state(verify_state, head_hash, history_file, truncate_to)

    print(f"truncated session={session_id} to seq={truncate_to}")
    print(f"backup={backup}")
    print(f"mirror_head={mirror_head}")
    return 0


def _read_manifest(policy_dir: Path) -> dict:
    manifest_path = policy_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"manifest invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("manifest invalid: unsupported version")
    if not isinstance(payload.get("rules"), list):
        raise ValueError("manifest invalid: rules must be a list")
    return payload


def _manifest_mismatches(policy_dir: Path, payload: dict) -> list[str]:
    errors: list[str] = []
    for item in payload.get("rules", []):
        if not isinstance(item, dict):
            errors.append("invalid manifest rule entry")
            continue
        rel = str(item.get("path") or "")
        expected = str(item.get("sha256") or "")
        if rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"invalid path: {rel}")
            continue
        rule_path = policy_dir / rel
        if not rule_path.is_file():
            errors.append(f"missing rule file: {rel}")
            continue
        actual = _sha256_file(rule_path)
        if actual != expected:
            errors.append(f"sha256 mismatch: {rel} expected={expected} actual={actual}")
    return errors


def _recalculated_manifest(policy_dir: Path) -> dict:
    rules_dir = policy_dir / "rules.d"
    rules = []
    for rule_file in sorted(rules_dir.glob("*.json")):
        rules.append(
            {
                "path": rule_file.relative_to(policy_dir).as_posix(),
                "sha256": _sha256_file(rule_file),
                "last_modified": _utc_now(),
            }
        )
    return {"version": 1, "rules": rules}


def _select_repair_event_session(project_root: Path) -> str:
    sessions_dir = project_root / ".gran-maestro" / "sessions"
    candidates = sorted(path.name for path in sessions_dir.iterdir() if path.is_dir()) if sessions_dir.is_dir() else []
    return candidates[0] if len(candidates) == 1 else "manifest-repair"


def _repair_manifest(args: argparse.Namespace) -> int:
    if getattr(args, "truncate_to", None) is not None:
        print("--truncate-to is only valid with --session", file=sys.stderr)
        return 2

    project_root = _project_root()
    policy_home = _policy_home()
    policy_dir = policy_home / "projects" / _project_key(project_root)
    manifest_path = policy_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    try:
        payload = _read_manifest(policy_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors = _manifest_mismatches(policy_dir, payload)
    if not errors:
        print(f"복구 불필요: manifest sha256 OK ({manifest_path})")
        return 0

    for error in errors:
        print(error, file=sys.stderr)
    if not _confirm_or_abort(args, f"recalculate manifest {manifest_path}?"):
        print("repair aborted", file=sys.stderr)
        return 1

    new_payload = _recalculated_manifest(policy_dir)
    _atomic_write_text(manifest_path, json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n")
    os.chmod(manifest_path, 0o600)

    session_id = _select_repair_event_session(project_root)
    _append_repair_event(
        project_root,
        policy_home,
        session_id,
        {"repair_target": "manifest", "manifest_path": str(manifest_path), "trigger": "user_cli"},
    )
    print(f"manifest repaired: {manifest_path}")
    print(f"repair_event_session={session_id}")
    return 0


def cmd_hook_repair(args: argparse.Namespace) -> int:
    try:
        require_user_tty()
        if args.session:
            return _repair_session(args)
        if args.manifest:
            return _repair_manifest(args)
        print("one of --session or --manifest is required", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def register(subparsers):
    hook = subparsers.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="subcommand")
    repair = hook_sub.add_parser("repair")
    mode = repair.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session")
    mode.add_argument("--manifest", action="store_true")
    repair.add_argument("--truncate-to", type=int)
    repair.add_argument("--yes", action="store_true")
    repair.set_defaults(func=cmd_hook_repair)
