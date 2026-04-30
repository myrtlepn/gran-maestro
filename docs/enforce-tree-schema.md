# enforce-tree.json Schema

`hooks/enforce-tree.json` is the single ground truth for mst:* enforcement metadata. It is intentionally plain JSON so `python3 scripts/mst.py enforce verify --strict --json` can validate it deterministically without external dependencies.

## Top-Level Object

- `version`: integer, currently `1`
- `schema_version`: string, currently `enforce-tree-v1`
- `skills`: object keyed by skill name, for example `mst:plan`
- `global_rules`: object containing:
  - `single_active_skill`: boolean
  - `subagent_inherits_parent_whitelist`: boolean
  - `allow_recursive_skill_call`: boolean
  - `max_recursion_depth`: integer

## Skill Object

Each `skills.<name>` entry contains:

- `entry_paths`: list of strings such as `skill_tool`, `slash_command`, and `agent_dispatch`
- `steps`: ordered list of step objects
- `step_graph`: object mapping each step id to a list of next step ids
- `exit_conditions`: object with `must_complete_steps` and optional `min_step_id_at_exit`

`step_graph` must be a DAG. Every `exit_conditions.must_complete_steps` entry must resolve to a defined step and be reachable from a workflow entrypoint. Steps not reachable from a workflow entrypoint are reported as isolated.

## Step Object

Each step requires:

- `id`: non-empty string
- `name`: string
- `required`: boolean
- `path_whitelist`: list of strings
- `allowed_sub_skills`: list of strings
- `idempotent`: JSON boolean `true` or `false`, or string `"unknown"`

The verifier also accepts string `"true"` and `"false"` for forward-compatible fixture handling, but the committed sample uses JSON booleans plus `"unknown"` where needed.

## Placeholder Policy

`path_whitelist` values may include placeholders such as `{PROJECT_ROOT}`, `{AGI_ID}`, `{PLN_ID}`, `{REQ_ID}`, and `{PPID}`. Schema validation treats these as literal strings. Runtime substitution belongs to later hook caller integration, not to `verify --strict`.

## Strict Verify Output

`python3 scripts/mst.py enforce verify --strict --json` returns deterministic JSON with:

- `registered`: number of registered skills
- `graph_dag`: boolean
- `graph_reachable`: boolean
- `graph_isolated_nodes`: list of `skill:step_id` strings
- `idempotent_missing_steps`: list of step ids with missing or invalid `idempotent`
- `errors`: list of validation failures

Exit code is `0` when `errors` is empty and `2` otherwise.
