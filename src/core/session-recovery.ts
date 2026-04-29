/**
 * Session recovery protocol for Gran Maestro.
 *
 * When a Claude Code session terminates unexpectedly, the file-based
 * state allows the engine to detect in-progress work and offer
 * recovery options on the next session start.
 *
 * @module session-recovery
 * @see design-decisions.md section 9
 */

import type { TaskStatus } from './task-fsm.ts';
import type { WorktreeState } from './worktree-manager.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Snapshot of a task that was found in a non-terminal state after a session crash. */
export interface RecoverableTask {
  /** Task identifier (e.g. "REQ-001-01"). */
  taskId: string;
  /** Parent request identifier (e.g. "REQ-001"). */
  reqId: string;
  /** Last known status before the session ended. */
  lastStatus: TaskStatus;
  /** Derived request-level phase at the time of the crash. */
  lastPhase: string;
  /** Worktree path associated with the task. */
  worktreePath: string;
  /** Whether a CLI process is still running for this task. */
  hasRunningProcess: boolean;
  /** Absolute path to `.gran-maestro/requests` used to resolve task status path. */
  basePath: string;
}

/**
 * Action the recovery engine can take for a given task.
 *
 * Derived from the decision table in design-decisions.md lines 579-585.
 */
export type RecoveryAction =
  | 'resume_monitoring'  // Process is still alive -- reattach log stream
  | 're_execute'         // Process is dead and task was executing -- restart CLI
  | 'resume_review'      // Task was in review -- reopen review flow
  | 'resume_feedback'    // Task had pending feedback -- re-trigger execution
  | 're_queue'           // Task was queued -- put it back in the queue
  | 'resolve_conflict_interactive'  // merge_conflict -- user resolves manually then resumes
  | 'abort_and_revert'              // merge_conflict -- abort merge and revert to prior state
  | 'user_decision';     // Ambiguous state -- ask the user

// ---------------------------------------------------------------------------
// Scanning
// ---------------------------------------------------------------------------

/** Terminal statuses that do not require recovery. */
const TERMINAL: ReadonlySet<string> = new Set(['done', 'failed', 'cancelled']);

/**
 * Scan the `.gran-maestro/requests/` directory tree for tasks that are
 * in a non-terminal state (i.e. they were in progress when the session died).
 *
 * @param basePath - Absolute path to `.gran-maestro/requests`.
 * @returns An array of {@link RecoverableTask} objects.
 */
export async function scanForRecoverableTasks(
  basePath: string,
): Promise<RecoverableTask[]> {
  const tasks: RecoverableTask[] = [];

  try {
    // Node.js fallback: fs.promises.readdir
    for await (const reqEntry of Deno.readDir(basePath)) {
      if (!reqEntry.isDirectory || !reqEntry.name.startsWith('REQ-')) continue;

      const reqId = reqEntry.name;
      const tasksDir = `${basePath}/${reqId}/tasks`;

      try {
        for await (const taskEntry of Deno.readDir(tasksDir)) {
          if (!taskEntry.isDirectory) continue;

          const taskNum = taskEntry.name;
          const statusPath = `${tasksDir}/${taskNum}/status.json`;

          try {
            // Node.js fallback: fs.promises.readFile
            const raw = await Deno.readTextFile(statusPath);
            const statusData = JSON.parse(raw) as {
              status?: string;
              phase?: string;
              worktree_path?: string;
            };

            const lastStatus = (statusData.status ?? 'unknown') as TaskStatus;

            if (TERMINAL.has(lastStatus)) continue;

            const taskId = `${reqId}-${taskNum}`;
            const worktreePath =
              statusData.worktree_path ??
              `.gran-maestro/worktrees/${taskId}`;

            // Check if a process is still running (best-effort)
            const hasRunningProcess = await checkProcessRunning(worktreePath);

            tasks.push({
              taskId,
              reqId,
              lastStatus,
              lastPhase: statusData.phase ?? 'unknown',
              worktreePath,
              hasRunningProcess,
              basePath,
            });
          } catch {
            // status.json missing or corrupt -- skip
          }
        }
      } catch {
        // tasks/ directory missing -- skip
      }
    }
  } catch {
    // requests/ directory missing -- nothing to recover
  }

  return tasks;
}

