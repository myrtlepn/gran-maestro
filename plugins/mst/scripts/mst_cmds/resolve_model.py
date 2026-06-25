from __future__ import annotations

import argparse
import copy
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
    _plugin_root,
    load_json,
)

PROVIDER_ALIASES = {"gemini": "agy"}

def _load_resolve_model_config():
    plugin_root = _plugin_root()
    config_paths = [
        _common.BASE_DIR / "config.resolved.json",
        plugin_root / "templates" / "defaults" / "config.json",
    ]
    for path in config_paths:
        config = load_json(path)
        if isinstance(config, dict):
            return config
    return {}

def _resolve_provider_default_model(provider, provider_cfg):
    if isinstance(provider_cfg, dict):
        default_tier = provider_cfg.get("default_tier")
        if isinstance(default_tier, str):
            default_model = provider_cfg.get(default_tier)
            if isinstance(default_model, str) and default_model:
                return default_model

    hardcoded = {
        "codex": "gpt-5.3-codex",
        "agy": "agy-default",
        "claude": "claude-sonnet-4-6",
    }
    return hardcoded.get(provider, hardcoded["codex"])

def cmd_resolve_model(args):
    requested_provider = str(args.provider or "").strip().lower()
    provider = PROVIDER_ALIASES.get(requested_provider, requested_provider)
    tier_or_section = str(args.tier_or_section or "").strip().lower()

    config = _load_resolve_model_config()
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg, dict) else {}
    provider_cfg = providers_cfg.get(provider) if isinstance(providers_cfg, dict) else None
    if not isinstance(provider_cfg, dict) and provider != requested_provider:
        provider_cfg = providers_cfg.get(requested_provider) if isinstance(providers_cfg, dict) else None

    fallback_model = _resolve_provider_default_model(provider, provider_cfg)

    if provider != requested_provider:
        print(
            f"Warning: deprecated provider '{requested_provider}' normalized to '{provider}'",
            file=sys.stderr,
        )

    if not isinstance(provider_cfg, dict):
        print(f"Warning: unknown provider '{provider}', using fallback model", file=sys.stderr)
        print(fallback_model)
        return 0

    default_tier = provider_cfg.get("default_tier")
    if not isinstance(default_tier, str):
        default_tier = None

    resolved_tier = None

    if tier_or_section == "default":
        resolved_tier = default_tier
    else:
        section_cfg = config.get(tier_or_section, {})
        is_section = isinstance(section_cfg, dict) and isinstance(section_cfg.get("agents"), dict)
        if is_section:
            agents_cfg = section_cfg.get("agents", {})
            provider_agent_cfg = agents_cfg.get(provider)
            if not isinstance(provider_agent_cfg, dict) and provider != requested_provider:
                provider_agent_cfg = agents_cfg.get(requested_provider)
            if isinstance(provider_agent_cfg, dict):
                section_tier = provider_agent_cfg.get("tier")
                if isinstance(section_tier, str):
                    resolved_tier = section_tier
            if not isinstance(resolved_tier, str):
                resolved_tier = default_tier
        else:
            resolved_tier = tier_or_section

    model = provider_cfg.get(resolved_tier) if isinstance(resolved_tier, str) else None
    if isinstance(model, str) and model:
        print(model)
        return 0

    print(
        f"Warning: unknown tier/section '{tier_or_section}' for provider '{provider}', "
        "using fallback model",
        file=sys.stderr,
    )
    print(fallback_model)
    return 0


def register(subparsers):
    sub = subparsers
    resolve_model = sub.add_parser("resolve-model")
    resolve_model.add_argument("provider")
    resolve_model.add_argument("tier_or_section")
