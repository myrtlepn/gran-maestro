from __future__ import annotations

import argparse

from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    read_workflow_state_auto_mode,
)
from scripts.mst_cmds import request
from scripts.mst_cmds import workflow
from scripts.mst_cmds import worktree
from scripts.mst_cmds import timestamp
from scripts.mst_cmds import set as set_mod
from scripts.mst_cmds import state
from scripts.mst_cmds import state_cmd
from scripts.mst_cmds import queue
from scripts.mst_cmds import measure
from scripts.mst_cmds import plan
from scripts.mst_cmds import intent
from scripts.mst_cmds import fact_check
from scripts.mst_cmds import reference
from scripts.mst_cmds import agile
from scripts.mst_cmds import enforce
from scripts.mst_cmds import counter
from scripts.mst_cmds import archive
from scripts.mst_cmds import gardening
from scripts.mst_cmds import capture
from scripts.mst_cmds import version
from scripts.mst_cmds import context
from scripts.mst_cmds import agents
from scripts.mst_cmds import cleanup
from scripts.mst_cmds import session
from scripts.mst_cmds import priority
from scripts.mst_cmds import task
from scripts.mst_cmds import explore
from scripts.mst_cmds import wait_files
from scripts.mst_cmds import resolve_model
from scripts.mst_cmds import stitch
from scripts.mst_cmds import notify
from scripts.mst_cmds import extension
from scripts.mst_cmds import config
from scripts.mst_cmds import preset
from scripts.mst_cmds import hooks
from scripts.mst_cmds import hook
from scripts.mst_cmds import skill
from scripts.mst_cmds import agile_detail
from scripts.mst_cmds import agile_governance
from scripts.mst_cmds import agile_stop_audit
from scripts.mst_cmds import dispatch
from scripts.mst_cmds import run as run_cmd
from scripts.mst_cmds import prompt
from scripts.mst_cmds import metrics
from scripts.mst_cmds import status
from scripts.mst_cmds import policy
from scripts.mst_cmds import confirm
from scripts.mst_cmds import on as on_cmd
from scripts.mst_cmds import resolver


def set_base_dir(base_dir):
    return _common.set_base_dir(base_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mst.py",
        description="Gran Maestro CLI utility"
    )
    sub = parser.add_subparsers(dest="command")

    request.register(sub)
    workflow.register(sub)
    worktree.register(sub)
    timestamp.register(sub)
    set_mod.register(sub)
    state.register(sub)
    queue.register(sub)
    measure.register(sub)
    plan.register(sub)
    intent.register(sub)
    fact_check.register(sub)
    reference.register(sub)
    agile.register(sub)
    enforce.register(sub)
    counter.register(sub)
    archive.register(sub)
    gardening.register(sub)
    capture.register(sub)
    version.register(sub)
    context.register(sub)
    agents.register(sub)
    cleanup.register(sub)
    session.register(sub)
    priority.register(sub)
    task.register(sub)
    explore.register(sub)
    wait_files.register(sub)
    resolve_model.register(sub)
    stitch.register(sub)
    notify.register(sub)
    extension.register(sub)
    config.register(sub)
    preset.register(sub)
    hooks.register(sub)
    hook.register(sub)
    skill.register(sub)
    dispatch.register(sub)
    run_cmd.register(sub)
    prompt.register(sub)
    metrics.register(sub)
    status.register(sub)
    policy.register(sub)
    confirm.register(sub)
    on_cmd.register(sub)
    resolver.register(sub)

    return parser


