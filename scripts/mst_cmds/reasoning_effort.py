from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.mst_cmds import resolve_model as resolve_model_mod
from scripts.mst_cmds import _common


PROVIDER_ALIASES = {"gemini": "agy"}
CONCRETE_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
PROVIDER_REASONING_EFFORTS = {
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "agy": ("low", "medium", "high"),
}


class ReasoningEffortError(ValueError):
    """Raised when an explicit execution effort cannot be honored."""


def _normalize_provider(provider: str) -> tuple[str, str]:
    requested = str(provider or "").strip().lower()
    return PROVIDER_ALIASES.get(requested, requested), requested


def _provider_config(config: dict[str, Any], provider: str, requested: str) -> dict[str, Any]:
    models = config.get("models") if isinstance(config, dict) else None
    providers = models.get("providers") if isinstance(models, dict) else None
    candidate = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(candidate, dict) and requested != provider and isinstance(providers, dict):
        candidate = providers.get(requested)
    return candidate if isinstance(candidate, dict) else {}


def _get_path(config: Any, dotted_path: str) -> Any:
    current = config
    for part in [item for item in str(dotted_path or "").split(".") if item]:
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return None
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _load_config(base_dir: Path | str | None = None) -> dict[str, Any]:
    candidates = []
    if base_dir is not None:
        candidates.append(Path(base_dir) / "config.resolved.json")
    elif _common.BASE_DIR is not None:
        candidates.append(Path(_common.BASE_DIR) / "config.resolved.json")
    candidates.append(_common._plugin_root() / "templates" / "defaults" / "config.json")
    for path in candidates:
        payload = _common.load_json(path)
        if isinstance(payload, dict):
            return payload
    return {}


def _selector_entry(
    config: dict[str, Any],
    *,
    provider: str,
    requested_provider: str,
    selector: str,
) -> tuple[dict[str, Any] | None, str | None]:
    normalized = str(selector or "default").strip()
    if normalized in {"", "default", "premium", "economy"}:
        return None, None

    direct = _get_path(config, normalized)
    if isinstance(direct, dict):
        agents = direct.get("agents")
        if isinstance(agents, dict):
            candidate = agents.get(provider)
            if not isinstance(candidate, dict) and requested_provider != provider:
                candidate = agents.get(requested_provider)
            if isinstance(candidate, dict):
                return candidate, f"{normalized}.agents.{provider}"
        return direct, normalized

    section = config.get(normalized)
    agents = section.get("agents") if isinstance(section, dict) else None
    if isinstance(agents, dict):
        candidate = agents.get(provider)
        if not isinstance(candidate, dict) and requested_provider != provider:
            candidate = agents.get(requested_provider)
        if isinstance(candidate, dict):
            return candidate, f"{normalized}.agents.{provider}"
    return None, None


