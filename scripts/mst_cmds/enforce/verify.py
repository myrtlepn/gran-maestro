from __future__ import annotations

import json
from collections import deque
from typing import Any

from scripts.mst_cmds.enforce._tree import (
    EnforceTreeError,
    load_tree,
    step_idempotent_is_valid,
    validate_schema_shape,
)


def _base_result(registered: int = 0) -> dict[str, Any]:
    return {
        "registered": registered,
        "graph_dag": True,
        "graph_reachable": True,
        "graph_isolated_nodes": [],
        "idempotent_missing_steps": [],
        "errors": [],
    }


def _emit_json(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _skill_steps(skill: dict[str, Any]) -> list[dict[str, Any]]:
    steps = skill.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _step_ids(skill: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for step in _skill_steps(skill):
        step_id = step.get("id")
        if isinstance(step_id, str) and step_id:
            ids.append(step_id)
    return ids


def _adjacency(skill: dict[str, Any], step_ids: list[str]) -> dict[str, list[str]]:
    known = set(step_ids)
    graph = skill.get("step_graph")
    adjacency = {step_id: [] for step_id in step_ids}
    if not isinstance(graph, dict):
        return adjacency
    for source in step_ids:
        targets = graph.get(source, [])
        if isinstance(targets, list):
            adjacency[source] = [target for target in targets if isinstance(target, str) and target in known]
    return adjacency


def _find_cycle(adjacency: dict[str, list[str]], ordered_nodes: list[str]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> list[str]:
        visiting.add(node)
        stack.append(node)
        for target in adjacency.get(node, []):
            if target in visited:
                continue
            if target in visiting:
                start = stack.index(target)
                return stack[start:] + [target]
            cycle = dfs(target)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in ordered_nodes:
        if node in visited:
            continue
        cycle = dfs(node)
        if cycle:
            return cycle
    return []


def _reachable_from(starts: list[str], adjacency: dict[str, list[str]]) -> set[str]:
    reached: set[str] = set()
    queue: deque[str] = deque(starts)
    while queue:
        node = queue.popleft()
        if node in reached:
            continue
        reached.add(node)
        for target in adjacency.get(node, []):
            if target not in reached:
                queue.append(target)
    return reached


def _entry_candidates(adjacency: dict[str, list[str]], ordered_nodes: list[str]) -> list[str]:
    indegree = {node: 0 for node in ordered_nodes}
    for targets in adjacency.values():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    return [node for node in ordered_nodes if indegree[node] == 0]


def _workflow_entrypoints(
    candidates: list[str],
    must_complete_steps: list[str],
    adjacency: dict[str, list[str]],
) -> list[str]:
    viable_candidates = [
        candidate
        for candidate in candidates
        if adjacency.get(candidate) or len(candidates) == 1
    ]
    known_must = [step for step in must_complete_steps if step in adjacency]
    if not known_must:
        return viable_candidates
    entries = []
    for candidate in viable_candidates:
        reached = _reachable_from([candidate], adjacency)
        if any(step in reached for step in known_must):
            entries.append(candidate)
    return entries


def _must_complete_steps(skill: dict[str, Any]) -> list[str]:
    exit_conditions = skill.get("exit_conditions")
    if not isinstance(exit_conditions, dict):
        return []
    steps = exit_conditions.get("must_complete_steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, str)]


def _idempotent_issues(skill_name: str, skill: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for index, step in enumerate(_skill_steps(skill)):
        if not step_idempotent_is_valid(step):
            step_id = step.get("id")
            issues.append(step_id if isinstance(step_id, str) and step_id else f"{skill_name}:step[{index}]")
    return issues


def verify_strict(tree: Any) -> dict[str, Any]:
    skills = tree.get("skills") if isinstance(tree, dict) else {}
    skills = skills if isinstance(skills, dict) else {}
    result = _base_result(registered=len(skills))

    schema_errors = validate_schema_shape(tree)
    result["errors"].extend(schema_errors)

    for skill_name in sorted(skills):
        skill = skills[skill_name]
        if not isinstance(skill, dict):
            continue

        idempotent_issues = _idempotent_issues(skill_name, skill)
        if idempotent_issues:
            result["idempotent_missing_steps"].extend(idempotent_issues)
            result["errors"].append(
                f"idempotent missing or invalid in {skill_name}: {', '.join(idempotent_issues)}"
            )

        step_ids = _step_ids(skill)
        adjacency = _adjacency(skill, step_ids)

        cycle = _find_cycle(adjacency, step_ids)
        if cycle:
            result["graph_dag"] = False
            result["errors"].append(f"cycle detected in {skill_name}: {' -> '.join(cycle)}")

        must_complete = _must_complete_steps(skill)
        candidates = _entry_candidates(adjacency, step_ids)
        entrypoints = _workflow_entrypoints(candidates, must_complete, adjacency)
        reached = _reachable_from(entrypoints, adjacency)

        unreachable = [step for step in must_complete if step not in reached]
        if unreachable:
            result["graph_reachable"] = False
            result["errors"].append(
                f"unreachable must_complete_steps in {skill_name}: {', '.join(unreachable)}"
            )

        isolated = [step for step in step_ids if step not in reached and step not in entrypoints]
        if isolated:
            result["graph_isolated_nodes"].extend(f"{skill_name}:{step}" for step in isolated)
            result["errors"].append(f"isolated steps in {skill_name}: {', '.join(isolated)}")

    result["graph_isolated_nodes"] = _ordered_unique(result["graph_isolated_nodes"])
    result["idempotent_missing_steps"] = _ordered_unique(result["idempotent_missing_steps"])
    return result


def cmd_enforce_verify(args) -> int:
    result = _base_result()
    if not getattr(args, "strict", False):
        result["errors"].append("verify currently requires --strict")
        _emit_json(result)
        return 2

    try:
        _, tree = load_tree(getattr(args, "tree", None))
    except EnforceTreeError as exc:
        result["errors"].append(str(exc))
        _emit_json(result)
        return 2

    result = verify_strict(tree)
    _emit_json(result)
    return 0 if not result["errors"] else 2
