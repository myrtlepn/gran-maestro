/**
 * Error model, timeout configuration, and retry/fallback policies
 * for Gran Maestro.
 *
 * Provides a common {@link ExecutionError} structure, error classification
 * heuristics, and resolution logic that drives the retry/fallback engine.
 *
 * @module error-model
 * @see design-decisions.md section 3
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Classification of an error's root cause.
 *
 * Used by {@link classifyError} to map raw CLI output to a known category.
 */
export type ErrorCategory =
  | 'cli_timeout'         // CLI execution timed out
  | 'cli_crash'           // CLI abnormal exit (OOM, segfault)
  | 'cli_auth_failure'    // CLI authentication failure (expired token)
  | 'cli_network_error'   // Network error (API 429, 5xx)
  | 'git_conflict'        // Git merge/rebase conflict
  | 'git_worktree_error'  // Worktree create/delete failure
  | 'file_lock_error'     // File lock contention
  | 'state_corruption'    // State file corruption
  | 'dashboard_error'     // Dashboard server error
  | 'unknown';            // Unclassified

/**
 * How severe the error is from the perspective of the orchestration engine.
 */
export type ErrorSeverity = 'critical' | 'recoverable' | 'warning';

/**
 * Possible resolution strategies the engine can apply.
 */
export type ErrorResolution =
  | { action: 'retry'; max_attempts: number; backoff_ms: number }
  | { action: 'fallback'; target_agent: string }
  | { action: 'user_intervention'; message: string }
  | { action: 'abort'; cleanup: boolean };

/** Structured error record persisted to `.gran-maestro/.../errors/ERR-NNN.json`. */
export interface ExecutionError {
  /** Unique error identifier, e.g. "ERR-001". */
  id: string;
  /** ISO 8601 timestamp. */
  timestamp: string;
  /** Owning task, e.g. "REQ-001-01". */
  task_id: string;
  /** Phase in which the error occurred. */
  phase: string;
  /** Classified error category. */
  category: ErrorCategory;
  /** Severity level. */
  severity: ErrorSeverity;
  /** Human-readable error description. */
  message: string;
  /** Arbitrary context data (exit code, stderr snippet, etc.). */
  context: Record<string, unknown>;
  /** Chosen resolution, if any. */
  resolution?: ErrorResolution;
}

// ---------------------------------------------------------------------------
// Timeout configuration
// ---------------------------------------------------------------------------

/** Timeout thresholds (in milliseconds) used by the orchestration engine. */
export interface TimeoutConfig {
  /** Default CLI execution timeout (5 min). */
  cli_execution_default_ms: number;
  /** Large-task CLI execution timeout (30 min). */
  cli_execution_large_task_ms: number;
  /** User approval timeout. `null` means unlimited. */
  user_approval_ms: number | null;
  /** Pre-check (typecheck + tests) timeout (2 min). */
  pre_check_ms: number;
  /** Merge operation timeout (1 min). */
  merge_ms: number;
  /** Dashboard health check timeout (10 s). */
  dashboard_health_check_ms: number;
}

/** Default timeout values from design-decisions.md lines 214-224. */
export const DEFAULT_TIMEOUTS: Readonly<TimeoutConfig> = {
  cli_execution_default_ms: 300_000,      // 5 minutes
  cli_execution_large_task_ms: 1_800_000, // 30 minutes
  user_approval_ms: null,                 // unlimited
  pre_check_ms: 120_000,                  // 2 minutes
  merge_ms: 60_000,                       // 1 minute
  dashboard_health_check_ms: 10_000,      // 10 seconds
} as const;

// ---------------------------------------------------------------------------
// Retry policy
// ---------------------------------------------------------------------------

/** Retry and fallback budget for a single error category. */
export interface RetryPolicy {
  /** Maximum retry attempts before escalation. */
  max_attempts: number;
  /** Base backoff delay for exponential backoff (ms). */
  backoff_base_ms: number;
  /** Maximum fallback chain depth (1 = single fallback hop). */
  max_fallback_depth: number;
}

/** Default retry policy from design-decisions.md (section 3, lines 232-245). */
export const DEFAULT_RETRY_POLICY: Readonly<RetryPolicy> = {
  max_attempts: 2,
  backoff_base_ms: 1_000,
  max_fallback_depth: 1,
} as const;

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

/**
 * Classify an error based on exit code, stderr content, and context.
 *
 * The heuristic inspects common patterns such as "SIGKILL", "401",
 * "CONFLICT", etc. to bucket the error into a known category.
 *
 * @param exitCode - Process exit code.
 * @param stderr   - Captured standard error output.
 * @param context  - Additional context (e.g. `{ timedOut: true }`).
 * @returns The best-matching {@link ErrorCategory}.
 */
