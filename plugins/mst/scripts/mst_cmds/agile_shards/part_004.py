def register(subparsers):
    sub = subparsers
    agile = sub.add_parser("agile")
    agile_sub = agile.add_subparsers(dest="subcommand")

    agile_init = agile_sub.add_parser("init")
    agile_init.add_argument("--steering-every", type=int, default=3)
    agile_init.add_argument("--json", action="store_true")

    agile_status = agile_sub.add_parser("status")
    agile_status.add_argument("agi_id")
    agile_status.add_argument("--json", action="store_true")

    agile_takeover = agile_sub.add_parser("takeover")
    agile_takeover.add_argument("--agi", required=True)

    agile_update = agile_sub.add_parser("update")
    agile_update.add_argument("agi_id")
    agile_update.add_argument("--status")
    agile_update.add_argument("--current-sprint", type=int)
    agile_update.add_argument("--steering-every", type=int)
    agile_update.add_argument("--objective-version", type=int)
    agile_update.add_argument("--user-requested", action="store_true",
        help="사용자가 직접 요청한 pause 전환임을 표시 (LLM 자발 정지 방지 게이트 우회)")
    agile_update.add_argument("--force", action="store_true", help="completion guard 우회")
    agile_update.add_argument("--json", action="store_true")

    agile_result = agile_sub.add_parser("result")
    agile_result.add_argument("agi_id")
    agile_result.add_argument("--sprint", type=int, required=True)
    agile_result.add_argument("--status", required=True)
    agile_result.add_argument("--planned")
    agile_result.add_argument("--completed")
    agile_result.add_argument("--pln", action="append")
    agile_result.add_argument("--req", action="append")
    agile_result.add_argument("--summary")
    agile_result.add_argument("--outcome")
    agile_result.add_argument("--sprint-goals")
    agile_result.add_argument("--sprint-purpose")
    agile_result.add_argument("--selection-reason")
    agile_result.add_argument("--target-dod")
    agile_result.add_argument("--target-dod-text")
    agile_result.add_argument("--dod-ref", default=None)
    agile_result.add_argument("--domain", default=None)
    agile_result.add_argument("--previous-direction")
    agile_result.add_argument("--previous-lessons")
    agile_result.add_argument(
        "--sprint-kind",
        choices=["user_observable", "foundational"],
        default="user_observable",
    )
    agile_result.add_argument("--user-observable-change", dest="user_observable_change")
    agile_result.add_argument("--foundational-reason", dest="foundational_reason")
    agile_result.add_argument("--json", action="store_true")

    agile_diagnose_lock = agile_sub.add_parser("diagnose-lock")
    agile_diagnose_lock.add_argument("--lock-kind", choices=["history", "result"], default="history")
    agile_diagnose_lock.add_argument("--lock-path")
    agile_diagnose_lock.add_argument("--session-id")
    agile_diagnose_lock.add_argument("--agi-id")
    agile_diagnose_lock.add_argument("--sprint", type=int)
    agile_diagnose_lock.add_argument("--sprint-id")
    agile_diagnose_lock.add_argument("--stale-after-sec", type=int, default=STALE_LOCK_SECONDS)

    agile_dispatch_result = agile_sub.add_parser("dispatch-result")
    agile_dispatch_result.add_argument("agi_id")
    agile_dispatch_result.add_argument("--sprint", type=int, required=True)
    agile_dispatch_result.add_argument("--status", required=True, choices=["success", "failed"])
    agile_dispatch_result.add_argument("--exit-code", type=int, required=True, dest="exit_code")
    agile_dispatch_result.add_argument("--pln")
    agile_dispatch_result.add_argument("--req")
    agile_dispatch_result.add_argument("--commit-sha", dest="commit_sha")
    agile_dispatch_result.add_argument("--sprint-kind", dest="sprint_kind")
    agile_dispatch_result.add_argument("--failure-reason", dest="failure_reason")
    agile_dispatch_result.add_argument(
        "--result-recorded",
        type=_common._parse_bool_arg,
        default=True,
        metavar="{true,false}",
        dest="result_recorded",
    )
    agile_dispatch_result.add_argument(
        "--retrospective-recorded",
        type=_common._parse_bool_arg,
        default=True,
        metavar="{true,false}",
        dest="retrospective_recorded",
    )
    agile_dispatch_result.add_argument("--json", action="store_true")

    agile_finalize = agile_sub.add_parser("finalize")
    agile_finalize.add_argument("agi_id")
    agile_finalize.add_argument("--json", action="store_true")

    parent_module = sys.modules.get("scripts.mst_cmds")
    dispatch = getattr(parent_module, "DISPATCH", None)
    if isinstance(dispatch, dict):
        dispatch.setdefault(("agile", "finalize"), cmd_agile_finalize)
        dispatch.setdefault(("agile", "diagnose-lock"), cmd_agile_diagnose_lock)

    agile_sprint_close = agile_sub.add_parser("sprint-close")
    agile_sprint_close.add_argument("agi_id")
    agile_sprint_close.add_argument("--sprint", type=int, required=True)
    agile_sprint_close.add_argument("--base")
    agile_sprint_close.add_argument("--branch")
    agile_sprint_close.add_argument("--worktree-path", dest="worktree_path")
    agile_sprint_close.add_argument("--dry-run", action="store_true", dest="dry_run")
    agile_sprint_close.add_argument("--json", action="store_true")
    agile_sprint_close.add_argument("--message")

    agile_retrospective = agile_sub.add_parser("retrospective")
    agile_retrospective.add_argument("agi_id")
    agile_retrospective.add_argument("--sprint", type=int, required=True)
    agile_retrospective.add_argument("--status", required=True)
    agile_retrospective.add_argument("--succeeded", action="append", required=False, default=None)
    agile_retrospective.add_argument("--failed", action="append", required=False, default=None)
    agile_retrospective.add_argument("--velocity-planned", type=int, required=True)
    agile_retrospective.add_argument("--velocity-completed", type=int, required=True)
    agile_retrospective.add_argument("--limitations", required=False, default="")
    agile_retrospective.add_argument("--lessons", required=True)
    agile_retrospective.add_argument("--direction", required=True)
    agile_retrospective.add_argument("--json", action="store_true")

    agile_known_issues = agile_sub.add_parser("known-issues")
    agile_known_issues_sub = agile_known_issues.add_subparsers(dest="known_issues_subcommand")

    agile_known_issues_add = agile_known_issues_sub.add_parser("add")
    agile_known_issues_add.add_argument("agi_id")
    agile_known_issues_add.add_argument("--description", required=True)
    agile_known_issues_add.add_argument(
        "--severity",
        required=True,
        choices=["MINOR", "MAJOR", "CRITICAL"],
    )
    agile_known_issues_add.add_argument("--sprint", type=int, required=True)
    agile_known_issues_add.add_argument("--json", action="store_true")

    agile_known_issues_resolve = agile_known_issues_sub.add_parser("resolve")
    agile_known_issues_resolve.add_argument("agi_id")
    agile_known_issues_resolve.add_argument("--issue-id", required=True)
    agile_known_issues_resolve.add_argument("--json", action="store_true")

    agile_known_issues_list = agile_known_issues_sub.add_parser("list")
    agile_known_issues_list.add_argument("agi_id")
    agile_known_issues_list.add_argument("--status", choices=["open", "resolved"])
    agile_known_issues_list.add_argument("--json", action="store_true")

    agile_review = agile_sub.add_parser("review")
    agile_review.add_argument("--agi", dest="agi_id", required=True)
    agile_review.add_argument("--perspective", required=True, choices=ADVERSARIAL_REVIEW_PERSPECTIVES)
    agile_review.add_argument("--json", action="store_true", required=True)

    agile_detail = agile_sub.add_parser("detail")
    agile_detail_sub = agile_detail.add_subparsers(dest="detail_subcommand")

    agile_detail_validate_mapping = agile_detail_sub.add_parser("validate-mapping")
    agile_detail_validate_mapping.add_argument("details_path")
    agile_detail_validate_mapping.add_argument("--json", action="store_true")

    agile_detail_validate_evidence = agile_detail_sub.add_parser("validate-evidence")
    agile_detail_validate_evidence.add_argument("details_path")
    agile_detail_validate_evidence.add_argument("--json", action="store_true")

    agile_detail_append = agile_detail_sub.add_parser("append")
    agile_detail_append.add_argument("--domain", required=True)
    agile_detail_append.add_argument("--chunk-id", type=int, required=True, dest="chunk_id")
    agile_detail_append.add_argument("--content-file", required=True, dest="content_file")
    agile_detail_append.add_argument("--target-dir", default=".", dest="target_dir")
    agile_detail_append.add_argument("--json", action="store_true")

    agile_detail_generate_anchors = agile_detail_sub.add_parser("generate-anchors")
    agile_detail_generate_anchors.add_argument("--details-dir", required=True, dest="details_dir")
    agile_detail_generate_anchors.add_argument("--output")
    agile_detail_generate_anchors.add_argument("--json", action="store_true")

    agile_evidence_check = agile_sub.add_parser("evidence-check")
    agile_evidence_check_scope = agile_evidence_check.add_mutually_exclusive_group(required=True)
    agile_evidence_check_scope.add_argument("--sprint")
    agile_evidence_check_scope.add_argument("--details-dir", dest="details_dir")
    agile_evidence_check.add_argument("--agi-id", dest="agi_id")
    agile_evidence_check.add_argument("--accept-evidence-gap", dest="accept_evidence_gap")
    agile_evidence_check.add_argument("--json", action="store_true")

    agile_drift_check = agile_sub.add_parser("drift-check")
    agile_drift_check_scope = agile_drift_check.add_mutually_exclusive_group(required=True)
    agile_drift_check_scope.add_argument("--sprint")
    agile_drift_check_scope.add_argument("--details-dir", dest="details_dir")
    agile_drift_check.add_argument("--agi-id", dest="agi_id")
    agile_drift_check.add_argument("--json", action="store_true")

    agile_recall = agile_sub.add_parser("recall")
    agile_recall.add_argument("--agi-id", dest="agi_id")
    agile_recall.add_argument("--level", type=int, default=2)
    agile_recall.add_argument("--reason", required=True, choices=["fail", "drift"])
    agile_recall.add_argument("--trigger", default="")
    agile_recall.add_argument("--approval-ticket", dest="approval_ticket")
    agile_recall.add_argument("--bypass-cooldown", action="store_true", dest="bypass_cooldown")
    agile_recall.add_argument("--fingerprint")
    agile_recall.add_argument("--json", action="store_true")

    agile_classify_change = agile_sub.add_parser("classify-change")
    agile_classify_change.add_argument("manifest")

    agile_unlock = agile_sub.add_parser("unlock")
    agile_unlock.add_argument("--dod", required=True)
    agile_unlock.add_argument(
        "--category",
        required=True,
        choices=[
            "upstream_evidence_changed",
            "integration_regression",
            "new_dependency_dod",
            "objective_precision_fix",
        ],
    )
    agile_unlock.add_argument("--reason")
    agile_unlock.add_argument("--evidence")
    agile_unlock.add_argument("--agi-id", dest="agi_id")
    agile_unlock.add_argument("--json", action="store_true")

    agile_revalidate_done = agile_sub.add_parser("revalidate-done")
    agile_revalidate_done.add_argument("dod")
    agile_revalidate_done.add_argument("--agi-id", dest="agi_id")
    agile_revalidate_done.add_argument("--json", action="store_true")

    agile_coverage_check = agile_sub.add_parser("coverage-check")
    agile_coverage_check.add_argument("original_path")
    agile_coverage_check.add_argument("--details-dir", required=True, dest="details_dir")
    agile_coverage_check.add_argument("--threshold", type=float)
    agile_coverage_check.add_argument("--anchor-manifest", dest="anchor_manifest")
    agile_coverage_check.add_argument("--downstream-trace", dest="downstream_trace")
    agile_coverage_check.add_argument("--json", action="store_true")

    agile_objective_transition = agile_sub.add_parser("objective-transition")
    agile_objective_transition.add_argument("agi_id")
    agile_objective_transition.add_argument("--story", required=True)
    agile_objective_transition.add_argument("--status", required=True)
    agile_objective_transition.add_argument("--deferred-promote", action="store_true")
    agile_objective_transition.add_argument("--sprint", type=int)
    agile_objective_transition.add_argument("--evidence-ref", action="append", default=[])
    agile_objective_transition.add_argument("--json", action="store_true")

    agile_objective_check = agile_sub.add_parser("objective-check")
    agile_objective_check.add_argument("agi_id")
    agile_objective_check.add_argument("--dod-id", default=None)
    agile_objective_check.add_argument("--json", action="store_true")

    agile_objective_snapshot = agile_sub.add_parser("objective-snapshot")
    agile_objective_snapshot.add_argument("agi_id")
    agile_objective_snapshot.add_argument("--reason", required=True)
    agile_objective_snapshot.add_argument("--json", action="store_true")

    agile_link = agile_sub.add_parser("link")
    agile_link.add_argument("agi_id")
    agile_link.add_argument("--pln", action="append")
    agile_link.add_argument("--req", action="append")
    agile_link.add_argument("--json", action="store_true")

    agile_integration_review = agile_sub.add_parser("integration-review")
    agile_integration_review.add_argument("agi_id")
    agile_integration_review.add_argument("--sprint", type=int, required=True)
    agile_integration_review.add_argument("--depth", type=int, default=None)
    agile_integration_review.add_argument("--threshold", type=float, default=None)
    agile_integration_review.add_argument("--escape-reason", default=None)
    agile_integration_review.add_argument("--reference-pattern", default=None)
    agile_integration_review.add_argument("--json", action="store_true")

    agile_alignment_package = agile_sub.add_parser("alignment-package")
    agile_alignment_package.add_argument("agi_id")
    agile_alignment_package.add_argument("--sprint", type=int, required=True)
    agile_alignment_package.add_argument("--depth", type=int, default=3)
    agile_alignment_package.add_argument("--json", action="store_true")

    agile_stop_audit = agile_sub.add_parser("stop-audit")
    agile_stop_audit_sub = agile_stop_audit.add_subparsers(dest="stop_audit_subcommand")
    agile_stop_audit_list = agile_stop_audit_sub.add_parser("list")
    agile_stop_audit_list.add_argument("--agi", required=True)
    agile_stop_audit_list.add_argument("--classification", choices=["blocked", "allowed", "pass_through"])
    agile_stop_audit_list.add_argument("--json", action="store_true")
    agile_stop_audit_aggregate = agile_stop_audit_sub.add_parser("aggregate")
    agile_stop_audit_aggregate.add_argument("--agi", required=True)
    agile_stop_audit_aggregate.add_argument(
        "--group-by",
        required=True,
        choices=["declared_reason", "classification"],
    )