/**
 * Best-effort check for a running CLI process associated with a worktree.
 *
 * @param worktreePath - Path pattern to search for in process arguments.
 * @returns `true` if a matching process is found.
 */
async function checkProcessRunning(worktreePath: string): Promise<boolean> {
  try {
    const command = new Deno.Command('pgrep', {
      args: ['-f', worktreePath],
      stdout: 'piped',
      stderr: 'piped',
    });
    const output = await command.output();
    return output.code === 0;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Recovery decision
// ---------------------------------------------------------------------------

/**
 * Determine the appropriate recovery action for a task based on its
 * last known status and whether its CLI process is still alive.
 *
 * @param task - A recoverable task snapshot.
 * @returns The recommended {@link RecoveryAction}.
 */
export function determineRecoveryAction(task: RecoverableTask): RecoveryAction {
  switch (task.lastStatus) {
    case 'executing':
      return task.hasRunningProcess ? 'resume_monitoring' : 're_execute';

    case 'pre_check':
    case 'pre_check_failed':
      return 're_execute';

    case 'review':
      return 'resume_review';

    case 'feedback':
      return 'resume_feedback';

    case 'queued':
    case 'pending':
      return 're_queue';

    case 'merge_conflict':
      return 'resolve_conflict_interactive';

    case 'merging':
      return 'user_decision';

    default:
      return 'user_decision';
  }
}

/**
 * Return the explicit alternative actions a user may choose when a task is in
 * `merge_conflict`. The first element is the recommended primary action; the
 * second is the fallback (abort the merge entirely).
 */
export function getMergeConflictAlternatives(
  _task: RecoverableTask,
): RecoveryAction[] {
  return ['resolve_conflict_interactive', 'abort_and_revert'];
}

// ---------------------------------------------------------------------------
// Recovery execution
// ---------------------------------------------------------------------------

/**
 * Execute a recovery action for a task.
 *
 * This is a dispatcher that updates the task's status file to reflect
 * the chosen recovery path. The actual re-execution / review resumption
 * is handled by the orchestration engine which reads the updated status.
 *
 * @param task   - The recoverable task.
 * @param action - The chosen recovery action.
 */
export async function recoverTask(
  task: RecoverableTask,
  action: RecoveryAction,
): Promise<void> {
  // Resolve the status file path from the task ID
  // e.g. "REQ-001-01" -> reqId="REQ-001", taskNum="01"
  const parts = task.taskId.split('-');
  const taskNum = parts[parts.length - 1];
  const reqId = parts.slice(0, -1).join('-');
  const statusPath = `${task.basePath}/requests/${reqId}/tasks/${taskNum}/status.json`;

  let newStatus: string;
  let recoveryNote: string;

  switch (action) {
    case 'resume_monitoring':
      newStatus = 'executing';
      recoveryNote = 'Resumed monitoring of existing process';
      break;
    case 're_execute':
      newStatus = 'queued';
      recoveryNote = 'Re-queued for execution after session recovery';
      break;
    case 'resume_review':
      newStatus = 'review';
      recoveryNote = 'Resumed review after session recovery';
      break;
    case 'resume_feedback':
      newStatus = 'feedback';
      recoveryNote = 'Resumed feedback processing after session recovery';
      break;
    case 're_queue':
      newStatus = 'queued';
      recoveryNote = 'Re-queued after session recovery';
      break;
    case 'resolve_conflict_interactive':
      newStatus = 'executing';
      recoveryNote = 'User chose interactive conflict resolution';
      break;
    case 'abort_and_revert':
      newStatus = 'failed';
      recoveryNote = 'User chose to abort merge and revert';
      break;
    case 'user_decision':
      // Do not change status -- the user will decide
      newStatus = task.lastStatus;
      recoveryNote = 'Awaiting user decision for recovery';
      break;
    default:
      newStatus = task.lastStatus;
      recoveryNote = 'Unknown recovery action';
  }

  try {
    // Read, patch, and write back the status file
    // Node.js fallback: fs.promises.readFile / fs.promises.writeFile
    let statusData: Record<string, unknown> = {};
    try {
      const raw = await Deno.readTextFile(statusPath);
      statusData = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      // File missing or corrupt -- start fresh
    }

    statusData.status = newStatus;
    statusData.recovery_action = action;
    statusData.recovery_note = recoveryNote;
    statusData.recovered_at = new Date().toISOString();

    const content = JSON.stringify(statusData, null, 2);

    // Atomic write: write to temp then rename
    const tmp = `${statusPath}.${Date.now()}.tmp`;
    await Deno.writeTextFile(tmp, content);
    await Deno.rename(tmp, statusPath);
  } catch (err) {
    throw new Error(
      `Failed to recover task ${task.taskId}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

// ---------------------------------------------------------------------------
// Task/worktree reconciliation
// ---------------------------------------------------------------------------

export type ReconcileAction =
  | 'noop'
  | 'cleanup_worktree'
  | 'user_decision'
  | 'explicit_recovery_required';

export interface ReconcileInput {
  taskId: string;
  taskStatus: TaskStatus;
  worktreeState: WorktreeState;
}

export interface ReconcileDecision {
  action: ReconcileAction;
  reason: string;
  prompt?: string;
  warn?: string;
  taskStatus: TaskStatus;
  worktreeState: WorktreeState;
}

const TERMINAL_TASK = new Set<TaskStatus>(['done', 'failed', 'cancelled']);
const ACTIVE_WT = new Set<WorktreeState>([
  'creating',
  'active',
  'stale',
  'pre_merge',
  'cleaning',
]);
const CLEANED_WT = new Set<WorktreeState>(['cleaned', 'merged']);
const ERROR_WT = new Set<WorktreeState>([
  'error',
  'conflict',
  'clean_failed',
  'create_failed',
]);

export function reconcileTaskAndWorktree(
  input: ReconcileInput,
): ReconcileDecision {
  const { taskId, taskStatus, worktreeState } = input;
  const base = { taskStatus, worktreeState };

  if (ERROR_WT.has(worktreeState)) {
    return {
      ...base,
      action: 'user_decision',
      reason: `worktree in error state: ${worktreeState}`,
      prompt: `Worktree for ${taskId} in error state ${worktreeState} — manual intervention required`,
    };
  }

  if (taskStatus === 'merge_conflict') {
    if (ACTIVE_WT.has(worktreeState)) {
      return {
        ...base,
        action: 'explicit_recovery_required',
        reason: 'merge_conflict requires AD-003 explicit action',
      };
    }

    if (CLEANED_WT.has(worktreeState)) {
      return {
        ...base,
        action: 'user_decision',
        reason: 'merge_conflict but worktree gone',
        prompt: `merge_conflict for ${taskId} but worktree ${worktreeState} — manual review needed`,
        warn: 'cannot resolve conflict without worktree',
      };
    }
  }

  if (TERMINAL_TASK.has(taskStatus)) {
    if (ACTIVE_WT.has(worktreeState)) {
      return {
        ...base,
        action: 'cleanup_worktree',
        reason: 'terminal task with active worktree — cleanup recommended',
      };
    }

    if (CLEANED_WT.has(worktreeState)) {
      return {
        ...base,
        action: 'noop',
        reason: 'aligned: terminal task and cleaned worktree',
      };
    }
  }

  if (ACTIVE_WT.has(worktreeState)) {
    return {
      ...base,
      action: 'noop',
      reason: 'aligned: active task and active worktree',
    };
  }

  if (CLEANED_WT.has(worktreeState)) {
    return {
      ...base,
      action: 'user_decision',
      reason: 'active task but worktree cleaned',
      prompt: `Active task ${taskId} (${taskStatus}) but worktree ${worktreeState} — mark as failed?`,
    };
  }

  return {
    ...base,
    action: 'user_decision',
    reason: 'unrecognized state combination',
    prompt: `Unrecognized state: task=${taskStatus} worktree=${worktreeState}`,
  };
}