DISPATCH = {
    ("request", "list"): request.cmd_request_list,
    ("request", "inspect"): request.cmd_request_inspect,
    ("request", "history"): request.cmd_request_history,
    ("request", "filter"): request.cmd_request_filter,
    ("request", "count"): request.cmd_request_count,
    ("request", "cancel"): request.cmd_request_cancel,
    ("request", "takeover"): request.cmd_request_takeover,
    ("request", "set-phase"): request.cmd_request_set_phase,
    ("request", "review"): request.cmd_request_review,
    ("workflow", "run"): workflow.cmd_workflow_run,
    ("worktree", "create"): worktree.cmd_worktree_create,
    ("worktree", "remove"): worktree.cmd_worktree_remove,
    ("worktree", "resolve-base"): worktree.cmd_worktree_resolve_base,
    ("worktree", "is-protected"): worktree.cmd_worktree_is_protected,
    ("worktree", "slug"): worktree.cmd_worktree_slug,
    ("worktree", "branch-name"): worktree.cmd_worktree_branch_name,
    ("worktree", "path"): worktree.cmd_worktree_path,
    ("worktree", "detect-orphans"): worktree.cmd_worktree_detect_orphans,
    ("worktree", "classify-collision"): worktree.cmd_worktree_classify_collision,
    ("worktree", "archive-retention"): worktree.cmd_worktree_archive_retention,
    ("worktree", "migrate-cleaned-meta"): worktree.cmd_worktree_migrate_cleaned_meta,
    ("worktree", "migrate-archive"): worktree.cmd_worktree_migrate_archive,
    ("timestamp", "now"): timestamp.cmd_timestamp,
    ("set-status", None): set_mod.cmd_set_status,
    ("set-field", None): set_mod.cmd_set_field,
    ("state", "set"): state.cmd_state_set,
    ("state", "set-workflow"): state.cmd_state_set_workflow,
    ("state", "get"): state.cmd_state_get,
    ("state", "clear"): state.cmd_state_clear,
    ("state", "migrate"): state.migrate,
    ("state", "recover"): state.cmd_state_recover,
    ("state", "mark-paused"): state.cmd_state_mark_paused,
    ("state", "resume-paused"): state.cmd_state_resume_paused,
    ("state", "paused-count"): state.cmd_state_paused_count,
    ("state", "validate"): state_cmd.cmd_state_validate,
    ("recover", None): state.cmd_state_recover,
    ("queue", "enqueue"): queue.cmd_queue_enqueue,
    ("queue", "peek"): queue.cmd_queue_peek,
    ("queue", "pop"): queue.cmd_queue_pop,
    ("queue", "list"): queue.cmd_queue_list,
    ("queue", "complete"): queue.cmd_queue_complete,
    ("queue", "fail"): queue.cmd_queue_fail,
    ("queue", "count"): queue.cmd_queue_count,
    ("measure", "stop-rate"): measure.cmd_measure_stop_rate,
    ("plan", "list"): plan.cmd_plan_list,
    ("plan", "count"): plan.cmd_plan_count,
    ("plan", "inspect"): plan.cmd_plan_inspect,
    ("plan", "complete"): plan.cmd_plan_complete,
    ("plan", "takeover"): plan.cmd_plan_takeover,
    ("plan", "sync"): plan.cmd_plan_sync,
    ("plan", "render-review"): plan.cmd_plan_render_review,
    ("plan", "review"): plan.cmd_plan_review,
    ("intent", "add"): intent.cmd_intent_add,
    ("intent", "get"): intent.cmd_intent_get,
    ("intent", "list"): intent.cmd_intent_list,
    ("intent", "update"): intent.cmd_intent_update,
    ("intent", "delete"): intent.cmd_intent_delete,
    ("intent", "search"): intent.cmd_intent_search,
    ("intent", "lookup"): intent.cmd_intent_lookup,
    ("intent", "related"): intent.cmd_intent_related,
    ("intent", "rebuild"): intent.cmd_intent_rebuild,
    ("fact-check", "add"): fact_check.cmd_fact_check_add,
    ("fact-check", "get"): fact_check.cmd_fact_check_get,
    ("fact-check", "list"): fact_check.cmd_fact_check_list,
    ("fact-check", "search"): fact_check.cmd_fact_check_search,
    ("fact-check", "update"): fact_check.cmd_fact_check_update,
    ("fact-check", "claim-update"): fact_check.cmd_fact_check_claim_update,
    ("reference", "add"): reference.cmd_reference_add,
    ("reference", "get"): reference.cmd_reference_get,
    ("reference", "list"): reference.cmd_reference_list,
    ("reference", "search"): reference.cmd_reference_search,
    ("reference", "update"): reference.cmd_reference_update,
    ("agile", "init"): agile.cmd_agile_init,
    ("agile", "status"): agile.cmd_agile_status,
    ("agile", "takeover"): agile.cmd_agile_takeover,
    ("agile", "update"): agile.cmd_agile_update,
    ("agile", "result"): agile.cmd_agile_result,
    ("agile", "diagnose-lock"): agile.cmd_agile_diagnose_lock,
    ("agile", "dispatch-result"): agile.cmd_agile_dispatch_result,
    ("agile", "sprint-close"): agile.cmd_agile_sprint_close,
    ("agile", "retrospective"): agile.cmd_agile_retrospective,
    ("agile", "known-issues"): agile.cmd_agile_known_issues,
    ("agile", "review"): agile.cmd_agile_review,
    ("agile", "detail"): agile_detail.cmd_agile_detail,
    ("agile", "evidence-check"): agile_detail.cmd_agile_evidence_check,
    ("agile", "drift-check"): agile_detail.cmd_agile_drift_check,
    ("agile", "recall"): agile_governance.cmd_agile_recall,
    ("agile", "classify-change"): agile_governance.cmd_agile_classify_change,
    ("agile", "unlock"): agile_governance.cmd_agile_unlock,
    ("agile", "revalidate-done"): agile_governance.cmd_agile_revalidate_done,
    ("agile", "coverage-check"): agile_detail.cmd_agile_coverage_check,
    ("agile", "objective-transition"): agile_governance.cmd_agile_objective_transition,
    ("agile", "objective-check"): agile_governance.cmd_agile_objective_check,
    ("agile", "objective-snapshot"): agile_governance.cmd_agile_objective_snapshot,
    ("agile", "link"): agile_detail.cmd_agile_link,
    ("agile", "integration-review"): agile_detail.cmd_agile_integration_review,
    ("agile", "alignment-package"): agile_detail.cmd_agile_alignment_package,
    ("agile", "stop-audit"): agile_stop_audit.cmd_agile_stop_audit,
    ("enforce", "verify"): enforce.cmd_enforce_verify,
    ("counter", "next"): counter.cmd_counter_next,
    ("counter", "peek"): counter.cmd_counter_peek,
    ("version", "get"): version.cmd_version_get,
    ("version", "check"): version.cmd_version_check,
    ("version", "bump"): version.cmd_version_bump,
    ("context", "gather"): context.cmd_context_gather,
    ("agents", "check"): agents.cmd_agents_check,
    ("agents", "sync"): agents.cmd_agents_sync,
    ("capture", "ttl-check"): capture.cmd_capture_ttl_check,
    ("capture", "mark-consumed"): capture.cmd_capture_mark_consumed,
    ("archive", "run"): archive.cmd_archive_run,
    ("archive", "run-all"): archive.cmd_archive_run_all,
    ("archive", "list"): archive.cmd_archive_list,
    ("archive", "restore"): archive.cmd_archive_restore,
    ("archive", "purge"): archive.cmd_archive_purge,
    ("gardening", "scan"): gardening.cmd_gardening_scan,
    ("gardening", "auto-archive"): gardening.cmd_gardening_auto_archive,
    ("gardening", "restore"): gardening.cmd_gardening_restore,
    ("cleanup", None): cleanup.cmd_cleanup,
    ("session", "list"): session.cmd_session_list,
    ("session", "inspect"): session.cmd_session_inspect,
    ("session", "complete"): session.cmd_session_complete,
    ("session", "resolve"): session.cmd_session_resolve,
    ("session", "split-prompts"): session.cmd_session_split_prompts,
    ("priority", None): priority.cmd_priority,
    ("task", "set-commit"): task.cmd_task_set_commit,
    ("explore", "index"): explore.cmd_explore_index,
    ("notify", None): notify.cmd_notify,
    ("stitch", "sleep"): stitch.cmd_stitch_sleep,
    ("wait-files", None): wait_files.cmd_wait_files,
    ("resolve-model", None): resolve_model.cmd_resolve_model,
    ("extension", "ensure-copy"): extension.cmd_extension_ensure_copy,
    ("config", "resolve"): config.cmd_config_resolve,
    ("config", "get"): config.cmd_config_get,
    ("config", "set"): config.cmd_config_set,
    ("config", "migrate"): config.cmd_config_migrate,
    ("preset", "list"): preset.cmd_preset_list,
    ("preset", "apply"): preset.cmd_preset_apply,
    ("preset", "diff"): preset.cmd_preset_diff,
    ("preset", "save"): preset.cmd_preset_save,
    ("hooks", "post-skill"): hooks.cmd_hooks_post_skill,
    ("hooks", "sync"): hooks.cmd_hooks_sync,
    ("hooks", "doctor"): hooks.doctor,
    ("hook", "repair"): hook.cmd_hook_repair,
    ("hook", "log"): hook.cmd_hook_log,
    ("hook", "allow"): hook.cmd_hook_allow,
    ("history", "log"): hook.cmd_history_log,
    ("history", "verify"): hook.cmd_history_verify,
    ("history", "head"): hook.cmd_history_head,
    ("skill", "build"): skill.cmd_skill_build,
    ("skill", "scaffold"): skill.cmd_skill_scaffold,
    ("dispatch", "build"): dispatch.cmd_dispatch_build,
    ("dispatch", "preflight"): dispatch.cmd_dispatch_preflight,
    ("dispatch", "register"): dispatch.cmd_dispatch_register,
    ("dispatch", "heartbeat"): dispatch.cmd_dispatch_heartbeat,
    ("dispatch", "list"): dispatch.cmd_dispatch_list,
    ("dispatch", "kill"): dispatch.cmd_dispatch_kill,
    ("dispatch", "cleanup"): dispatch.cmd_dispatch_cleanup,
    ("run", None): run_cmd.cmd_run,
    ("prompt", "build"): prompt.cmd_prompt_build,
    ("prompt", "validate"): prompt.cmd_prompt_validate,
    ("prompt", "write-context"): prompt.cmd_prompt_write_context,
    ("metrics", "summary"): metrics.cmd_metrics_summary,
    ("status", "context-usage"): status.cmd_status_context_usage,
    ("policy", "init"): policy.cmd_policy_init,
    ("policy", "list"): policy.cmd_policy_list,
    ("policy", "verify"): policy.cmd_policy_verify,
    ("confirm", None): confirm.cmd_confirm,
    ("on", "cleanup"): on_cmd.cmd_on_cleanup,
    ("resolve-next-action", None): resolver.resolve_next_action,
}
