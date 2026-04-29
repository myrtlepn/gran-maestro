/**
 * Task-level finite state machine for Gran Maestro.
 *
 * Defines the dual-layer state model:
 *   - **TaskStatus** -- per-task FSM (status.json)
 *   - **RequestPhase** -- per-request derived phase (request.json)
 *
 * All valid transitions are encoded declaratively so the engine can
 * enforce invariants at runtime.
 *
 * @module task-fsm
 * @see design-decisions.md section 2
 */

import { TERMINAL, TRANSITIONS, type TaskStatus } from './state-schema';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Task status sourced from `state-schema.ts` single source-of-truth.
 */
export type { TaskStatus } from './state-schema';

/**
 * Derived request-level phase computed from the statuses of all child tasks.
 */
export type RequestPhase =
  | 'phase1_analysis'
  | 'phase2_execution'
  | 'phase3_review'
  | 'phase4_feedback'
  | 'phase5_acceptance'
  | 'done'
  | 'cancelled'
  | 'failed'
  | 'unknown';

/** A single permitted state transition with optional condition / guard descriptions. */
export interface TaskTransition {
  /** Source status. Use `'*'` for "any non-terminal state". */
  from: TaskStatus | '*';
  /** Target status. */
  to: TaskStatus;
  /** Human-readable condition that must be true for this transition. */
  condition: string;
  /** Optional guard expression evaluated at runtime. */
  guard?: string;
}

/** Runtime state of a single task. */
export interface TaskState {
  /** Unique task identifier, e.g. "REQ-001-01". */
  id: string;
  /** Current FSM status. */
  status: TaskStatus;
  /** Number of times this task has been retried. */
  retry_count: number;
  /** Current feedback round (0 = initial). */
  feedback_round: number;
  /** Agent key assigned to this task (e.g. "codex-dev"). */
  assigned_agent: string;
  /** Absolute path to the task's git worktree. */
  worktree_path: string;
  /** ISO 8601 creation timestamp. */
  created_at: string;
  /** ISO 8601 last-update timestamp. */
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Transition table
// ---------------------------------------------------------------------------

/** Terminal statuses -- no outgoing transitions except to themselves. */
const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set(TERMINAL);

/**
 * Declarative table of every valid state transition.
 *
 * Derived from design-decisions.md lines 153-167.
 */
export const VALID_TRANSITIONS: readonly TaskTransition[] = TRANSITIONS;

// ---------------------------------------------------------------------------
// Transition helpers
// ---------------------------------------------------------------------------

/**
 * Check whether transitioning from `from` to `to` is valid according to
 * the declared transition table.
 *
 * @param from - Current task status.
 * @param to   - Desired target status.
 * @returns `true` if a matching transition rule exists.
 */
export function canTransition(from: TaskStatus, to: TaskStatus): boolean {
  if (TERMINAL_STATUSES.has(from)) {
    return false;
  }
  return VALID_TRANSITIONS.some(
    (t) => (t.from === from || t.from === '*') && t.to === to,
  );
}

/**
 * Validate and apply a status transition to a task.
 *
 * Returns a **new** {@link TaskState} object (immutable update) with the
 * status and `updated_at` fields changed.
 *
 * @param task - The current task state.
 * @param to   - The desired target status.
 * @returns A new task state with the transition applied.
 * @throws {Error} If the transition is not valid.
 */
export function transitionTask(task: TaskState, to: TaskStatus): TaskState {
  if (!canTransition(task.status, to)) {
    throw new Error(
      `Invalid transition: ${task.status} -> ${to} for task ${task.id}`,
    );
  }
  return {
    ...task,
    status: to,
    updated_at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Request-phase computation
// ---------------------------------------------------------------------------

/**
 * Derive the overall request phase from the statuses of all its child tasks.
 *
 * The phase reflects the *most-behind* task so the PM knows where
 * attention is needed.
 *
 * @param tasks - Array of task states belonging to the same request.
 * @returns The computed {@link RequestPhase}.
 */
export function computeRequestPhase(tasks: TaskState[]): RequestPhase {
  if (tasks.length === 0) return 'unknown';

  if (tasks.every((t) => t.status === 'done')) return 'done';
  if (tasks.every((t) => t.status === 'cancelled')) return 'cancelled';
  if (tasks.some((t) => t.status === 'failed')) return 'failed';

  // Determine phase from the most-behind task
  if (tasks.some((t) => t.status === 'pending')) return 'phase1_analysis';
  if (
    tasks.some((t) =>
      ['queued', 'executing', 'pre_check', 'pre_check_failed'].includes(
        t.status,
      ),
    )
  )
    return 'phase2_execution';
  if (tasks.some((t) => t.status === 'review')) return 'phase3_review';
  if (tasks.some((t) => t.status === 'feedback')) return 'phase4_feedback';
  if (tasks.some((t) => ['merging', 'merge_conflict'].includes(t.status)))
    return 'phase5_acceptance';

  return 'unknown';
}