export function classifyError(
  exitCode: number,
  stderr: string,
  context: Record<string, unknown> = {},
): ErrorCategory {
  const lower = stderr.toLowerCase();

  // Timeout (signalled by context flag or common patterns)
  if (context.timedOut === true || lower.includes('timed out') || lower.includes('timeout')) {
    return 'cli_timeout';
  }

  // Auth failures
  if (
    exitCode === 401 ||
    lower.includes('401') ||
    lower.includes('unauthorized') ||
    lower.includes('auth') && lower.includes('fail')
  ) {
    return 'cli_auth_failure';
  }

  // Network errors (rate limit, server errors)
  if (
    lower.includes('429') ||
    lower.includes('rate limit') ||
    lower.includes('503') ||
    lower.includes('502') ||
    lower.includes('network') ||
    lower.includes('econnrefused') ||
    lower.includes('enotfound')
  ) {
    return 'cli_network_error';
  }

  // Git conflicts
  if (lower.includes('conflict') && (lower.includes('merge') || lower.includes('rebase'))) {
    return 'git_conflict';
  }

  // Git worktree issues
  if (lower.includes('worktree') && (lower.includes('error') || lower.includes('fatal'))) {
    return 'git_worktree_error';
  }

  // File locking
  if (lower.includes('lock') && (lower.includes('unable') || lower.includes('fail'))) {
    return 'file_lock_error';
  }

  // State corruption
  if (lower.includes('json') && (lower.includes('parse') || lower.includes('syntax'))) {
    return 'state_corruption';
  }

  // CLI crash (signal-based exit codes on POSIX: 128+signal)
  if (exitCode >= 128 || lower.includes('segfault') || lower.includes('oom') || lower.includes('killed')) {
    return 'cli_crash';
  }

  return 'unknown';
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Determine the appropriate resolution for a classified error.
 *
 * Implements the retry / fallback / user-intervention cascade from
 * design-decisions.md section 3, lines 232-245.
 *
 * @param category   - The classified error category.
 * @param retryCount - How many times the task has already been retried.
 * @param policy     - The retry policy in effect.
 * @returns The recommended {@link ErrorResolution}.
 */
export function resolveError(
  category: ErrorCategory,
  retryCount: number,
  policy: RetryPolicy = DEFAULT_RETRY_POLICY,
): ErrorResolution {
  switch (category) {
    case 'cli_timeout':
      if (retryCount < 1) {
        // First retry: double the timeout (communicated via backoff_ms)
        return { action: 'retry', max_attempts: 1, backoff_ms: policy.backoff_base_ms * 2 };
      }
      if (retryCount < 1 + policy.max_fallback_depth) {
        return { action: 'fallback', target_agent: '' }; // Caller fills in the actual fallback
      }
      return { action: 'user_intervention', message: 'CLI timed out after retry and fallback.' };

    case 'cli_crash':
      if (retryCount < 1) {
        return { action: 'retry', max_attempts: 1, backoff_ms: policy.backoff_base_ms };
      }
      if (retryCount < 1 + policy.max_fallback_depth) {
        return { action: 'fallback', target_agent: '' };
      }
      return { action: 'user_intervention', message: 'CLI crashed after retry and fallback.' };

    case 'cli_auth_failure':
      // No retry -- user must refresh credentials
      return { action: 'user_intervention', message: 'Authentication failed. Please refresh CLI credentials.' };

    case 'cli_network_error':
      if (retryCount < policy.max_attempts) {
        const backoff = policy.backoff_base_ms * Math.pow(2, retryCount);
        return { action: 'retry', max_attempts: policy.max_attempts, backoff_ms: backoff };
      }
      return { action: 'user_intervention', message: 'Network error persists after retries.' };

    case 'git_conflict':
      return { action: 'user_intervention', message: 'Git merge/rebase conflict requires manual resolution.' };

    case 'git_worktree_error':
      return { action: 'abort', cleanup: true };

    case 'file_lock_error':
      if (retryCount < policy.max_attempts) {
        return { action: 'retry', max_attempts: policy.max_attempts, backoff_ms: policy.backoff_base_ms };
      }
      return { action: 'abort', cleanup: false };

    case 'state_corruption':
      return { action: 'abort', cleanup: true };

    case 'dashboard_error':
      // Dashboard errors are non-fatal warnings; retry silently.
      return { action: 'retry', max_attempts: 3, backoff_ms: policy.backoff_base_ms };

    case 'unknown':
    default:
      return { action: 'user_intervention', message: `Unclassified error (exit code ${retryCount}). Check logs.` };
  }
}
