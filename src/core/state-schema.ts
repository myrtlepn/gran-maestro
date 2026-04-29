/**
 * Single source-of-truth task state schema shared across TS and Python.
 */

export const TASK_STATUSES = [
  "pending",
  "queued",
  "executing",
  "pre_check",
  "pre_check_failed",
  "review",
  "feedback",
  "merging",
  "merge_conflict",
  "done",
  "failed",
  "cancelled"
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

export const TERMINAL = [
  "done",
  "failed",
  "cancelled"
] as const;

export const TRANSITIONS = [
  {
    "from": "pending",
    "to": "queued",
    "condition": "PM decides execution order",
    "guard": "no pending predecessors or predecessors completed"
  },
  {
    "from": "queued",
    "to": "executing",
    "condition": "Parallel slot available",
    "guard": "active_tasks < max_parallel_tasks"
  },
  {
    "from": "executing",
    "to": "pre_check",
    "condition": "CLI exit code === 0",
    "guard": "commit exists in worktree"
  },
  {
    "from": "executing",
    "to": "failed",
    "condition": "CLI exit code !== 0 and retries exhausted",
    "guard": "retry_count >= max_retries"
  },
  {
    "from": "pre_check",
    "to": "review",
    "condition": "Typecheck + tests pass"
  },
  {
    "from": "pre_check",
    "to": "pre_check_failed",
    "condition": "Typecheck or tests fail"
  },
  {
    "from": "pre_check_failed",
    "to": "executing",
    "condition": "Auto retry with feedback attached",
    "guard": "retry_count < max_retries"
  },
  {
    "from": "pre_check_failed",
    "to": "feedback",
    "condition": "Retries exhausted",
    "guard": "retry_count >= max_retries"
  },
  {
    "from": "review",
    "to": "feedback",
    "condition": "FAIL or PARTIAL verdict"
  },
  {
    "from": "review",
    "to": "merging",
    "condition": "PASS verdict -- all acceptance criteria met, proceed to merge"
  },
  {
    "from": "feedback",
    "to": "executing",
    "condition": "Root cause classified as implementation error"
  },
  {
    "from": "feedback",
    "to": "pending",
    "condition": "Root cause classified as insufficient spec"
  },
  {
    "from": "merging",
    "to": "done",
    "condition": "Merge succeeded"
  },
  {
    "from": "merging",
    "to": "merge_conflict",
    "condition": "Merge conflict detected"
  },
  {
    "from": "*",
    "to": "cancelled",
    "condition": "/mc invoked",
    "guard": "CLI process receives SIGTERM"
  },
  {
    "from": "*",
    "to": "failed",
    "condition": "Unrecoverable system error"
  }
] as const;

export const RECOVERY_ACTIONS = [
  "retry",
  "rollback",
  "manual",
  "abort"
] as const;

const LEGACY_DONE_STATUSES = new Set(["completed", "accepted"]);
const LEGACY_MIGRATION_WARNED = new Set<string>();

function warnLegacyMigration(rawStatus: string): void {
  const dedupeKey = rawStatus.toLowerCase();
  if (LEGACY_MIGRATION_WARNED.has(dedupeKey)) {
    return;
  }
  LEGACY_MIGRATION_WARNED.add(dedupeKey);
  const processLike = (globalThis as { process?: { stderr?: { write?: (chunk: string) => unknown } } }).process;
  processLike?.stderr?.write?.(`[mst-state] migrated '${rawStatus}' → 'done'\n`);
}

export function migrateLegacyStatus(rawStatus: string): TaskStatus {
  if (LEGACY_DONE_STATUSES.has(rawStatus.toLowerCase())) {
    warnLegacyMigration(rawStatus);
    return "done";
  }
  return rawStatus as TaskStatus;
}
