from __future__ import annotations

import argparse
import copy
import fcntl
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    _compact_json,
    _flat_diff,
    _load_config_for_get,
    _plugin_root,
    deep_merge,
    load_json,
    save_json,
)

LEGACY_AGENT_SECTIONS = ["debug", "explore", "discussion", "ideation", "prereview"]

LEGACY_MODEL_KEYS = ["claude", "codex", "gemini", "developer", "reviewer"]

CLAUDE_MODEL_TO_TIER = {
    "opus": "premium",
    "sonnet": "economy",
    "haiku": "economy",
}

def _load_json_strict(path: Path, required=True):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            print(f"Error: file not found: {path}", file=sys.stderr)
            raise SystemExit(1)
        return None
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as exc:
        print(f"Error: failed to read {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)

def _has_legacy_format(config):
    if not isinstance(config, dict):
        return False

    for section in LEGACY_AGENT_SECTIONS:
        agents = config.get(section, {}).get("agents", {})
        if not isinstance(agents, dict):
            continue
        for value in agents.values():
            if isinstance(value, (int, float)):
                return True

    models = config.get("models", {})
    if isinstance(models, dict):
        for legacy_key in LEGACY_MODEL_KEYS:
            if legacy_key in models:
                return True

    code_review = config.get("code_review", {})
    if isinstance(code_review, dict) and isinstance(code_review.get("agent_roster"), str):
        return True

    phase1 = config.get("phase1_exploration", {})
    roles = phase1.get("roles", {}) if isinstance(phase1, dict) else {}
    if isinstance(roles, dict):
        for role_cfg in roles.values():
            if isinstance(role_cfg, dict) and "model" in role_cfg:
                return True

    return False

def _provider_model_to_tier(provider, model_name, default_providers):
    if not isinstance(provider, str) or not isinstance(model_name, str):
        return None

    if provider == "claude" and model_name in CLAUDE_MODEL_TO_TIER:
        return CLAUDE_MODEL_TO_TIER[model_name]

    provider_defaults = default_providers.get(provider)
    if isinstance(provider_defaults, dict):
        for tier, tier_model in provider_defaults.items():
            if tier == "default_tier":
                continue
            if isinstance(tier_model, str) and tier_model == model_name:
                return tier

    return None

def _prune_empty_dicts(node):
    if not isinstance(node, dict):
        return
    for key in list(node.keys()):
        value = node.get(key)
        if isinstance(value, dict):
            _prune_empty_dicts(value)
            if not value:
                del node[key]

def _ensure_roles_dict(models):
    roles = models.get("roles")
    if roles is None:
        models["roles"] = {}
        return models["roles"]
    if isinstance(roles, dict):
        return roles
    return None

def _default_section_claude_tier(defaults, section):
    section_cfg = defaults.get(section, {}) if isinstance(defaults, dict) else {}
    agents = section_cfg.get("agents", {}) if isinstance(section_cfg, dict) else {}
    claude_cfg = agents.get("claude", {}) if isinstance(agents, dict) else {}
    if isinstance(claude_cfg, dict):
        tier = claude_cfg.get("tier")
        if isinstance(tier, str):
            return tier
    return None

def _migrate_config(config, defaults):
    migrated = copy.deepcopy(config) if isinstance(config, dict) else {}
    warnings = []

    def warn(message):
        warnings.append(message)

    defaults_models = defaults.get("models", {}) if isinstance(defaults, dict) else {}
    default_providers = defaults_models.get("providers", {}) if isinstance(defaults_models, dict) else {}
    default_roles = defaults_models.get("roles", {}) if isinstance(defaults_models, dict) else {}

    for section in LEGACY_AGENT_SECTIONS:
        section_cfg = migrated.get(section)
        if not isinstance(section_cfg, dict):
            continue
        agents = section_cfg.get("agents")
        if not isinstance(agents, dict):
            continue

        for provider, raw_value in list(agents.items()):
            if not isinstance(raw_value, (int, float)):
                continue

            provider_defaults = default_providers.get(provider)
            if not isinstance(provider_defaults, dict):
                warn(
                    f"수동 확인 필요: {section}.agents.{provider}={_compact_json(raw_value)}"
                )
                continue

            if isinstance(raw_value, bool):
                count = int(raw_value)
                warn(
                    f"{section}.agents.{provider}: bool 값을 count={count}로 보정"
                )
            else:
                count = int(raw_value)
                if raw_value < 0 or (
                    isinstance(raw_value, float) and not raw_value.is_integer()
                ):
                    warn(
                        f"{section}.agents.{provider}: {raw_value} 값을 count={max(0, count)}로 보정"
                    )
                if count < 0:
                    count = 0

            if count == 0:
                agents[provider] = {"count": 0}
                continue

            default_tier = provider_defaults.get("default_tier")
            if not isinstance(default_tier, str) or not default_tier:
                warn(
                    f"수동 확인 필요: {section}.agents.{provider}={_compact_json(raw_value)}"
                )
                continue
            agents[provider] = {"count": count, "tier": default_tier}

    models = migrated.get("models")
    if isinstance(models, dict):
        legacy_claude = models.get("claude")
        if isinstance(legacy_claude, dict):
            for role, model_name in list(legacy_claude.items()):
                legacy_key = f"models.claude.{role}"
                if role in LEGACY_AGENT_SECTIONS:
                    mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                    if not isinstance(mapped_tier, str):
                        warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                        continue

                    section_cfg = migrated.get(role)
                    agents = section_cfg.get("agents") if isinstance(section_cfg, dict) else None
                    claude_cfg = agents.get("claude") if isinstance(agents, dict) else None

                    count = 0
                    if isinstance(claude_cfg, dict):
                        raw_count = claude_cfg.get("count")
                        if isinstance(raw_count, bool):
                            count = int(raw_count)
                        elif isinstance(raw_count, (int, float)):
                            count = int(raw_count)
                    elif isinstance(claude_cfg, bool):
                        count = int(claude_cfg)
                    elif isinstance(claude_cfg, (int, float)):
                        count = int(claude_cfg)

                    if count > 0:
                        default_section_tier = _default_section_claude_tier(defaults, role)
                        if mapped_tier != default_section_tier:
                            if isinstance(claude_cfg, dict):
                                if "tier" not in claude_cfg:
                                    claude_cfg["tier"] = mapped_tier
                            elif isinstance(agents, dict) and "claude" not in agents:
                                agents["claude"] = {"count": count, "tier": mapped_tier}
                            else:
                                warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                                continue

                    del legacy_claude[role]
                    continue

                roles_cfg = models.get("roles")
                if isinstance(roles_cfg, dict) and role in roles_cfg:
                    del legacy_claude[role]
                    continue

                mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                    continue

                default_role_cfg = default_roles.get(role) if isinstance(default_roles, dict) else None
                if isinstance(default_role_cfg, dict):
                    default_provider = default_role_cfg.get("provider")
                    default_tier = default_role_cfg.get("tier")
                    if default_provider == "claude" and default_tier == mapped_tier:
                        del legacy_claude[role]
                        continue

                roles_cfg = _ensure_roles_dict(models)
                if roles_cfg is None:
                    warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                    continue
                if role not in roles_cfg:
                    roles_cfg[role] = {"tier": mapped_tier}
                del legacy_claude[role]

        for provider in ["codex", "gemini"]:
            legacy_provider = models.get(provider)
            if not isinstance(legacy_provider, dict):
                continue
            if "default" not in legacy_provider:
                continue

            value = legacy_provider.get("default")
            provider_defaults = default_providers.get(provider)
            default_premium_model = (
                provider_defaults.get("premium")
                if isinstance(provider_defaults, dict)
                else None
            )
            if isinstance(default_premium_model, str) and value == default_premium_model:
                del legacy_provider["default"]
                continue

            warn(f"수동 확인 필요: models.{provider}.default={_compact_json(value)}")

        def migrate_legacy_role_array(legacy_key, role_key):
            legacy_cfg = models.get(legacy_key)
            if not isinstance(legacy_cfg, dict):
                return

            roles_cfg = models.get("roles")
            role_preexisting = isinstance(roles_cfg, dict) and role_key in roles_cfg
            role_defaults = (
                default_roles.get(role_key)
                if isinstance(default_roles, dict)
                else None
            )

            for index, field in enumerate(["primary", "fallback"]):
                if field not in legacy_cfg:
                    continue
                legacy_leaf = f"models.{legacy_key}.{field}"
                if role_preexisting:
                    del legacy_cfg[field]
                    continue

                model_name = legacy_cfg.get(field)
                default_provider = None
                default_tier = None
                if isinstance(role_defaults, list) and index < len(role_defaults):
                    default_role = role_defaults[index]
                    if isinstance(default_role, dict):
                        default_provider = default_role.get("provider")
                        default_tier = default_role.get("tier")

                expected_model = None
                provider_defaults = (
                    default_providers.get(default_provider)
                    if isinstance(default_provider, str)
                    else None
                )
                if isinstance(provider_defaults, dict) and isinstance(default_tier, str):
                    expected_model = provider_defaults.get(default_tier)

                if isinstance(expected_model, str) and model_name == expected_model:
                    del legacy_cfg[field]
                    continue

                if not isinstance(default_provider, str):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                mapped_tier = _provider_model_to_tier(default_provider, model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                roles_cfg = _ensure_roles_dict(models)
                if roles_cfg is None:
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                role_override = roles_cfg.get(role_key)
                if role_override is None:
                    if isinstance(role_defaults, list):
                        role_override = copy.deepcopy(role_defaults)
                    else:
                        role_override = []
                    roles_cfg[role_key] = role_override
                if not isinstance(role_override, list):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                while len(role_override) <= index:
                    role_override.append({})
                if not isinstance(role_override[index], dict):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                if "tier" not in role_override[index]:
                    role_override[index]["tier"] = mapped_tier
                del legacy_cfg[field]

        migrate_legacy_role_array("developer", "developer")
        migrate_legacy_role_array("reviewer", "reviewer")

        legacy_developer = models.get("developer")
        if isinstance(legacy_developer, dict):
            claude_dev = legacy_developer.get("claude_dev")
            if isinstance(claude_dev, dict) and "model" in claude_dev:
                model_name = claude_dev.get("model")
                roles_cfg = models.get("roles")
                if isinstance(roles_cfg, dict) and "developer_claude" in roles_cfg:
                    del claude_dev["model"]
                else:
                    mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                    if not isinstance(mapped_tier, str):
                        warn(
                            "수동 확인 필요: "
                            f"models.developer.claude_dev.model={_compact_json(model_name)}"
                        )
                    else:
                        roles_cfg = _ensure_roles_dict(models)
                        if roles_cfg is None:
                            warn(
                                "수동 확인 필요: "
                                f"models.developer.claude_dev.model={_compact_json(model_name)}"
                            )
                        else:
                            role_cfg = roles_cfg.get("developer_claude")
                            if role_cfg is None:
                                roles_cfg["developer_claude"] = {"tier": mapped_tier}
                            elif isinstance(role_cfg, dict) and "tier" not in role_cfg:
                                role_cfg["tier"] = mapped_tier
                            del claude_dev["model"]

    code_review = migrated.get("code_review")
    if isinstance(code_review, dict):
        agent_roster = code_review.get("agent_roster")
        if isinstance(agent_roster, str):
            tokens = []
            seen = set()
            for item in agent_roster.split(","):
                token = item.strip()
                if not token or token in seen:
                    continue
                seen.add(token)
                tokens.append(token)
            code_review["agent_roster"] = tokens

    phase1 = migrated.get("phase1_exploration")
    if isinstance(phase1, dict):
        roles = phase1.get("roles")
        if isinstance(roles, dict):
            for role_name, role_cfg in roles.items():
                if not isinstance(role_cfg, dict):
                    continue
                if "model" not in role_cfg:
                    continue
                model_name = role_cfg.get("model")
                provider = role_cfg.get("agent")
                if not isinstance(provider, str) or not isinstance(
                    default_providers.get(provider), dict
                ):
                    warn(
                        "수동 확인 필요: "
                        f"phase1_exploration.roles.{role_name}.model={_compact_json(model_name)}"
                    )
                    continue
                mapped_tier = _provider_model_to_tier(provider, model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(
                        "수동 확인 필요: "
                        f"phase1_exploration.roles.{role_name}.model={_compact_json(model_name)}"
                    )
                    continue
                role_cfg["tier"] = mapped_tier
                del role_cfg["model"]

    for root_key in ["models", "code_review", "phase1_exploration"]:
        root_cfg = migrated.get(root_key)
        if not isinstance(root_cfg, dict):
            continue
        _prune_empty_dicts(root_cfg)
        if not root_cfg:
            del migrated[root_key]

    return migrated, warnings

def _path_exists(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True

def _format_migrate_value(value):
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return _compact_json(value)
    return str(value)

def cmd_config_migrate(args):
    plugin_root = _plugin_root()
    defaults_path = plugin_root / "templates" / "defaults" / "config.json"
    config_path = _common.BASE_DIR / "config.json"

    defaults = _load_json_strict(defaults_path, required=True)
    if not isinstance(defaults, dict):
        print(f"Error: invalid defaults format: {defaults_path}", file=sys.stderr)
        return 1

    overrides = _load_json_strict(config_path, required=False)
    if overrides is None:
        print("변환할 항목 없음")
        return 0
    if not isinstance(overrides, dict):
        print(f"Error: invalid config format: {config_path}", file=sys.stderr)
        return 1

    migrated, warnings = _migrate_config(overrides, defaults)
    changed = _flat_diff(overrides, migrated)
    if not changed:
        print("변환할 항목 없음")
        for message in warnings:
            print(f"[WARN]    {message}")
        print(f"총 0건 변환, {len(warnings)}건 경고")
        return 0

    for key, (old_value, new_value) in changed.items():
        if key == "<root>":
            old_text = _format_migrate_value(old_value)
            new_text = _format_migrate_value(new_value)
        else:
            old_text = "(added)" if not _path_exists(overrides, key) else _format_migrate_value(old_value)
            new_text = "(deleted)" if not _path_exists(migrated, key) else _format_migrate_value(new_value)
        print(f"[MIGRATE] {key}: {old_text} → {new_text}")

    for message in warnings:
        print(f"[WARN]    {message}")
    print(f"총 {len(changed)}건 변환, {len(warnings)}건 경고")

    if not args.apply:
        return 0

    save_json(config_path, migrated)
    resolved = deep_merge(defaults, migrated)
    save_json(_common.BASE_DIR / "config.resolved.json", resolved)
    print("config.json updated")
    print("config.resolved.json updated")
    return 0

def cmd_config_resolve(args):
    plugin_root = _common._plugin_root()
    defaults_path = plugin_root / "templates" / "defaults" / "config.json"
    defaults = load_json(defaults_path) or {}
    overrides = load_json(_common.BASE_DIR / "config.json") or {}
    if _has_legacy_format(overrides):
        print(
            "⚠ 구 포맷 설정 감지. `python3 scripts/mst.py config migrate` 실행을 권장합니다.",
            file=sys.stderr,
        )
    resolved = deep_merge(defaults, overrides)
    save_json(_common.BASE_DIR / "config.resolved.json", resolved)
    print(f"config.resolved.json updated ({len(resolved)} top-level keys)")
    return 0

def _get_dotted_path(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current

def cmd_config_get(args):
    key_path = str(args.key_path or "").strip()
    if not key_path:
        print("Error: key.path is required", file=sys.stderr)
        return 1

    config = _load_config_for_get()
    found, value = _get_dotted_path(config, key_path)
    if not found:
        if args.default_value is None:
            print(f"Error: key not found: {key_path}", file=sys.stderr)
            return 1
        value = args.default_value

    if args.json:
        print(json.dumps({"key": key_path, "value": value}, ensure_ascii=False))
        return 0

    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


def register(subparsers):
    sub = subparsers
    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="subcommand")
    cfg_resolve = cfg_sub.add_parser("resolve", help="defaults + overrides → config.resolved.json")
    cfg_resolve.set_defaults(func=cmd_config_resolve)
    cfg_get = cfg_sub.add_parser("get", help="read config value by dot-path")
    cfg_get.add_argument("key_path")
    cfg_get.add_argument("--default", dest="default_value")
    cfg_get.add_argument("--json", action="store_true")
    cfg_migrate = cfg_sub.add_parser("migrate", help="구 포맷 config를 신 포맷으로 마이그레이션")
    cfg_migrate.add_argument("--apply", action="store_true", help="실제 적용 (기본: dry-run)")
    cfg_migrate.set_defaults(func=cmd_config_migrate)