@lru_cache(maxsize=1)
def _codex_model_catalog() -> dict[str, dict[str, Any]]:
    executable = shutil.which("codex")
    if not executable:
        return {}
    try:
        result = subprocess.run(
            [executable, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        levels = item.get("supported_reasoning_levels")
        supported = []
        if isinstance(levels, list):
            for level in levels:
                effort = level.get("effort") if isinstance(level, dict) else None
                if isinstance(effort, str) and effort in CONCRETE_REASONING_EFFORTS:
                    supported.append(effort)
        catalog[slug] = {
            "efforts": supported,
            "default": item.get("default_reasoning_level"),
        }
    return catalog


def supported_reasoning_efforts(provider: str, model: str | None) -> list[str]:
    normalized, _ = _normalize_provider(provider)
    if normalized == "codex":
        entry = _codex_model_catalog().get(str(model or ""))
        return list(entry.get("efforts") or []) if isinstance(entry, dict) else []
    return list(PROVIDER_REASONING_EFFORTS.get(normalized, ()))


def validate_reasoning_effort(provider: str, model: str | None, effort: str | None) -> None:
    if effort is None:
        return
    normalized, _ = _normalize_provider(provider)
    supported = supported_reasoning_efforts(normalized, model)
    if not supported:
        raise ReasoningEffortError(
            f"reasoning capability unavailable for provider '{normalized}' and model '{model or ''}'"
        )
    if effort not in supported:
        raise ReasoningEffortError(
            f"unsupported reasoning effort '{effort}' for provider '{normalized}' "
            f"and model '{model or ''}' (supported: {', '.join(supported)})"
        )


def resolve_execution(
    provider: str,
    selector: str = "default",
    *,
    explicit_model: str | None = None,
    explicit_reasoning_effort: str | None = None,
    validate: bool = True,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    normalized_provider, requested_provider = _normalize_provider(provider)
    normalized_selector = str(selector or "default").strip() or "default"
    config = _load_config(base_dir)
    provider_cfg = _provider_config(config, normalized_provider, requested_provider)
    entry, entry_path = _selector_entry(
        config,
        provider=normalized_provider,
        requested_provider=requested_provider,
        selector=normalized_selector,
    )

    default_tier = provider_cfg.get("default_tier")
    if not isinstance(default_tier, str) or not default_tier:
        default_tier = None
    if normalized_selector in {"premium", "economy"}:
        tier = normalized_selector
        tier_source = "selector"
    elif isinstance(entry, dict) and isinstance(entry.get("tier"), str):
        tier = str(entry["tier"])
        tier_source = f"{entry_path}.tier" if entry_path else "entry.tier"
    else:
        tier = default_tier
        tier_source = f"models.providers.{normalized_provider}.default_tier"

    model = str(explicit_model).strip() if isinstance(explicit_model, str) and explicit_model.strip() else None
    model_source = "explicit"
    if model is None:
        configured_model = provider_cfg.get(tier) if isinstance(tier, str) else None
        if isinstance(configured_model, str) and configured_model.strip():
            model = configured_model.strip()
            model_source = f"models.providers.{normalized_provider}.{tier}"
        elif isinstance(tier, str):
            # A configured/selected tier with no model is an invalid binding.
            # Do not silently replace it with a provider fallback because
            # preflight must fail before launching the provider.
            model = None
            model_source = f"models.providers.{normalized_provider}.{tier}:missing"
        else:
            model = resolve_model_mod._resolve_provider_default_model(normalized_provider, provider_cfg)
            model_source = "fallback"

    provider_default = provider_cfg.get("default_reasoning_effort", "inherit")
    if not isinstance(provider_default, str):
        provider_default = "inherit"
    entry_value = entry.get("reasoning_effort", "default") if isinstance(entry, dict) else "default"
    if not isinstance(entry_value, str):
        entry_value = "default"
    requested_effort = (
        str(explicit_reasoning_effort).strip()
        if isinstance(explicit_reasoning_effort, str) and explicit_reasoning_effort.strip()
        else entry_value
    )
    effort_source = "explicit" if explicit_reasoning_effort is not None else (
        f"{entry_path}.reasoning_effort" if entry_path else "default"
    )
    if requested_effort == "default":
        tier_default_key = (
            f"{tier}_reasoning_effort"
            if tier in {"premium", "economy"}
            else None
        )
        tier_default = provider_cfg.get(tier_default_key) if tier_default_key else None
        if isinstance(tier_default, str):
            requested_effort = tier_default
            effort_source = f"models.providers.{normalized_provider}.{tier_default_key}"
        else:
            # The tier-specific setting is optional so existing configurations
            # continue to use the provider-wide default.
            requested_effort = provider_default
            effort_source = f"models.providers.{normalized_provider}.default_reasoning_effort"
    if requested_effort == "inherit":
        effective_effort = None
    elif requested_effort in CONCRETE_REASONING_EFFORTS:
        effective_effort = requested_effort
    else:
        raise ReasoningEffortError(
            f"invalid reasoning effort '{requested_effort}' for provider '{normalized_provider}'"
        )

    if validate:
        validate_reasoning_effort(normalized_provider, model, effective_effort)

    return {
        "provider": normalized_provider,
        "requested_provider": requested_provider,
        "selector": normalized_selector,
        "tier": tier,
        "tier_source": tier_source,
        "model": model,
        "model_source": model_source,
        "reasoning_effort": effective_effort,
        "reasoning_effort_setting": requested_effort,
        "reasoning_effort_source": effort_source,
    }


def reasoning_capabilities(base_dir: Path | str | None = None) -> dict[str, Any]:
    config = _load_config(base_dir)
    providers: dict[str, Any] = {}
    codex_catalog = _codex_model_catalog()
    for provider in ("codex", "agy", "claude"):
        provider_cfg = _provider_config(config, provider, provider)
        binary = shutil.which(provider)
        selected_models = {
            tier: provider_cfg.get(tier)
            for tier in ("premium", "economy")
            if isinstance(provider_cfg.get(tier), str)
        }
        if provider == "codex":
            providers[provider] = {
                "available": bool(binary and codex_catalog),
                "source": "codex-debug-models",
                "models": codex_catalog,
                "selected_models": selected_models,
            }
        else:
            providers[provider] = {
                "available": bool(binary),
                "source": f"{provider}-cli-adapter",
                "efforts": list(PROVIDER_REASONING_EFFORTS[provider]),
                "selected_models": selected_models,
            }
    return {"schema_version": 1, "providers": providers}


def cmd_resolve_execution(args: argparse.Namespace) -> int:
    try:
        payload = resolve_execution(
            args.provider,
            args.selector,
            explicit_model=args.model,
            explicit_reasoning_effort=args.reasoning_effort,
            validate=not args.skip_validation,
        )
    except ReasoningEffortError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


def cmd_reasoning_capabilities(args: argparse.Namespace) -> int:
    print(json.dumps(reasoning_capabilities(), ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


def register(subparsers) -> None:
    resolve_execution_parser = subparsers.add_parser("resolve-execution")
    resolve_execution_parser.add_argument("provider")
    resolve_execution_parser.add_argument("selector", nargs="?", default="default")
    resolve_execution_parser.add_argument("--model")
    resolve_execution_parser.add_argument("--reasoning-effort")
    resolve_execution_parser.add_argument("--skip-validation", action="store_true")
    resolve_execution_parser.add_argument("--pretty", action="store_true")

    capabilities = subparsers.add_parser("reasoning-capabilities")
    capabilities.add_argument("--pretty", action="store_true")
