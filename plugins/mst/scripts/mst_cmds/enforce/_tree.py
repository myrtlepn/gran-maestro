from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.mst_cmds import _common

SCHEMA_VERSION = "enforce-tree-v1"
VALID_IDEMPOTENT_VALUES = {"true", "false", "unknown"}


class EnforceTreeError(ValueError):
    """Raised when enforce-tree.json cannot be loaded."""


def default_tree_path() -> Path:
    return _common._plugin_root() / "hooks" / "enforce-tree.json"


def resolve_tree_path(path: str | None) -> Path:
    if path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    return default_tree_path().resolve()


def load_tree(path: str | None = None) -> tuple[Path, Any]:
    tree_path = resolve_tree_path(path)
    try:
        with tree_path.open(encoding="utf-8") as fh:
            return tree_path, json.load(fh)
    except FileNotFoundError as exc:
        raise EnforceTreeError(f"enforce-tree.json not found: {tree_path}") from exc
    except json.JSONDecodeError as exc:
        raise EnforceTreeError(f"invalid JSON in {tree_path}: {exc}") from exc


def _is_list_of_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _is_int(value: Any) -> bool:
    return type(value) is int


def _validate_global_rules(global_rules: Any, errors: list[str]) -> None:
    if not isinstance(global_rules, dict):
        errors.append("global_rules must be an object")
        return

    expected = {
        "single_active_skill": _is_bool,
        "subagent_inherits_parent_whitelist": _is_bool,
        "allow_recursive_skill_call": _is_bool,
        "max_recursion_depth": _is_int,
    }
    for key, predicate in expected.items():
        if key not in global_rules:
            errors.append(f"global_rules.{key} is required")
        elif not predicate(global_rules[key]):
            errors.append(f"global_rules.{key} has invalid type")


def _step_id(step: Any, index: int) -> str:
    if isinstance(step, dict) and isinstance(step.get("id"), str) and step["id"]:
        return step["id"]
    return f"<step[{index}]>"


def step_idempotent_is_valid(step: dict[str, Any]) -> bool:
    if "idempotent" not in step:
        return False
    value = step.get("idempotent")
    if type(value) is bool:
        return True
    return isinstance(value, str) and value in VALID_IDEMPOTENT_VALUES


def validate_schema_shape(tree: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(tree, dict):
        return ["enforce tree must be a JSON object"]

    if tree.get("version") != 1:
        errors.append("version must be 1")
    if tree.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    skills = tree.get("skills")
    if not isinstance(skills, dict):
        errors.append("skills must be an object")
        skills = {}

    _validate_global_rules(tree.get("global_rules"), errors)

    for skill_name in sorted(skills):
        skill = skills[skill_name]
        prefix = f"skills.{skill_name}"
        if not isinstance(skill, dict):
            errors.append(f"{prefix} must be an object")
            continue

        if not _is_list_of_strings(skill.get("entry_paths")):
            errors.append(f"{prefix}.entry_paths must be a list of strings")

        steps = skill.get("steps")
        if not isinstance(steps, list):
            errors.append(f"{prefix}.steps must be a list")
            steps = []

        step_ids: list[str] = []
        seen_step_ids: set[str] = set()
        for index, step in enumerate(steps):
            step_prefix = f"{prefix}.steps[{index}]"
            if not isinstance(step, dict):
                errors.append(f"{step_prefix} must be an object")
                continue

            for field in ("id", "name", "required", "path_whitelist", "allowed_sub_skills", "idempotent"):
                if field not in step:
                    errors.append(f"{step_prefix}.{field} is required")

            sid = _step_id(step, index)
            if not isinstance(step.get("id"), str) or not step.get("id"):
                errors.append(f"{step_prefix}.id must be a non-empty string")
            elif sid in seen_step_ids:
                errors.append(f"{step_prefix}.id duplicates step id {sid}")
            else:
                seen_step_ids.add(sid)
                step_ids.append(sid)

            if "name" in step and not isinstance(step.get("name"), str):
                errors.append(f"{step_prefix}.name must be a string")
            if "required" in step and not _is_bool(step.get("required")):
                errors.append(f"{step_prefix}.required must be a boolean")
            if "path_whitelist" in step and not _is_list_of_strings(step.get("path_whitelist")):
                errors.append(f"{step_prefix}.path_whitelist must be a list of strings")
            if "allowed_sub_skills" in step and not _is_list_of_strings(step.get("allowed_sub_skills")):
                errors.append(f"{step_prefix}.allowed_sub_skills must be a list of strings")
            if "idempotent" in step and not step_idempotent_is_valid(step):
                errors.append(f"{step_prefix}.idempotent must be true, false, or unknown")

        known_steps = set(step_ids)
        step_graph = skill.get("step_graph")
        if not isinstance(step_graph, dict):
            errors.append(f"{prefix}.step_graph must be an object")
            step_graph = {}

        for source in sorted(step_graph):
            targets = step_graph[source]
            if not isinstance(source, str):
                errors.append(f"{prefix}.step_graph keys must be strings")
                continue
            if source not in known_steps:
                errors.append(f"{prefix}.step_graph.{source} references undefined step")
            if not _is_list_of_strings(targets):
                errors.append(f"{prefix}.step_graph.{source} must be a list of strings")
                continue
            for target in targets:
                if target not in known_steps:
                    errors.append(f"{prefix}.step_graph.{source} references undefined target {target}")

        exit_conditions = skill.get("exit_conditions")
        if not isinstance(exit_conditions, dict):
            errors.append(f"{prefix}.exit_conditions must be an object")
            continue

        must_complete_steps = exit_conditions.get("must_complete_steps")
        if not _is_list_of_strings(must_complete_steps):
            errors.append(f"{prefix}.exit_conditions.must_complete_steps must be a list of strings")
        else:
            for step_id in must_complete_steps:
                if step_id not in known_steps:
                    errors.append(f"{prefix}.exit_conditions.must_complete_steps references undefined step {step_id}")

        min_step_id_at_exit = exit_conditions.get("min_step_id_at_exit")
        if min_step_id_at_exit is not None and not isinstance(min_step_id_at_exit, str):
            errors.append(f"{prefix}.exit_conditions.min_step_id_at_exit must be a string")

    return errors
