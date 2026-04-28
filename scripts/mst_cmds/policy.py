from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import _common


POLICY_HOME = Path(".claude") / "gran-maestro-policy"
DEFAULT_RULE_FILE = "core-bypass.json"


DEFAULT_RULESET = {
    "version": 1,
    "rules": [
        {
            "id": "GM-CORE-BYPASS-DOCUMENTATION",
            "description": "Hardcoded core bypass protections live in hooks/lib/rule_engine.bash and cannot be weakened by JSON policy.",
            "severity": "warn",
            "trigger": {"tool": "__never__"},
            "action": {
                "decision": "warn",
                "message": "hardcoded core protections are enforced by hook code",
            },
        }
    ],
}


def _project_root() -> Path:
    base_dir = _common.BASE_DIR
    if base_dir is not None:
        return base_dir.parent.resolve()
    return Path.cwd().resolve()


def _project_key(project_root: Path) -> str:
    canonical = os.path.realpath(project_root)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _policy_project_dir(project_root: Path | None = None) -> Path:
    root = project_root or _project_root()
    return Path.home() / POLICY_HOME / "projects" / _project_key(root)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chmod_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _manifest_payload(policy_dir: Path) -> dict:
    rules = []
    rules_dir = policy_dir / "rules.d"
    for rule_file in sorted(rules_dir.glob("*.json")):
        rules.append(
            {
                "path": rule_file.relative_to(policy_dir).as_posix(),
                "sha256": _sha256_file(rule_file),
                "last_modified": _utc_now(),
            }
        )
    return {"version": 1, "rules": rules}


def cmd_policy_init(args: argparse.Namespace) -> int:
    project_root = _project_root()
    policy_dir = _policy_project_dir(project_root)
    rules_dir = policy_dir / "rules.d"

    (Path.home() / ".claude").mkdir(parents=True, exist_ok=True)
    for directory in (
        Path.home() / POLICY_HOME,
        Path.home() / POLICY_HOME / "projects",
        policy_dir,
        rules_dir,
    ):
        _chmod_private_dir(directory)

    rule_file = rules_dir / DEFAULT_RULE_FILE
    if not rule_file.exists():
        _write_private_json(rule_file, DEFAULT_RULESET)
    else:
        os.chmod(rule_file, 0o600)

    _write_private_json(policy_dir / "manifest.json", _manifest_payload(policy_dir))

    print(f"project_key={_project_key(project_root)}")
    print(f"policy_dir={policy_dir}")
    return 0


def _read_manifest(policy_dir: Path) -> dict:
    manifest_path = policy_dir / "manifest.json"
    with manifest_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("unsupported manifest version")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("manifest rules must be a list")
    return payload


def _verified_rules(policy_dir: Path) -> tuple[list[Path], list[str]]:
    payload = _read_manifest(policy_dir)
    paths: list[Path] = []
    errors: list[str] = []

    for item in payload.get("rules", []):
        if not isinstance(item, dict):
            errors.append("invalid manifest rule entry")
            continue
        rel = str(item.get("path") or "")
        expected = str(item.get("sha256") or "")
        if rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"invalid manifest path: {rel}")
            continue
        path = policy_dir / rel
        if not path.is_file():
            errors.append(f"missing rule file: {rel}")
            continue
        actual = _sha256_file(path)
        if actual != expected:
            errors.append(f"sha256 mismatch: {rel} expected={expected} actual={actual}")
            continue
        paths.append(path)
    return paths, errors


def cmd_policy_verify(args: argparse.Namespace) -> int:
    policy_dir = _policy_project_dir()
    try:
        rules, errors = _verified_rules(policy_dir)
    except Exception as exc:
        print(f"policy verify failed: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2

    print(f"ok rules={len(rules)} policy_dir={policy_dir}")
    return 0


def cmd_policy_list(args: argparse.Namespace) -> int:
    policy_dir = _policy_project_dir()
    print(f"project_key={_project_key(_project_root())}")
    print(f"policy_dir={policy_dir}")
    manifest_path = policy_dir / "manifest.json"
    if not manifest_path.is_file():
        print("manifest=missing")
        return 1
    payload = _read_manifest(policy_dir)
    for item in payload.get("rules", []):
        if isinstance(item, dict):
            print(f"rule={item.get('path', '')} sha256={item.get('sha256', '')}")
    return 0


def register(subparsers):
    policy = subparsers.add_parser("policy")
    policy_sub = policy.add_subparsers(dest="subcommand")
    policy_sub.add_parser("init")
    policy_sub.add_parser("list")
    policy_sub.add_parser("verify")
